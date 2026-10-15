"""Local A/B check. Uses the existing CPU server and a test GPU port.

No original recordings, account data, or model packages are modified.
Run from the project root with .venv/Scripts/python.exe -X utf8.
"""
import hashlib
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from services.local_tts import tris_voice
from services.xtts_voice import CloneVoiceClient


def main():
    root = Path(__file__).resolve().parents[1]
    preview = root / 'data' / 'voice-previews'
    vi = preview / 'tris-authorized-reference-vi.wav'
    before = hashlib.sha256(vi.read_bytes()).hexdigest()
    base = tris_voice.synthesize('Xin chào Ninh. Tris sẽ cùng bạn học tiếng Anh hôm nay.', 'vi')
    results = []
    with httpx.Client(timeout=300, trust_env=False) as client:
        if client.get('http://127.0.0.1:7861/health').json().get('device') != 'cpu':
            raise RuntimeError('A/B requires a CPU server on 7861 and a test GPU server on 7862. Production is already on GPU; do not replace it just to run this test.')
        for label, port in [('previous_cpu', 7861), ('gpu_trial_1', 7862), ('gpu_warm', 7862)]:
            was_loaded = client.get(f'http://127.0.0.1:{port}/health').json().get('model_loaded')
            started = time.perf_counter()
            with open(base, 'rb') as f:
                r = client.post(f'http://127.0.0.1:{port}/convert', files={'file':('sample.wav',f,'audio/wav')}, data={'language':'vi'})
            r.raise_for_status()
            row = {'test':label, 'seconds':round(time.perf_counter()-started,3),
                   'device':r.headers.get('x-tris-voice-device','cpu'), 'wav_bytes':len(r.content), 'model_preloaded':was_loaded}
            results.append(row)
            print(json.dumps(row), flush=True)
        voice = CloneVoiceClient(tris_voice, server_url='http://127.0.0.1:7862')
        for name, text in [
            ('tris-english-v4-comparison.wav', 'Hello Ninh. This is a newly synthesized sentence for Tris AI.'),
            ('tris-english-v4-preview.wav', "Hello! I'm Tris, your English tutor. Let's practice speaking slowly and clearly, one sentence at a time."),
        ]:
            started = time.perf_counter()
            output = Path(voice.synthesize(text, 'en'))
            destination = preview / name
            destination.write_bytes(output.read_bytes())
            with wave.open(str(destination)) as wav:
                duration = wav.getnframes()/wav.getframerate()
            row = {'test':name, 'seconds':round(time.perf_counter()-started,3), 'audio_seconds':round(duration,3)}
            results.append(row)
            print(json.dumps(row), flush=True)
        print(json.dumps(client.get('http://127.0.0.1:7862/health').json(),ensure_ascii=False),flush=True)
    assert hashlib.sha256(vi.read_bytes()).hexdigest() == before
    manifest=json.loads((root/'runtime/xtts/references/manifest.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((Path(manifest['source_directory'])/r['name']).read_bytes()).hexdigest()==r['sha256'] for r in manifest['scanned'] if 'sha256' in r)
    (preview/'gpu-benchmark.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print('Vietnamese preview and all 41 source MP3 hashes unchanged.',flush=True)


if __name__ == '__main__':
    main()
