"""No model/GPU downloads. Exercise device policy and language isolation."""
import contextlib
import importlib.util
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

# exercise_conversion imports numpy lazily. Import it here first: a module first imported
# inside patch.dict('sys.modules') is dropped on exit, and numpy cannot load twice per process
# (later test modules that import it would then fail).
import numpy  # noqa: F401

spec =importlib.util.spec_from_file_location('tris_clone_test', Path(__file__).resolve().parents[1]/'runtime/xtts/clone_server.py')
clone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clone)


class CloneServerTests(unittest.TestCase):
    def setUp(self):
        clone._state.update(converter=None, targets={}, error=None, device=None, device_notice=None)

    def fake_torch(self, free=3*1024**3, available=True, arches=None):
        torch = Mock()
        torch.cuda.is_available.return_value=available
        torch.cuda.get_device_capability.return_value=(6,1)
        torch.cuda.get_arch_list.return_value=arches or ['sm_61']
        torch.cuda.get_device_name.return_value='NVIDIA GeForce GTX 1060'
        torch.cuda.mem_get_info.return_value=(free,6*1024**3)
        return torch

    def test_pascal_cuda_and_low_memory_cpu_policy(self):
        with patch.dict('sys.modules', {'torch':self.fake_torch()}), patch.object(clone,'DEVICE','auto'):
            self.assertEqual(clone.preferred_device(),'cuda:0')
        with patch.dict('sys.modules', {'torch':self.fake_torch(free=256*1024**2)}):
            self.assertEqual(clone.preferred_device(),'cpu')
            self.assertIn('giữ nguyên giọng mẫu', clone._state['device_notice'])
        with patch.dict('sys.modules', {'torch':self.fake_torch(available=False)}):
            self.assertEqual(clone.preferred_device(),'cpu')
        with patch.dict('sys.modules', {'torch':self.fake_torch(arches=['sm_80'])}):
            self.assertEqual(clone.preferred_device(),'cpu')

    def test_english_reference_cannot_change_vietnamese(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ['vi','en']:
                target=root/name; target.mkdir()
                (target/'ref.wav').write_bytes(name.encode())
                (target/'manifest.json').write_text(json.dumps({'authorized':True,'references':[{'file':'ref.wav'}]}))
            with patch.object(clone,'MANIFEST',root/'vi/manifest.json'),patch.object(clone,'EN_MANIFEST',root/'en/manifest.json'):
                before=clone.reference_info('vi')
                self.assertNotEqual(before[1],clone.reference_info('en')[1])
                (root/'en/ref.wav').write_bytes(b'changed english')
                self.assertEqual(before,clone.reference_info('vi'))

    def test_cuda_failure_retries_same_voice_on_cpu(self):
        converter=Mock()
        def get_converter(force_cpu=False):
            clone._state['converter']=converter
            clone._state['device']='cpu' if force_cpu else 'cuda:0'
            converter.device=clone._state['device']
            return converter
        def convert(**kwargs):
            if converter.device=='cuda:0': raise RuntimeError('CUDA out of memory')
            Path(kwargs['output_path']).write_bytes(b'synthesized-wave'*20)
        converter.convert.side_effect=convert
        with patch.object(clone,'get_converter',side_effect=get_converter) as get, \
             patch.object(clone,'reference_info',return_value=([Path('approved.wav')],'same-reference')), \
             patch.object(clone,'release_vram') as release, \
             patch.dict('sys.modules',{'soundfile':SimpleNamespace(info=lambda _:SimpleNamespace(duration=2))}):
            result=clone.convert_locked(SimpleNamespace(file=io.BytesIO(b'audio'*100)), 'en')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.headers['x-tris-voice-device'],'cpu')
        self.assertEqual(result.headers['x-tris-voice-reference'],'same-reference')
        self.assertEqual(get.call_count,2)
        self.assertGreaterEqual(release.call_count,2)

    def test_reject_oversized_audio_before_loading_model(self):
        with patch.object(clone,'get_converter') as get:
            result=clone.convert_locked(SimpleNamespace(file=io.BytesIO(b'x'*(12*1024*1024+1))))
            self.assertEqual(result.status_code,413)
            get.assert_not_called()

    def fake_converter(self):
        converter=Mock()
        converter.extract_se.side_effect=lambda paths: Mock(**{'detach.return_value.cpu.return_value':f'emb:{paths[0]}'})
        def get_converter(force_cpu=False):
            clone._state['converter']=converter; clone._state['device']='cpu'
            return converter
        return converter,get_converter

    def test_warmup_caches_both_targets_once_per_revision(self):
        converter,get_converter=self.fake_converter()
        revisions={'vi':'rev-vi','en':'rev-en'}
        with patch.object(clone,'get_converter',side_effect=get_converter), \
             patch.object(clone,'reference_info',side_effect=lambda lang='vi':([Path(f'{lang}.wav')],revisions[lang])), \
             patch.object(clone,'release_vram') as release, \
             patch.object(clone,'exercise_conversion',return_value=True) as exercise:
            result=clone.warmup()
            body=json.loads(result.body)
            self.assertEqual(result.status_code,200)
            self.assertEqual((body['status'],body['device'],body['languages']),('ready','cpu',['vi','en']))
            self.assertIsInstance(body['seconds'],float)
            self.assertEqual(clone._state['targets'],{'vi':('rev-vi','emb:vi.wav'),'en':('rev-en','emb:en.wav')})
            self.assertEqual(converter.extract_se.call_count,2)
            exercise.assert_called_once_with(converter,'emb:vi.wav')
            release.assert_called_once()
            # Same revisions: nothing re-extracted, no second warm conversion.
            self.assertEqual(clone.warmup().status_code,200)
            self.assertEqual(converter.extract_se.call_count,2)
            self.assertEqual(exercise.call_count,1)
            self.assertEqual(release.call_count,2)
            # A changed English reference refreshes only English.
            revisions['en']='rev-en-2'
            clone.warmup()
            self.assertEqual(converter.extract_se.call_count,3)
            self.assertEqual(clone._state['targets']['vi'][0],'rev-vi')
            self.assertEqual(clone._state['targets']['en'][0],'rev-en-2')
        self.assertFalse(clone.conversion_lock.locked())

    def test_warmup_reports_busy_when_conversion_holds_lock(self):
        clone.conversion_lock.acquire()
        try:
            with patch.object(clone,'WARMUP_LOCK_WAIT_SECONDS',.01), patch.object(clone,'get_converter') as get:
                result=clone.warmup()
        finally:
            clone.conversion_lock.release()
        self.assertEqual(result.status_code,202)
        self.assertEqual(json.loads(result.body),{'status':'busy'})
        get.assert_not_called()

    def test_warmup_failure_returns_500_and_releases_lock(self):
        with patch.object(clone,'reference_info',return_value=([Path('vi.wav')],'rev')), \
             patch.object(clone,'get_converter',side_effect=OSError('missing checkpoint')), \
             patch('traceback.print_exc'):
            result=clone.warmup()
        self.assertEqual(result.status_code,500)
        self.assertEqual(json.loads(result.body)['detail'],'OSError: missing checkpoint')
        self.assertFalse(clone.conversion_lock.locked())

    def test_exercise_conversion_cleans_up_and_never_raises(self):
        written=[]
        def write(path,data,rate):
            written.append(path); Path(path).write_bytes(b'RIFF'+b'\x00'*100)
            self.assertGreater(len(data)*22050/rate,16000)
        converter=Mock(device='cpu'); converter.hps.data.sampling_rate=22050
        with patch.dict('sys.modules',{'soundfile':SimpleNamespace(write=write)}):
            self.assertTrue(clone.exercise_conversion(converter,Mock()))
            self.assertEqual(converter.convert.call_args.kwargs['message'],'TrisAI')
            converter.convert.side_effect=RuntimeError('kernel failure')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(clone.exercise_conversion(converter,Mock()))
        self.assertEqual(len(written),2)
        self.assertFalse(any(Path(p).exists() for p in written))

    def test_convert_waits_for_lock_then_gives_429(self):
        clone.conversion_lock.acquire()
        threading.Timer(.05,clone.conversion_lock.release).start()
        with patch.object(clone,'CONVERT_LOCK_WAIT_SECONDS',5), \
             patch.object(clone,'convert_locked',return_value='converted'):
            self.assertEqual(clone.convert(SimpleNamespace(file=io.BytesIO(b'a')),'vi'),'converted')
        self.assertFalse(clone.conversion_lock.locked())
        clone.conversion_lock.acquire()
        try:
            with patch.object(clone,'CONVERT_LOCK_WAIT_SECONDS',.01):
                self.assertEqual(clone.convert(SimpleNamespace(file=io.BytesIO(b'a')),'vi').status_code,429)
        finally:
            clone.conversion_lock.release()

    def test_health_lists_cached_targets(self):
        clone._state.update(device='cpu',targets={'vi':('rev-vi','emb'),'en':('rev-en','emb')})
        with patch.object(clone,'reference_info',return_value=([Path('ref.wav')],'rev')):
            self.assertEqual(clone.health()['targets_cached'],['en','vi'])
        clone._state['targets']={}
        with patch.object(clone,'reference_info',return_value=([Path('ref.wav')],'rev')):
            self.assertEqual(clone.health()['targets_cached'],[])


if __name__=='__main__': unittest.main()
