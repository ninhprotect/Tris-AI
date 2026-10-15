"""Voice warmup at host startup: fake httpx and a fake clock, no real servers."""
import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

import workspace_host


class WarmVoiceTests(unittest.TestCase):
    def run_warm(self, post, **kwargs):
        clock=[0.0]
        fake_time=SimpleNamespace(monotonic=lambda: clock[0],
                                  sleep=Mock(side_effect=lambda s: clock.__setitem__(0,clock[0]+s)))
        out=io.StringIO()
        with patch('config.settings.TTS_ENGINE','clone'), patch('config.settings.TTS_ENABLED',True), \
             patch('config.settings.XTTS_SERVER_URL','http://127.0.0.1:7861/'), \
             patch('httpx.post',post), patch.object(workspace_host,'time',fake_time), \
             patch('services.local_tts.tris_voice.preload',return_value=[]), \
             contextlib.redirect_stdout(out):
            workspace_host.warm_voice(**kwargs)
        return out.getvalue(),fake_time.sleep

    def test_piper_voices_preload_and_failure_does_not_stop_conversion_warmup(self):
        post=Mock(return_value=Mock(status_code=200,json=lambda:{'seconds':2.0,'device':'cpu'}))
        out=io.StringIO()
        with patch('config.settings.TTS_ENGINE','clone'), patch('config.settings.TTS_ENABLED',True), \
             patch('httpx.post',post), patch('services.local_tts.tris_voice.preload',return_value=['vi','en']) as preload, \
             contextlib.redirect_stdout(out):
            workspace_host.warm_voice()
        preload.assert_called_once()
        self.assertIn('Piper voices loaded in RAM: vi, en.',out.getvalue())
        post.assert_called_once()
        out=io.StringIO()
        with patch('config.settings.TTS_ENGINE','clone'), patch('config.settings.TTS_ENABLED',True), \
             patch('httpx.post',post), patch('services.local_tts.tris_voice.preload',side_effect=OSError('broken')), \
             contextlib.redirect_stdout(out):
            workspace_host.warm_voice()
        self.assertIn('Piper voice preload skipped: OSError',out.getvalue())
        self.assertEqual(post.call_count,2)

    def test_success_prints_seconds_and_device(self):
        post=Mock(return_value=Mock(status_code=200,json=lambda:{'status':'ready','seconds':41.2,'device':'cpu'}))
        out,sleep=self.run_warm(post)
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0],'http://127.0.0.1:7861/warmup')
        self.assertIs(post.call_args.kwargs['trust_env'],False)
        self.assertGreaterEqual(post.call_args.kwargs['timeout'].read,600)
        self.assertIn('41.2s on cpu',out)
        sleep.assert_not_called()

    def test_old_server_without_warmup_stops_without_retry(self):
        post=Mock(return_value=Mock(status_code=404,text='Not Found'))
        out,sleep=self.run_warm(post)
        post.assert_called_once()
        sleep.assert_not_called()
        self.assertIn('restart the voice server',out)
        self.assertEqual(len(out.strip().splitlines()),1)

    def test_connection_errors_retry_until_deadline_then_give_up(self):
        post=Mock(side_effect=httpx.ConnectError('refused'))
        out,sleep=self.run_warm(post,deadline_seconds=9,retry_seconds=3)
        self.assertEqual(post.call_count,4)
        self.assertEqual(sleep.call_count,3)
        self.assertIn('first use',out)

    def test_server_comes_up_after_retries(self):
        ok=Mock(status_code=200,json=lambda:{'seconds':3.5,'device':'cpu'})
        post=Mock(side_effect=[httpx.ConnectError('refused'),httpx.ConnectTimeout('slow'),ok])
        out,sleep=self.run_warm(post)
        self.assertEqual(post.call_count,3)
        self.assertEqual(sleep.call_count,2)
        self.assertIn('3.5s on cpu',out)

    def test_other_failures_never_raise(self):
        for post in (Mock(side_effect=httpx.ReadTimeout('slow')),
                     Mock(return_value=Mock(status_code=500,text='{"detail":"OSError: x"}')),
                     Mock(return_value=Mock(status_code=202,text='{"status":"busy"}'))):
            out,sleep=self.run_warm(post)
            post.assert_called_once()
            sleep.assert_not_called()
            self.assertEqual(len(out.strip().splitlines()),1)

    def test_other_engines_skip_warmup(self):
        post=Mock()
        with patch('config.settings.TTS_ENGINE','piper'), patch('httpx.post',post), \
             patch('services.local_tts.tris_voice.preload',return_value=['vi']) as preload, \
             contextlib.redirect_stdout(io.StringIO()):
            workspace_host.warm_voice()
        post.assert_not_called()
        preload.assert_called_once()  # Piper itself still warms for the stock voice


if __name__=='__main__': unittest.main()
