import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import lab
import llm_records
from reviewers import Config,ReviewClients


class LlmRecordTests(unittest.TestCase):
    def test_running_response_can_be_refreshed_during_partial_utf8_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);record=llm_records.begin(root/'llm','primary','reference-1','model','送信内容')
            (record/'response.txt').write_bytes(b'\xe3')
            self.assertEqual(llm_records.read(root)['calls'][0]['response'],'')
            llm_records.finish(record,'ok','受信内容')
            self.assertEqual(llm_records.read(root)['calls'][0]['response'],'受信内容')

    def test_primary_records_exact_prompt_response_and_redacts_known_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);client=lab.Llm(root,'configured-model',root,{'rows':[]})
            client.record_redact=Config(gemini_key='private-token').redact
            def run(command,**kwargs):
                path=Path(command[command.index('-OutputFile')+1])
                path.write_text('{"reading":"カミテ","words":[],"reason":"private-token"}',encoding='utf-8')
                return subprocess.CompletedProcess(command,0)
            with patch('lab.subprocess.run',side_effect=run):client.ask('reference','private-token',{'original':'上手'})
            calls=llm_records.read(root)['calls'];self.assertEqual(len(calls),1)
            self.assertEqual(calls[0]['model'],'configured-model');self.assertEqual(calls[0]['status'],'ok')
            self.assertIn('上手',calls[0]['request']);self.assertIn('[REDACTED]',calls[0]['response'])
            for path in (root/'llm').rglob('*'):
                if path.is_file():self.assertNotIn('private-token',path.read_text(encoding='utf-8'))

    def test_retry_keeps_previous_response_and_does_not_reuse_it_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);client=lab.Llm(root,'test',root,{'rows':[]})
            def run(command,**kwargs):
                Path(command[command.index('-OutputFile')+1]).write_text('{"reading":"カミテ","words":[]}',encoding='utf-8')
            with patch('lab.subprocess.run',side_effect=run):client.ask('reference','初回',{'original':'上手'})
            with patch('lab.subprocess.run',side_effect=RuntimeError('transport failed')),self.assertRaises(RuntimeError):
                client.ask('reference','再照会',{'original':'上手'})
            calls=llm_records.read(root)['calls'];self.assertEqual(len(calls),2)
            failed=next(c for c in calls if c['status']=='failed');successful=next(c for c in calls if c['status']=='ok')
            self.assertEqual(failed['response'],'');self.assertIn('カミテ',successful['response'])

    def test_provider_failure_has_status_but_never_raw_http_body_or_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cfg=Config(gemini_key='private-token',sarashina_key='sara-token')
            client=ReviewClients(cfg,root/'llm')
            response={'opinions':[{'surface':'上手','reading':'カミテ','reason':'private-token','uncertain':False}]}
            error=urllib.error.HTTPError('https://example.invalid',503,'private-token',{},None)
            with patch.object(client,'gemini',side_effect=error),patch.object(client,'sarashina',return_value=(response,'actual-model')):
                client.review('上手',{'rows':[]},['上手'])
            calls=llm_records.read(root)['calls'];self.assertEqual(len(calls),2)
            gemini=next(c for c in calls if c['provider']=='gemini');self.assertEqual(gemini['http_status'],503);self.assertEqual(gemini['response'],'')
            sara=next(c for c in calls if c['provider']=='sarashina');self.assertEqual(sara['model'],'actual-model');self.assertEqual(sara['response_kind'],'parsed_json')
            self.assertNotIn('private-token',json.dumps(calls));self.assertNotIn('sara-token',json.dumps(calls))

    def test_disabled_provider_is_recorded_as_not_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ReviewClients(Config(gemini_enabled=False,sarashina_enabled=False),root/'llm').review('上手',{},['上手'])
            calls=llm_records.read(root)['calls']
            self.assertTrue(all(c['request_kind']=='not_sent' and c['request']=='' for c in calls))


if __name__=='__main__':unittest.main()
