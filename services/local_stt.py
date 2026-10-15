"""Bounded, offline speech-to-text for microphone input.

The service intentionally accepts only a model already installed inside the
project (or at ``STT_MODEL_DIR``).  A browser request must never trigger a
model download.  ``faster-whisper`` and the local model are loaded lazily and
kept in RAM so subsequent microphone turns do not pay the load cost again.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import re
import threading
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal

from config.settings import PROJECT_ROOT


logger = logging.getLogger(__name__)

Language = Literal["vi", "en"]
InputLanguage = Literal["vi", "en", "auto"]

_DEFAULT_MODEL_ROOT = Path(PROJECT_ROOT) / "runtime" / "stt" / "models"
_DEFAULT_SMALL_MODEL = _DEFAULT_MODEL_ROOT / "small"
_DEFAULT_BASE_MODEL = _DEFAULT_MODEL_ROOT / "base"
_DEFAULT_INSTALLED_MODEL = (
    _DEFAULT_SMALL_MODEL
    if all((_DEFAULT_SMALL_MODEL / name).is_file() for name in ("config.json", "model.bin", "tokenizer.json"))
    else _DEFAULT_BASE_MODEL
)
DEFAULT_MODEL_DIR = Path(
    os.getenv("STT_MODEL_DIR", str(_DEFAULT_INSTALLED_MODEL))
).expanduser()
DEFAULT_DEVICE = os.getenv("STT_DEVICE", "cpu").strip().casefold() or "cpu"
DEFAULT_COMPUTE_TYPE = os.getenv("STT_COMPUTE_TYPE", "int8").strip() or "int8"
DEFAULT_MAX_AUDIO_BYTES = int(os.getenv("STT_MAX_AUDIO_BYTES", str(12 * 1024 * 1024)))
DEFAULT_MAX_AUDIO_SECONDS = float(os.getenv("STT_MAX_AUDIO_SECONDS", "90"))
# Physical cores, not hyper-threads: CTranslate2 slows down when it oversubscribes.
DEFAULT_CPU_THREADS = max(1, int(os.getenv("STT_CPU_THREADS", str(max(1, (os.cpu_count() or 2) // 2)))))

SUPPORTED_AUDIO_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".oga",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}
REQUIRED_MODEL_FILES = ("config.json", "model.bin", "tokenizer.json")
SETUP_HINT = (
    "Hãy chạy scripts\\setup_stt.ps1 để cài faster-whisper 1.2.1 và model small "
    "vào runtime\\stt\\models\\small, sau đó khởi động lại Tris AI."
)


class LocalSTTError(RuntimeError):
    """A safe, user-facing local transcription failure."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def _is_vad_unavailable(exc: BaseException) -> bool:
    """True when faster-whisper failed only because Silero VAD cannot load.

    Silero VAD runs on onnxruntime.  On Windows without a recent Visual C++
    Redistributable (MSVCP140_1.dll) its DLL fails to import, and
    faster-whisper reports "Applying the VAD filter requires the onnxruntime
    package".  Decoding itself (CTranslate2) still works in that case.
    """

    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ImportError) or "onnxruntime" in str(current).casefold():
            return True
        current = current.__cause__ or current.__context__
    return False


@dataclass(frozen=True)
class TranscriptionResult:
    """Serializable result returned by the workspace transcription route."""

    text: str
    language: Language
    audio_seconds: float
    processing_seconds: float
    model: str
    device: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class LocalSTT:
    """Lazy faster-whisper adapter with strict local-only and input bounds."""

    def __init__(
        self,
        model_dir: Path | str = DEFAULT_MODEL_DIR,
        *,
        device: str = DEFAULT_DEVICE,
        compute_type: str = DEFAULT_COMPUTE_TYPE,
        max_audio_bytes: int = DEFAULT_MAX_AUDIO_BYTES,
        max_audio_seconds: float = DEFAULT_MAX_AUDIO_SECONDS,
        cpu_threads: int = DEFAULT_CPU_THREADS,
        model_factory: Callable[..., object] | None = None,
    ) -> None:
        self.model_dir = Path(model_dir).expanduser().resolve()
        self.device = device.casefold()
        if self.device not in {"cpu", "cuda", "auto"}:
            raise ValueError("STT_DEVICE phải là cpu, cuda hoặc auto.")
        self.compute_type = compute_type
        self.max_audio_bytes = max(1, int(max_audio_bytes))
        self.max_audio_seconds = max(1.0, float(max_audio_seconds))
        self.cpu_threads = max(1, int(cpu_threads))
        self._model_factory = model_factory
        self._model: object | None = None
        self._model_lock = threading.RLock()
        self._transcription_lock = threading.Lock()
        # Becomes False after Silero VAD fails to load once, so later turns skip
        # the doomed attempt instead of failing every microphone recording.
        self._vad_usable = True

    def _missing_model_files(self) -> list[str]:
        if not self.model_dir.is_dir():
            return list(REQUIRED_MODEL_FILES)
        return [name for name in REQUIRED_MODEL_FILES if not (self.model_dir / name).is_file()]

    def _require_local_model(self) -> None:
        missing = self._missing_model_files()
        if missing:
            detail = ", ".join(missing)
            raise LocalSTTError(
                f"Chưa có model nhận dạng giọng nói local ({detail}) tại {self.model_dir}. {SETUP_HINT}",
                503,
            )

    def _load_model(self) -> object:
        self._require_local_model()
        factory = self._model_factory
        if factory is None:
            try:
                from faster_whisper import WhisperModel
            except (ImportError, OSError) as exc:
                raise LocalSTTError(
                    f"STT local chưa được cài hoặc thiếu thư viện chạy. {SETUP_HINT}", 503
                ) from exc
            factory = WhisperModel
        try:
            # Passing an absolute model directory plus local_files_only=True is
            # deliberate: inference requests can never contact Hugging Face.
            return factory(
                str(self.model_dir),
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=self.cpu_threads,
                num_workers=1,
                local_files_only=True,
            )
        except LocalSTTError:
            raise
        except Exception as exc:
            raise LocalSTTError(
                f"Không nạp được model STT local ở {self.model_dir}. {SETUP_HINT}", 503
            ) from exc

    def _get_model(self) -> object:
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is None:
                self._model = self._load_model()
        return self._model

    def status(self) -> dict[str, object]:
        """Report availability without loading weights or downloading data."""

        dependency = self._model_factory is not None or importlib.util.find_spec("faster_whisper") is not None
        missing = self._missing_model_files()
        return {
            "ready": bool(dependency and not missing),
            "dependency_installed": bool(dependency),
            "model_installed": not missing,
            "model_loaded": self._model is not None,
            "model_dir": str(self.model_dir),
            "model": self.model_dir.name,
            "device": self.device,
            "compute_type": self.compute_type,
            "max_audio_seconds": self.max_audio_seconds,
            "max_audio_bytes": self.max_audio_bytes,
            "missing_files": missing,
            "vad_enabled": self._vad_usable,
        }

    def warmup(self) -> dict[str, object]:
        """Load installed weights into RAM; never installs or downloads them."""

        self._get_model()
        return self.status()

    def _wav_duration(self, path: Path) -> float | None:
        if path.suffix.casefold() != ".wav":
            return None
        try:
            with wave.open(str(path), "rb") as stream:
                rate = stream.getframerate()
                return stream.getnframes() / rate if rate else 0.0
        except (EOFError, wave.Error):
            # WAVE_FORMAT_EXTENSIBLE and unusual WAV containers are handled by
            # PyAV below, which ships with faster-whisper.
            return None

    def _audio_duration(self, path: Path) -> float:
        duration = self._wav_duration(path)
        if duration is not None:
            return duration
        try:
            import av
        except (ImportError, OSError) as exc:
            raise LocalSTTError(f"Thiếu bộ giải mã âm thanh local. {SETUP_HINT}", 503) from exc

        seconds = 0.0
        try:
            with av.open(str(path), mode="r") as container:
                streams = [stream for stream in container.streams if stream.type == "audio"]
                if not streams:
                    raise LocalSTTError("Tệp ghi âm không chứa luồng âm thanh.")
                stream = streams[0]
                # Decode without retaining PCM.  This works for MediaRecorder
                # WebM files that often omit reliable container duration.
                for packet in container.demux(stream):
                    for frame in packet.decode():
                        rate = int(frame.sample_rate or 0)
                        samples = int(frame.samples or 0)
                        if rate > 0 and samples > 0:
                            seconds += samples / rate
                        elif frame.duration is not None and frame.time_base is not None:
                            seconds += float(frame.duration * frame.time_base)
                        if seconds > self.max_audio_seconds:
                            break
                    if seconds > self.max_audio_seconds:
                        break
        except LocalSTTError:
            raise
        except Exception as exc:
            raise LocalSTTError("Không đọc được tệp ghi âm. Hãy thu lại bằng micro.") from exc
        return seconds

    def _validate_audio(self, source: Path | str) -> tuple[Path, float]:
        path = Path(source).expanduser().resolve()
        if not path.is_file():
            raise LocalSTTError("Không tìm thấy tệp ghi âm tạm.")
        if path.suffix.casefold() not in SUPPORTED_AUDIO_SUFFIXES:
            raise LocalSTTError("Định dạng ghi âm chưa được hỗ trợ.")
        size = path.stat().st_size
        if size <= 0:
            raise LocalSTTError("Tệp ghi âm trống. Hãy kiểm tra micro rồi thử lại.")
        if size > self.max_audio_bytes:
            raise LocalSTTError(
                f"Bản ghi vượt giới hạn {self.max_audio_bytes // (1024 * 1024)} MB. Hãy thu đoạn ngắn hơn."
            )
        self._require_local_model()
        duration = self._audio_duration(path)
        if duration <= 0.05:
            raise LocalSTTError("Không tìm thấy âm thanh trong bản ghi. Hãy kiểm tra micro rồi thử lại.")
        if duration > self.max_audio_seconds:
            raise LocalSTTError(
                f"Bản ghi vượt giới hạn {int(self.max_audio_seconds)} giây. Hãy thu đoạn ngắn hơn."
            )
        return path, duration

    def _decode(self, model: object, source: Path, language: InputLanguage, *, vad: bool) -> tuple[str, object]:
        options: dict[str, object] = {"vad_filter": vad}
        if vad:
            options["vad_parameters"] = {
                "min_speech_duration_ms": 180,
                "min_silence_duration_ms": 450,
                "speech_pad_ms": 180,
            }
        segments, info = model.transcribe(
            str(source),
            language=None if language == "auto" else language,
            task="transcribe",
            # Greedy decoding keeps short push-to-talk clips responsive
            # on the target desktop CPU; the multilingual small model
            # provides the accuracy instead of an expensive beam search.
            beam_size=1,
            temperature=0.0,
            condition_on_previous_text=False,
            word_timestamps=False,
            hotwords=(
                "Tris, Tris AI, Nguyễn Hải Hà Ninh, Đại học Thủ Dầu Một, "
                "tiếng Anh, tiếng Việt, micro, microphone"
            ),
            **options,
        )
        text = " ".join(str(segment.text).strip() for segment in segments if str(segment.text).strip())
        return text, info

    def transcribe(self, path: Path | str, language: InputLanguage = "auto") -> TranscriptionResult:
        """Transcribe one bounded local file using VAD and a RAM-cached model."""

        if language not in {"vi", "en", "auto"}:
            raise LocalSTTError("Ngôn ngữ nhận dạng phải là vi, en hoặc auto.")
        source, audio_seconds = self._validate_audio(path)
        model = self._get_model()
        started = time.perf_counter()
        try:
            with self._transcription_lock:
                try:
                    text, info = self._decode(model, source, language, vad=self._vad_usable)
                except Exception as exc:
                    if not (self._vad_usable and _is_vad_unavailable(exc)):
                        raise
                    logger.warning(
                        "Silero VAD unavailable (onnxruntime failed to load: %s); transcribing without VAD. "
                        "Install the latest Microsoft Visual C++ Redistributable x64 to restore it.",
                        exc,
                    )
                    self._vad_usable = False
                    text, info = self._decode(model, source, language, vad=False)
        except Exception as exc:
            logger.exception("Local STT failed for %s", source.name)
            raise LocalSTTError("Không thể chuyển giọng nói thành văn bản. Hãy thu lại rồi thử lại.") from exc

        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            raise LocalSTTError("Không phát hiện lời nói rõ ràng. Hãy nói gần micro hơn rồi thử lại.")
        fallback_language: Language = "vi" if language == "auto" else language
        detected = str(getattr(info, "language", fallback_language) or fallback_language).casefold()
        result_language: Language = detected if detected in {"vi", "en"} else fallback_language
        return TranscriptionResult(
            text=text,
            language=result_language,
            audio_seconds=round(audio_seconds, 3),
            processing_seconds=round(time.perf_counter() - started, 3),
            model=self.model_dir.name,
            device=self.device,
        )


_LOCAL_STT: LocalSTT | None = None
_LOCAL_STT_LOCK = threading.Lock()


def get_local_stt() -> LocalSTT:
    """Return the process-wide service so loaded weights remain in RAM."""

    global _LOCAL_STT
    if _LOCAL_STT is not None:
        return _LOCAL_STT
    with _LOCAL_STT_LOCK:
        if _LOCAL_STT is None:
            _LOCAL_STT = LocalSTT()
    return _LOCAL_STT

