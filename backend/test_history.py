import base64
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from export_history import export, read_trial, effective_scores


class HistoryTests(unittest.TestCase):
    def make_trial(self, root, original="四月一日さんです。"):
        trial = root / "trial-01"
        trial.mkdir()
        (trial / "original.txt").write_text(original, encoding="utf-8")
        manifest = {"status": "candidates_ready", "completed_stages": [], "settings": {
            "text_sha256": hashlib.sha256(original.encode()).hexdigest(), "llm_model": "test-model",
            "whisper_model": "small", "voice": "ui_ja_JP", "voice_version": "2.0.0"}}
        (trial / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return trial

    def test_only_explicit_artifacts_are_collected(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = self.make_trial(Path(directory))
            (trial / ".env").write_text("SECRET=private", encoding="utf-8")
            (trial / "dictionary-before.dic").write_text("無関係", encoding="utf-8")
            bundle = read_trial(trial)
            self.assertEqual(set(bundle["artifacts"]), {"original.txt", "manifest.json"})
            self.assertNotIn("private", json.dumps(bundle))

    def test_html_escapes_text_and_embedded_json(self):
        attack = '</script><img src="https://example.invalid/leak" onerror="alert(1)">'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trial = self.make_trial(root, attack)
            page = export([trial], root / "report")
            text = page.read_text(encoding="utf-8")
            self.assertNotIn(attack, text)
            embedded = re.search(r'<script id="history-data" type="application/json">(.*?)</script>', text).group(1)
            self.assertEqual(json.loads(embedded)["trials"][0]["artifacts"]["original.txt"], attack)
            self.assertIn("script-src 'none'", text)

    def test_audio_is_embedded_and_matches_source_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trial = self.make_trial(root)
            raw = b"RIFFtest-audio"
            (trial / "before-2.wav").write_bytes(raw)
            audio = {"sha256": hashlib.sha256(raw).hexdigest(), "seconds": 1, "sample_rate": 48000}
            (trial / "before-2-audio.json").write_text(json.dumps(audio), encoding="utf-8")
            page = export([trial], root / "report")
            self.assertIn("data:audio/wav;base64,", page.read_text(encoding="utf-8"))
            bundle = json.loads((page.parent / "history.json").read_text(encoding="utf-8"))
            media = bundle["trials"][0]["media"]["before-2.wav"]
            self.assertEqual(base64.b64decode(media["base64"]), raw)
            self.assertEqual(media["sha256"], hashlib.sha256(raw).hexdigest())

    def test_unperformed_after_stage_is_not_reported_as_a_score(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = export([self.make_trial(root)], root / "report")
            text = page.read_text(encoding="utf-8")
            self.assertIn("候補作成まで・登録後評価なし", text)
            self.assertIn("未実施", text)

    def test_changed_original_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = self.make_trial(Path(directory))
            (trial / "original.txt").write_text("別の原文", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_trial(trial)

    def test_changed_audio_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = self.make_trial(Path(directory))
            (trial / "before-2.wav").write_bytes(b"changed")
            (trial / "before-2-audio.json").write_text(json.dumps({"sha256": "wrong"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_trial(trial)

    def test_reference_only_check_shows_full_dictionary_table(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trial = self.make_trial(root)
            manifest = json.loads((trial / "manifest.json").read_text(encoding="utf-8"))
            manifest.update(status="reference_verified", completed_stages=["known-readings"])
            (trial / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            snapshot = {"words": [{"surface": "四月一日", "reading": "ワタヌキ"}],
                        "table": {"columns": ["優先順位", "表記", "読み", "アクセント核"],
                                  "rows": [[1, "四月一日", "ワタヌキ", 0], [2, "原文外", "ゲンブンガイ", 1]]}}
            (trial / "known-readings.json").write_text(json.dumps(snapshot), encoding="utf-8")
            page = export([trial], root / "report")
            content = page.read_text(encoding="utf-8")
            self.assertIn("辞書添付と基準読みのみ確認", content)
            self.assertIn("全2件のローカルスナップショット", content)
            self.assertIn("<td>原文外</td>", content)
            self.assertIn("<th>アクセント核</th>", content)

    def test_history_archives_are_allowlisted_and_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); trial = self.make_trial(root)
            history = trial / 'decision-history'; history.mkdir()
            (history / 'adjudication-001.json').write_text('{"old_decision":"previous"}', encoding='utf-8')
            (history / 'private-001.json').write_text('{"key":"should-not-export"}', encoding='utf-8')
            page = export([trial], root / 'report')
            raw = page.read_text(encoding='utf-8')
            self.assertIn('previous', raw)
            self.assertNotIn('should-not-export', raw)
            self.assertIn('変更前の記録', raw)

    def test_final_basis_is_preferred_without_erasing_provisional_scores(self):
        data = {'comparison-1-2.json': {'llm_score': 40}, 'comparison-adopted-before.json': {'llm_score': 80},
                'comparison-final-before.json': {'llm_score': 100}, 'comparison-final-after.json': {'llm_score': 100}}
        before, after = effective_scores(data)
        self.assertEqual((before['llm_score'], after['llm_score']), (100, 100))
        self.assertEqual(data['comparison-1-2.json']['llm_score'], 40)

    def test_flowchart_is_native_svg_with_no_external_scripts(self):
        import xml.etree.ElementTree as ET
        from flowchart import render_flowchart
        svg = render_flowchart()
        element = ET.fromstring(re.search(r'(<svg.*</svg>)', svg).group(1))
        self.assertTrue(element.tag.endswith('svg'))
        self.assertIn('Gemini API/CLI', svg); self.assertIn('確認待ち', svg)
        self.assertNotIn('<script', svg)

    def test_context_control_results_are_readable_and_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);trial=self.make_trial(root)
            data={'phrase':{'surface':'舞台の上手','observed':['ブタイノカミテ']},'controls':[{'text':'歌が上手','before_readings':['ジョーズ'],'after_readings':['ジョーズ']}], 'existing_rows_preserved':True}
            (trial/'context-regression.json').write_text(json.dumps(data),encoding='utf-8')
            page=export([trial],root/'report')
            text=page.read_text(encoding='utf-8')
            self.assertIn('登録語句「舞台の上手」',text)
            self.assertIn('登録前＝ジョーズ、登録後＝ジョーズ',text)
            self.assertIn('context-regression.json',read_trial(trial)['artifacts'])

    def test_dictionary_conflict_is_preserved_and_explained_before_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);trial=self.make_trial(root)
            manifest=json.loads((trial/'manifest.json').read_text(encoding='utf-8'));manifest['status']='dictionary_conflict'
            (trial/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            checked={'has_conflicts':True,'entries':[{'surface':'上手','reading':'カミテ','state':'conflict','existing_readings':['ジョウズ']}]}
            (trial/'dictionary-precheck.json').write_text(json.dumps(checked),encoding='utf-8')
            page=export([trial],root/'report');text=page.read_text(encoding='utf-8')
            self.assertIn('辞書の読みが競合・登録前で停止',text)
            self.assertIn('上手＝カミテ：読みの競合。既存の読み：ジョウズ。',text)
            self.assertEqual(read_trial(trial)['artifacts']['dictionary-precheck.json'],checked)


if __name__ == "__main__":
    unittest.main()
