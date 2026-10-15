"""Small, framework-free adapter for the local Ollama server."""

import json
import os
from collections.abc import Sequence
from typing import Any

import httpx
from ollama import Client, ResponseError

from config.settings import (
    CONTEXT_WINDOW,
    MAX_HISTORY_MESSAGES,
    MODEL_NAME,
    OLLAMA_HOST,
    OLLAMA_TIMEOUT_SECONDS,
    TEMPERATURE,
)

ChatMessage = dict[str, Any]

# Cap plain chat replies so the model never rambles for minutes on a 6GB GPU.
CHAT_MAX_TOKENS = int(os.getenv("OLLAMA_CHAT_MAX_TOKENS", "384"))

# Keep every model resident in VRAM/RAM between messages so follow-up turns do
# not pay the multi-second reload cost after 5 idle minutes.
KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

import re as _re

_CREATOR_NAME = "Nguyễn Hải Hà Ninh"
# Matches "Đại học <wrong words>" (and "Trường Đại học ...") except the
# correct name; group 3 keeps trailing punctuation.
_UNIVERSITY_BAD_RE = _re.compile(
    r"((?:Trường\s+)?Đại\s*học)\s+(?!Thủ\s*Dầu\s*Một\b)"
    r"([^\n.,!?;:]*?)\s*([.,!?;:]?|$)",
    _re.UNICODE,
)

# Small 4B models mangle the low-frequency Vietnamese university name when
# rephrasing; these deterministic fixes guarantee the creator identity stays
# accurate no matter how the model paraphrases.
_UNIVERSITY_NAME_FIXES = [
    ("Thuận Đạo", "Thủ Dầu Một"),
    ("Thuận Đa Mỹ", "Thủ Dầu Một"),
    ("Thuận Đa Mỹ", "Thủ Dầu Một"),
    ("Thuận Đa", "Thủ Dầu Một"),
    ("Thuan Dao", "Thủ Dầu Một"),
    ("Thu Đău Môt", "Thủ Dầu Một"),
    ("Thu Đầu Một", "Thủ Dầu Một"),
    ("Đại học Thu Dau Mot", "Đại học Thủ Dầu Một"),
    ("Kỹ thuật Thông tin", "Công nghệ thông tin"),
]


def _fix_identity_names(text: str) -> str:
    for wrong, right in _UNIVERSITY_NAME_FIXES:
        if wrong in text:
            text = text.replace(wrong, right)
    if _CREATOR_NAME in text:
        # Catch any paraphrased misspelling of the university name in creator
        # answers, e.g. "Thuận Đa Mỹ" or "Thu Đậu Mật" instead of Thủ Dầu Một.
        spans = []
        for m in _re.finditer(r"(Trường\s+)?Đại\s*học", text):
            start = m.end()
            if text[start:].lstrip().startswith("Thủ Dầu Một"):
                continue
            end = len(text)
            for i in range(start, len(text)):
                if text[i] in ".,!?;:\n":
                    end = i
                    break
            if text[start:end].strip():
                spans.append((start, end))
        for start, end in reversed(spans):
            text = text[:start] + " Thủ Dầu Một" + text[end:]
    return text


class LocalAIError(RuntimeError):
    """Base error that is safe for the UI to handle."""


class LocalAIConnectionError(LocalAIError):
    """Raised when the Ollama server cannot be reached."""


class LocalAIModelError(LocalAIError):
    """Raised when the configured model is unavailable."""


class OllamaLLM:
    """Send chat messages to one configurable local Ollama model."""

    def __init__(self, client: Client | None = None) -> None:
        self.client = client or Client(
            host=OLLAMA_HOST,
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )

    def chat(
        self,
        system_prompt: str,
        history: Sequence[ChatMessage],
        user_message: str,
        learner_context: str = "",
    ) -> str:
        """Return one assistant response while preserving recent context."""
        from ai.identity import identity_answer
        identity = identity_answer(user_message)
        if identity:
            return identity
        if learner_context:
            system_prompt = f"{system_prompt}\n\n{learner_context}"
        messages: list[ChatMessage] = [
            {"role": "system", "content": system_prompt},
            *self._trim_history(history),
            {"role": "user", "content": user_message},
        ]

        try:
            response: Any = self.client.chat(
                model=MODEL_NAME,
                messages=messages,
                think=False,
                keep_alive=KEEP_ALIVE,
                options={
                    "temperature": TEMPERATURE,
                    "num_ctx": CONTEXT_WINDOW,
                    "num_predict": CHAT_MAX_TOKENS,
                },
            )
        except ResponseError as exc:
            error_text = str(exc).lower()
            if exc.status_code == 404 or "not found" in error_text:
                raise LocalAIModelError(
                    f"Không tìm thấy model '{MODEL_NAME}'. "
                    f"Hãy chạy: ollama pull {MODEL_NAME}"
                ) from exc
            raise LocalAIError(
                "Local AI gặp lỗi khi tạo phản hồi. Hãy thử lại."
            ) from exc
        except (httpx.ConnectError, httpx.TimeoutException, ConnectionError, OSError) as exc:
            raise LocalAIConnectionError(
                "Không thể kết nối với Local AI. Hãy kiểm tra Ollama đang chạy."
            ) from exc

        content = self._get_content(response).strip()
        if not content:
            raise LocalAIError("Local AI không trả về nội dung. Hãy thử lại.")
        return _fix_identity_names(content)

    def chat_structured(
        self,
        system_prompt: str,
        user_message: str,
        response_schema: dict[str, Any],
        learner_context: str = "",
    ) -> dict[str, Any]:
        """Ask local Qwen for schema-constrained JSON, ready for other UIs."""
        if learner_context:
            system_prompt = f"{system_prompt}\n\n{learner_context}"
        messages: list[ChatMessage] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        try:
            response: Any = self.client.chat(
                model=MODEL_NAME,
                messages=messages,
                think=False,
                format=response_schema,
                keep_alive=KEEP_ALIVE,
                options={
                    "temperature": 0.3,
                    "num_ctx": CONTEXT_WINDOW,
                    "num_predict": 2048,
                },
            )
        except ResponseError as exc:
            error_text = str(exc).lower()
            if exc.status_code == 404 or "not found" in error_text:
                raise LocalAIModelError(
                    f"Không tìm thấy model '{MODEL_NAME}'. "
                    f"Hãy chạy: ollama pull {MODEL_NAME}"
                ) from exc
            raise LocalAIError(
                "Local AI gặp lỗi khi sinh bài tập. Hãy thử lại."
            ) from exc
        except (httpx.ConnectError, httpx.TimeoutException, ConnectionError, OSError) as exc:
            raise LocalAIConnectionError(
                "Không thể kết nối với Local AI. Hãy kiểm tra Ollama đang chạy."
            ) from exc

        content = self._get_content(response).strip()
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LocalAIError(
                "Local AI trả về bài tập không đúng cấu trúc JSON. Hãy tạo lại."
            ) from exc
        if not isinstance(payload, dict):
            raise LocalAIError("Local AI trả về bài tập không hợp lệ. Hãy tạo lại.")
        return payload

    @staticmethod
    def _trim_history(history: Sequence[ChatMessage]) -> list[ChatMessage]:
        """Keep the prompt bounded while retaining the newest conversation."""
        clean_history: list[ChatMessage] = []
        for item in history:
            role = item.get("role")
            content = OllamaLLM._content_to_text(item.get("content"))
            if role in {"user", "assistant"} and content:
                clean_history.append({"role": role, "content": content})
        return clean_history[-MAX_HISTORY_MESSAGES:]

    @staticmethod
    def _content_to_text(content: Any) -> str:
        """Convert Gradio 6 rich-text message parts into plain Ollama text."""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            return str(content.get("text") or content.get("content") or "")
        if isinstance(content, list):
            return "".join(OllamaLLM._content_to_text(part) for part in content)
        return str(content) if content is not None else ""

    @staticmethod
    def _get_content(response: Any) -> str:
        """Support both typed Ollama responses and mapping-like test doubles."""
        if hasattr(response, "message"):
            message = response.message
            if hasattr(message, "content"):
                return message.content or ""
        if isinstance(response, dict):
            return str(response.get("message", {}).get("content", ""))
        return ""
