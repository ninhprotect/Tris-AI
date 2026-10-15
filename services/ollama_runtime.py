"""Reliable Ollama discovery and startup for the local desktop application.

The Ollama desktop process can outlive changes to the Windows user environment.
In that case ``/api/tags`` is reachable but points at the old/empty model store.
Tris must not mistake "HTTP server is alive" for "the tutor model is ready".

This module deliberately never downloads, creates, moves, or deletes a model.
When the default Ollama daemon cannot see an installed chat model, Tris starts a
private Ollama sidecar on another loopback port with the configured model store.
The sidecar is owned by Tris and is stopped when the app exits normally.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_TUTOR_MODEL = "english-tutor-local:4b"
SIDECAR_PORTS = range(11435, 11440)
# Models dedicated to embedding or image understanding must never become a
# silent fallback for the text tutor.
NON_CHAT_MARKERS = ("embed", "nomic", "bge-", "qwen2.5vl", "llava", "vision")


def normalize_host(value: str | None) -> str:
    host = (value or DEFAULT_OLLAMA_HOST).strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host


def _windows_user_environment(name: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value).strip()
    except (FileNotFoundError, OSError):
        return ""


def environment_value(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is not None and value.strip():
        return value.strip()
    return _windows_user_environment(name) or default


def _canonical_model(name: str) -> str:
    value = name.strip().lower()
    if value.startswith("registry.ollama.ai/library/"):
        value = value.removeprefix("registry.ollama.ai/library/")
    return value[:-7] if value.endswith(":latest") else value


def is_chat_model(name: str) -> bool:
    lowered = name.lower()
    return bool(name.strip()) and not any(marker in lowered for marker in NON_CHAT_MARKERS)


def choose_model(requested: str, available: list[str], preferred: str = DEFAULT_TUTOR_MODEL) -> str | None:
    """Resolve aliases/stale browser choices to one installed chat model.

    Exact names win. ``:latest`` is treated as the untagged alias. If a browser
    remembers a model that is no longer installed, prefer the configured tutor
    model, then the 4B tutor/Qwen options that fit the target 6 GB GPU.
    """
    chat_models = [name for name in available if is_chat_model(name)]
    if not chat_models:
        return None
    canonical = {_canonical_model(name): name for name in chat_models}
    for candidate in (requested, preferred):
        if candidate in chat_models:
            return candidate
        matched = canonical.get(_canonical_model(candidate))
        if matched:
            return matched
    preference = (
        "english-tutor-local:4b",
        "qwen3:4b-instruct",
        "qwen3:4b",
        "english-tutor-local:8b",
    )
    for candidate in preference:
        matched = canonical.get(_canonical_model(candidate))
        if matched:
            return matched
    return chat_models[0]


def _request_json(url: str, *, payload: dict[str, Any] | None = None, timeout: float = 5) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urlopen(request, timeout=timeout) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Ollama returned a non-object response")
    return parsed


def installed_model_names(host: str, attempts: int = 2) -> list[str]:
    for attempt in range(max(1, attempts)):
        try:
            payload = _request_json(f"{normalize_host(host)}/api/tags", timeout=4)
            return [str(item.get("name", "")) for item in payload.get("models", [])
                    if isinstance(item, dict) and item.get("name")]
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            if attempt + 1 < attempts:
                time.sleep(0.4)
    return []


def _configured_model_store(project_root: Path) -> Path | None:
    candidates = [
        environment_value("OLLAMA_MODELS"),
        str(Path("D:/TrisAI/ollama_models")) if os.name == "nt" else "",
        str(Path.home() / ".ollama" / "models"),
    ]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw).expanduser().resolve()
        if (path / "manifests").is_dir() and (path / "blobs").is_dir():
            return path
    return None


def _ollama_executable() -> Path | None:
    candidates: list[Path] = []
    if os.name == "nt":
        local = os.getenv("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
    found = shutil.which("ollama")
    if found:
        candidates.append(Path(found))
    return next((path.resolve() for path in candidates if path.is_file()), None)


def _is_loopback(host: str) -> bool:
    parsed = urlparse(normalize_host(host))
    return parsed.hostname in {"127.0.0.1", "localhost", "::1"}


@dataclass
class OllamaRuntime:
    host: str
    model: str
    process: subprocess.Popen | None = None
    log_stream: Any | None = None

    @property
    def managed(self) -> bool:
        return self.process is not None

    def close(self) -> None:
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            # Ask Ollama to release the runner/VRAM before terminating its HTTP
            # parent. New Ollama versions can otherwise leave llama-server.exe
            # orphaned on Windows after the parent process exits.
            try:
                _request_json(
                    f"{self.host.rstrip('/')}/api/generate",
                    payload={"model": self.model, "prompt": "", "stream": False, "keep_alive": 0},
                    timeout=20,
                )
                for _ in range(20):
                    running = _request_json(f"{self.host.rstrip('/')}/api/ps", timeout=2).get("models", [])
                    if not any(
                        isinstance(item, dict)
                        and _canonical_model(str(item.get("name") or item.get("model") or ""))
                        == _canonical_model(self.model)
                        for item in running
                    ):
                        break
                    time.sleep(0.1)
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
                pass
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if self.log_stream is not None:
            self.log_stream.close()
            self.log_stream = None


def _preload(host: str, model: str) -> None:
    timeout = float(environment_value("OLLAMA_LOAD_TIMEOUT_SECONDS", "240"))
    keep_alive = environment_value("OLLAMA_KEEP_ALIVE", "30m")
    # Load with the chat context size up front; otherwise the Modelfile default
    # (2048) is loaded and the first question pays a full model reload.
    num_ctx = int(environment_value("OLLAMA_CONTEXT_WINDOW", "4096"))
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            _request_json(
                f"{normalize_host(host)}/api/generate",
                payload={"model": model, "prompt": "", "stream": False, "keep_alive": keep_alive,
                         "options": {"num_ctx": num_ctx}},
                timeout=timeout,
            )
            return
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(1)
    raise RuntimeError(
        f"Ollama thấy model '{model}' nhưng không nạp thử được vào RAM/VRAM. "
        "Hãy đóng tác vụ GPU khác rồi chạy lại Tris AI."
    ) from last_error


def _start_sidecar(project_root: Path, model_store: Path, requested_model: str) -> OllamaRuntime:
    executable = _ollama_executable()
    if executable is None:
        raise RuntimeError("Không tìm thấy Ollama trên máy. Tris AI không tự tải Ollama hoặc model.")
    log_dir = project_root / "data"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Reuse a healthy sidecar left by an abnormal previous exit instead of
    # spawning multiple Ollama daemons. Normal exits stop processes we create.
    for port in SIDECAR_PORTS:
        host = f"http://127.0.0.1:{port}"
        names = installed_model_names(host, attempts=1)
        selected = choose_model(requested_model, names, requested_model)
        if selected:
            os.environ["OLLAMA_HOST"] = host
            os.environ["OLLAMA_MODEL"] = selected
            _preload(host, selected)
            return OllamaRuntime(host=host, model=selected)

    for port in SIDECAR_PORTS:
        host = f"http://127.0.0.1:{port}"
        # Do not take over a port occupied by an unrelated HTTP service.
        try:
            _request_json(f"{host}/api/version", timeout=1)
            continue
        except HTTPError:
            continue
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            pass

        child_env = os.environ.copy()
        child_env.update({
            "OLLAMA_HOST": f"127.0.0.1:{port}",
            "OLLAMA_MODELS": str(model_store),
            "OLLAMA_FLASH_ATTENTION": environment_value("OLLAMA_FLASH_ATTENTION", "1"),
            "OLLAMA_KV_CACHE_TYPE": environment_value("OLLAMA_KV_CACHE_TYPE", "q8_0"),
            "OLLAMA_NUM_PARALLEL": environment_value("OLLAMA_NUM_PARALLEL", "1"),
            "OLLAMA_MAX_LOADED_MODELS": environment_value("OLLAMA_MAX_LOADED_MODELS", "1"),
            "OLLAMA_KEEP_ALIVE": environment_value("OLLAMA_KEEP_ALIVE", "30m"),
        })
        log_stream = (log_dir / "ollama-tris-managed.log").open("a", encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            [str(executable), "serve"],
            cwd=str(project_root),
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        runtime = OllamaRuntime(host=host, model=requested_model, process=process, log_stream=log_stream)
        for _ in range(40):
            if process.poll() is not None:
                break
            names = installed_model_names(host, attempts=1)
            selected = choose_model(requested_model, names, requested_model)
            if selected:
                runtime.model = selected
                os.environ["OLLAMA_HOST"] = host
                os.environ["OLLAMA_MODEL"] = selected
                try:
                    _preload(host, selected)
                except Exception:
                    runtime.close()
                    raise
                return runtime
            time.sleep(0.5)
        runtime.close()

    raise RuntimeError(
        f"Ollama đang chạy nhưng không thấy model trong kho {model_store}. "
        "Không có model nào được tự tải hoặc xóa."
    )


_ACTIVE_RUNTIME: OllamaRuntime | None = None
_RUNTIME_LOCK = threading.RLock()


def _prepare_ollama_unlocked(project_root: Path) -> OllamaRuntime:
    """Return a verified, preloaded Ollama runtime and update process env."""
    global _ACTIVE_RUNTIME
    if _ACTIVE_RUNTIME is not None:
        return _ACTIVE_RUNTIME

    configured_host = normalize_host(environment_value("OLLAMA_HOST", DEFAULT_OLLAMA_HOST))
    requested = environment_value("OLLAMA_MODEL", DEFAULT_TUTOR_MODEL)
    names = installed_model_names(configured_host, attempts=3)
    selected = choose_model(requested, names, requested)
    if selected:
        os.environ["OLLAMA_HOST"] = configured_host
        os.environ["OLLAMA_MODEL"] = selected
        _preload(configured_host, selected)
        _ACTIVE_RUNTIME = OllamaRuntime(host=configured_host, model=selected)
    else:
        if not _is_loopback(configured_host):
            raise RuntimeError(
                f"Ollama tại {configured_host} chưa cung cấp model hội thoại đã cài. "
                "Tris không tự đổi một máy chủ từ xa."
            )
        store = _configured_model_store(project_root)
        if store is None:
            raise RuntimeError(
                "Không tìm thấy kho model Ollama. Hãy kiểm tra biến OLLAMA_MODELS; "
                "Tris không tự tải hoặc xóa model."
            )
        _ACTIVE_RUNTIME = _start_sidecar(project_root, store, requested)

    atexit.register(close_ollama_runtime)
    print(f"Ollama ready: {_ACTIVE_RUNTIME.model} at {_ACTIVE_RUNTIME.host} "
          f"({'managed sidecar' if _ACTIVE_RUNTIME.managed else 'existing daemon'})")
    return _ACTIVE_RUNTIME


def prepare_ollama(project_root: Path) -> OllamaRuntime:
    with _RUNTIME_LOCK:
        return _prepare_ollama_unlocked(project_root)


def current_ollama_host(default: str = DEFAULT_OLLAMA_HOST) -> str:
    with _RUNTIME_LOCK:
        return _ACTIVE_RUNTIME.host if _ACTIVE_RUNTIME is not None else normalize_host(default)


def recover_ollama(project_root: Path) -> OllamaRuntime:
    """Re-check a failed runtime and rebuild only Tris' managed sidecar."""
    global _ACTIVE_RUNTIME
    with _RUNTIME_LOCK:
        if _ACTIVE_RUNTIME is not None:
            names = installed_model_names(_ACTIVE_RUNTIME.host, attempts=2)
            selected = choose_model(_ACTIVE_RUNTIME.model, names, _ACTIVE_RUNTIME.model)
            if selected:
                _ACTIVE_RUNTIME.model = selected
                return _ACTIVE_RUNTIME
            _ACTIVE_RUNTIME.close()
            _ACTIVE_RUNTIME = None
        return _prepare_ollama_unlocked(project_root)


def close_ollama_runtime() -> None:
    global _ACTIVE_RUNTIME
    with _RUNTIME_LOCK:
        runtime, _ACTIVE_RUNTIME = _ACTIVE_RUNTIME, None
        if runtime is not None:
            runtime.close()

