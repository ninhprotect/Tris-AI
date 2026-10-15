"""Cloned-mascot speech engine for Tris AI.

Pipeline: Piper synthesizes the text (correct Vietnamese/English
pronunciation, built-in subtle tone preset) -> the local tone-conversion
server (runtime/xtts, OpenVoice V2) recolors it with the mascot voice from
the user-authorized clips. If conversion fails, report the error rather than
silently playing the unconverted base speaker.
"""

from __future__ import annotations

import hashlib
import httpx
import wave
from pathlib import Path

from config.settings import (
    PROJECT_ROOT,
    TTS_ENABLED,
    XTTS_SERVER_URL,
    XTTS_TIMEOUT_SECONDS,
)
from services.local_tts import LocalTTSError, TrisLocalVoice, speech_text


class CloneVoiceClient:
    """Piper speech + tone-color conversion to the mascot voice."""

    def __init__(
        self,
        piper_voice,
        server_url: str = XTTS_SERVER_URL,
        timeout: int = XTTS_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        self.piper = piper_voice
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self._client = client or httpx.Client(timeout=timeout, trust_env=False)

    def available(self, language: str = "vi") -> bool:
        if not TTS_ENABLED:
            return False
        try:
            response = self._client.get(f"{self.server_url}/health", timeout=5)
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return False
        return bool(payload.get("speaker")) and not payload.get("error")

    def synthesize(self, text: str, language: str = "vi") -> str:
        if not TTS_ENABLED:
            raise LocalTTSError("Giọng đọc local đang bị tắt trong cấu hình.")
        clean = speech_text(text)
        if not clean:
            raise LocalTTSError("Không có nội dung phù hợp để đọc.")
        lang = "vi" if language.lower().startswith("vi") else "en"
        try:
            health = self._client.get(f'{self.server_url}/health', timeout=5)
            health.raise_for_status()
            status = health.json()
            revision = status.get('reference_revisions', {}).get(lang) or status.get('reference_revision')
            if not revision or status.get('error') or not status.get('speaker'):
                raise LocalTTSError('Giọng mẫu chưa sẵn sàng. Không tự đổi sang giọng khác.')
        except (httpx.HTTPError, ValueError) as exc:
            raise LocalTTSError('Không kết nối được giọng mẫu local. Không tự đổi sang giọng khác.') from exc
        digest = hashlib.sha256(
            f"{TrisLocalVoice.cache_profile(lang)}|{revision}|{lang}|{clean}".encode("utf-8")
        ).hexdigest()[:24]
        cache_dir = Path(PROJECT_ROOT) / "runtime" / "tts" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        output_path = cache_dir / f"clone-{lang}-{digest}.wav"
        if output_path.is_file() and output_path.stat().st_size > 44:
            return str(output_path)

        base_path = self.piper.synthesize(clean, language)
        try:
            with open(base_path, "rb") as handle:
                response = self._client.post(
                    f"{self.server_url}/convert",
                    files={"file": (output_path.name, handle, "audio/wav")},
                    data={"language": lang},
                    timeout=self.timeout,
                )
        except httpx.HTTPError as exc:
            raise LocalTTSError(
                "Không gọi được server chuyển giọng local (7861)."
            ) from exc
        if response.status_code != 200:
            detail = str(response.json().get("detail", ""))[:200]
            raise LocalTTSError(f"Chuyển giọng gặp lỗi: {detail}")
        if len(response.content) <= 44:
            raise LocalTTSError("Giọng chuyển đổi trả về dữ liệu rỗng.")
        output_path.write_bytes(response.content)
        try:
            with wave.open(str(output_path), "rb") as probe:
                if probe.getnframes() == 0:
                    raise ValueError("empty wav")
        except (wave.Error, ValueError) as exc:
            output_path.unlink(missing_ok=True)
            raise LocalTTSError("Tệp giọng chuyển đổi không đọc được.") from exc
        return str(output_path)
