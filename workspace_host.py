"""Primary Tris AI host: one backend, one event loop, web :7860 and API :8000."""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import urlparse


_ollama_runtime = None


def prepare_local_postgres():
    from config.settings import POSTGRES_DSN, PROJECT_ROOT
    parsed = urlparse(POSTGRES_DSN)
    binary = PROJECT_ROOT / "runtime" / "postgresql-17.11" / "pgsql" / "bin"
    cluster = PROJECT_ROOT / "data" / "postgres-account-db"
    # A copied project can carry an un-administrable account cluster whose
    # superuser secret never travelled with it. Once setup_postgres_fresh.ps1
    # has produced the replacement beside it, prefer the fresh cluster.
    if (PROJECT_ROOT / "data" / "postgres-account-db-fresh" / "PG_VERSION").is_file():
        cluster = PROJECT_ROOT / "data" / "postgres-account-db-fresh"
    if parsed.hostname not in {"127.0.0.1", "localhost"} or not (binary / "pg_ctl.exe").is_file() or not (cluster / "PG_VERSION").is_file():
        return
    options = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
               "creationflags": subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0}
    try:
        ready = subprocess.run([str(binary / "pg_isready.exe"), "-h", "127.0.0.1", "-p", str(parsed.port or 5432)], timeout=5, **options)
        if ready.returncode:
            subprocess.run([str(binary / "pg_ctl.exe"), "-D", str(cluster), "-l",
                            str(PROJECT_ROOT / "data" / "postgres-account-db.log"),
                            "-o", f"-p {parsed.port or 5432}", "-w", "-t", "20", "start"], timeout=25, **options)
    except (OSError, subprocess.TimeoutExpired):
        print("PostgreSQL startup not confirmed; check account availability in /health.")


def create_application():
    global _ollama_runtime
    # Verify the actual tutor model, not just that an Ollama HTTP port exists.
    # This runs before settings/AI modules are imported so a private sidecar
    # host can be selected process-wide when the desktop daemon has stale env.
    if _ollama_runtime is None:
        from services.ollama_runtime import prepare_ollama
        _ollama_runtime = prepare_ollama(Path(__file__).resolve().parent)
    from config.settings import APP_HOST, APP_PORT
    # This must be set BEFORE api imports its OAuth return URL.
    os.environ["WEB_PUBLIC_BASE_URL"] = f"http://{APP_HOST}:{APP_PORT}"
    prepare_local_postgres()
    import api
    from fastapi.staticfiles import StaticFiles
    from workspace_api import install_workspace_routes
    from workspace_features import install_feature_routes
    # settings can have been imported by a legacy entrypoint already.
    api.WEB_PUBLIC_BASE_URL = os.environ["WEB_PUBLIC_BASE_URL"]
    if getattr(api.app.state, "workspace_installed", False):
        return api.app
    install_workspace_routes(api)
    install_feature_routes(api)
    api.app.state.workspace_installed = True
    api.app.state.runtime_id = uuid.uuid4().hex

    @api.app.get("/v1/workspace/runtime")
    def runtime():
        from config.settings import MODEL_NAME
        return {"ui": "tris-workspace", "runtime_id": api.app.state.runtime_id,
                "web_url": api.WEB_PUBLIC_BASE_URL, "model": MODEL_NAME}

    dist = Path(__file__).resolve().parent / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        raise RuntimeError("Build the UI with scripts/build_workspace.ps1 before starting Tris AI.")

    @api.app.middleware("http")
    async def revalidate_pages(request, call_next):
        # Pages and Companion files keep the same URL across updates. Without this header
        # browsers heuristically reuse a stale copy (old Companion, old blink code). With it
        # they revalidate via ETag, which costs a cheap 304 when nothing changed.
        response = await call_next(request)
        path = request.url.path
        if "cache-control" not in response.headers and (
            path == "/" or path.endswith(".html") or path.startswith("/companion/")
        ):
            response.headers["Cache-Control"] = "no-cache"
        return response
    api.app.mount("/", StaticFiles(directory=dist, html=True), name="workspace")
    return api.app


def warm_local_stt():
    """Keep the installed microphone model in RAM without delaying the web UI."""
    try:
        from services.local_stt import get_local_stt
        service = get_local_stt()
        if service.status()["ready"]:
            service.warmup()
            print("Local microphone transcription loaded in RAM.")
    except Exception as exc:
        # The UI reports an actionable setup error on use. Missing optional STT
        # must never prevent chat/Ollama from starting.
        print(f"Local microphone transcription warmup skipped: {type(exc).__name__}")


def warm_voice(deadline_seconds: float = 180, retry_seconds: float = 3):
    """Pre-load the mascot voice converter so the first spoken sentence is fast.

    The voice server (:7861) is a separate process that may still be starting,
    so connection errors are retried until the deadline. Never raises.
    """
    try:
        import httpx
        from config.settings import TTS_ENABLED, TTS_ENGINE, XTTS_SERVER_URL
        if not TTS_ENABLED:
            return
        # Piper (the text-to-speech step before tone conversion) loads its ONNX
        # voices lazily; doing it now saves 3-5 s on the first sentence per language.
        try:
            from services.local_tts import tris_voice
            loaded = tris_voice.preload()
            if loaded:
                print(f"Piper voices loaded in RAM: {', '.join(loaded)}.")
        except Exception as exc:
            print(f"Piper voice preload skipped: {type(exc).__name__}")
        if TTS_ENGINE != "clone":
            return
        url = f"{XTTS_SERVER_URL.rstrip('/')}/warmup"
        # First load on CPU takes 30-65 s; read timeout stays generous.
        timeout = httpx.Timeout(600.0, connect=5.0)
        deadline = time.monotonic() + deadline_seconds
        while True:
            try:
                response = httpx.post(url, timeout=timeout, trust_env=False)
                break
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if time.monotonic() + retry_seconds > deadline:
                    print("Mascot voice warmup skipped: voice server not reachable; it will warm on first use.")
                    return
                time.sleep(retry_seconds)
        if response.status_code == 404:
            print("Mascot voice server has no /warmup yet: it will warm on first use "
                  "(restart the voice server to enable warmup).")
            return
        if response.status_code == 202:
            print("Mascot voice warmup skipped: a conversion is already warming the voice server.")
            return
        if response.status_code != 200:
            print(f"Mascot voice warmup failed (HTTP {response.status_code}): {response.text[:160]}")
            return
        payload = response.json()
        print(f"Mascot voice warmed in {payload.get('seconds')}s on {payload.get('device')}.")
    except Exception as exc:
        # Speech still works (slower first sentence); never block the web UI.
        print(f"Mascot voice warmup skipped: {type(exc).__name__}")


def main():
    import uvicorn
    from config.settings import API_HOST, API_PORT, APP_HOST, APP_PORT, APP_OPEN_BROWSER
    sockets = []
    try:
        # Fail before starting either listener instead of leaving two split apps.
        for host, port in dict.fromkeys([(APP_HOST, APP_PORT), (API_HOST, API_PORT)]):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(sock)
            sock.bind((host, port))
            sock.listen(128)
            sock.setblocking(False)
        application = create_application()
        server = uvicorn.Server(uvicorn.Config(application, log_level="info"))
        application.state.stop_server = lambda: setattr(server, "should_exit", True)
        threading.Thread(target=warm_local_stt, daemon=True).start()
        threading.Thread(target=warm_voice, daemon=True).start()
        if APP_OPEN_BROWSER:
            def open_when_ready():
                while not server.started and not server.should_exit:
                    time.sleep(.2)
                if server.started:
                    webbrowser.open(f"http://{APP_HOST}:{APP_PORT}")
            threading.Thread(target=open_when_ready, daemon=True).start()
        print(f"Tris AI: http://{APP_HOST}:{APP_PORT} | shared API :{API_PORT}")
        asyncio.run(server.serve(sockets=sockets))
    finally:
        for sock in sockets:
            sock.close()
        # Only a sidecar created by this Tris process is terminated. An
        # independently running Ollama desktop daemon is never killed here.
        from services.ollama_runtime import close_ollama_runtime
        close_ollama_runtime()


if __name__ == "__main__":
    main()
