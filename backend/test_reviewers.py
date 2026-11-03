import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from reviewers import Config, ReviewClients, run_cli, validate_opinions


def opinion(reading='カミテ'):
    return {'opinions': [{'surface': '上手', 'reading': reading, 'reason': '舞台の文脈', 'uncertain': False}]}


class ReviewerTests(unittest.TestCase):
    def test_blank_keys_never_launch_network_or_cli(self):
        with patch.object(ReviewClients, 'gemini') as g, patch.object(ReviewClients, 'sarashina') as s:
            result = ReviewClients(Config()).review('舞台の上手', {}, ['上手'])
        self.assertFalse(g.called or s.called)
        self.assertEqual([p['status'] for p in result['providers']], ['not_configured'] * 2)

    def test_independent_prompts_do_not_include_other_opinions(self):
        prompts = []
        def backend(prompt):
            prompts.append(prompt)
            return opinion(), 'test-model'
        clients = ReviewClients(Config(gemini_key='gemini-secret', sarashina_key='sara-secret'))
        with patch.object(clients, 'gemini', side_effect=backend), patch.object(clients, 'sarashina', side_effect=backend):
            result = clients.review('舞台の上手', {'rows': []}, ['上手'])
        self.assertEqual(prompts[0], prompts[1])
        self.assertNotIn('gemini-secret', json.dumps(result))
        self.assertNotIn('sara-secret', json.dumps(result))
        self.assertNotIn('comparison_1_2', prompts[0])

    def test_errors_and_response_text_do_not_leak_keys(self):
        clients = ReviewClients(Config(gemini_key='gemini-secret', sarashina_key='sara-secret'))
        bad = opinion(); bad['opinions'][0]['reason'] = 'sara-secret'
        with patch.object(clients, 'gemini', side_effect=RuntimeError('gemini-secret')), patch.object(clients, 'sarashina', return_value=(bad, 'test')):
            result = clients.review('上手', {}, ['上手'])
        raw = json.dumps(result)
        self.assertNotIn('gemini-secret', raw); self.assertNotIn('sara-secret', raw)
        self.assertIn('[REDACTED]', raw)

    def test_missing_duplicate_and_foreign_opinions_are_rejected(self):
        for value in ({'opinions': []}, {'opinions': opinion()['opinions'] * 2}, {'opinions': [{**opinion()['opinions'][0], 'surface': '別語'}]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_opinions(value, ['上手'])

    def test_wrong_uncertainty_and_non_kana_are_rejected(self):
        for replacement in ({'uncertain': 'false'}, {'reading': '上手'}):
            value = opinion(); value['opinions'][0].update(replacement)
            with self.assertRaises(ValueError): validate_opinions(value, ['上手'])

    def test_config_reads_only_requested_file_and_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'keys.env'
            path.write_text('SARASHINA_API_KEY=secret\nREVIEW_TIMEOUT_SECONDS=45\n', encoding='utf-8')
            cfg = Config.load(path, {'SARASHINA_MODEL': 'test-model'})
            self.assertEqual(cfg.timeout, 45); self.assertEqual(cfg.sarashina_model, 'test-model')
            self.assertNotIn('secret', repr(cfg)); self.assertNotIn('secret', json.dumps(cfg.public()))

    def test_base_url_with_secret_query_is_rejected(self):
        with self.assertRaises(ValueError): ReviewClients(Config(sarashina_base='https://api.sarashina.ai/v1?key=secret'))

    def test_sarashina_transport_uses_json_and_authorization_only_in_header(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'model': 'mock-sara', 'choices': [{'message': {'content': json.dumps(opinion())}}]}).encode()
        opener = MagicMock(); opener.open.return_value = response
        with patch('reviewers.urllib.request.build_opener', return_value=opener):
            value, model = ReviewClients(Config(sarashina_key='transport-secret')).sarashina('独立した原文と辞書')
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.sarashina.ai/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer transport-secret')
        self.assertNotIn('transport-secret', request.data.decode())
        self.assertEqual(json.loads(request.data)['response_format'], {'type': 'json_object'})
        self.assertEqual((value, model), (opinion(), 'mock-sara'))

    def test_direct_gemini_api_keeps_key_in_header_and_parses_json(self):
        from unittest.mock import MagicMock
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps({'modelVersion':'test-gemini','candidates':[{'content':{'parts':[{'text':json.dumps(opinion())}]}}]}).encode()
        opener=MagicMock();opener.open.return_value=response
        client=ReviewClients(Config(gemini_key='transport-secret',gemini_model='test-model',gemini_transport='api'))
        with patch('reviewers.urllib.request.build_opener',return_value=opener):value,model=client.gemini('原文と辞書')
        request=opener.open.call_args.args[0]
        self.assertEqual(request.get_header('X-goog-api-key'),'transport-secret')
        self.assertNotIn('transport-secret',request.full_url+request.data.decode())
        self.assertEqual(json.loads(request.data)['generationConfig']['responseMimeType'],'application/json')
        self.assertEqual((value,model),(opinion(),'test-gemini'))

    def test_http_failure_is_not_a_successful_secondary_opinion(self):
        import urllib.error
        client=ReviewClients(Config(gemini_key='secret',gemini_model='test-model',gemini_transport='api'))
        with patch.object(client,'gemini',side_effect=urllib.error.HTTPError('https://example.invalid',503,'private-secret',{},None)):
            result=client.review('上手',{},['上手'])
        self.assertEqual(result['providers'][0]['status'],'unavailable')
        self.assertEqual(result['providers'][0]['http_status'],503)
        self.assertNotIn('private-secret',json.dumps(result))

    def test_gemini_transport_isolates_tools_home_and_foreign_keys(self):
        def execute(command, **kwargs):
            env = kwargs['env']; work = Path(kwargs['cwd'])
            self.assertEqual(env['GEMINI_API_KEY'], 'gemini-secret')
            self.assertNotIn('SARASHINA_API_KEY', env)
            self.assertNotIn('OPENAI_API_KEY', env)
            self.assertEqual(env['GEMINI_CLI_HOME'], str(work))
            self.assertEqual(env['GEMINI_CLI_TRUST_WORKSPACE'], 'true')
            settings = json.loads((work / '.gemini/settings.json').read_text())
            self.assertEqual(settings['tools']['core'], [])
            self.assertEqual(settings['mcpServers'], {})
            self.assertIn('decision = "deny"', (work / '.gemini/policies/deny-tools.toml').read_text())
            self.assertEqual(kwargs['input'], '独立入力')
            self.assertNotIn('gemini-secret', str(command))
            return SimpleNamespace(returncode=0, stdout=json.dumps({'response': json.dumps(opinion())}))
        with patch.dict('os.environ', {'SARASHINA_API_KEY': 'other-secret', 'OPENAI_API_KEY': 'other-secret'}), patch('reviewers.shutil.which', return_value='gemini.cmd'), patch('reviewers.run_cli', side_effect=execute):
            value, _ = ReviewClients(Config(gemini_key='gemini-secret')).gemini('独立入力')
        self.assertEqual(value, opinion())

    def test_cli_reads_input_and_returns_output(self):
        result=run_cli([sys.executable,'-c','import sys; print(sys.stdin.read())'], input='読みの検証',
                       text=True,encoding='utf-8',timeout=10)
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.stdout.strip(),'読みの検証')

    @unittest.skipUnless(os.name=='nt','Windowsのプロセスツリー終了を検証')
    def test_timeout_stops_cli_descendant(self):
        import ctypes
        from ctypes import wintypes
        script='import subprocess,sys,time,pathlib; child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(15)"]); pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(15)'
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'child.pid'
            with self.assertRaises(TimeoutError):
                run_cli([sys.executable,'-c',script,str(path)],input='',text=True,encoding='utf-8',timeout=1)
            self.assertTrue(path.exists())
            kernel=ctypes.windll.kernel32;kernel.OpenProcess.restype=wintypes.HANDLE
            handle=kernel.OpenProcess(0x100000,False,int(path.read_text()))
            if handle:
                try:self.assertNotEqual(kernel.WaitForSingleObject(wintypes.HANDLE(handle),0),258,'子プロセスが残存しています')
                finally:kernel.CloseHandle(wintypes.HANDLE(handle))


if __name__ == '__main__': unittest.main()
