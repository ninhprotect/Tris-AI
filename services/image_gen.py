"""Local media generation service for Tris AI (image, GIF, short video)."""

from __future__ import annotations

import subprocess
import threading
import json
import tempfile
import time
from uuid import uuid4
from typing import Any
from datetime import datetime
from pathlib import Path

import httpx
from services.image_prompt import ImagePromptError, prepare_image_prompt

from config.settings import (
    IMAGEGEN_TIMEOUT_SECONDS,
    IMAGEGEN_MODEL,
    OLLAMA_HOST,
    PROJECT_ROOT,
)

GENERATED_DIR = PROJECT_ROOT / "data" / "generated"
MODE_SUFFIXES = {"image": "png", "gif": "gif", "video": "mp4"}

class ImageGenError(RuntimeError):
    """Safe media-generation error suitable for the UI and API."""


class ImageGenService:
    """Drive the isolated runtime/imagegen environment as a subprocess."""
    _generation_lock = threading.Lock()

    def __init__(self, runtime_dir: Path | None = None, runner: Any | None = None,
                 prompt_preparer: Any | None = None, popener: Any | None = None) -> None:
        root = runtime_dir or (PROJECT_ROOT / "runtime" / "imagegen")
        self.python_exe = root / ".venv" / "Scripts" / "python.exe"
        self.script = root / "generate.py"
        self.runtime_dir = root
        self._runner = runner or subprocess.run
        self._popener = popener or subprocess.Popen
        self._prompt_preparer = prompt_preparer or prepare_image_prompt

    @property
    def available(self) -> bool:
        return self.python_exe.is_file() and self.script.is_file()

    def generate(
        self, prompt: str, mode: str = 'image', frames: int = 6,
        timeout: int | None = None, unload_ollama: bool = True,
        on_event: Any | None = None,
    ) -> Path:
        if not self._generation_lock.acquire(blocking=False):
            raise ImageGenError('Bộ tạo ảnh đang bận. Chờ ảnh hiện tại hoàn tất rồi thử lại.')
        try:
            return self._generate(prompt, mode, frames, timeout, unload_ollama, on_event)
        finally:
            self._generation_lock.release()

    def _generate(
        self,
        prompt: str,
        mode: str = "image",
        frames: int = 6,
        timeout: int | None = None,
        unload_ollama: bool = True,
        on_event: Any | None = None,
    ) -> Path:
        """Render one media file locally and return its path.

        ``on_event`` receives truthful stage/progress dicts while the render
        runs (engine load, prepared description, per-step/per-frame counts).
        It never invents percentages; only counts the system actually knows.
        """
        clean = " ".join(str(prompt or "").split())
        if not clean:
            raise ImageGenError("Hãy nhập mô tả nội dung muốn tạo.")
        if mode not in MODE_SUFFIXES:
            raise ImageGenError("Kiểu tạo chỉ nhận: image, gif, video.")
        if not self.available:
            raise ImageGenError(
                "Chưa cài bộ tạo ảnh local. Hãy chạy scripts/setup_imagegen.ps1."
            )
        # Translate while the local LLM is still available, then release its
        # VRAM for diffusion. Never render an untranslated fallback on failure.
        try:
            prepared = self._prompt_preparer(clean)
        except ImagePromptError as exc:
            raise ImageGenError(str(exc)) from exc
        if on_event is not None:
            self._emit(on_event, {"stage": "prepared", "prompt": prepared.prompt,
                                  "translated": prepared.translated})
        if unload_ollama:
            self._unload_ollama_models()
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + '_' + uuid4().hex[:8]
        destination = GENERATED_DIR / f"tris_{mode}_{stamp}.{MODE_SUFFIXES[mode]}"
        command = [
            str(self.python_exe),
            str(self.script),
            "--prompt",
            prepared.prompt,
            "--out",
            str(destination),
            "--mode",
            mode,
            "--frames",
            str(max(2, min(int(frames or 6), 16))),
            "--model",
            IMAGEGEN_MODEL,
        ]
        try:
            if on_event is None:
                result = self._runner(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout or IMAGEGEN_TIMEOUT_SECONDS,
                    check=False,
                    encoding="utf-8",
                    errors="replace",
                    cwd=str(self.runtime_dir),
                )
                stderr_text = result.stderr or ""
                returncode = result.returncode
            else:
                self._emit(on_event, {"stage": "engine_load"})
                stderr_text, returncode = self._run_streaming(command, on_event, timeout)
        except subprocess.TimeoutExpired as exc:
            raise ImageGenError("Tạo nội dung quá thời gian chờ. Hãy thử lại.") from exc
        except OSError as exc:
            raise ImageGenError("Không khởi động được bộ tạo ảnh local.") from exc
        if returncode != 0 or not destination.is_file():
            detail = (stderr_text or "").strip().splitlines()
            hint = detail[-1][:300] if detail else ""
            raise ImageGenError(
                f"Bộ tạo ảnh local gặp lỗi{': ' + hint if hint else ''}."
            )
        # Audit the exact input supplied to diffusion, without changing the
        # public generate()->Path contract. No private media leaves the device.
        metadata = {
            "original_prompt": prepared.original,
            "prepared_prompt": prepared.prompt,
            "translated": prepared.translated,
            "translator": prepared.translator,
            "image_model": IMAGEGEN_MODEL,
            "mode": mode,
        }
        destination.with_suffix(destination.suffix + ".json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return destination

    @staticmethod
    def _emit(on_event: Any, event: dict) -> None:
        try:
            on_event(event)
        except Exception:
            # A broken progress listener must never fail the render itself.
            pass

    def _run_streaming(self, command: list[str], on_event: Any, timeout: int | None) -> tuple[str, int]:
        """Stream PROGRESS lines from the render subprocess until it exits.

        stderr goes to a temp file so a chatty child can never deadlock the
        stdout reader. A watchdog kills the process at the same timeout the
        blocking path enforces and reports the identical message.
        """
        budget = timeout or IMAGEGEN_TIMEOUT_SECONDS
        state = {"timed_out": False}
        with tempfile.TemporaryFile() as stderr_file:
            process = self._popener(
                command,
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(self.runtime_dir),
            )

            def watchdog() -> None:
                state["timed_out"] = True
                process.kill()

            timer = threading.Timer(budget, watchdog)
            timer.start()
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    line = line.strip()
                    if line.startswith("PROGRESS "):
                        try:
                            event = json.loads(line[len("PROGRESS "):])
                        except ValueError:
                            continue
                        if isinstance(event, dict) and isinstance(event.get("stage"), str):
                            self._emit(on_event, event)
                returncode = process.wait()
            finally:
                timer.cancel()
            if state["timed_out"]:
                raise subprocess.TimeoutExpired(cmd=command[0], timeout=budget)
            stderr_file.seek(0)
            return stderr_file.read().decode("utf-8", "replace"), returncode

    @staticmethod
    def _unload_ollama_models() -> None:
        """Release only resident models, with a small bounded time budget.

        Query /api/ps rather than installed tags or hardcoded candidates: an
        absent name must never be requested merely to free VRAM. No pulling,
        proxy inheritance, or long per-model 30-second waits are involved.
        """
        deadline = time.monotonic() + 10.0
        try:
            with httpx.Client(timeout=3.0, trust_env=False) as client:
                response = client.get(f"{OLLAMA_HOST}/api/ps")
                response.raise_for_status()
                rows = response.json().get("models", [])
                if not isinstance(rows, list):
                    return
                seen = set()
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    model = row.get("name") or row.get("model")
                    if not isinstance(model, str) or not model.strip() or model in seen:
                        continue
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    seen.add(model)
                    try:
                        unloaded = client.post(
                            f"{OLLAMA_HOST}/api/generate",
                            json={"model": model, "keep_alive": 0, "stream": False},
                            timeout=min(3.0, remaining),
                        )
                        unloaded.raise_for_status()
                    except httpx.HTTPError:
                        continue
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            # Diffusion's existing CUDA-OOM handling remains the last resort.
            # If /api/ps fails, do not fall back to speculative model requests.
            return
