# -*- coding: utf-8 -*-
"""Voice tone-conversion server for the Tris AI mascot.

Launched by start_clone.py with the installed CUDA runtime and existing
speech dependencies. Accepts newly synthesized Piper speech and applies
authorized voice conditioning. Vietnamese/English references are separate.
Weights return to CPU between calls; GPU allocation is released. Fully local:

POST /convert (multipart file=...) -> audio/wav
POST /warmup -> JSON (pre-loads converter + vi/en target voices at startup)
"""

from __future__ import annotations

import os
import hashlib
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # vendored openvoice package

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response

PORT = int(os.getenv("CLONE_PORT", "7861"))
DEVICE = os.getenv("CLONE_DEVICE", "auto").strip().lower()
CHECKPOINT = HERE / "checkpoints_v2" / "converter"
SPEAKER_REF = HERE / "speaker_ref.wav"
MANIFEST = HERE / 'references' / 'manifest.json'
EN_MANIFEST = HERE / 'references_en' / 'manifest.json'
conversion_lock = threading.Lock()
# Speech streams sentence by sentence, so /convert queues behind a warmup or
# another tab instead of failing at once. Warmup never queues: a conversion in
# progress is already warming the same model.
CONVERT_LOCK_WAIT_SECONDS = 90
WARMUP_LOCK_WAIT_SECONDS = 5
WARMUP_LANGUAGES = ('vi', 'en')


def reference_info(language='vi'):
    manifest = EN_MANIFEST if language == 'en' and EN_MANIFEST.is_file() else MANIFEST
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding='utf-8'))
        paths = [(manifest.parent / Path(item['file']).name).resolve() for item in data['references']]
        if not data.get('authorized') or not paths or not all(p.is_file() for p in paths):
            raise RuntimeError('Speaker references are incomplete or not authorized.')
        digest = hashlib.sha256(b'refs-v1' + b''.join(p.read_bytes() for p in paths)).hexdigest()[:20]
        return paths, digest
    return [SPEAKER_REF], hashlib.sha256(SPEAKER_REF.read_bytes()).hexdigest()[:20]

app = FastAPI(title="Tris voice clone server")
_state: dict = {"converter": None, "targets": {}, "error": None, "device": None,
                "gpu_name": None, "device_notice": None, "last_conversion_seconds": None}


def preferred_device():
    import torch
    if DEVICE == 'cpu':
        return 'cpu'
    try:
        if torch.cuda.is_available():
            major, minor = torch.cuda.get_device_capability(0)
            if f'sm_{major}{minor}' not in torch.cuda.get_arch_list():
                raise RuntimeError('Installed CUDA build does not support this GPU.')
            _state['gpu_name'] = torch.cuda.get_device_name(0)
            free, _ = torch.cuda.mem_get_info(0)
            if free < 1024 ** 3:
                _state['device_notice'] = 'VRAM thấp: tạm dùng CPU, vẫn giữ nguyên giọng mẫu.'
                return 'cpu'
            _state['device_notice'] = None
            return 'cuda:0'
        _state['device_notice'] = 'CUDA chưa sẵn sàng: dùng CPU với cùng giọng mẫu.'
    except Exception:
        _state['device_notice'] = 'CUDA không tương thích: dùng CPU với cùng giọng mẫu.'
    return 'cpu'


def move_converter(converter, device):
    converter.model.to(device)
    if converter.watermark_model is not None:
        converter.watermark_model.to(device)
    converter.device = device


def release_vram():
    """Keep warm CPU weights/embeddings; release GPU tensors between requests."""
    import torch
    converter = _state['converter']
    if converter is not None:
        move_converter(converter, 'cpu')
    # OpenVoice caches STFT windows by device separately from model weights.
    from openvoice import mel_processing
    mel_processing.hann_window.clear()
    mel_processing.mel_basis.clear()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def get_converter(force_cpu=False):
    import torch
    # Physical cores: the convolutional decoder scales with cores, not hyper-threads.
    torch.set_num_threads(min(6, max(1, (os.cpu_count() or 2) // 2)))
    if _state['converter'] is None:
        from openvoice.api import ToneColorConverter
        converter = ToneColorConverter(
            str(CHECKPOINT / "config.json"), device='cpu'
        )
        converter.load_ckpt(str(CHECKPOINT / "checkpoint.pth"))
        _state["converter"] = converter
    device = 'cpu' if force_cpu else preferred_device()
    _state['device'] = device
    move_converter(_state['converter'], device)
    return _state["converter"]


def ensure_target(converter, language, paths, revision):
    """Cache the CPU target embedding once per reference revision.

    Returns True when it had to be extracted (i.e. this call did real work).
    """
    cached = _state['targets'].get(language)
    if cached and cached[0] == revision:
        return False
    target = converter.extract_se([str(p) for p in paths]).detach().cpu()
    _state['targets'][language] = (revision, target)
    return True


@app.get("/health")
def health() -> dict:
    try:
        paths, revision = reference_info()
        _, en_revision = reference_info('en')
        reference_error = None
    except Exception:
        paths, revision, en_revision, reference_error = [], '', '', 'Speaker reference unavailable'
    return {
        "status": "ok",
        "device": _state['device'] or preferred_device(),
        "gpu_name": _state['gpu_name'],
        "device_notice": _state['device_notice'],
        "last_conversion_seconds": _state['last_conversion_seconds'],
        "speaker": bool(paths),
        "reference_count": len(paths),
        "reference_revision": revision,
        "reference_revisions": {'vi': revision, 'en': en_revision},
        "engine": "openvoice-v2",
        "synthesized": True,
        "model_loaded": _state["converter"] is not None,
        "targets_cached": sorted(_state['targets']),
        "error": _state["error"] or reference_error,
    }


@app.post("/convert")
def convert(file: UploadFile = File(...), language: str = Form('vi')) -> Response:
    # Sync endpoint -> FastAPI threadpool, so a bounded blocking wait is fine.
    if not conversion_lock.acquire(timeout=CONVERT_LOCK_WAIT_SECONDS):
        return JSONResponse({'detail':'Đang tổng hợp giọng khác, vui lòng thử lại.'}, status_code=429)
    try:
        if language not in ('vi', 'en'):
            return JSONResponse({'detail': 'Language must be vi or en.'}, status_code=400)
        return convert_locked(file, language)
    finally:
        file.file.close()
        conversion_lock.release()


def convert_locked(file, language='vi'):
    started = time.perf_counter()
    src_bytes = file.file.read(12 * 1024 * 1024 + 1)
    if len(src_bytes) > 12 * 1024 * 1024:
        return JSONResponse({'detail':'Audio exceeds 12 MB.'}, status_code=413)
    if len(src_bytes) < 100:
        return JSONResponse({"detail": "empty audio"}, status_code=400)
    tmp_src = tmp_out = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as h:
            tmp_src = h.name
            h.write(src_bytes)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as h:
            tmp_out = h.name

        import soundfile as sf
        info = sf.info(tmp_src)
        if info.duration > 90 or info.duration < .1:
            return JSONResponse({'detail':'Audio duration must be 0.1–90 seconds.'}, status_code=400)
        paths, revision = reference_info(language)
        for attempt in range(2):
            try:
                converter = get_converter(force_cpu=attempt > 0)
                ensure_target(converter, language, paths, revision)
                converter.convert(
                    audio_src_path=tmp_src,
                    src_se=converter.extract_se(tmp_src),
                    tgt_se=_state['targets'][language][1].to(converter.device),
                    output_path=tmp_out, message='TrisAI',
                )
                break
            except RuntimeError:
                if attempt or not str(_state['device']).startswith('cuda'):
                    raise
                release_vram()
                _state['device_notice'] = 'GPU bận hoặc thiếu VRAM: đã xử lý bằng CPU, cùng giọng mẫu.'
        with open(tmp_out, "rb") as f:
            data = f.read()
        if len(data) <= 44:
            return JSONResponse({"detail": "conversion produced empty audio"}, 500)
        _state['error'] = None
        _state['last_conversion_seconds'] = round(time.perf_counter() - started, 3)
        return Response(content=data, media_type="audio/wav", headers={
            'X-Tris-Voice-Engine':'openvoice-v2', 'X-Tris-Voice-Reference':revision,
            'X-Tris-Voice-Device': _state['device'],
            'X-Tris-Voice-Seconds': str(_state['last_conversion_seconds']),
        })
    except Exception as exc:
        import traceback

        traceback.print_exc()
        return JSONResponse(
            {"detail": f"{type(exc).__name__}: {exc}"}, status_code=500
        )
    finally:
        if _state['converter'] is not None:
            try:
                release_vram()
            except Exception as exc:
                print(f'[clone] GPU cleanup: {type(exc).__name__}', flush=True)
        for p in (tmp_src, tmp_out):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


@app.post("/warmup")
def warmup() -> Response:
    """Pre-load converter + vi/en target voices so the first sentence is fast."""
    if not conversion_lock.acquire(timeout=WARMUP_LOCK_WAIT_SECONDS):
        return JSONResponse({'status': 'busy'}, status_code=202)
    try:
        return warmup_locked()
    finally:
        conversion_lock.release()


def warmup_locked():
    started = time.perf_counter()
    try:
        references = {lang: reference_info(lang) for lang in WARMUP_LANGUAGES}
        loaded = _state['converter'] is None
        for attempt in range(2):
            try:
                converter = get_converter(force_cpu=attempt > 0)
                for lang, (paths, revision) in references.items():
                    loaded = ensure_target(converter, lang, paths, revision) or loaded
                break
            except RuntimeError:
                if attempt or not str(_state['device']).startswith('cuda'):
                    raise
                release_vram()
                _state['device_notice'] = 'GPU bận hoặc thiếu VRAM: đã xử lý bằng CPU, cùng giọng mẫu.'
        # Only a fresh load needs hot kernels; an already warm server answers fast.
        exercised = loaded and exercise_conversion(converter, _state['targets']['vi'][1])
        return JSONResponse({
            'status': 'ready', 'seconds': round(time.perf_counter() - started, 3),
            'device': _state['device'], 'languages': list(WARMUP_LANGUAGES),
            'exercised': bool(exercised),
        })
    except Exception as exc:
        import traceback

        traceback.print_exc()
        return JSONResponse(
            {"detail": f"{type(exc).__name__}: {exc}"}, status_code=500
        )
    finally:
        if _state['converter'] is not None:
            try:
                release_vram()
            except Exception as exc:
                print(f'[clone] GPU cleanup: {type(exc).__name__}', flush=True)


def exercise_conversion(converter, target):
    """Run one ~1.2 s conversion of a quiet tone (spectrogram, decoder, WavMark).

    Best effort only: returns False instead of failing the warmup.
    """
    tmp_src = tmp_out = None
    try:
        import numpy as np
        import soundfile as sf

        rate = int(converter.hps.data.sampling_rate)
        t = np.arange(int(rate * 1.2)) / rate
        noise = np.random.default_rng(0).standard_normal(t.size)
        # >16000 output samples so the watermark chunk is exercised too.
        signal = (0.05 * np.sin(2 * np.pi * 220 * t) + 0.005 * noise).astype('float32')
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as h:
            tmp_src = h.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as h:
            tmp_out = h.name
        sf.write(tmp_src, signal, rate)
        converter.convert(
            audio_src_path=tmp_src, src_se=converter.extract_se(tmp_src),
            tgt_se=target.to(converter.device), output_path=tmp_out, message='TrisAI',
        )
        return True
    except Exception as exc:
        print(f'[clone] warmup conversion skipped: {type(exc).__name__}: {exc}', flush=True)
        return False
    finally:
        for p in (tmp_src, tmp_out):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def warm_on_start():
    """Warm this server itself, so a voice server (re)started on its own — not
    only one started together with the Tris host — answers the first sentence
    fast. The host's POST /warmup stays as a harmless second trigger."""
    try:
        response = warmup()
        print(f'[clone] startup warmup: {response.body.decode("utf-8", "replace")[:200]}', flush=True)
    except Exception as exc:
        print(f'[clone] startup warmup skipped: {type(exc).__name__}: {exc}', flush=True)


if __name__ == "__main__":
    import uvicorn

    if os.getenv("CLONE_WARMUP_ON_START", "1").strip() != "0":
        threading.Thread(target=warm_on_start, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
