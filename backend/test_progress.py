from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

import lab
import progress_log
from reviewers import Config
from test_pipeline import Simulation


class ProgressTests(unittest.TestCase):
    def test_pending_and_human_answer_preserve_reasons_and_registration_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            s=Simulation(Path(directory),False);s.execute()
            folder=s.args.run_dir;before=(folder/'progress.jsonl').read_bytes()
            text=progress_log.read(folder)['text']
            for expected in ('全文の読み：カミテ','TTSの発音：上手 → ジョーズ','音声から認識した文章：ジョーズ','食い違い候補「上手」','キー未設定','辞書登録・再生成を保留'):
                self.assertIn(expected,text)
            s.answer('カミテ');s.execute()
            self.assertTrue((folder/'progress.jsonl').read_bytes().startswith(before))
            text=progress_log.read(folder)['text']
            for expected in ('保存済みの工程から再開','保存済み結果を再利用','利用者の指定・回答','上手＝カミテ：新規登録','登録前40点 → 登録後100点'):
                self.assertIn(expected,text)

    def test_legacy_reconstruction_does_not_write_until_first_new_event(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            lab.save(root/'before-2-whisper.json',{'text':'模擬の文字起こし'})
            result=progress_log.read(root)
            self.assertTrue(result['reconstructed']);self.assertIn('模擬の文字起こし',result['text'])
            self.assertFalse((root/'progress.jsonl').exists())
            with redirect_stdout(io.StringIO()):progress_log.emit(root,'run','resumed')
            text=progress_log.read(root)['text']
            self.assertIn('当時の実行時刻',text);self.assertIn('模擬の文字起こし',text);self.assertIn('再開',text)

    def test_events_redact_credentials_and_show_safe_http_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cfg=Config(gemini_key='secret-value')
            with redirect_stdout(io.StringIO()) as output:
                progress_log.emit(root,'run',message='secret-value',redact=cfg.redact)
                progress_log.result(root,'secondary-review',{'providers':[{'provider':'gemini','status':'unavailable','http_status':503,'error_type':'HTTPError','opinions':[]}]},cfg.redact)
            for path in (root/'progress.jsonl',root/'progress.log'):self.assertNotIn('secret-value',path.read_text(encoding='utf-8'))
            self.assertNotIn('secret-value',output.getvalue());self.assertIn('HTTP 503',progress_log.read(root)['text'])

    def test_partial_last_line_does_not_hide_completed_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with redirect_stdout(io.StringIO()):progress_log.emit(root,'run','started')
            with (root/'progress.jsonl').open('a',encoding='utf-8') as stream:stream.write('{"timestamp":')
            with (root/'progress.jsonl').open('ab') as stream:stream.write(b'\xe3')
            self.assertIn('実行：開始',progress_log.read(root)['text'])


if __name__=='__main__':unittest.main()
