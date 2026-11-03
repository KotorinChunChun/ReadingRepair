"""アプリとCLIの共有状態を、実サービスへ送信しない一巡で検証する。"""
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from application import Application, exclusive
import lab
from test_pipeline import Simulation


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); backend = self.root / 'backend'; backend.mkdir()
        self.simulation = Simulation(backend, False)
        self.app = Application(self.root, self.root / 'settings.json')
        self.app.save_settings({'runs_root': str(self.root / 'runs'), 'dictionary_file': str(self.simulation.args.dictionary_file),
            'reviewer_env': str(self.root / 'missing.env'), 'whisper_model': str(self.root / 'small'),
            'whisper_site_packages': '', 'llm_model': 'simulation', 'project_root': str(backend)})

    def execute(self, job, **kwargs):
        s = self.simulation
        with ExitStack() as stack:
            stack.enter_context(patch('lab.HERE', s.root))
            stack.enter_context(patch('lab.TalkApi', lambda *a:s))
            stack.enter_context(patch('lab.Llm', lambda *a:s))
            stack.enter_context(patch('lab.Whisper', lambda *a:s))
            stack.enter_context(patch('lab.ReviewClients.review', side_effect=s.review))
            stack.enter_context(patch('lab.subprocess.run', side_effect=s.subprocess))
            stack.enter_context(redirect_stdout(io.StringIO()))
            return self.app.execute(job['id'], **kwargs)

    def test_create_pending_answer_and_resume_share_the_same_run(self):
        job=self.app.create({'text':'上手'})
        before=self.execute(job)
        self.assertEqual(before['status'],'pending_confirmation')
        q=before['questions'][0]
        self.app.answer(job['id'],{'answers':[{'id':q['id'],'action':'accept','reading':'カミテ','reason':'模擬利用者の回答'}]})
        after=self.execute(job)
        self.assertEqual(after['status'],'completed')
        self.assertEqual((self.simulation.syntheses,self.simulation.registrations),(2,1))
        self.assertTrue(Path(after['report']).is_file())

    def test_known_readings_do_not_become_fake_model_consensus(self):
        job=self.app.create({'text':'上手','known_readings':[{'surface':'上手','reading':'ジョーズ'}]})
        after=self.execute(job)
        self.assertEqual(after['status'],'completed')
        self.assertEqual(self.simulation.registrations,0)
        self.assertEqual(after['summary']['after']['llm_score'],100)

    def test_verify_requires_explicit_apply_before_registration(self):
        self.simulation.available=True
        job=self.app.create({'text':'上手','mode':'verify'})
        before=self.execute(job)
        self.assertEqual(before['status'],'candidates_ready')
        self.assertEqual(self.simulation.registrations,0)
        after=self.execute(job,apply=True)
        self.assertEqual(after['status'],'completed')
        self.assertEqual(self.simulation.registrations,1)

    def test_cancel_preserves_completed_audio_and_can_resume(self):
        job=self.app.create({'text':'上手'})
        synth=self.simulation.synthesize
        def cancelled(text,path):
            synth(text,path); self.app.cancel(job['id'])
        self.simulation.synthesize=cancelled
        stopped=self.execute(job)
        self.assertEqual(stopped['status'],'cancelled')
        self.assertTrue(Path(stopped['audio_before']).exists())
        self.assertEqual(self.simulation.registrations,0)
        self.simulation.synthesize=synth
        resumed=self.execute(job)
        self.assertEqual(resumed['status'],'pending_confirmation')
        self.assertEqual(self.simulation.syntheses,1)

    def test_same_dictionary_cannot_run_two_jobs(self):
        job=self.app.create({'text':'上手'})
        with exclusive(self.app.lock_file()), self.assertRaises(ValueError):
            self.execute(job)
        self.assertEqual(self.app.status(job['id'])['status'],'ready')

    def test_existing_job_keeps_its_dictionary_lock_after_settings_change(self):
        job=self.app.create({'text':'上手'})
        original_lock=self.app.lock_file(job['settings'])
        self.app.save_settings({'dictionary_file':str(self.root/'another-dictionary.dic')})
        with exclusive(original_lock):
            with self.assertRaises(ValueError): self.execute(job)
            path=self.app.directory(job['id'])/'app-job.json'
            saved=lab.load(path);saved['status']='running';lab.save(path,saved)
            self.assertEqual(self.app.status(job['id'])['status'],'running')
        self.assertEqual(self.app.status(job['id'])['status'],'interrupted')
        self.assertEqual(self.simulation.syntheses,0)

    def test_answers_for_other_original_or_unknown_ids_are_not_written(self):
        job=self.app.create({'text':'上手'}); self.execute(job)
        with self.assertRaises(ValueError):
            self.app.answer(job['id'],{'answers':[{'id':'foreign','action':'accept','reading':'カミテ','reason':'無効'}]})
        self.assertFalse((self.app.directory(job['id'])/'user-answers.json').exists())

    def test_original_tampering_is_rejected_before_synthesis(self):
        job=self.app.create({'text':'上手'})
        (self.app.directory(job['id'])/'input.txt').write_text('別の文章',encoding='utf-8')
        with self.assertRaises(ValueError):self.execute(job)
        self.assertEqual(self.simulation.syntheses,0)

    def test_paths_and_unknown_setting_keys_are_rejected(self):
        with self.assertRaises(ValueError):self.app.directory('../escape')
        with self.assertRaises(ValueError):self.app.save_settings({'GEMINI_API_KEY':'do-not-save'})
        self.assertNotIn('do-not-save',self.app.settings_file.read_text(encoding='utf-8'))

    def test_partial_answers_leave_other_questions_pending(self):
        job=self.app.create({'text':'上手'}); self.execute(job)
        with self.assertRaises(ValueError):self.app.answer(job['id'],{'answers':[]})
        self.assertEqual(self.app.status(job['id'])['status'],'pending_confirmation')

    def test_history_uses_saved_jobs_and_keeps_old_scores(self):
        job=self.app.create({'text':'上手'}); self.execute(job)
        history=self.app.history()
        self.assertEqual(history[0]['id'],job['id'])
        self.assertEqual(history[0]['status'],'pending_confirmation')

    def test_registration_batches_do_not_exceed_helper_limit(self):
        entries=[{'surface':chr(0x2460+i),'reading':'マルイチ'} for i in range(21)]
        sizes=[]
        def register(command,**kwargs):
            batch=lab.load(Path(command[3]));sizes.append(len(batch['entries']))
            lab.save(Path(command[4]),{'entries':[{**e,'state':'registered'} for e in batch['entries']]})
        run=self.root/'batch-run';run.mkdir()
        with patch('lab.HERE',self.simulation.root),patch('lab.subprocess.run',side_effect=register):
            result=lab.register_entries(run,self.simulation.args.dictionary_file,''.join(e['surface'] for e in entries),entries)
        self.assertEqual(sizes,[20,1]);self.assertEqual(len(result['entries']),21)

    def test_reviewer_retry_updates_only_reviewer_configuration(self):
        job=self.app.create({'text':'上手'});self.execute(job)
        self.app.save_settings({'gemini_transport':'cli','review_timeout':20,'voice':'different-voice'})
        updated=self.execute(job,retry_reviewers=True)
        self.assertEqual(updated['settings']['gemini_transport'],'cli')
        self.assertEqual(updated['settings']['review_timeout'],20)
        self.assertEqual(updated['settings']['voice'],'ui_ja_JP')

    def test_audio_and_export_use_the_job_artifacts(self):
        job=self.app.create({'text':'上手'});self.execute(job)
        audio=self.app.audio(job['id'],'before')
        self.assertGreater(audio['seconds'],0)
        self.assertTrue(Path(self.app.export(job['id'])['report']).is_file())

    def test_initial_job_metadata_archive_does_not_prevent_start(self):
        job=self.app.create({'text':'上手'})
        result=self.execute(job)
        self.assertEqual(result['status'],'pending_confirmation')
        archived=list((self.app.directory(job['id'])/'decision-history').glob('app-job-*.json'))
        self.assertTrue(any(lab.load(p)['status']=='ready' for p in archived))

    def test_multiline_inputs_roundtrip_and_resume_without_changed_text_error(self):
        for newline in ('\r\n','\n','\r'):
            with self.subTest(newline=repr(newline)):
                job=self.app.create({'text':f'上手{newline}{newline}上手'})
                path=self.app.directory(job['id'])
                self.assertEqual((path/'input.txt').read_bytes(),'上手\n\n上手'.encode())
                self.assertEqual(job['original'],'上手\n\n上手')
                result=self.execute(job)
                self.assertEqual(result['status'],'pending_confirmation')
                self.assertEqual(self.execute(job)['status'],'pending_confirmation')
                self.assertEqual((path/'original.txt').read_bytes(),'上手\n\n上手'.encode())

    def test_legacy_windows_newlines_are_recovered_only_with_original_hash(self):
        job=self.app.create({'text':'上手\n\n上手'})
        path=self.app.directory(job['id'])
        original='上手\r\n\r\n上手'
        saved=lab.load(path/'app-job.json');saved.pop('text_contract')
        saved['text_sha256']=lab.hashlib.sha256(original.encode()).hexdigest()
        lab.save(path/'app-job.json',saved)
        raw=original.replace('\n','\r\n').encode()
        (path/'input.txt').write_bytes(raw)
        self.assertEqual(self.app.status(job['id'])['original'],'上手\n\n上手')
        result=self.execute(job)
        self.assertEqual(result['status'],'pending_confirmation')
        self.assertEqual(result['text_contract'],'lf.v1')
        self.assertEqual((path/'input.txt').read_bytes(),'上手\n\n上手'.encode())
        backups=list((path/'decision-history').glob('input-before-normalization-*.bin'))
        self.assertEqual(backups[0].read_bytes(),raw)

    def test_legacy_newline_recovery_does_not_accept_changed_words(self):
        job=self.app.create({'text':'上手\n上手'})
        path=self.app.directory(job['id'])
        saved=lab.load(path/'app-job.json');saved.pop('text_contract');lab.save(path/'app-job.json',saved)
        raw='上手\r\r\n別の語'.encode();(path/'input.txt').write_bytes(raw)
        with self.assertRaises(ValueError): self.execute(job)
        self.assertEqual((path/'input.txt').read_bytes(),raw)
        self.assertEqual(self.simulation.syntheses,0)

    def test_dictionary_refresh_retains_priority_accent_and_detects_existing_conflicts(self):
        dictionary=self.simulation.args.dictionary_file
        dictionary.write_text('ＨＴＴＰ [エイチティーティーピー] ACCENT="3"\nHTTP [ベツ] ACCENT="1"\n値 [アタイ] ACCENT="0"\n値 [アタイ] ACCENT="2"\n',encoding='utf-8')
        before=dictionary.read_bytes()
        view=self.app.dictionary()
        self.assertEqual([r['priority'] for r in view['entries']],[1,2,3,4])
        self.assertEqual([r['accent'] for r in view['entries']],[3,1,0,2])
        self.assertEqual([r['state'] for r in view['issues']],['conflict','duplicate'])
        self.assertEqual(dictionary.read_bytes(),before)
        dictionary.write_text('雨衣 [ウイ]\n',encoding='utf-8')
        self.assertEqual(self.app.dictionary()['entries'][0]['surface'],'雨衣')

    def test_precheck_separates_width_duplicates_conflicts_and_circled_numbers(self):
        self.simulation.args.dictionary_file.write_text('ＨＴＴＰ [オーバー]\n１ [イチ]\n',encoding='utf-8')
        result=self.app.check_dictionary({'entries':[{'surface':'HTTP','reading':'オーバー'},{'surface':'ＨＴＴＰ','reading':'ベツ'},
            {'surface':'1','reading':'イチ'},{'surface':'①','reading':'マルイチ'},{'surface':'①','reading':'マルイチ'}]})
        self.assertEqual([r['state'] for r in result['entries']],['conflict','conflict','already_registered','new','duplicate_candidate'])
        self.assertFalse(result['can_register'])

    def test_manual_add_requires_check_and_rechecks_changed_dictionary(self):
        request={'entries':[{'surface':'雨衣','reading':'ウイ'}]}
        with self.assertRaises(ValueError): self.app.add_dictionary(request)
        checked=self.app.check_dictionary(request)
        self.simulation.args.dictionary_file.write_text('値 [アタイ]\n',encoding='utf-8')
        with patch('lab.register_entries') as register:
            result=self.app.add_dictionary({**request,'dictionary_sha256':checked['dictionary_sha256']})
            self.assertEqual(result['status'],'dictionary_changed');register.assert_not_called()

    def test_manual_add_skips_existing_and_blocks_conflicts_before_helper(self):
        dictionary=self.simulation.args.dictionary_file
        dictionary.write_text('雨衣 [ウイ] ACCENT="2"\n',encoding='utf-8')
        before=dictionary.read_bytes()
        for reading,state in (('ウイ','already_registered'),('アマギヌ','dictionary_conflict')):
            request={'entries':[{'surface':'雨衣','reading':reading}]}
            checked=self.app.check_dictionary(request)
            with patch('lab.register_entries') as register:
                result=self.app.add_dictionary({**request,'dictionary_sha256':checked['dictionary_sha256']})
                self.assertEqual(result['status'],state);register.assert_not_called()
        self.assertEqual(dictionary.read_bytes(),before)

    def test_manual_add_uses_common_registration_and_refreshes_current_table(self):
        request={'entries':[{'surface':'雨衣','reading':'ウイ'},{'surface':'雨衣','reading':'ウイ'}]}
        checked=self.app.check_dictionary(request)
        with patch('lab.HERE',self.simulation.root),patch('lab.subprocess.run',side_effect=self.simulation.subprocess):
            result=self.app.add_dictionary({**request,'dictionary_sha256':checked['dictionary_sha256']})
        self.assertEqual(result['status'],'registered')
        self.assertEqual(self.simulation.registrations,1)
        self.assertEqual(len(result['dictionary']['entries']),1)
        self.assertTrue((Path(result['record'])/'dictionary-precheck.json').is_file())

    def test_late_batch_conflict_prevents_any_registration(self):
        entries=[{'surface':chr(0x2460+i),'reading':'マルイチ'} for i in range(21)]
        dictionary=self.simulation.args.dictionary_file
        dictionary.write_text(entries[-1]['surface']+' [ベツ]\n',encoding='utf-8')
        with patch('lab.subprocess.run') as register:
            with self.assertRaises(ValueError):lab.register_entries(self.root/'conflict-run',dictionary,''.join(e['surface'] for e in entries),entries)
            register.assert_not_called()

    def test_repair_plan_checks_current_dictionary_before_apply(self):
        self.simulation.args.dictionary_file.write_text('上手 [ジョーズ]\n',encoding='utf-8')
        job=self.app.create({'text':'上手','known_readings':[{'surface':'上手','reading':'カミテ'}]})
        result=self.execute(job)
        self.assertEqual(result['status'],'dictionary_conflict')
        self.assertTrue(result['dictionary_precheck']['has_conflicts'])
        self.assertEqual(self.simulation.registrations,0)
        self.assertEqual(self.simulation.syntheses,1)

    def test_invalid_dictionary_entries_are_rejected_before_check(self):
        for entry in ({'surface':'語\n句','reading':'ゴク'},{'surface':'語','reading':'abc'},{'surface':'','reading':'ゴ'}):
            with self.subTest(entry=entry),self.assertRaises(ValueError):self.app.check_dictionary({'entries':[entry]})


if __name__=='__main__':unittest.main()
