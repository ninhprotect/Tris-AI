# -*- coding: utf-8 -*-
"""XTTS v2 voice-cloning TTS server for the Tris AI mascot.

Runs inside runtime/xtts/.venv (isolated heavy deps) and serves one endpoint:
POST /tts {"text": "...", "language": "vi"} -> audio/wav

The voice is cloned zero-shot from runtime/xtts/speaker_ref.wav, which the
project owner built from their own provided mascot clips. Everything stays
on this machine.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

PORT = int(os.getenv("XTTS_PORT", "7861"))
DEVICE = os.getenv("XTTS_DEVICE", "cpu").strip().lower()
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SPEAKER_WAV = Path(
    os.getenv("XTTS_SPEAKER_WAV", str(Path(__file__).resolve().parent / "speaker_ref.wav"))
)

app = FastAPI(title="Tris XTTS clone server")
_state: dict = {"tts": None, "error": None}


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    language: str = Field(default="vi", max_length=8)


def get_tts():
    if _state["tts"] is not None or _state["error"] is not None:
        return _state["tts"]
    try:
        from TTS.api import TTS as CoquiTTS

        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        tts = CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2")
        tts.to(DEVICE)
        _state["tts"] = tts
        print(f"[xtts] model ready on {DEVICE}", flush=True)
    except Exception as exc:  # keep the server alive and report the reason
        _state["error"] = f"{type(exc).__name__}: {exc}"
        print(f"[xtts] model load FAILED: {_state['error']}", flush=True)
    return _state["tts"]


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "device": DEVICE,
        "speaker": SPEAKER_WAV.is_file(),
        "model_loaded": _state["tts"] is not None,
        "error": _state["error"],
    }


@app.post("/tts")
def tts(request: TTSRequest):
    tts_api = get_tts()
    if tts_api is None:
        return JSONResponse(
            {"detail": _state["error"] or "model not loaded"}, status_code=503
        )
    language = "vi" if request.language.lower().startswith("vi") else "en"
    text = " ".join(request.text.split())
    if not text:
        return JSONResponse({"detail": "empty text"}, status_code=400)
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            out_path = handle.name
        tts_api.tts_to_file(
            text=text,
            speaker_wav=str(SPEAKER_WAV),
            language=language,
            file_path=out_path,
            split_sentences=True,
        )
        with open(out_path, "rb") as f:
            data = f.read()
        os.unlink(out_path)
        return Response(content=data, media_type="audio/wav")
    except Exception as exc:
        try:
            os.unlink(out_path)
        except OSError:
            pass
        return JSONResponse(
            {"detail": f"{type(exc).__name__}: {exc}"}, status_code=500
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
