"""Offline text-to-speech for the original Tris AI mascot voice.

The preset intentionally uses licensed stock Piper voices and synthesis
parameters only.  It does not train on, clone, or reproduce a character or
performer's recordings.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import threading
import wave
from pathlib import Path

from config.settings import (
    TTS_CACHE_DIR,
    TTS_CUTE_PITCH,
    TTS_CUTE_TEMPO,
    TTS_ENABLED,
    TTS_EN_MODEL,
    TTS_EN_LENGTH_SCALE,
    TTS_EN_PITCH,
    TTS_EN_TEMPO,
    TTS_MAX_CACHE_FILES,
    TTS_MAX_CHARACTERS,
    TTS_MODEL_DIR,
    TTS_VI_MODEL,
)

logger = logging.getLogger(__name__)


class LocalTTSError(RuntimeError):
    """Raised when local speech synthesis is unavailable or fails safely."""


def _piper_import_error(exc: ImportError) -> LocalTTSError:
    """Explain why Piper cannot load instead of surfacing a raw ImportError."""
    logger.error("Piper TTS failed to import: %s", exc)
    if "DLL load failed" in str(exc):
        # Piper runs on onnxruntime, which needs MSVCP140_1.dll from a recent
        # Visual C++ Redistributable; Windows without it fails at import time.
        return LocalTTSError(
            "Bộ đọc giọng local (Piper/onnxruntime) không nạp được vì máy thiếu Microsoft Visual C++ "
            "Redistributable x64. Hãy cài bản mới tại https://aka.ms/vs/17/release/vc_redist.x64.exe "
            "rồi mở lại Tris AI."
        )
    return LocalTTSError("Chưa cài thư viện giọng local Piper. Hãy chạy scripts/setup_tts.py.")


# Emoji and pictographic icons that Piper/espeak would otherwise read aloud by
# name ("play button", "copyright", "hash").  Letters (incl. Vietnamese
# diacritics), digits, punctuation and currency are outside these ranges and
# are kept; arrows are turned into pauses by _ARROW_PAUSE instead.  Escapes are
# deliberate: zero-width characters must stay visible in review.
_ICON_PATTERN = re.compile(
    "[#*]️?⃣"  # "#" / "*" keycaps, otherwise a bare "#" is read "hash"
    "|["
    "\U0001F000-\U0001FAFF"  # emoji, pictographs, flags, skin-tone modifiers
    "☀-➠➢-➿"  # misc symbols + dingbats (minus arrow U+27A1)
    "⬀-⬄⬈-⯿"  # misc symbols and arrows (minus U+2B05-U+2B07)
    "⌀-⏿"  # misc technical (watches, hourglasses)
    "■-◿"  # geometric shapes used as bullets/buttons (▶ ◀ ▪ ◼)
    "©®™ℹ⁉Ⓜ"  # © ® ™ ℹ ⁉ Ⓜ
    "〰〽㊗㊙"  # 〰 〽 ㊗ ㊙
    "︎️‍⃣"  # variation selectors, ZWJ, keycap
    "\U000E0020-\U000E007F"  # tag characters (subdivision flags)
    "]+"
)
# Arrows ("go → went → gone") are read as "right arrow"; a comma keeps the
# pause they stand for.  U+27A1 and U+2B05-U+2B07 are the emoji arrows.
_ARROW_CHARS = "←-⇿➡⤴⤵⬅-⬇"
_ARROW = f"[{_ARROW_CHARS}]"
# Only pause after a word: not after punctuation, an opening bracket, another
# arrow, or a closer that already ends a sentence such as "!)".
_PAUSE_AFTER = (
    r"(?<=[^\s.!?,;:…(\[{" + _ARROW_CHARS + r"])"
    r"(?<![.!?,;:…][)\]}\"'”’])"
)
_ARROW_PAUSE = re.compile(_PAUSE_AFTER + r"[^\S\n]*" + _ARROW + r"[^\S\n]*")
_ARROW_LEFTOVER = re.compile(_ARROW)
# Line breaks become plain spaces later, so mark unpunctuated ones as a sentence
# end, e.g. "tutor 😊\n\nHow are you?" -> "tutor. How are you?".
_LINE_PAUSE = re.compile(_PAUSE_AFTER + r"[^\S\n]*\n\s*")
# Brackets left empty once icons/markup are gone, e.g. "(😊)" -> "( )".
_EMPTY_BRACKETS = re.compile(r"\(\s*\)|\[\s*\]|\{\s*\}")


def speech_text(value: str, limit: int = TTS_MAX_CHARACTERS) -> str:
    """Convert a Markdown answer into a short, speakable plain-text passage."""
    text = str(value or "")
    text = _ICON_PATTERN.sub(" ", text)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^]]*]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_>|]", " ", text)
    text = _ARROW_PAUSE.sub(", ", text)
    text = _ARROW_LEFTOVER.sub(" ", text)  # arrows after punctuation or at the start
    previous = None
    while previous != text:  # repeat so nested pairs like "([ ])" also go
        previous = text
        text = _EMPTY_BRACKETS.sub(" ", text)
    text = _LINE_PAUSE.sub(". ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,")
    if len(text) <= limit:
        return text
    shortened = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{shortened}."


class TrisLocalVoice:
    """Lazy, bounded Piper TTS service shared by the web and future mobile API."""

    def __init__(self) -> None:
        self._voices: dict[str, object] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _language(value: str) -> str:
        return "en" if str(value or "").casefold().startswith("en") else "vi"

    @staticmethod
    def _model_name(language: str) -> str:
        return TTS_EN_MODEL if language == "en" else TTS_VI_MODEL

    @staticmethod
    def speech_profile(language: str) -> tuple[float, float, float]:
        if language == 'en':
            return (max(1.0, min(1.6, TTS_EN_LENGTH_SCALE)),
                    max(.8, min(1.6, TTS_EN_PITCH)), max(.8, min(1.5, TTS_EN_TEMPO)))
        # Nhịp đọc tự nhiên (1.0): câu ngắn hơn → tổng hợp nhanh hơn trên CPU.
        return (1.0, max(.8, min(1.6, TTS_CUTE_PITCH)), max(.8, min(1.5, TTS_CUTE_TEMPO)))

    @classmethod
    def cache_profile(cls, language: str) -> str:
        if language == 'vi':
            return 'tris-clone-v3'  # keep approved Vietnamese cache untouched
        length, pitch, tempo = cls.speech_profile(language)
        return f'tris-clone-en-v4|{TTS_EN_MODEL}|{length:.3f}|{pitch:.3f}|{tempo:.3f}'

    def available(self, language: str = "vi") -> bool:
        model = TTS_MODEL_DIR / f"{self._model_name(self._language(language))}.onnx"
        return TTS_ENABLED and model.is_file() and Path(f"{model}.json").is_file()

    def _voice(self, language: str) -> object:
        if language in self._voices:
            return self._voices[language]
        model = TTS_MODEL_DIR / f"{self._model_name(language)}.onnx"
        config = Path(f"{model}.json")
        if not model.is_file() or not config.is_file():
            raise LocalTTSError(
                "Chưa cài mô hình giọng local. Hãy chạy scripts/setup_tts.py."
            )
        try:
            from piper import PiperVoice

            voice = PiperVoice.load(model, config_path=config, use_cuda=False)
        except ImportError as exc:
            raise _piper_import_error(exc) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise LocalTTSError("Không thể khởi tạo mô hình giọng local.") from exc
        self._voices[language] = voice
        return voice

    def preload(self) -> list[str]:
        """Load the installed Piper voices into RAM (startup warmup, no downloads)."""
        loaded = []
        for language in ("vi", "en"):
            if self.available(language):
                with self._lock:
                    self._voice(language)
                loaded.append(language)
        return loaded

    @staticmethod
    def _prune_cache() -> None:
        files = sorted(
            TTS_CACHE_DIR.glob("*.wav"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for old_file in files[TTS_MAX_CACHE_FILES:]:
            try:
                old_file.unlink()
            except OSError:
                pass

    def synthesize(self, text: str, language: str = "vi") -> str:
        """Create or reuse a bounded local WAV file and return its absolute path."""
        if not TTS_ENABLED:
            raise LocalTTSError("Giọng đọc local đang bị tắt trong cấu hình.")
        clean_text = speech_text(text)
        if not clean_text:
            raise LocalTTSError("Không có nội dung phù hợp để đọc.")
        selected_language = self._language(language)
        length_scale, pitch, tempo = self.speech_profile(selected_language)
        profile = 'tris-calm-v3' if selected_language == 'vi' else self.cache_profile('en')
        digest = hashlib.sha256(
            f"{profile}|{selected_language}|{clean_text}|{pitch:.3f}|{tempo:.3f}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        output_path = (TTS_CACHE_DIR / f"{selected_language}-{digest}.wav").resolve()
        if output_path.is_file() and output_path.stat().st_size > 44:
            return str(output_path)

        try:
            from piper import SynthesisConfig

            # A calm, clear tutor preset: relaxed pace so learners can follow,
            # restrained variance, normalized volume.
            synthesis = SynthesisConfig(
                length_scale=length_scale,
                noise_scale=0.62,
                noise_w_scale=0.72,
                normalize_audio=True,
                volume=0.94,
            )
            with self._lock:
                voice = self._voice(selected_language)
                with wave.open(str(output_path), "wb") as wav_file:
                    voice.synthesize_wav(clean_text, wav_file, syn_config=synthesis)
            if not output_path.is_file() or output_path.stat().st_size <= 44:
                raise LocalTTSError("Mô hình không tạo được dữ liệu âm thanh.")
            if abs(pitch - 1) > .01 or abs(tempo - 1) > .01:
                self._apply_cute_tone(output_path, pitch, tempo)
            self._prune_cache()
            return str(output_path)
        except LocalTTSError:
            output_path.unlink(missing_ok=True)
            raise
        except ImportError as exc:
            output_path.unlink(missing_ok=True)
            raise _piper_import_error(exc) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            output_path.unlink(missing_ok=True)
            raise LocalTTSError("Không thể tạo giọng đọc cho câu trả lời này.") from exc

    @staticmethod
    def _ffmpeg_executable() -> str:
        import shutil

        resolved = shutil.which("ffmpeg")
        if resolved:
            return resolved
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()

    def _apply_cute_tone(self, output_path: Path, pitch: float, tempo: float) -> None:
        """Raise pitch and brighten delivery with ffmpeg; keep duration close."""
        temp_path = output_path.with_suffix(".cute.wav")
        try:
            with wave.open(str(output_path), "rb") as probe:
                rate = probe.getframerate()
            result = subprocess.run(
                [
                    self._ffmpeg_executable(),
                    "-y",
                    "-i",
                    str(output_path),
                    "-af",
                    # asetrate raises pitch but also speeds up by `pitch`, so
                    # atempo=tempo/pitch restores the intended delivery pace.
                    f"asetrate={int(rate * pitch)},atempo={tempo / pitch:.5f}",
                    "-ar",
                    str(rate),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    str(temp_path),
                ],
                capture_output=True,
                timeout=60,
                check=False,
            )
            if result.returncode != 0 or not temp_path.is_file() or temp_path.stat().st_size <= 44:
                logger.warning(
                    "Cute tone skipped: %s",
                    result.stderr.decode("utf-8", "replace")[:200],
                )
                temp_path.unlink(missing_ok=True)
                return
            temp_path.replace(output_path)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            logger.warning("Cute tone failed: %s", exc)
            temp_path.unlink(missing_ok=True)


tris_voice = TrisLocalVoice()
