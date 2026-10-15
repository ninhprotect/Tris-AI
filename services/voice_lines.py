"""Context-aware mascot voice lines for Tris AI.

Plays one of the mascot's original voice clips (categorised as vui/chien_dau/
hung_phan/buon) before the Piper speech, chosen from the emotional tone of the
reply. The clips are pre-recorded assets; the speech itself is always Piper,
so nothing here clones a character voice.
"""

from __future__ import annotations

import hashlib
import json
import random
import re as _re
import threading
from pathlib import Path

import os

from config.settings import PROJECT_ROOT, TTS_CACHE_DIR

import logging

logger = logging.getLogger(__name__)

VOICE_LINES_DIR = Path(
    os.getenv("TTS_VOICE_LINES_DIR", str(PROJECT_ROOT / "runtime" / "voice_lines"))
)
VOICE_LINES_ENABLED = os.getenv("TTS_VOICE_LINES", "false").lower() in {"1", "true", "yes"}
INTRO_GAP_MS = 160
CATEGORIES = ("vui", "chien_dau", "hung_phan", "buon")

# Keyword scores per mood. Vietnamese first, English second; the tutor answers
# mix both, so one table covers the two reply languages.
_MOOD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "chien_dau": (
        "chiến đấu", "chiến thắng", "đánh bại", "kẻ địch", "đối thủ", "trận đấu",
        "đánh nhau", "pháo", "nổ", "tấn công", "chiến trường", "ra trận",
        "đấu với", "thắng cuộc", "hạ gục",
        "battle", "fight", "enemy", "attack", "war", "victory", "defeat",
        "charge", "combat", "opponent", "explode",
    ),
    "hung_phan": (
        "xuất sắc", "hoàn hảo", "giỏi quá", "chúc mừng", "làm tốt lắm", "tuyệt vời",
        "đúng rồi", "chính xác", "điểm tuyệt đối", "quá đỉnh", "nhất rồi",
        "mạnh lên", "cấp độ mới", "kỷ lục",
        "awesome", "amazing", "perfect", "excellent", "congratulations",
        "brilliant", "great job", "well done", "incredible", "fantastic",
        "level up", "record",
    ),
    "buon": (
        "buồn", "tiếc", "tạm biệt", "mệt", "thất vọng", "sai rồi", "chưa đúng",
        "lại sai", "không ổn", "cố lên", "đừng lo", "dần dà", "từ từ",
        "sorry", "sad", "tired", "unfortunately", "mistake", "not quite",
        "don't worry", "take a break", "rest",
    ),
    "vui": (
        "chào", "xin chào", "hello", "hi", "hey", "cùng học", "học thôi",
        "bắt đầu", "vui", "cười", "haha", "bạn ơi", "mình và bạn", "ngày mới",
        "play", "fun", "happy", "let's go", "let us", "ready", "start",
        "today", "practice",
    ),
}

# The mascot never picks a battle cry for a grammar explanation; keep the
# intro rare on long neutral answers so it stays charming instead of noisy.
_MAX_NEUTRAL_LENGTH = 600


def pick_category(text: str, mode: str = "") -> str | None:
    """Return the mood label for a reply, or None when no intro fits."""
    clean = " ".join(str(text or "").split())
    if not clean:
        return None
    lowered = clean.lower()
    scores = {
        mood: sum(
            1
            for kw in keywords
            if _re.search(rf"\b{_re.escape(kw)}\b", lowered)
        )
        for mood, keywords in _MOOD_KEYWORDS.items()
    }
    best = max(scores, key=lambda mood: scores[mood])
    if scores[best] == 0:
        if mode == "Exercises":
            return "hung_phan"
        if len(clean) > _MAX_NEUTRAL_LENGTH:
            return None
        return "vui"
    return best


def _load_catalog() -> dict[str, list[str]]:
    path = VOICE_LINES_DIR / "catalog.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        mood: [name for name in items if (VOICE_LINES_DIR / name).is_file()]
        for mood, items in data.items()
        if isinstance(items, list)
    }


class VoiceLineService:
    """Pick an intro clip by mood and merge it in front of the speech engine."""

    def __init__(self, speech, fallback=None) -> None:
        self._speech = speech
        self._fallback = fallback
        self._lock = threading.Lock()
        self._last_clip: str | None = None

    def _speech_path(self, text: str, language: str) -> str:
        try:
            return self._speech.synthesize(text, language)
        except Exception:
            if self._fallback is None:
                raise
            return self._fallback.synthesize(text, language)

    def _ensure_ffmpeg(self) -> str:
        import shutil

        resolved = shutil.which("ffmpeg")
        if resolved:
            return resolved
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()

    def synthesize_with_intro(
        self, text: str, language: str = "vi", mode: str = ""
    ) -> str:
        """Return a WAV that starts with a mood-matched clip, then the reply."""
        speech_path = self._speech_path(text, language)
        if not VOICE_LINES_ENABLED:
            return speech_path
        mood = pick_category(text, mode)
        if mood is None:
            return speech_path
        catalog = _load_catalog()
        clips = catalog.get(mood) or []
        if not clips:
            return speech_path
        with self._lock:
            choices = [c for c in clips if c != self._last_clip] or clips
            clip_name = random.choice(choices)
            self._last_clip = clip_name
        merged_path = self._merge(Path(speech_path), clip_name)
        return merged_path if merged_path else speech_path

    def _merge(self, speech_path: Path, clip_name: str) -> str | None:
        import subprocess
        import tempfile
        import wave

        digest = hashlib.sha256(
            f"tris-intro-v1|{clip_name}|{speech_path.name}".encode("utf-8")
        ).hexdigest()[:24]
        TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        output_path = (TTS_CACHE_DIR / f"intro-{digest}.wav").resolve()
        if output_path.is_file() and output_path.stat().st_size > 44:
            return str(output_path)
        temp_wav: str | None = None
        try:
            ffmpeg = self._ensure_ffmpeg()
            with wave.open(str(speech_path), "rb") as probe:
                channels = probe.getnchannels()
                rate = probe.getframerate()
                sampwidth = probe.getsampwidth()
                speech_frames = probe.readframes(probe.getnframes())

            # Convert the clip to the exact PCM shape of the Piper speech so
            # the two can be concatenated as raw frames (no ffprobe needed).
            with tempfile.NamedTemporaryFile(
                suffix=".wav", delete=False
            ) as handle:
                temp_wav = handle.name
            convert = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(VOICE_LINES_DIR / clip_name),
                    "-ar",
                    str(rate),
                    "-ac",
                    str(channels),
                    "-sample_fmt",
                    "s16" if sampwidth == 2 else "s16",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    temp_wav,
                ],
                capture_output=True,
                timeout=30,
                check=False,
            )
            if convert.returncode != 0:
                logger.warning(
                    "Voice clip convert failed: %s", convert.stderr.decode("utf-8", "replace")[:200]
                )
                return None
            with wave.open(temp_wav, "rb") as clip_file:
                clip_frames = clip_file.readframes(clip_file.getnframes())

            gap_frames = b"\x00" * int(
                rate * INTRO_GAP_MS / 1000 * channels * sampwidth
            )
            with wave.open(str(output_path), "wb") as merged:
                merged.setnchannels(channels)
                merged.setsampwidth(sampwidth)
                merged.setframerate(rate)
                merged.writeframes(clip_frames + gap_frames + speech_frames)
            if not output_path.is_file() or output_path.stat().st_size <= 44:
                return None
            return str(output_path)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            logger.warning("Voice line merge failed: %s", exc)
            return None
        finally:
            if temp_wav:
                try:
                    Path(temp_wav).unlink(missing_ok=True)
                except OSError:
                    pass
