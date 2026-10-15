"""Tests for the local media generation service."""

import subprocess
import tempfile
import unittest
import json
from unittest.mock import Mock, patch
from pathlib import Path
from types import SimpleNamespace

import httpx

import services.image_gen as image_gen_module
from services.image_gen import ImageGenError, ImageGenService
from services.image_prompt import ImagePromptError, PreparedImagePrompt


class Completed:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


def make_runtime(root: Path) -> Path:
    runtime = root / "imagegen"
    (runtime / ".venv" / "Scripts").mkdir(parents=True)
    (runtime / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    (runtime / "generate.py").write_text("# fake", encoding="utf-8")
    return runtime


class ImageGenServiceTests(unittest.TestCase):
    def setUp(self):
        self.outputs = tempfile.TemporaryDirectory()
        self.addCleanup(self.outputs.cleanup)
        output_patch = patch.object(image_gen_module, "GENERATED_DIR", Path(self.outputs.name))
        output_patch.start()
        self.addCleanup(output_patch.stop)

    def test_generate_creates_requested_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = make_runtime(Path(directory))

            def runner(command, **kwargs):
                out = Path(command[command.index("--out") + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"fake-png")
                self.assertIn("--mode", command)
                self.assertEqual(command[command.index("--mode") + 1], "gif")
                return Completed()

            service = ImageGenService(runtime_dir=runtime, runner=runner)
            path = service.generate("a red house", mode="gif", frames=4, unload_ollama=False)
        self.assertEqual(path.suffix, ".gif")
        self.assertTrue(path.name.startswith("tris_gif_"))

    def test_missing_runtime_mentions_setup_script(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ImageGenService(runtime_dir=Path(directory) / "empty")
            with self.assertRaises(ImageGenError) as ctx:
                service.generate("a house")
        self.assertIn("setup_imagegen", str(ctx.exception))

    def test_empty_prompt_and_bad_mode_are_rejected(self) -> None:
        service = ImageGenService(runtime_dir=Path("unused"), runner=lambda *a, **k: Completed())
        with self.assertRaises(ImageGenError):
            service.generate("   ")
        with self.assertRaises(ImageGenError):
            service.generate("a house", mode="mp3")

    def test_failed_subprocess_surfaces_last_error_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = make_runtime(Path(directory))
            failing = Completed(returncode=1, stderr="CUDA out of memory\nline2")
            service = ImageGenService(runtime_dir=runtime, runner=lambda *a, **k: failing)
            with self.assertRaises(ImageGenError) as ctx:
                service.generate("a house", unload_ollama=False)
        self.assertIn("line2", str(ctx.exception))

    def test_timeout_maps_to_safe_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = make_runtime(Path(directory))

            def runner(*args, **kwargs):
                raise subprocess.TimeoutExpired(cmd="x", timeout=1)

            service = ImageGenService(runtime_dir=runtime, runner=runner)
            with self.assertRaises(ImageGenError):
                service.generate("a house", unload_ollama=False)

    def test_unload_models_ignores_network_errors(self) -> None:
        with patch.object(image_gen_module.httpx, "Client") as factory:
            client = factory.return_value.__enter__.return_value
            client.get.side_effect = httpx.ConnectError("refused")
            ImageGenService._unload_ollama_models()
            client.post.assert_not_called()

    def test_unload_only_actual_resident_models_without_proxy_inheritance(self):
        with patch.object(image_gen_module.httpx, "Client") as factory:
            client = factory.return_value.__enter__.return_value
            client.get.return_value.json.return_value = {"models": [
                {"name": "custom-loaded:latest"}, {"model": "embedding:latest"},
                {"name": "custom-loaded:latest"}, {}, "invalid", {"name": 123},
            ]}
            ImageGenService._unload_ollama_models()
            factory.assert_called_once_with(timeout=3.0, trust_env=False)
            client.get.assert_called_once_with(f"{image_gen_module.OLLAMA_HOST}/api/ps")
            requested = [call.kwargs["json"]["model"] for call in client.post.call_args_list]
            self.assertEqual(requested, ["custom-loaded:latest", "embedding:latest"])
            for call in client.post.call_args_list:
                self.assertEqual(call.kwargs["json"]["keep_alive"], 0)
                self.assertLessEqual(call.kwargs["timeout"], 3.0)

    def test_unload_empty_residency_never_requests_installed_candidates(self):
        with patch.object(image_gen_module.httpx, "Client") as factory:
            client = factory.return_value.__enter__.return_value
            client.get.return_value.json.return_value = {"models": []}
            ImageGenService._unload_ollama_models()
            client.post.assert_not_called()

    def test_unload_stops_at_overall_deadline(self):
        with patch.object(image_gen_module.httpx, "Client") as factory:
            client = factory.return_value.__enter__.return_value
            client.get.return_value.json.return_value = {"models": [
                {"name": "one:latest"}, {"name": "two:latest"},
            ]}
            with patch.object(image_gen_module.time, "monotonic", side_effect=[100.0, 109.5, 110.1]):
                ImageGenService._unload_ollama_models()
            client.post.assert_called_once()
            self.assertEqual(client.post.call_args.kwargs["timeout"], 0.5)

    def test_unload_post_error_does_not_prevent_remaining_resident_release(self):
        with patch.object(image_gen_module.httpx, "Client") as factory:
            client = factory.return_value.__enter__.return_value
            client.get.return_value.json.return_value = {"models": [
                {"name": "one:latest"}, {"name": "two:latest"},
            ]}
            client.post.side_effect = [httpx.ConnectError("gone"), Mock()]
            ImageGenService._unload_ollama_models()
            self.assertEqual(client.post.call_count, 2)

    def test_translates_before_unloading_and_keeps_actual_prompt_metadata(self):
        events = []
        with tempfile.TemporaryDirectory() as directory:
            runtime = make_runtime(Path(directory))
            def prepare(prompt):
                events.append("prepare")
                return PreparedImagePrompt(prompt, "An orange cat", True, "local-test")
            def runner(command, **kwargs):
                events.append("render")
                self.assertEqual(command[command.index("--prompt") + 1], "An orange cat")
                Path(command[command.index("--out") + 1]).write_bytes(b"fake-png")
                return Completed()
            service = ImageGenService(runtime, runner, prepare)
            with patch.object(service, "_unload_ollama_models", side_effect=lambda: events.append("unload")):
                result = service.generate("tạo ảnh mèo cam")
            metadata = json.loads(result.with_suffix(".png.json").read_text(encoding="utf-8"))
            self.assertEqual(events, ["prepare", "unload", "render"])
            self.assertEqual(metadata["prepared_prompt"], "An orange cat")
            self.assertEqual(metadata["original_prompt"], "tạo ảnh mèo cam")

    def test_streaming_path_forwards_real_progress_events(self):
        import io

        with tempfile.TemporaryDirectory() as directory:
            runtime = make_runtime(Path(directory))

            class FakeStreamProcess:
                def __init__(self, lines: list[str]) -> None:
                    self.stdout = io.StringIO("".join(lines))
                    self.killed = False

                def wait(self) -> int:
                    return 0

                def kill(self) -> None:
                    self.killed = True

            def popener(command, **kwargs):
                Path(command[command.index("--out") + 1]).write_bytes(b"fake-png")
                return FakeStreamProcess([
                    'PROGRESS {"stage": "step", "step": 1, "total": 4}\n',
                    "PROGRESS not-json\n",
                    'PROGRESS {"stage": "frame", "frame": 2, "total": 6}\n',
                    "D:\\fake\\out.png\n",
                ])

            events = []
            service = ImageGenService(runtime_dir=runtime, popener=popener)
            path = service.generate("a house", unload_ollama=False, on_event=events.append)
        self.assertEqual(path.suffix, ".png")
        self.assertEqual(
            events,
            [
                {"stage": "prepared", "prompt": "a house", "translated": False},
                {"stage": "engine_load"},
                {"stage": "step", "step": 1, "total": 4},
                {"stage": "frame", "frame": 2, "total": 6},
            ],
        )

    def test_broken_progress_listener_never_fails_the_render(self):
        import io

        with tempfile.TemporaryDirectory() as directory:
            runtime = make_runtime(Path(directory))

            class FakeStreamProcess:
                def __init__(self) -> None:
                    self.stdout = io.StringIO('PROGRESS {"stage": "step", "step": 1, "total": 4}\n')

                def wait(self) -> int:
                    return 0

                def kill(self) -> None:
                    pass

            def popener(command, **kwargs):
                Path(command[command.index("--out") + 1]).write_bytes(b"fake-png")
                return FakeStreamProcess()

            service = ImageGenService(runtime_dir=runtime, popener=popener)
            path = service.generate(
                "a house", unload_ollama=False, on_event=lambda event: 1 / 0
            )
        self.assertTrue(path.name.startswith("tris_image_"))

    def test_streaming_failure_surfaces_stderr_last_line(self):
        import io

        with tempfile.TemporaryDirectory() as directory:
            runtime = make_runtime(Path(directory))

            class FailingProcess:
                def __init__(self) -> None:
                    self.stdout = io.StringIO("")

                def wait(self) -> int:
                    return 1

                def kill(self) -> None:
                    pass

            def popener(command, stderr=None, **kwargs):
                stderr.write(b"CUDA out of memory\nlast error line\n")
                return FailingProcess()

            service = ImageGenService(runtime_dir=runtime, popener=popener)
            with self.assertRaises(ImageGenError) as ctx:
                service.generate("a house", unload_ollama=False, on_event=lambda event: None)
        self.assertIn("last error line", str(ctx.exception))

    def test_translation_failure_never_unloads_or_renders_wrong_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = make_runtime(Path(directory))
            runner = Mock()
            preparer = Mock(side_effect=ImagePromptError("Cannot translate"))
            service = ImageGenService(runtime, runner, preparer)
            with patch.object(service, "_unload_ollama_models") as unload:
                with self.assertRaisesRegex(ImageGenError, "Cannot translate"):
                    service.generate("tạo ảnh mèo cam")
            runner.assert_not_called()
            unload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
