"""Shared speech-engine selection for Tris AI.

Primary: Piper speech recolored to the mascot voice via the local tone
conversion server (recordings authorized by the user). Stock Piper is used
only when explicitly configured. Conversion failure never substitutes a
different speaker silently.
"""

from __future__ import annotations

from config.settings import TTS_ENGINE
from services.local_tts import tris_voice
from services.xtts_voice import CloneVoiceClient


class DualVoiceEngine:
    """Use the selected voice. Never silently substitute a different speaker."""

    def __init__(self, primary, fallback) -> None:
        self.primary = primary
        self.fallback = fallback

    def available(self, language: str = "vi") -> bool:
        return self.primary.available(language)

    def synthesize(self, text: str, language: str = "vi") -> str:
        return self.primary.synthesize(text, language)


_engine: DualVoiceEngine | None = None


def get_speech_engine() -> DualVoiceEngine:
    """Process-wide singleton shared by the web UI and the REST API."""
    global _engine
    if _engine is None:
        if TTS_ENGINE == "clone":
            primary = CloneVoiceClient(tris_voice)
        else:
            primary = tris_voice
        _engine = DualVoiceEngine(primary, tris_voice)
    return _engine
