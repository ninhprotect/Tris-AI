"""Bounded context and recoverable local chat transport, without model swaps."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncIterator

import httpx

from config.settings import OLLAMA_HOST, OLLAMA_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class ChatRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def bounded_history(history: list[dict], system: str, message: str, context_window: int,
                    reply_tokens: int) -> list[dict]:
    """Conservative UTF-8 budget (not a tokenizer); keep whole recent turns.

    Never slice a sentence/assistant turn into a different meaning, or drop
    the current question/system rules to accommodate old conversation.
    """
    remaining = max(0, (context_window - reply_tokens - 128) * 3
                    - len(system.encode('utf-8')) - len(message.encode('utf-8')))
    kept = []
    for item in reversed(history[-12:]):
        cost = len(item['content'].encode('utf-8')) + 24
        if cost > remaining:
            break
        kept.append(item)
        remaining -= cost
    kept.reverse()
    while kept and kept[0]['role'] != 'user':
        kept.pop(0)
    return kept


CONTEXT_TRIMMED_NOTE = "\n[… phần còn lại đã được rút gọn cho vừa bộ nhớ ngữ cảnh]"


def fit_context(system: str, context: str, message: str, context_window: int, reply_tokens: int,
                history_reserve: int = 600) -> str:
    """Trim attached source material so system + sources + question + reply fit num_ctx.

    Same conservative 3-bytes-per-token budget as bounded_history. Without it, a
    long image description, document chunks or web pages push the request past
    the window: Ollama rejects it (HTTP 400) or runs out of room mid-answer.
    """
    budget = ((context_window - reply_tokens - 128) * 3 - len(system.encode('utf-8'))
              - len(message.encode('utf-8')) - history_reserve - len(CONTEXT_TRIMMED_NOTE.encode('utf-8')))
    data = context.encode('utf-8')
    if len(data) <= budget:
        return context
    if budget <= 0:
        return ''
    cut = data[:budget].decode('utf-8', 'ignore')
    # End on a line break when one is close, so a source is not cut mid-sentence.
    newline = cut.rfind('\n')
    if newline > len(cut) // 2:
        cut = cut[:newline]
    return cut.rstrip() + CONTEXT_TRIMMED_NOTE


# Measured on Tris 4b: a stricter checklist made the reviewer flag drafts but return near copies (+4-5 s,
# nothing fixed), and a list-mistakes-then-rewrite pass fixed one error but introduced another (+7 s).
# This light pass costs 0.2-0.8 s and only replaces a reply it rewrites in full (see accept_review).
SELF_REVIEW_SYSTEM = (
    "You are the quality checker for Tris, a friendly local English tutor. You receive the learner's "
    "message and Tris's draft reply. Check the draft for: wrong facts or wrong answers; incorrect English "
    "grammar, spelling or translations in examples; explanations in the wrong language (explanations must be "
    "in {explain}, practice examples in English); content that does not answer the message, contradicts "
    "itself, repeats itself or is cut off. Keep citation tags such as [S1] or [W1] exactly as written.{role}\n"
    "If the draft is correct and complete, reply with exactly: OK\n"
    "Otherwise reply with the full corrected reply only, in the same language, tone and format and about the "
    "same length. Never mention the draft, a review or these instructions."
)
_REVIEW_DELIMITERS = re.compile(r"^\s*<<<\s*|\s*>>>\s*$")
_REVIEW_META = re.compile(r"(?i)\b(draft|reviewer|the review|bản nháp|rà soát)\b")
_CITATION = re.compile(r"\[(?:S|W)\d+\]")


def review_messages(question: str, draft: str, language: str, mode: str) -> list[dict]:
    """Messages for one self-review pass of a finished draft."""
    role = (" This is a role-play: the reply stays in character and in English; do not turn it into an "
            "explanation." if mode == "Role Play" else "")
    system = SELF_REVIEW_SYSTEM.format(explain="Vietnamese" if language == "vi" else "English", role=role)
    user = f"Learner message:\n<<<\n{question}\n>>>\n\nDraft reply:\n<<<\n{draft}\n>>>"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def accept_review(draft: str, review: str) -> str:
    """Use the reviewer's correction only when it is a plausible full reply; otherwise keep the draft."""
    text = _REVIEW_DELIMITERS.sub("", (review or "").strip())
    if not text:
        return draft
    if text.split("\n", 1)[0].strip().rstrip(".!").upper() == "OK":
        return draft
    if _REVIEW_META.search(text):
        return draft  # commentary about the draft, not a reply to the learner
    if len(draft) > 200 and len(text) < 0.35 * len(draft):
        return draft  # truncated or summarised instead of corrected
    if _CITATION.search(draft) and not _CITATION.search(text):
        return draft  # a correction must not silently drop the sources
    return text


def upstream_error(status: int, body: str) -> ChatRuntimeError:
    lower = body.lower()
    if any(word in lower for word in ('out of memory', 'not enough memory', 'requires more', 'cuda error', 'failed to allocate')):
        return ChatRuntimeError('AI_MEMORY', 'Model đang thiếu RAM/VRAM. Hãy chọn english-tutor-local:4b trên máy 6 GB VRAM, hoặc chờ tác vụ GPU khác hoàn tất.')
    if status == 404:
        return ChatRuntimeError('AI_MODEL_MISSING', 'Ollama không tìm thấy model đã chọn. Hãy chọn lại một model đã cài; Tris không tự tải model.')
    if status == 400:
        return ChatRuntimeError('AI_REQUEST_REJECTED', 'Ollama từ chối cấu hình hoặc ngữ cảnh của yêu cầu (400). Hãy thử cuộc trò chuyện mới hoặc chọn english-tutor-local:4b.')
    return ChatRuntimeError('AI_SERVICE_ERROR', f'Ollama chưa chạy được model đã chọn (HTTP {status}). Hãy thử lại hoặc chọn english-tutor-local:4b; dữ liệu hội thoại vẫn được giữ.')


async def stream_local_chat(payload: dict, request, base_url: str | None = None) -> AsyncIterator[dict]:
    """Retry a transient HTTP failure once, only before any answer is emitted."""
    produced = False
    host = (base_url or OLLAMA_HOST).rstrip('/')
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(OLLAMA_TIMEOUT_SECONDS, connect=5), trust_env=False) as client:
                async with client.stream('POST', f'{host}/api/chat', json=payload) as response:
                    if response.status_code >= 400:
                        raw = (await response.aread()).decode('utf-8', 'replace')[:4096]
                        error = upstream_error(response.status_code, raw)
                        # No prompts, auth headers, paths or raw upstream text in logs.
                        logger.warning('Local chat failure status=%d code=%s attempt=%d', response.status_code, error.code, attempt + 1)
                        if response.status_code in (500, 502, 503, 504) and error.code != 'AI_MEMORY' and not attempt and not produced:
                            yield {'status': 'Ollama đang nạp lại model; Tris thử kết nối lại một lần…'}
                            await asyncio.sleep(.5)
                            if await request.is_disconnected():
                                return
                            continue
                        raise error
                    response.raise_for_status()
                    async for raw in response.aiter_lines():
                        if await request.is_disconnected():
                            return
                        if not raw:
                            continue
                        event = json.loads(raw)
                        if not isinstance(event, dict) or not isinstance(event.get('message', {}), dict):
                            raise ValueError('Invalid stream event shape')
                        if event.get('error'):
                            raise upstream_error(500, str(event['error']))
                        delta = event.get('message', {}).get('content', '')
                        if delta:
                            produced = True
                            yield {'delta': delta}
                        if event.get('done'):
                            if not produced:
                                raise ChatRuntimeError('AI_EMPTY', 'Model chưa tạo được câu trả lời. Hãy thử lại với câu hỏi ngắn hơn.')
                            yield {'complete': True}
                            return
                    raise ChatRuntimeError('AI_INCOMPLETE', 'Kết nối AI bị ngắt trước khi hoàn tất. Hãy thử lại; câu trả lời dở chưa được lưu là kết quả hoàn chỉnh.')
        except httpx.TimeoutException as exc:
            if attempt == 0 and not produced:
                yield {'status': 'Ollama đang nạp model vào RAM/VRAM; Tris tự thử lại một lần…'}
                await asyncio.sleep(.5)
                if await request.is_disconnected():
                    return
                continue
            raise ChatRuntimeError('AI_TIMEOUT', 'Ollama mất quá lâu để nạp/trả lời. Hãy chờ tác vụ khác xong hoặc chọn model 4b rồi thử lại.') from exc
        except httpx.ConnectError as exc:
            if attempt == 0 and not produced:
                yield {'status': 'Kết nối Ollama vừa khởi động lại; Tris tự nối lại một lần…'}
                await asyncio.sleep(.5)
                if await request.is_disconnected():
                    return
                continue
            raise ChatRuntimeError('AI_OFFLINE', 'Không kết nối được Ollama. Hãy chạy lại Tris AI rồi gửi lại câu hỏi.') from exc
        except httpx.HTTPError as exc:
            if attempt == 0 and not produced:
                yield {'status': 'Kết nối model vừa bị gián đoạn; Tris tự nối lại một lần…'}
                await asyncio.sleep(.5)
                if await request.is_disconnected():
                    return
                continue
            raise ChatRuntimeError('AI_CONNECTION', 'Kết nối với Ollama bị gián đoạn. Hãy thử lại; Tris không tự tải model.') from exc
        except (ValueError, TypeError) as exc:
            raise ChatRuntimeError('AI_BAD_RESPONSE', 'Ollama trả dữ liệu không hợp lệ. Hãy thử lại hoặc khởi động lại Ollama.') from exc
