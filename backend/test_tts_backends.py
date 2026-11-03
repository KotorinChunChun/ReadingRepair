"""実HTTPサーバーを使い、外部TTS・利用者辞書へ触れずに境界を検証する。"""
from contextlib import ExitStack,redirect_stdout
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import os
import threading
import unittest
from unittest.mock import patch
import wave
import lab
import tts_backends
from application import Application
from test_pipeline import Simulation

class Server:
    def __init__(self):
        self.requests=[];self.code=200;self.invalid=False;outer=self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                outer.requests.append((value,self.headers.get('Authorization')))
                stream=io.BytesIO()
                with wave.open(stream,'wb') as w:
                    w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\x10\x00'*160)
                self.send_response(outer.code);self.end_headers();self.wfile.write(b'invalid secret' if outer.invalid else stream.getvalue())
            def log_message(self,*args):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join()

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.server=Server();self.addCleanup(self.server.close)
        self.env=self.root/'tts.env';self.env.write_text(f'TTS_URL=http://127.0.0.1:{self.server.server.server_port}/tts\nTTS_API_KEY=test-secret-not-in-logs\nTTS_BODY_JSON={{"input":"{{text}}","voice":"{{voice}}","response_format":"wav"}}\n',encoding='utf-8')
        self.settings={'tts_engine':'http-wav','tts_env':str(self.env),'voice':'test','voice_version':'1','api_dictionary_file':str(self.root/'dictionary.json')}
        self.backend=tts_backends.create(self.settings)
    def test_http_dictionary_applies_longest_phrase_once_and_returns_real_wav(self):
        before=self.root/'before.wav';self.backend.synthesize('舞台の上手。上手。',before)
        self.backend.register(self.root/'run','舞台の上手。上手。',[{'surface':'舞台の上手','reading':'ブタイノカミテ'},{'surface':'上手','reading':'ジョーズ'}])
        after=self.root/'after.wav';self.backend.synthesize('舞台の上手。上手。',after)
        self.assertEqual(self.server.requests[0][0]['input'],'舞台の上手。上手。')
        self.assertEqual(self.server.requests[1][0]['input'],'ブタイノカミテ。ジョーズ。')
        self.assertEqual(self.server.requests[1][1],'Bearer test-secret-not-in-logs')
        self.assertGreater(lab.wav_info(after)['seconds'],0)
        self.assertFalse(self.backend.analyze('上手')['supported'])
        self.assertEqual(lab.auxiliary_talk_differences({'words':[]},self.backend.analyze('上手')),[])
        self.assertNotIn('test-secret',after.with_suffix('.tts-input.json').read_text(encoding='utf-8'))
    def test_ascii_width_matching_preserves_unmatched_original_text(self):
        self.backend.register(self.root/'run','HTTP',[{'surface':'HTTP','reading':'エイチティーティーピー'}])
        self.assertEqual(self.backend.transformed_text('ＡとＨＴＴＰ。'),'Ａとエイチティーティーピー。')
        self.assertEqual(lab.dictionary_snapshot(self.root/'dictionary.json','ＨＴＴＰ')['words'][0]['surface'],'ＨＴＴＰ')
    def test_existing_conflict_never_overwrites_dictionary(self):
        self.backend.register(self.root/'a','上手',[{'surface':'上手','reading':'ジョーズ'}]);before=self.root.joinpath('dictionary.json').read_bytes()
        with self.assertRaises(ValueError):self.backend.register(self.root/'b','上手',[{'surface':'上手','reading':'カミテ'}])
        self.assertEqual(before,self.root.joinpath('dictionary.json').read_bytes())
    def test_duplicate_candidate_registers_only_once(self):
        self.backend.register(self.root/'a','上手',[{'surface':'上手','reading':'カミテ'}]*2)
        self.assertEqual(len(lab.load(self.root/'dictionary.json')['entries']),1)
    def test_http_failure_and_invalid_audio_hide_response_and_credentials(self):
        for code,invalid in [(503,False),(200,True),(302,True)]:
            self.server.code=code;self.server.invalid=invalid
            with self.assertRaises((ValueError,RuntimeError)) as error:self.backend.synthesize('上手',self.root/'bad.wav')
            self.assertNotIn('secret',str(error.exception));self.assertFalse((self.root/'bad.wav').exists())
    def test_non_https_external_and_credentials_in_url_rejected(self):
        for url in ('http://example.com/tts','https://user:pass@example.com/tts','https://example.com/tts?key=x'):
            self.env.write_text('TTS_URL='+url,encoding='utf-8')
            with self.assertRaises(ValueError):tts_backends.create(self.settings)
    def test_full_pipeline_uses_actual_http_before_registration_and_after(self):
        folder=self.root/'simulation';folder.mkdir();s=Simulation(folder,True)
        app=Application(self.root,self.root/'settings.json')
        app.save_settings({**self.settings,'runs_root':str(self.root/'runs'),'llm_model':'simulation','reviewer_env':str(self.root/'no.env'),'whisper_site_packages':''})
        job=app.create({'text':'上手\n上手'})
        def recognize(path):return {'text':'カミテ' if path.name.startswith('after') else 'ジョーズ','segments':[]}
        with ExitStack() as stack:
            stack.enter_context(patch('lab.Llm',lambda *a:s));stack.enter_context(patch('lab.Whisper',lambda *a:type('Recognizer',(),{'transcribe':staticmethod(recognize)})()))
            stack.enter_context(patch('lab.ReviewClients.review',side_effect=s.review));stack.enter_context(redirect_stdout(io.StringIO()))
            result=app.execute(job['id'])
        self.assertEqual(result['status'],'completed',lab.load(Path(result['settings']['runs_root'])/result['id']/'manifest.json').get('error'))
        self.assertEqual(self.server.requests[0][0]['input'],'上手\n上手');self.assertEqual(self.server.requests[1][0]['input'],'カミテ\nカミテ')
        self.assertEqual(result['before_score'],40);self.assertEqual(result['after_score'],100)
        self.assertTrue(Path(result['report']).is_file())
    def test_cli_json_remains_utf8_when_windows_default_is_cp932(self):
        env={**os.environ,'PYTHONUTF8':'0','PYTHONIOENCODING':'cp932'}
        result=subprocess.run([sys.executable,str(Path(__file__).parent/'application.py'),'status','--job','bad','--settings',str(self.root/'isolated.json')],env=env,capture_output=True)
        self.assertEqual(result.returncode,2)
        self.assertEqual(json.loads(result.stdout.decode('utf-8'))['message'],'実行IDが不正です。')
    def test_profile_switch_selects_separate_dictionary(self):
        app=Application(self.root,self.root/'settings.json');app.save_settings({'api_dictionary_file':str(self.root/'first.json')})
        settings=app.save_settings({'tts_profile':'second'})
        self.assertNotEqual(settings['api_dictionary_file'],str(self.root/'first.json'))
        with self.assertRaises(ValueError):app.save_settings({'tts_profile':'../other'})

if __name__=='__main__':unittest.main()
