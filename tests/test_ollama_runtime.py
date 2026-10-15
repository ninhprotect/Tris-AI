"""Ollama readiness tests that never start, stop, or download real models."""
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from services import ollama_runtime


class ModelResolutionTests(unittest.TestCase):
    def test_exact_and_latest_aliases_resolve_to_installed_name(self):
        self.assertEqual(
            ollama_runtime.choose_model("custom", ["custom:latest"]),
            "custom:latest",
        )
        self.assertEqual(
            ollama_runtime.choose_model("custom:8b", ["custom:4b", "custom:8b"]),
            "custom:8b",
        )

    def test_stale_choice_falls_back_to_local_4b_not_api_order(self):
        available = ["qwen3:8b", "english-tutor-local:4b", "qwen3:4b"]
        self.assertEqual(
            ollama_runtime.choose_model("removed:latest", available),
            "english-tutor-local:4b",
        )

    def test_embedding_and_vision_models_are_not_chat_fallbacks(self):
        available = ["nomic-embed-text:latest", "qwen2.5vl:3b"]
        self.assertIsNone(ollama_runtime.choose_model("removed:latest", available))


class StartupResolutionTests(unittest.TestCase):
    def setUp(self):
        ollama_runtime._ACTIVE_RUNTIME = None

    def tearDown(self):
        ollama_runtime._ACTIVE_RUNTIME = None

    def test_existing_daemon_is_accepted_only_with_chat_model_and_preloaded(self):
        with (
            patch.object(ollama_runtime, "environment_value", side_effect=lambda name, default="": {
                "OLLAMA_HOST": "http://127.0.0.1:11434",
                "OLLAMA_MODEL": "english-tutor-local:4b",
            }.get(name, default)),
            patch.object(ollama_runtime, "installed_model_names", return_value=["english-tutor-local:4b"]),
            patch.object(ollama_runtime, "_preload") as preload,
            patch.object(ollama_runtime.atexit, "register"),
            patch.dict(os.environ, {}, clear=False),
        ):
            runtime = ollama_runtime.prepare_ollama(Path("."))
        self.assertFalse(runtime.managed)
        self.assertEqual(runtime.model, "english-tutor-local:4b")
        preload.assert_called_once_with("http://127.0.0.1:11434", "english-tutor-local:4b")

    def test_reachable_but_empty_daemon_uses_verified_sidecar_store(self):
        sidecar = ollama_runtime.OllamaRuntime(
            host="http://127.0.0.1:11435", model="english-tutor-local:4b"
        )
        store = Path("D:/TrisAI/ollama_models")
        with (
            patch.object(ollama_runtime, "environment_value", side_effect=lambda name, default="": {
                "OLLAMA_HOST": "http://127.0.0.1:11434",
                "OLLAMA_MODEL": "english-tutor-local:4b",
            }.get(name, default)),
            patch.object(ollama_runtime, "installed_model_names", return_value=[]),
            patch.object(ollama_runtime, "_configured_model_store", return_value=store),
            patch.object(ollama_runtime, "_start_sidecar", return_value=sidecar) as start,
            patch.object(ollama_runtime.atexit, "register"),
        ):
            runtime = ollama_runtime.prepare_ollama(Path("D:/project"))
        self.assertIs(runtime, sidecar)
        start.assert_called_once_with(Path("D:/project"), store, "english-tutor-local:4b")

    def test_managed_sidecar_unloads_model_before_terminating_parent(self):
        process = Mock()
        process.poll.return_value = None
        runtime = ollama_runtime.OllamaRuntime(
            host="http://127.0.0.1:11435",
            model="english-tutor-local:4b",
            process=process,
        )
        with patch.object(
            ollama_runtime,
            "_request_json",
            side_effect=[{"done": True}, {"models": []}],
        ) as request:
            runtime.close()
        self.assertEqual(request.call_args_list[0].kwargs["payload"]["keep_alive"], 0)
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=8)


if __name__ == "__main__":
    unittest.main()
