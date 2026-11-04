"""保存済みの辞書検証を、音声入りの単独HTMLと一連のJSONへまとめる。"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import html
import json
from pathlib import Path
import re
from flowchart import render_flowchart

FILES = (
    "manifest.json", "original.txt", "preflight.json", "known-readings.json", "reference-1.json",
    "before-2-audio.json", "before-2-talk-analysis.json", "before-2-whisper.json", "comparison-1-2.json",
    "registration-plan.json", "registration.json", "registered-readings.json", "after-3-audio.json", "after-3-talk-analysis.json",
    "after-3-whisper.json", "comparison-1-3.json", "summary.json", "table-check.json",
    "secondary-review.json", "adjudication.json", "confirmation-questions.json", "answers-template.json",
    "reference-adopted.json", "comparison-adopted-before.json", "post-secondary-review.json",
    "post-adjudication.json", "post-confirmation-questions.json", "post-answers-template.json",
    "reference-final.json", "comparison-final-before.json", "comparison-final-after.json", "dictionary-invariance-check.json",
    "user-answers.json", "user-decision-record.json", "gemini-api-check.json", "provider-connection-check.json",
    "context-regression-before.json", "context-regression.json", "app-job.json", "dictionary-precheck.json", "progress.jsonl", "progress.log", "before-2.tts-input.json", "after-3.tts-input.json",
)
LLM_NAMES = ("reference", "comparison-1-2", "registration-plan", "comparison-1-3", "reference-adopted",
             "comparison-adopted-before", "reference-final", "comparison-final-before", "comparison-final-after")
STAGES = (
    ("preflight", "実行条件の確認"), ("known-readings", "既存の確定読み"),
    ("reference-1", "一次LLMによる読みの仮説 1"), ("before-2-audio", "登録前の原文を音声合成してWAV化"),
    ("before-2-whisper", "Whisperの文字起こし 2"), ("comparison-1-2", "1と2の暫定比較"),
    ("secondary-review", "外部2モデルへの独立照会"), ("adjudication", "採用判断と確認待ち"),
    ("reference-adopted", "採用した読みの基準"), ("comparison-adopted-before", "採用基準による登録前の再評価"),
    ("registration-plan", "採用候補からの登録計画"), ("dictionary-precheck", "最新辞書との重複・競合チェック"), ("registration", "選択TTS用の辞書登録"),
    ("registered-readings", "登録後のユーザー辞書テーブル"),
    ("after-3-audio", "登録後のTTS音声"), ("after-3-whisper", "Whisperの文字起こし 3"),
    ("comparison-1-3", "1と3の比較・再評価"),
    ("post-secondary-review", "登録後の独立照会"), ("post-adjudication", "登録後の採用判断と確認待ち"),
    ("reference-final", "最終の採用基準"), ("comparison-final-before", "最終基準による登録前の評価"),
    ("comparison-final-after", "同じ最終基準による登録後の評価"),
)


def read_trial(directory: Path, annotation=None):
    directory = directory.resolve()
    artifacts, sources, media = {}, [], {}
    names = list(FILES) + [f"llm/{name}.{suffix}.txt" for name in LLM_NAMES for suffix in ("prompt", "raw")]
    allowed_stems = {Path(name).stem for name in FILES if name.endswith('.json')}
    for archived in sorted((directory / 'decision-history').glob('*.json')):
        if any(re.fullmatch(re.escape(stem) + r'-\d{3,}\.json', archived.name) for stem in allowed_stems):
            names.append('decision-history/' + archived.name)
    for call in sorted((directory/'llm/calls').glob('*')):
        if call.is_symlink() or not call.is_dir() or not re.fullmatch(r'\d{8}T\d{12}-[a-z]+-[a-f0-9]{8}',call.name):continue
        for filename in ('metadata.json','request.txt','response.txt'):
            path=call/filename
            if path.is_file() and not path.is_symlink() and path.stat().st_size<=4*1024*1024:names.append(str(path.relative_to(directory)).replace('\\','/'))
    for name in names:
        path = directory / name
        if not path.is_file():
            continue
        raw = path.read_bytes()
        value = raw.decode("utf-8-sig")
        artifacts[name] = json.loads(value) if name.endswith(".json") else value
        sources.append({"name": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    if "manifest.json" not in artifacts or "original.txt" not in artifacts:
        raise ValueError("manifest.jsonとoriginal.txtがある実行フォルダーを指定してください。")
    expected_hash = artifacts["manifest.json"]["settings"]["text_sha256"]
    if hashlib.sha256(artifacts["original.txt"].strip().encode()).hexdigest() != expected_hash:
        raise ValueError("原文のハッシュが実行記録と一致しません。")
    for name in ("before-2.wav", "after-3.wav"):
        path = directory / name
        if path.is_file():
            if path.stat().st_size > 100 * 1024 * 1024:
                raise ValueError("埋め込み音声が100MiBを超えています。")
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            recorded = artifacts.get(name.replace(".wav", "-audio.json"), {}).get("sha256")
            if recorded and recorded != digest:
                raise ValueError("音声のハッシュが実行記録と一致しません。")
            media[name] = {"mime": "audio/wav", "bytes": len(raw), "sha256": digest,
                           "base64": base64.b64encode(raw).decode("ascii")}
            sources.append({"name": name, "bytes": len(raw), "sha256": digest})
    return {"id": directory.name, "artifacts": artifacts, "media": media, "sources": sources,
            "annotation": annotation or {}}


def e(value):
    return html.escape(str(value), quote=True)


def paragraph(text, css=""):
    return f'<p class="{css}">{e(text)}</p>'


def text_block(text):
    return f'<blockquote>{e(text)}</blockquote>'


def details(title, data):
    value = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
    return f'<details><summary>{e(title)}</summary><pre>{e(value)}</pre></details>'


def score_table(before, after=None):
    def value(item, field):
        if not item:
            return "未実施"
        if field == "score":
            return f'{item["llm_score"]:g}点'
        if field == "cer":
            return f'{item["metrics"]["cer"] * 100:.2f}％'
        if field == "match":
            return f'{item["metrics"]["kana_match_percent"]:.3f}％'
        return str(item["metrics"]["edit_distance"])
    rows = "".join(f'<tr><th>{label}</th><td>{value(before, field)}</td><td>{value(after, field)}</td></tr>'
                   for label, field in (("LLM評価", "score"), ("カナ文字誤り率", "cer"), ("カナ一致率", "match"), ("編集距離", "distance")))
    return '<div class="table-wrap"><table><thead><tr><th>指標</th><th>登録前・1対2</th><th>登録後・1対3</th></tr></thead><tbody>' + rows + '</tbody></table></div>'


def candidate_table(entries, comparison=False, reference=False):
    if not entries:
        return paragraph("該当する記録は0件です。")
    rows = []
    for entry in entries:
        expected = entry.get("expected_reading", entry.get("reading", ""))
        last = entry.get("observed_reading", "") if comparison else entry.get("state", "登録計画")
        tail = "" if reference else f'<td>{e(last or "省略")}</td>'
        rows.append(f'<tr><td>{e(entry["surface"])}</td><td>{e(expected)}</td>{tail}</tr>')
    title = "文字起こし側の読み" if comparison else "状態"
    tail_heading = "" if reference else f'<th>{title}</th>'
    return f'<div class="table-wrap"><table><thead><tr><th>表記</th><th>基準・登録する読み</th>{tail_heading}</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'


def effective_scores(data):
    return (data.get('comparison-final-before.json', data.get('comparison-adopted-before.json', data.get('comparison-1-2.json'))),
            data.get('comparison-final-after.json', data.get('comparison-1-3.json')))


def decision_body(item):
    out = []
    labels = {'user': 'ユーザー回答', 'model_consensus': '3モデルの一致', 'model_majority':'モデル多数決による仮採用', 'tts_matches_reference': 'TTSの発音と仮説が一致',
              'accepted': '採用', 'rejected': '登録却下', 'pending': '確認待ち', 'verification_failed': '登録後も不一致'}
    for row in item['decisions']:
        source = labels.get(row['source'], row['source'])
        out.append(paragraph(f'{row["surface"]}：{labels.get(row["status"], row["status"])}。採用読み＝{row["accepted_reading"] or "未確定"}。判断元＝{source or "未確定"}。'))
        out.append(paragraph(row['reason']))
        registration = row.get('registration')
        if registration:
            out.append(paragraph(f'辞書への登録単位：{registration["surface"]}＝{registration["reading"]}。対象語の採用読みと分けて記録します。'))
        out.append(paragraph('TTS解析の発音：' + '、'.join(row['tts_readings'])))
    for question in item['questions']:
        out.append('<div class="notice">' + paragraph(question['question']) + paragraph('候補：' + ' ／ '.join(question['choices'])) + paragraph(question['reason']) + '</div>')
    if item['status'] == 'pending_confirmation':
        out.append(paragraph('確認待ちです。採用未確定の語は自動登録しません。空の回答テンプレートに実際の回答を記入して再開できます。', 'notice'))
    elif not item['decisions']:
        out.append(paragraph('この工程では新しい食い違い候補はありません。'))
    return ''.join(out)


def stage_body(trial, stage):
    data = trial["artifacts"]
    item = data.get(stage + ".json", {})
    if not item:
        return paragraph("この試行には記録がありません。", "muted")
    out = []
    if stage == 'dictionary-precheck':
        labels = {'new':'新規','already_registered':'登録済み','duplicate_candidate':'候補内の重複','conflict':'読みの競合'}
        if item['has_conflicts']: out.append(paragraph('読みの競合があるため、追加登録は行いません。', 'notice'))
        for entry in item['entries']:
            out.append(paragraph(f'{entry["surface"]}＝{entry["reading"]}：{labels[entry["state"]]}。既存の読み：{"、".join(entry["existing_readings"]) or "なし"}。'))
        return ''.join(out) or paragraph('追加対象は0件です。')
    if stage == "preflight":
        settings = data["manifest.json"]["settings"]
        out.append(paragraph(f'LLMは{settings["llm_model"]}、Whisperは{Path(settings["whisper_model"]).name}、音声は{settings["voice"]} / {settings["voice_version"]}で実行しました。'))
        out.append(paragraph(data['manifest.json'].get('assumption', '旧実験：一次LLMの基準読みを正解とした評価です。')))
    elif stage in ("known-readings", "registered-readings"):
        pairs = "、".join(f'{w["surface"]}＝{w["reading"]}' for w in item["words"])
        out.append(paragraph(f'既存辞書で確定している「{pairs}」をローカルの適用対象として記録しています。Whisperへの正解ヒントには使っていません。'))
        table = item.get("table")
        if table:
            out.append(paragraph(f'登録順を保った全{len(table["rows"])}件のローカルスナップショットです。実際の送信内容はLLM送受信記録を参照してください。'))
            headings = "".join(f'<th>{e(column)}</th>' for column in table["columns"])
            rows = "".join('<tr>' + "".join(f'<td>{e(cell if cell is not None else "未記録")}</td>' for cell in row) + '</tr>' for row in table["rows"])
            out.append('<div class="table-wrap"><table><thead><tr>' + headings + '</tr></thead><tbody>' + rows + '</tbody></table></div>')
    elif stage.startswith('reference-'):
        out.append(paragraph(f'全文の読みと{len(item["words"])}件の単語別の読みです。' + ('一次LLMの仮説であり、裁定前の暫定基準です。' if stage == 'reference-1' else 'この工程で採用した評価基準です。')))
        out.append(text_block(item["reading"]))
        out.append(candidate_table(item["words"], reference=True))
    elif stage.endswith("-audio"):
        position = "登録前" if stage.startswith("before") else "登録後"
        out.append(paragraph(f'{position}の辞書の状態で、漢字の原文をVoiSonaへ送りました。音声は{item["seconds"]:.3f}秒、{item["sample_rate"]:,}Hzです。'))
        name = stage.replace("-audio", ".wav")
        audio = trial["media"].get(name)
        if audio:
            out.append(f'<audio controls preload="none" aria-label="{e(position)}の音声"><source src="data:audio/wav;base64,{audio["base64"]}" type="audio/wav"></audio>')
    elif stage.endswith("-whisper"):
        out.append(paragraph("Whisperが音声から認識した文章です。漢字への変換も含め、認識したままの文章を残しています。"))
        out.append(text_block(item["text"]))
        parameters = item.get("parameters", {})
        if parameters:
            out.append(paragraph(f'beam_size={parameters.get("beam_size")}、temperature={parameters.get("temperature")}、VAD={parameters.get("vad_filter")}。原文・基準読み・候補語をinitial_promptやhotwordsには渡していません。'))
    elif stage.startswith("comparison"):
        out.append(paragraph(f'LLM評価は{item["llm_score"]:g}点、カナ文字誤り率は{item["metrics"]["cer"] * 100:.2f}％でした。'))
        out.append(paragraph(item["explanation"]))
        out.append(text_block(item["observed_reading"]))
        out.append(candidate_table(item["errors"], comparison=True))
        for error in item["errors"]:
            out.append(paragraph(f'{error["surface"]}：{error["evidence"]}'))
    elif stage.endswith('secondary-review'):
        for provider in item['providers']:
            status = {'ok': '応答取得', 'not_configured': 'キー未設定', 'disabled': '無効', 'unavailable': '照会失敗'}.get(provider['status'], provider['status'])
            out.append(paragraph(f'{provider["provider"]}：{status}。モデル＝{provider.get("model", "未確認")}。'))
            for opinion in provider.get('opinions', []):
                out.append(paragraph(f'{opinion["surface"]}＝{opinion["reading"]}。判断不能＝{opinion["uncertain"]}。{opinion["reason"]}'))
        if not item['providers']:
            out.append(paragraph('外部照会が必要な発音差はありませんでした。'))
        else:
            scoped='targets' in item.get('independent_payload',{})
            out.append(paragraph('外部モデルには未確定語・必要な原文の文脈・その範囲の辞書適用結果だけを渡します。辞書全件や他モデルの回答は渡しません。' if scoped else 'この照会は旧形式の履歴です。当時の保存済み入力を表示します。'))
    elif stage.endswith('adjudication'):
        out.append(decision_body(item))
    elif stage == "registration-plan":
        out.append(paragraph(f'登録計画へ変換した候補は{len(item["entries"])}件でした。新方式は採用済みで登録が必要な候補だけを対象とします。'))
        out.append(candidate_table(item["entries"]))
    elif stage == "registration":
        entries = item["entries"]
        registered = [entry for entry in entries if entry.get("state") == "registered"]
        out.append(paragraph(f'登録方法は{item.get("method", item.get("state", "記録参照"))}です。新規登録は{len(registered)}件でした。'))
        out.append(candidate_table(entries))
        for entry in registered:
            duration=f'登録時間は{entry["elapsedMs"] / 1000:.3f}秒です。' if entry.get('elapsedMs') is not None else '個別の登録時間は計測していません。'
            out.append(paragraph(f'{entry["surface"]}を{entry["reading"]}として登録し、辞書ファイルの読戻しで確認しました。'+duration))
    return "".join(out) + details("この工程の記録データ", item)


def render(bundle):
    trials = bundle["trials"]
    completed = [t for t in trials if t["artifacts"]["manifest.json"]["status"] == "completed"]
    last = completed[-1] if completed else trials[-1]
    latest = last["artifacts"]
    body = ['<header><h1>ユーザー辞書 検証履歴</h1><nav><a href="#flowchart">処理手順</a><a href="#result">検証結果</a><a href="#improvements">改善記録</a><a href="#trials">工程の履歴</a><a href="#evidence">元データ</a></nav></header>',
            '<section id="flowchart"><h2>処理手順</h2>' + render_flowchart() + '</section>']
    body += ['<section id="result"><h2>検証結果</h2>', paragraph(f'{len(trials)}回の試行を、指定した順序で一連の履歴として保存しました。完了した一巡の試行は{len(completed)}回です。')]
    body.append(score_table(*effective_scores(latest)))
    newest = trials[-1]['artifacts']['manifest.json']
    if newest['status'] == 'pending_confirmation':
        body.append(paragraph('最新の試行は確認待ちです。下の点数は最後に一巡完了した試行の評価です。最新の暫定評価と質問は工程の履歴にあります。' if completed else '最新の試行は確認待ちです。表示される点数は採用未確定の暫定評価です。', 'notice'))
    body.append(paragraph("100点はLLMとWhisperを使った比較の結果です。実音声の誤読がゼロであることを保証する値ではありません。", "notice"))
    body.append('<h3>上記の評価に使った原文</h3>' + text_block(latest["original.txt"]))
    body.append('</section><section id="improvements"><h2>改善記録</h2>')
    for number, trial in enumerate(trials, 1):
        note = trial["annotation"]
        body.append(f'<article class="improvement"><h3>{number}. {e(note.get("title", trial["id"]))}</h3>')
        for text in note.get("paragraphs", []):
            body.append(paragraph(text))
        if not note.get("paragraphs"):
            body.append(paragraph(f'試行の状態は{trial["artifacts"]["manifest.json"]["status"]}です。詳細は工程の履歴に記録しています。'))
        body.append('</article>')
    for finding in bundle.get("findings", []):
        body.append('<article class="notice"><h3>' + e(finding["title"]) + '</h3>' + paragraph(finding["text"]) + '</article>')
    body.append('</section><section id="trials"><h2>工程の履歴</h2>')
    for number, trial in enumerate(trials, 1):
        manifest = trial["artifacts"]["manifest.json"]
        title = trial["annotation"].get("title", trial["id"])
        state = {"completed": "一巡完了", "pending_confirmation": "確認待ち・追加自動登録を停止", "dictionary_conflict":"辞書の読みが競合・登録前で停止", "candidates_ready": "候補作成まで・登録後評価なし", "reference_verified": "辞書添付と基準読みのみ確認"}.get(manifest["status"], manifest["status"])
        body.append(f'<article class="trial" id="trial-{number}"><h3>{number}. {e(title)}</h3><p class="state">{e(state)}</p>')
        body.append(score_table(*effective_scores(trial['artifacts'])))
        if 'progress.log' in trial['artifacts']: body.append(details('時系列の詳細ログ',trial['artifacts']['progress.log']))
        for name,value in trial['artifacts'].items():
            if name.startswith('llm/calls/'):body.append(details('LLM送受信：'+name,value))
        if 'reference-adopted.json' not in trial['artifacts'] and 'adjudication.json' in trial['artifacts']:
            body.append(paragraph('採用読みが未確定のため、上の点数は一次LLMの仮説による暫定評価です。', 'notice'))
        for index, (stage, label) in enumerate(STAGES, 1):
            finished = stage in manifest["completed_stages"] or stage + '.json' in trial['artifacts']
            duration = manifest.get("duration_seconds", {}).get(stage)
            timing = f'・{duration:.3f}秒' if duration is not None else ""
            body.append(f'<section class="stage"><h4><span>{index:02d}</span> {e(label)}</h4><p class="state">{"記録済み" if finished else "記録なし"}{timing}</p>')
            body.append(stage_body(trial, stage))
            llm_name = 'reference' if stage == 'reference-1' else stage if stage in LLM_NAMES else None
            if llm_name:
                for suffix, label in (("prompt", "LLMへの入力"), ("raw", "LLMの元の出力")):
                    key = f"llm/{llm_name}.{suffix}.txt"
                    if key in trial["artifacts"]:
                        body.append(details(label, trial["artifacts"][key]))
            body.append('</section>')
        regression = trial['artifacts'].get('context-regression.json')
        if regression:
            body.append('<section class="stage"><h4>文脈を分けた対照確認</h4>')
            phrase = regression['phrase']
            body.append(paragraph(f'登録語句「{phrase["surface"]}」のTTS解析は「{"、".join(phrase["observed"])}」でした。'))
            for control in regression['controls']:
                body.append(paragraph(f'「{control["text"]}」の上手：登録前＝{"、".join(control["before_readings"])}、登録後＝{"、".join(control["after_readings"])}。'))
            body.append(paragraph('短語の「上手」は一律登録せず、既存辞書の保持を確認しました。対照文の確認はTTS解析によるもので、人間の聴取評価ではありません。'))
            body.append('</section>')
        connection = trial['artifacts'].get('provider-connection-check.json')
        if connection:
            body.append('<section class="stage"><h4>実キーでの接続確認</h4>')
            body.append(paragraph(f'Gemini：モデル一覧APIの認証成功。生成APIはHTTP {connection["gemini"]["generation_http_status"]}、CLIは{connection["gemini"]["cli_result"]}でした。Sarashina：認証と生成応答を取得しました。'))
            body.append(paragraph('今回の登録判断はモデルの全員一致ではなく、ユーザーの最新の訂正指示を採用しています。'))
            body.append('</section>')
        for name in ("before-2-talk-analysis.json", "after-3-talk-analysis.json", "summary.json", "dictionary-invariance-check.json",
                     "user-answers.json", "user-decision-record.json", "gemini-api-check.json", "provider-connection-check.json", "context-regression.json"):
            if name in trial["artifacts"]:
                title = 'キー未設定で初回保留した時点の辞書不変検査' if name == 'dictionary-invariance-check.json' else name
                body.append(details(title, trial["artifacts"][name]))
        for name, value in trial['artifacts'].items():
            if name.startswith('decision-history/'):
                body.append(details('変更前の記録：' + name, value))
            elif name.endswith('answers-template.json') or name.endswith('confirmation-questions.json'):
                body.append(details(name, value))
        body.append('</article>')
    body.append('</section><section id="evidence"><h2>元データ</h2>')
    body.append(paragraph("原文・モデル条件・LLM入出力・工程別JSON・音声をまとめて保存しています。以下の一覧で、取り込んだファイルの名前とSHA-256を確認できます。"))
    for trial in trials:
        body.append(details(trial["id"] + "の取り込み一覧", trial["sources"]))
    body.append(paragraph("生成日時（日本時間）：" + bundle["generated_at"]) + '</section>')
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; media-src data:; script-src \'none\'; base-uri \'none\'; form-action \'none\'"><title>ユーザー辞書 検証履歴</title><style>' + CSS + '</style></head><body><main>' + "".join(body) + '</main><script id="history-data" type="application/json">' + payload + '</script></body></html>'


CSS = """
.flow-wrap{overflow:auto}.flow-wrap svg{display:block;width:100%;min-width:850px;height:auto;font-family:'Yu Gothic UI','Meiryo',sans-serif}
:root{color-scheme:light;--ink:#192a3d;--muted:#58687b;--line:#d6e0e9;--accent:#12666b}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#edf2f6;color:var(--ink);font:16px/1.85 'Yu Gothic UI','Meiryo',sans-serif}main{max-width:1060px;margin:auto;padding:32px 24px 80px}header{padding:12px 0 24px}h1{font-size:30px;letter-spacing:.03em;margin:0 0 20px}h2{font-size:24px;margin:0 0 18px}h3{font-size:20px;margin:8px 0 16px}h4{font-size:18px;margin:0 0 10px}nav{display:flex;gap:10px;flex-wrap:wrap}a{color:var(--accent)}nav a{background:white;border:1px solid var(--line);padding:6px 14px;border-radius:6px;text-decoration:none}main>section{padding:28px;background:white;border:1px solid var(--line);border-radius:12px;margin:0 0 24px}p{margin:10px 0 16px;overflow-wrap:anywhere}.notice{background:#fff7e4;border-left:4px solid #c58a18;padding:14px 18px;margin:18px 0}.improvement{border-left:3px solid var(--accent);padding:8px 0 8px 20px;margin-bottom:20px}.trial+.trial{border-top:3px solid var(--line);padding-top:28px;margin-top:34px}.stage{border-left:2px solid var(--line);margin:24px 0 0 10px;padding:0 0 18px 22px}.stage h4 span{color:var(--accent);font-variant-numeric:tabular-nums}.state,.muted{color:var(--muted);font-size:14px}.table-wrap{overflow:auto;margin:16px 0 22px}table{width:100%;border-collapse:collapse;text-align:left;white-space:normal}th,td{border-bottom:1px solid var(--line);padding:10px 12px;vertical-align:top}thead th{background:#eaf3f3}tbody th{font-weight:500}blockquote{margin:14px 0;padding:16px 20px;background:#f3f6f9;border-left:3px solid #a7bccc;overflow-wrap:anywhere;white-space:pre-wrap}audio{width:100%;margin:12px 0 20px}details{border:1px solid var(--line);border-radius:6px;margin:12px 0;background:#fafcfd}summary{cursor:pointer;padding:9px 14px;color:var(--accent);font-weight:600}pre{font:13px/1.75 Consolas,'Meiryo',monospace;white-space:pre-wrap;overflow-wrap:anywhere;max-height:460px;overflow:auto;margin:0;padding:16px;border-top:1px solid var(--line)}@media(max-width:640px){main{padding:16px 10px 40px}main>section{padding:20px 14px}h1{font-size:25px}.stage{margin-left:0;padding-left:14px}th,td{padding:8px;font-size:14px}}@media print{body{background:white}main{padding:0;max-width:none}nav,audio{display:none}main>section{border:0;padding:10px 0}.stage{break-inside:avoid}details{display:none}}
"""


def export(directories, output, notes=None):
    notes = notes or {}
    bundle = {"format": "voisona.pronunciation-dictionary-history.v1",
              "generated_at": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
              "trials": [read_trial(path, notes.get("trials", {}).get(path.name)) for path in directories],
              "findings": notes.get("findings", [])}
    output.mkdir(parents=True, exist_ok=True)
    (output / "history.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    page = output / "index.html"
    page.write_text(render(bundle), encoding="utf-8")
    return page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", type=Path, required=True, help="時系列の順番で指定する実行フォルダー")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--notes", type=Path, help="工程間の改善理由を記したJSON")
    args = parser.parse_args()
    notes = json.loads(args.notes.read_text(encoding="utf-8-sig")) if args.notes else {}
    print(export(args.run, args.output, notes).resolve())


if __name__ == "__main__":
    main()
