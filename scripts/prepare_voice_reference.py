"""Prepare speaker conditioning only; never insert source clips into TTS output.

Run with runtime/xtts/.venv/Scripts/python.exe. Requires permission from the
speaker/rights holder. Original MP3s are opened read-only, never changed.
"""
import argparse
import hashlib
import json
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--authorized', action='store_true')
    parser.add_argument('--language', choices=['vi', 'en'], default='vi')
    parser.add_argument('--include', nargs='+', help='Use only these source filenames; never change originals.')
    args = parser.parse_args()
    if not args.authorized:
        parser.error('Confirm permission with --authorized before preparing a speaker reference.')
    root = Path(__file__).resolve().parents[1] / 'runtime' / 'xtts' / 'references'
    if args.language == 'en':
        root = root.with_name('references_en')
    root.mkdir(parents=True, exist_ok=True)
    candidates, report = [], []
    for path in sorted(args.source.glob('*.mp3')):
        if args.include and path.name not in args.include:
            continue
        try:
            audio, sr = sf.read(path, dtype='float32', always_2d=True)
            audio = audio.mean(axis=1)
            clipping = float(np.mean(np.abs(audio) > .995))
            audio = librosa.resample(audio, orig_sr=sr, target_sr=22050)
            audio = sosfilt(butter(3, 70, fs=22050, btype='highpass', output='sos'), audio)
            audio, _ = librosa.effects.trim(audio, top_db=28)
            duration = len(audio)/22050
            row = {'name':path.name, 'seconds':round(duration,2), 'clipping':round(clipping,5),
                   'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            report.append(row)
            if 2 <= duration <= 12 and clipping < .01:
                rms = float(np.sqrt(np.mean(audio ** 2)))
                if rms > .002:
                    audio *= min(4, .1/rms, .95/max(float(np.max(np.abs(audio))), .001))
                    candidates.append((duration*(1-clipping), row, audio.astype('float32')))
        except Exception as exc:
            report.append({'name':path.name,'error':type(exc).__name__})
    chosen = sorted(candidates, key=lambda item:item[0], reverse=True)[:6]
    if not chosen:
        raise RuntimeError('No usable 2–12 second speech clips found.')
    references=[]
    for _, row, audio in chosen:
        output = root / (row['sha256'][:16]+'.wav')
        sf.write(output, audio, 22050, subtype='PCM_16')
        references.append({'file':output.name, **row})
    revision=hashlib.sha256(('refs-v1|'+'|'.join(row['sha256'] for row in references)).encode()).hexdigest()[:20]
    manifest={'revision':revision,'source_directory':str(args.source.resolve()),'authorized':True,
              'purpose':'speaker conditioning only; output speech is newly synthesized from text',
              'references':references,'scanned':report}
    (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'scanned':len(report),'selected':len(references),'seconds':sum(r['seconds'] for r in references),'revision':revision,'manifest':str(root/'manifest.json')},ensure_ascii=False))


if __name__=='__main__': main()
