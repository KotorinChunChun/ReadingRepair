import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from application import Application, exclusive
import dictionary_git
import lab


class DictionaryGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'native.dic'; self.source.write_text('検証 [ケンショー] ACCENT="0"\n', encoding='utf-8')
        self.repo = self.root / 'repo'; (self.repo / '.git').mkdir(parents=True)
        (self.repo / 'scripts').mkdir(); (self.repo / 'scripts/Sync-Dictionary.ps1').write_text('# fixture', encoding='utf-8')
        self.config = self.root / 'dictionary-git.json'
        lab.save(self.config, {'format':dictionary_git.FORMAT, 'enabled':True, 'repository':str(self.repo), 'source_dictionary':str(self.source)})
        self.settings = {'tts_engine':'voisona', 'dictionary_file':str(self.source)}

    def receipt(self):
        return {'changed':True, 'committed':True, 'commit':'a'*40, 'entry_count':1,
                'sha256':hashlib.sha256(self.source.read_bytes()).hexdigest()}

    def test_only_explicit_native_source_is_sent_and_credentials_are_not_inherited(self):
        reply=self.receipt()
        with patch.dict('os.environ', {'VOISONA_PASSWORD':'private-value'}), patch('dictionary_git.subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps(reply),'') ) as run:
            result=dictionary_git.sync(self.config,self.settings)
        self.assertEqual(result['status'],'committed')
        args,kwargs=run.call_args
        self.assertEqual(args[0][0],'pwsh');self.assertIn('-Commit',args[0])
        self.assertIn(str(self.source.resolve()),args[0])
        self.assertNotIn('VOISONA_PASSWORD',kwargs['env'])
        self.assertNotIn('private-value',' '.join(args[0]))

    def test_unconfigured_http_and_different_dictionary_do_not_run_sync(self):
        cases=[(self.root/'absent.json',self.settings),
               (self.config,{**self.settings,'tts_engine':'http-wav'}),
               (self.config,{**self.settings,'dictionary_file':str(self.root/'different.dic')})]
        with patch('dictionary_git.subprocess.run') as run:
            for config,settings in cases:
                self.assertIn(dictionary_git.sync(config,settings)['status'],('disabled','skipped'))
            run.assert_not_called()

    def test_command_failure_and_invalid_receipt_preserve_source(self):
        before=self.source.read_bytes()
        for response in (subprocess.CompletedProcess([],1,'','別のステージ済み変更があります。'),
                         subprocess.CompletedProcess([],0,'{"changed":false}','')):
            with patch('dictionary_git.subprocess.run',return_value=response):
                self.assertEqual(dictionary_git.sync(self.config,self.settings)['status'],'failed')
        self.assertEqual(self.source.read_bytes(),before)

    def test_source_changed_during_sync_is_reported_not_as_latest_commit(self):
        result=self.receipt(); result['sha256']='0'*64
        with patch('dictionary_git.subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps(result),'')):
            receipt=dictionary_git.sync(self.config,self.settings)
        self.assertEqual(receipt['status'],'failed');self.assertIn('同期中に実辞書が変わり',receipt['message'])


class DictionaryGitLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'native.dic'
        self.source.write_text('既存 [キソン] ACCENT="0"\n',encoding='utf-8')
        self.app=Application(self.root,self.root/'settings.json')
        self.app.save_settings({'runs_root':str(self.root/'runs'),'dictionary_file':str(self.source)})

    def receipt(self,status='committed'):
        return {'status':status,'commit':'b'*40,'message':'試験の同期結果'}

    def run_with(self,job,stage,receipt=None):
        with patch('application.lab.run',side_effect=stage), patch('application.lab.export_current_history'), \
             patch('application.dictionary_git.sync',return_value=receipt or self.receipt()) as sync, redirect_stdout(io.StringIO()):
            result=self.app.execute(job['id'])
        self.assertEqual(sync.call_count,1)
        return result

    def test_sync_runs_once_after_completion_and_remains_under_dictionary_lock(self):
        job=self.app.create({'text':'検証'})
        def stage(args):
            self.source.write_text('追加 [ツイカ] ACCENT="0"\n',encoding='utf-8')
            lab.save(args.run_dir/'manifest.json',{'status':'completed'})
        def sync(config,settings):
            self.assertIn('追加',self.source.read_text(encoding='utf-8'))
            with self.assertRaises(ValueError):
                with exclusive(self.app.lock_file()):pass
            return self.receipt()
        with patch('application.lab.run',side_effect=stage),patch('application.lab.export_current_history'), \
             patch('application.dictionary_git.sync',side_effect=sync) as transport,redirect_stdout(io.StringIO()):
            result=self.app.execute(job['id'])
        self.assertEqual(transport.call_count,1)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['dictionary_git_sync']['status'],'committed')
        self.assertTrue((self.app.directory(job['id'])/'dictionary-git-sync.json').is_file())

    def test_pending_cancelled_and_partial_failure_also_finish_sync_once(self):
        for outcome in ('pending_confirmation','cancelled','failed'):
            with self.subTest(outcome=outcome):
                job=self.app.create({'text':'検証'})
                def stage(args):
                    self.source.write_text('途中登録 [トチュートーロク] ACCENT="0"\n',encoding='utf-8')
                    lab.save(args.run_dir/'manifest.json',{'status':outcome})
                    if outcome=='cancelled':raise InterruptedError('停止')
                    if outcome=='failed':raise RuntimeError('元の登録エラー')
                result=self.run_with(job,stage)
                self.assertEqual(result['status'],outcome)
                self.assertEqual(result['dictionary_git_sync']['status'],'committed')

    def test_git_failure_does_not_replace_pipeline_result_and_completed_job_can_retry(self):
        job=self.app.create({'text':'検証'})
        result=self.run_with(job,lambda args:lab.save(args.run_dir/'manifest.json',{'status':'completed'}),self.receipt('failed'))
        self.assertEqual(result['status'],'completed');self.assertEqual(result['dictionary_git_sync']['status'],'failed')
        with patch('application.lab.run') as run,patch('application.dictionary_git.sync',return_value=self.receipt('unchanged')), \
             patch('application.lab.export_current_history'),redirect_stdout(io.StringIO()):
            result=self.app.execute(job['id'])
        run.assert_not_called();self.assertEqual(result['dictionary_git_sync']['status'],'unchanged')

    def test_manual_partial_registration_keeps_original_error_and_syncs_actual_changes(self):
        request={'entries':[{'surface':'追加','reading':'ツイカ'}]}
        request['dictionary_sha256']=self.app.check_dictionary(request)['dictionary_sha256']
        def register(*args):
            with self.source.open('a',encoding='utf-8') as stream:stream.write('追加 [ツイカ] ACCENT="0"\n')
            raise RuntimeError('元の部分登録エラー')
        with patch('application.lab.register_entries',side_effect=register), \
             patch('application.dictionary_git.sync',return_value=self.receipt()) as sync,redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'元の部分登録エラー'):self.app.add_dictionary(request)
        self.assertEqual(sync.call_count,1)
        self.assertIn('追加',self.source.read_text(encoding='utf-8'))
        self.assertEqual(len(list((self.root/'runs').glob('dictionary-additions-*/dictionary-git-sync.json'))),1)

    def test_unexpected_sync_exception_does_not_hide_original_pipeline_failure(self):
        job=self.app.create({'text':'検証'})
        with patch('application.lab.run',side_effect=RuntimeError('元の処理エラー')), \
             patch('application.dictionary_git.sync',side_effect=OSError('同期側のエラー')),redirect_stdout(io.StringIO()):
            result=self.app.execute(job['id'])
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['message'],'元の処理エラー')
        self.assertEqual(result['dictionary_git_sync']['status'],'failed')


if __name__=='__main__':unittest.main()
