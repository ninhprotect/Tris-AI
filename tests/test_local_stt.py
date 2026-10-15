from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from services.local_stt import LocalSTT, LocalSTTError, get_local_stt


class FakeModel:
    def __init__(self, text: str = " xin chào ") -> None:
        self.text = text
        self.calls: list[tuple[str, dict]] = []

    def transcribe(self, path: str, **kwargs):
        self.calls.append((path, kwargs))
        parts = [SimpleNamespace(text=value) for value in self.text.split("|")]
        return iter(parts), SimpleNamespace(language=kwargs["language"])


class LocalSTTTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model_dir = self.root / "base"
        self.model_dir.mkdir()
        for name in ("config.json", "model.bin", "tokenizer.json"):
            (self.model_dir / name).write_bytes(b"local-test-model")
        self.audio = self.root / "speech.wav"
        self._write_wav(self.audio, seconds=0.5)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _write_wav(path: Path, seconds: float) -> None:
        rate = 16_000
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(b"\x01\x00" * int(rate * seconds))

    def test_model_is_lazy_cached_and_vad_is_enabled(self) -> None:
        fake = FakeModel(" xin| chào ")
        factory = Mock(return_value=fake)
        service = LocalSTT(self.model_dir, model_factory=factory)
        self.assertFalse(service.status()["model_loaded"])

        first = service.transcribe(self.audio, "vi")
        second = service.transcribe(self.audio, "vi")

        self.assertEqual(first.text, "xin chào")
        self.assertEqual(second.language, "vi")
        self.assertEqual(factory.call_count, 1)
        _, factory_kwargs = factory.call_args
        self.assertEqual(factory_kwargs["device"], "cpu")
        self.assertEqual(factory_kwargs["compute_type"], "int8")
        self.assertTrue(factory_kwargs["local_files_only"])
        self.assertEqual(len(fake.calls), 2)
        options = fake.calls[0][1]
        self.assertTrue(options["vad_filter"])
        self.assertFalse(options["condition_on_previous_text"])
        self.assertEqual(options["language"], "vi")

    def test_broken_onnxruntime_falls_back_to_decoding_without_vad(self) -> None:
        class NoVadModel(FakeModel):
            def transcribe(self, path: str, **kwargs):
                if kwargs["vad_filter"]:
                    self.calls.append((path, kwargs))
                    try:
                        raise ImportError("DLL load failed while importing onnxruntime_pybind11_state")
                    except ImportError as exc:
                        raise RuntimeError("Applying the VAD filter requires the onnxruntime package") from exc
                return super().transcribe(path, **kwargs)

        fake = NoVadModel(" xin chào ")
        service = LocalSTT(self.model_dir, model_factory=lambda *args, **kwargs: fake)

        first = service.transcribe(self.audio, "vi")
        second = service.transcribe(self.audio, "vi")

        self.assertEqual(first.text, "xin chào")
        self.assertEqual(second.text, "xin chào")
        # One failed VAD attempt, then every turn decodes directly.
        self.assertEqual([call[1]["vad_filter"] for call in fake.calls], [True, False, False])
        self.assertFalse(service.status()["vad_enabled"])

    def test_unrelated_decode_failure_is_not_retried(self) -> None:
        model = Mock()
        model.transcribe.side_effect = ValueError("corrupt tensor")
        service = LocalSTT(self.model_dir, model_factory=lambda *args, **kwargs: model)
        with self.assertRaisesRegex(LocalSTTError, "Không thể chuyển giọng nói"):
            service.transcribe(self.audio, "vi")
        model.transcribe.assert_called_once()
        self.assertTrue(service.status()["vad_enabled"])

    def test_result_is_serializable(self) -> None:
        result = LocalSTT(self.model_dir, model_factory=lambda *args, **kwargs: FakeModel()).transcribe(
            self.audio, "vi"
        )
        payload = result.as_dict()
        self.assertEqual(payload["text"], "xin chào")
        self.assertAlmostEqual(payload["audio_seconds"], 0.5, places=2)
        self.assertEqual(payload["model"], "base")

    def test_missing_model_never_invokes_factory(self) -> None:
        factory = Mock()
        service = LocalSTT(self.root / "missing", model_factory=factory)
        with self.assertRaisesRegex(LocalSTTError, "setup_stt.ps1"):
            service.transcribe(self.audio, "vi")
        factory.assert_not_called()

    def test_incomplete_model_is_not_reported_ready(self) -> None:
        (self.model_dir / "tokenizer.json").unlink()
        service = LocalSTT(self.model_dir, model_factory=lambda *args, **kwargs: FakeModel())
        status = service.status()
        self.assertFalse(status["ready"])
        self.assertIn("tokenizer.json", status["missing_files"])

    def test_oversize_audio_is_rejected_before_loading_model(self) -> None:
        factory = Mock(return_value=FakeModel())
        service = LocalSTT(self.model_dir, model_factory=factory, max_audio_bytes=20)
        with self.assertRaisesRegex(LocalSTTError, "giới hạn"):
            service.transcribe(self.audio, "vi")
        factory.assert_not_called()

    def test_long_audio_is_rejected_before_loading_model(self) -> None:
        long_audio = self.root / "long.wav"
        self._write_wav(long_audio, seconds=1.5)
        factory = Mock(return_value=FakeModel())
        service = LocalSTT(
            self.model_dir,
            model_factory=factory,
            max_audio_seconds=1,
            max_audio_bytes=100_000,
        )
        with self.assertRaisesRegex(LocalSTTError, "1 giây"):
            service.transcribe(long_audio, "en")
        factory.assert_not_called()

    def test_empty_transcript_has_clear_error(self) -> None:
        service = LocalSTT(
            self.model_dir,
            model_factory=lambda *args, **kwargs: FakeModel("   "),
        )
        with self.assertRaisesRegex(LocalSTTError, "Không phát hiện lời nói"):
            service.transcribe(self.audio, "vi")

    def test_invalid_language_and_extension_are_rejected(self) -> None:
        service = LocalSTT(self.model_dir, model_factory=lambda *args, **kwargs: FakeModel())
        with self.assertRaisesRegex(LocalSTTError, "vi, en hoặc auto"):
            service.transcribe(self.audio, "fr")  # type: ignore[arg-type]
        bad = self.root / "speech.txt"
        bad.write_text("not audio", encoding="utf-8")
        with self.assertRaisesRegex(LocalSTTError, "Định dạng"):
            service.transcribe(bad, "vi")

    def test_auto_language_detection_does_not_force_ui_language(self) -> None:
        fake = FakeModel(" hello ")
        service = LocalSTT(self.model_dir, model_factory=lambda *args, **kwargs: fake)
        result = service.transcribe(self.audio, "auto")
        self.assertIsNone(fake.calls[0][1]["language"])
        self.assertEqual(result.text, "hello")

    def test_warmup_loads_without_transcribing(self) -> None:
        factory = Mock(return_value=FakeModel())
        service = LocalSTT(self.model_dir, model_factory=factory)
        status = service.warmup()
        self.assertTrue(status["ready"])
        self.assertTrue(status["model_loaded"])
        factory.assert_called_once()

    def test_process_singleton_is_stable(self) -> None:
        self.assertIs(get_local_stt(), get_local_stt())


if __name__ == "__main__":
    unittest.main()
