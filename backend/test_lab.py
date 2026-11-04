import unittest
import tempfile
from pathlib import Path
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

from lab import Llm, auxiliary_talk_differences, comparison_checked, dictionary_snapshot, existing_reading_hints, kana, metrics, normalize_kana, plan_checked, reference_checked, run, validate_known_readings


class LabTests(unittest.TestCase):
    def setUp(self):
        self.original = "小鳥遊さんの値"
        self.reference = {"reading": "タカナシサンノアタイ", "words": [{"surface": "小鳥遊", "reading": "タカナシ"}, {"surface": "値", "reading": "アタイ"}]}
        self.comparison = {"errors": [{"surface": "小鳥遊", "expected_reading": "タカナシ"}]}

    def test_normalization_accepts_hiragana_and_fullwidth_punctuation(self):
        self.assertEqual(normalize_kana("たかなし、 さん。"), "タカナシサン")

    def test_identical_reading_is_full_match(self):
        self.assertEqual(metrics("あたい", "アタイ。")["cer"], 0)

    def test_substitution_and_deletion_are_counted(self):
        self.assertEqual(metrics("アタイ", "アメ")["edit_distance"], 2)

    def test_cer_can_exceed_one_and_score_is_clamped(self):
        measured = metrics("ア", "アタイアタイ")
        self.assertGreater(measured["cer"], 1)
        self.assertEqual(measured["kana_match_percent"], 0)

    def test_empty_transcript_is_all_deletions(self):
        self.assertEqual(metrics("アタイ", "")["cer"], 1)

    def test_kanji_in_kana_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            kana("小鳥遊")

    def test_reference_word_outside_original_is_rejected(self):
        with self.assertRaises(ValueError):
            reference_checked(self.original, {"reading": "アタイ", "words": [{"surface": "原文外", "reading": "アタイ"}]})

    def test_scores_require_finite_number_in_range(self):
        for score in [True, -1, 101, float("nan")]:
            with self.subTest(score=score), self.assertRaises(ValueError):
                comparison_checked(self.original, self.reference, {"observed_reading": "タカナシサンノアタイ", "score": score, "explanation": "理由", "errors": []})

    def test_surface_not_found_in_comparison_cannot_be_registered(self):
        with self.assertRaises(ValueError):
            plan_checked(self.original, self.reference, self.comparison, {"entries": [{"surface": "値", "reading": "アタイ"}]})

    def test_llm_cannot_change_reference_reading(self):
        with self.assertRaises(ValueError):
            plan_checked(self.original, self.reference, self.comparison, {"entries": [{"surface": "小鳥遊", "reading": "コトリアソビ"}]})

    def test_duplicate_candidates_are_rejected(self):
        with self.assertRaises(ValueError):
            plan_checked(self.original, self.reference, self.comparison, {"entries": [{"surface": "小鳥遊", "reading": "タカナシ"}] * 2})

    def test_context_dependent_readings_cannot_be_registered_globally(self):
        self.reference["words"].append({"surface": "小鳥遊", "reading": "コトリアソビ"})
        with self.assertRaises(ValueError):
            plan_checked(self.original, self.reference, self.comparison, {"entries": [{"surface": "小鳥遊", "reading": "タカナシ"}]})

    def test_valid_plan_preserves_original_and_reading(self):
        plan = plan_checked(self.original, self.reference, self.comparison, {"entries": [{"surface": "小鳥遊", "reading": "タカナシ"}]})
        self.assertEqual(plan["original"], self.original)
        self.assertEqual(plan["entries"], [{"surface": "小鳥遊", "reading": "タカナシ"}])

    def test_existing_readings_use_first_priority_and_only_original_words(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.dic"
            path.write_text('雨衣 [ウイ] ACCENT="0"\n雨衣 [アメコロモ] ACCENT="0"\n原文外 [ゲンブンガイ] ACCENT="0"\n', encoding="utf-8")
            self.assertEqual(existing_reading_hints(path, "雨衣です"), [{"surface": "雨衣", "reading": "ウイ"}])

    def test_registration_plan_cannot_silently_omit_errors(self):
        with self.assertRaises(ValueError):
            plan_checked(self.original, self.reference, self.comparison, {"entries": []})

    def test_auxiliary_analysis_preserves_homograph_difference(self):
        reference = {"words": [{"surface": "上手", "reading": "カミテ"}]}
        analysis = {"analyzed_text": '<tsml><word pronunciation="ジョーズ">上手</word></tsml>'}
        rows = auxiliary_talk_differences(reference, analysis)
        self.assertEqual(rows[0]["talk_reading"], "ジョーズ")
        self.assertEqual(rows[0]["reference_reading"], "カミテ")

    def test_auxiliary_analysis_ignores_devoicing_marker(self):
        analysis = {"analyzed_text": '<tsml><word pronunciation="タカナシ’">小鳥遊</word></tsml>'}
        self.assertEqual(auxiliary_talk_differences(self.reference, analysis), [])

    def test_full_dictionary_table_keeps_unrelated_words_duplicates_and_accents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.dic"
            path.write_text('雨衣 [ウイ] ACCENT="0"\n原文外 [ゲンブンガイ] ACCENT="3"\n雨衣 [アメコロモ] ACCENT="1"\n', encoding="utf-8")
            snapshot = dictionary_snapshot(path, "雨衣です")
            self.assertEqual(snapshot["table"]["rows"], [[1, "雨衣", "ウイ", 0], [2, "原文外", "ゲンブンガイ", 3], [3, "雨衣", "アメコロモ", 1]])
            self.assertEqual(snapshot["words"], [{"surface": "雨衣", "reading": "ウイ"}])
            self.assertEqual(snapshot["dictionary_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_unreadable_dictionary_row_does_not_silently_disappear(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.dic"
            path.write_text('雨衣 [ウイ] ACCENT="0"\n壊れた行\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                dictionary_snapshot(path, "雨衣")

    def test_primary_requests_never_attach_full_dictionary(self):
        table = {'columns':['優先順位','表記','読み','アクセント核'],'rows':[[1,'雨衣','ウイ',0],[2,'原文外','ゲンブンガイ',0]]}
        with tempfile.TemporaryDirectory() as directory:
            llm=Llm(Path(directory),'test',Path(directory),table)
            def fake_backend(command,**kwargs):
                prompt=Path(command[command.index('-PromptFile')+1]).read_text(encoding='utf-8')
                self.assertNotIn('原文外',prompt);self.assertNotIn(json.dumps(table,ensure_ascii=False),prompt)
                self.assertIn('修復せず',prompt)
                if 'segments' in json.loads(prompt.split('入力JSON:\n')[-1]):
                    result={'segments':[{'id':'u1','reading':'トアタイ','words':[{'surface':'値','reading':'アタイ'}]}]}
                else:result={'ok':True}
                Path(command[command.index('-OutputFile')+1]).write_text(json.dumps(result),encoding='utf-8')
            with patch('lab.subprocess.run',side_effect=fake_backend) as backend:
                reference=llm.ask('reference','検証',{'original':'雨衣と値'})
                self.assertEqual(reference['reading'],'ウイトアタイ')
                self.assertIn({'surface':'雨衣','reading':'ウイ'},reference['words'])
                for name in ('comparison-1-2','comparison-1-3'):
                    self.assertEqual(llm.ask(name,'検証',{'original':'雨衣と値','whisper_transcript':'アマギヌトアタイ'}),{'ok':True})
                self.assertEqual(backend.call_count,3)

    def test_llm_request_without_dictionary_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            llm = Llm(Path(directory), "test", Path(directory))
            with self.assertRaises(ValueError):
                llm.build_prompt("検証", {})

    def test_after_registration_reference_uses_latest_dictionary_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            llm=Llm(Path(directory),'test',Path(directory),{'rows':[]})
            llm.dictionary_table={'rows':[[1,'四月一日','ワタヌキ',0]]}
            with patch('lab.subprocess.run') as backend:
                result=llm.ask('reference-final','比較',{'original':'四月一日'})
            backend.assert_not_called()
            self.assertEqual(result,{'reading':'ワタヌキ','words':[{'surface':'四月一日','reading':'ワタヌキ'}]})
            self.assertNotIn('四月一日',llm.build_prompt('比較',{}))

    def test_reference_cannot_omit_or_override_registered_reading(self):
        hints = [{"surface": "雨衣", "reading": "ウイ"}]
        for words in ([], [{"surface": "雨衣", "reading": "アマゴロモ"}]):
            with self.subTest(words=words), self.assertRaises(ValueError):
                validate_known_readings({"words": words}, hints)
        validate_known_readings({"words": hints}, hints)

    def test_resume_rejects_old_prompt_contract_without_changing_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = "雨衣です"
            original = root / "original.txt"
            original.write_text(text, encoding="utf-8")
            args = SimpleNamespace(run_dir=root, text_file=original, llm_model="test", whisper_model=root / "small", voice="ui_ja_JP", voice_version="2.0.0", resume=True)
            settings = {"text_sha256": hashlib.sha256(text.encode()).hexdigest(), "llm_model": "test", "whisper_model": str(args.whisper_model.resolve()), "voice": args.voice, "voice_version": args.voice_version}
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"status": "completed", "settings": settings}), encoding="utf-8")
            previous = manifest.read_bytes()
            with self.assertRaisesRegex(ValueError, "LLM入力形式"):
                run(args)
            self.assertEqual(manifest.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
