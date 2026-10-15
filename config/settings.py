"""Central configuration for Tris AI.

Environment variables are optional. They make it possible to switch model or
port later without changing source code.
"""

import os
from pathlib import Path


def _environment_value(name: str, default: str = "") -> str:
    """Read process env, then the Windows user environment for desktop launches."""
    value = os.getenv(name)
    if value is not None:
        return value
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                stored, _ = winreg.QueryValueEx(key, name)
                return str(stored)
        except (FileNotFoundError, OSError):
            pass
    return default


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_ICON_PATH = (PROJECT_ROOT / "assets" / "tris.ico").resolve()


# english-tutor-local:4b fits 6GB VRAM at 100% GPU (fast, stable); the 8B
# variant needs ~7GB effective and offloads layers to the CPU on this laptop.
MODEL_NAME = os.getenv("OLLAMA_MODEL", "english-tutor-local:4b")
# Chat models offered in the UI model picker (comma separated). Other installed
# models stay on disk but are hidden, so a stale browser choice can never route
# a question to an untuned base model.
VISIBLE_CHAT_MODELS = tuple(
    name.strip() for name in os.getenv("TRIS_VISIBLE_MODELS", "english-tutor-local:4b").split(",") if name.strip()
)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))

TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.6"))
# 4096 for the 4B tutor on the CUDA runner: the q8_0 KV cache is ~306 MB, so
# the model stays 100% on the 6 GB GPU. 2048 was too small: system prompt plus
# attached sources reached 2.3k-6.3k tokens, Ollama rejected the request or ran
# out of room mid-answer and the reply derailed.
CONTEXT_WINDOW = int(os.getenv("OLLAMA_CONTEXT_WINDOW", "4096"))
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "12"))
# Tris 4b re-reads its own draft once before sending (facts, grammar, language,
# truncation). Costs one short extra pass when the draft is fine. 0 disables it.
CHAT_SELF_REVIEW = os.getenv("TRIS_SELF_REVIEW", "1").strip() != "0"

DATABASE_PATH = Path(
    os.getenv("TUTOR_DATABASE_PATH", str(PROJECT_ROOT / "data" / "english_tutor.db"))
).resolve()
DEFAULT_LEARNER_NAME = os.getenv("DEFAULT_LEARNER_NAME", "Local Learner")

DOCUMENT_LIBRARY_PATH = Path(
    os.getenv("TUTOR_DOCUMENT_PATH", str(PROJECT_ROOT / "data" / "documents"))
).resolve()
QDRANT_PATH = Path(
    os.getenv("QDRANT_PATH", str(PROJECT_ROOT / "data" / "qdrant"))
).resolve()
QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "english_tutor_chunks")
EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))

# Upload safety limits. Gradio also enforces the largest per-file limit before
# an upload reaches application code; smaller limits are checked by file type.
MAX_ATTACHMENT_FILES = int(os.getenv("MAX_ATTACHMENT_FILES", "5"))
MAX_DOCUMENT_BYTES = int(os.getenv("MAX_DOCUMENT_MB", "20")) * 1024 * 1024
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_MB", "10")) * 1024 * 1024
MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_MEGAPIXELS", "25")) * 1_000_000
MAX_VIDEO_BYTES = int(os.getenv("MAX_VIDEO_MB", "150")) * 1024 * 1024
MAX_ATTACHMENT_TOTAL_BYTES = (
    int(os.getenv("MAX_ATTACHMENT_TOTAL_MB", "180")) * 1024 * 1024
)
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "250"))
MAX_EXTRACTED_CHARACTERS = int(os.getenv("MAX_EXTRACTED_CHARACTERS", "2000000"))

# Offline mascot speech. Models are installed explicitly so starting the app
# never triggers a surprise network download.
TTS_ENABLED = os.getenv("TTS_ENABLED", "true").lower() in {"1", "true", "yes"}
TTS_MODEL_DIR = Path(
    os.getenv("TTS_MODEL_DIR", str(PROJECT_ROOT / "runtime" / "tts" / "models"))
).resolve()
TTS_CACHE_DIR = Path(
    os.getenv("TTS_CACHE_DIR", str(PROJECT_ROOT / "runtime" / "tts" / "cache"))
).resolve()
TTS_VI_MODEL = os.getenv("TTS_VI_MODEL", "vi_VN-vais1000-medium")
TTS_EN_MODEL = os.getenv("TTS_EN_MODEL", "en_US-lessac-medium")
TTS_MAX_CHARACTERS = int(os.getenv("TTS_MAX_CHARACTERS", "800"))
TTS_MAX_CACHE_FILES = int(os.getenv("TTS_MAX_CACHE_FILES", "100"))

# Post-synthesis shaping of the base voice before tone conversion. Kept near
# neutral (pitch 1.06, tempo 0.94 = slower, calmer) after feedback.
TTS_CUTE_PITCH = float(os.getenv("TTS_CUTE_PITCH", "1.06"))
TTS_CUTE_TEMPO = float(os.getenv("TTS_CUTE_TEMPO", "1.0"))
# English has its own articulation preset. Never retune Vietnamese implicitly.
TTS_EN_LENGTH_SCALE = float(os.getenv("TTS_EN_LENGTH_SCALE", "1.00"))
TTS_EN_PITCH = float(os.getenv("TTS_EN_PITCH", "1.0"))
TTS_EN_TEMPO = float(os.getenv("TTS_EN_TEMPO", "1.00"))

# Primary speech engine: "clone" recolors Piper speech with the owner-provided
# mascot clips via the local OpenVoice server (port 7861); "piper" uses the
# stock fallback voice.
TTS_ENGINE = os.getenv("TTS_ENGINE", "clone").strip().lower()
XTTS_SERVER_URL = os.getenv("XTTS_SERVER_URL", "http://127.0.0.1:7861").strip()
XTTS_TIMEOUT_SECONDS = int(os.getenv("XTTS_TIMEOUT_SECONDS", "300"))

# MinerU is kept in an isolated environment because its ML dependencies are
# much larger than the web app. RapidOCR is the lightweight offline fallback.
MINERU_EXECUTABLE = os.getenv("MINERU_EXECUTABLE", "").strip()
MINERU_BACKEND = os.getenv("MINERU_BACKEND", "pipeline").strip() or "pipeline"
MINERU_TIMEOUT_SECONDS = int(os.getenv("MINERU_TIMEOUT_SECONDS", "900"))

# Optional Google Web Detection. The image is only transmitted after the user
# explicitly opts in from the attachment panel. Without a key, visual search
# stays local and produces Google Images/Lens links from OCR text.
GOOGLE_VISION_API_KEY = _environment_value("GOOGLE_VISION_API_KEY").strip()
VISUAL_SEARCH_TIMEOUT_SECONDS = int(
    os.getenv("VISUAL_SEARCH_TIMEOUT_SECONDS", "20")
)
VISUAL_SEARCH_MAX_RESULTS = int(os.getenv("VISUAL_SEARCH_MAX_RESULTS", "8"))

# Local image understanding runs on a multimodal Ollama model. Descriptions
# stay on this machine; only the user's text keywords ever reach a search
# engine, and only after an explicit search action.
VISION_MODEL = os.getenv("VISION_MODEL", "qwen2.5vl:3b").strip() or "qwen2.5vl:3b"
VISION_TIMEOUT_SECONDS = float(os.getenv("VISION_TIMEOUT_SECONDS", "240"))

# Local media generation lives in runtime/imagegen (isolated torch CUDA venv).
# sd-turbo keeps each frame to a few seconds on a 6GB GPU.
IMAGEGEN_MODEL = os.getenv("IMAGEGEN_MODEL", "stabilityai/sd-turbo").strip()
IMAGEGEN_TIMEOUT_SECONDS = int(os.getenv("IMAGEGEN_TIMEOUT_SECONDS", "900"))

# Web search uses the keyless DuckDuckGo HTML endpoint plus local page reading.
WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
WEB_SEARCH_TIMEOUT_SECONDS = int(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "20"))
WEB_SEARCH_MAX_PAGES = int(os.getenv("WEB_SEARCH_MAX_PAGES", "3"))
WEB_FETCH_MAX_CHARACTERS = int(os.getenv("WEB_FETCH_MAX_CHARACTERS", "3000"))

API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))

# When the last browser tab closes, wait this long before exiting the whole
# app (web + API) and releasing Ollama VRAM. The desktop host is an older
# laptop, so nothing should keep running in the background.
SHUTDOWN_GRACE_SECONDS = int(os.getenv("TUTOR_SHUTDOWN_GRACE_SECONDS", "120"))
API_TOKEN = os.getenv("TUTOR_API_TOKEN", "").strip()
POSTGRES_DSN = _environment_value("TUTOR_POSTGRES_DSN").strip()
AUTH_REQUIRED = _environment_value("TUTOR_AUTH_REQUIRED", "false").lower() in {
    "1",
    "true",
    "yes",
}
AUTH_SESSION_HOURS = int(_environment_value("TUTOR_AUTH_SESSION_HOURS", "24"))

# Social sign-in. Secrets are read from the process/Windows user environment and
# are intentionally never stored in the repository.
GOOGLE_OAUTH_CLIENT_ID = _environment_value("GOOGLE_OAUTH_CLIENT_ID").strip()
GOOGLE_OAUTH_CLIENT_SECRET = _environment_value("GOOGLE_OAUTH_CLIENT_SECRET").strip()
FACEBOOK_OAUTH_CLIENT_ID = _environment_value("FACEBOOK_OAUTH_CLIENT_ID").strip()
FACEBOOK_OAUTH_CLIENT_SECRET = _environment_value(
    "FACEBOOK_OAUTH_CLIENT_SECRET"
).strip()
FACEBOOK_GRAPH_VERSION = _environment_value(
    "FACEBOOK_GRAPH_VERSION", "v25.0"
).strip()
OAUTH_PUBLIC_BASE_URL = _environment_value(
    "OAUTH_PUBLIC_BASE_URL", "http://127.0.0.1:8000"
).rstrip("/")
WEB_PUBLIC_BASE_URL = _environment_value(
    "WEB_PUBLIC_BASE_URL", "http://127.0.0.1:7860"
).rstrip("/")
OAUTH_SESSION_SECRET = _environment_value("TUTOR_OAUTH_SESSION_SECRET").strip()

APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "7860"))
APP_OPEN_BROWSER = os.getenv("APP_OPEN_BROWSER", "true").lower() in {
    "1",
    "true",
    "yes",
}
