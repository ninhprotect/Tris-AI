import io
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch
from services.voice_engine import DualVoiceEngine
from services.xtts_voice import CloneVoiceClient
from services.local_tts import LocalTTSError


class VoiceTests(unittest.TestCase):
    def test_no_silent_substitution(self):
        primary=Mock(); fallback=Mock()
        primary.synthesize.side_effect=LocalTTSError('Unavailable')
        with self.assertRaises(LocalTTSError): DualVoiceEngine(primary,fallback).synthesize('New sentence')
        fallback.synthesize.assert_not_called()

    def test_reference_revision_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); base=root/'base.wav'
            buf=io.BytesIO()
            with wave.open(buf,'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(22050);f.writeframes(b'\x00\x00'*2205)
            base.write_bytes(buf.getvalue())
            piper=Mock();piper.synthesize.return_value=str(base)
            client=Mock();client.get.return_value.json.return_value={'reference_revision':'first','speaker':True}
            client.post.return_value.status_code=200;client.post.return_value.content=buf.getvalue()
            voice=CloneVoiceClient(piper,client=client)
            with patch('services.xtts_voice.PROJECT_ROOT',root):
                first=voice.synthesize('New text','en')
                self.assertEqual(first,voice.synthesize('New text','en'))
                self.assertEqual(client.post.call_count,1)
                client.get.return_value.json.return_value={'reference_revision':'second','speaker':True}
                second=voice.synthesize('New text','en')
                self.assertNotEqual(first,second)
                self.assertEqual(client.post.call_count,2)
                piper.synthesize.assert_called_with('New text','en')
                self.assertEqual(client.post.call_args.kwargs['data'], {'language':'en'})

    def test_vietnamese_keeps_its_original_cache_key(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache = root/'runtime/tts/cache'
            cache.mkdir(parents=True)
            digest = hashlib.sha256('tris-clone-v3|vi-ref|vi|Xin chào'.encode()).hexdigest()[:24]
            expected = cache/f'clone-vi-{digest}.wav'
            expected.write_bytes(b'existing approved speech'*10)
            client=Mock()
            client.get.return_value.json.return_value={
                'speaker':True, 'reference_revision':'vi-ref',
                'reference_revisions':{'vi':'vi-ref','en':'new-english-ref'}}
            voice=CloneVoiceClient(Mock(),client=client)
            with patch('services.xtts_voice.PROJECT_ROOT',root):
                self.assertEqual(Path(voice.synthesize('Xin chào','vi')),expected)
            client.post.assert_not_called()


if __name__=='__main__': unittest.main()
