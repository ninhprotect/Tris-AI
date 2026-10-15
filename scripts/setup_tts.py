"""Install the two local Tris AI speech models without starting the web app."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import TTS_EN_MODEL, TTS_MODEL_DIR, TTS_VI_MODEL


def main() -> int:
    TTS_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "piper.download_voices",
        "--data-dir",
        str(TTS_MODEL_DIR),
        TTS_VI_MODEL,
        TTS_EN_MODEL,
    ]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
