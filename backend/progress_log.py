"""工程の事実を文章化し、CLI・画面・保存ログで同じ経緯を表示する。"""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import xml.etree.ElementTree as ET

LABELS = {
    'run':'実行', 'preflight':'接続条件', 'known-readings':'登録済み辞書',
    'reference-1':'一次LLMの読みの仮説', 'before-2-audio':'登録前の音声生成',
    'before-2-talk-analysis':'登録前のTTS発音', 'before-2-whisper':'登録前の文字起こし',
    'comparison-1-2':'読みの食い違いの検出', 'secondary-review':'外部モデルへの独立照会',
    'adjudication':'採用判断', 'reference-adopted':'採用した読みの基準',
    'comparison-adopted-before':'採用基準での登録前評価', 'registration-plan':'辞書登録の計画',
    'dictionary-precheck':'最新辞書との重複・競合確認', 'registration':'辞書登録',
    'registered-readings':'登録後の辞書', 'after-3-audio':'登録後の音声生成',
    'after-3-talk-analysis':'登録後のTTS発音', 'after-3-whisper':'登録後の文字起こし',
    'comparison-1-3':'登録後の評価', 'post-secondary-review':'登録後の独立照会',
    'post-adjudication':'登録後の採用判断', 'reference-final':'最終の採用基準',
    'comparison-final-before':'最終基準での登録前評価', 'comparison-final-after':'最終基準での登録後評価',
    'summary':'前後の最終結果', 'answer':'利用者の回答',
}
STATES={'started':'開始','completed':'完了','reused':'保存済み結果を再利用','failed':'失敗','cancelled':'停止','paused':'保留','resumed':'再開'}


def details(stage, value):
    if stage in ('known-readings','registered-readings'):
        yield f'辞書全{len(value.get("table",{}).get("rows",[]))}件を取得。辞書はローカルで適用し、全件テーブルはLLMへ送信しません。'
        for row in value.get('words',[]): yield f'原文中の登録語：{row["surface"]}＝{row["reading"]}'
    elif stage.startswith('reference-'):
        yield '全文の読み：' + value['reading']
        for row in value['words']: yield f'語句の読み：{row["surface"]}＝{row["reading"]}'
    elif stage.endswith('-audio'):
        yield f'WAVを生成：{value["seconds"]:.3f}秒、{value["sample_rate"]}Hz。ファイル：{Path(value["wav"]).name}'
    elif stage.endswith('-talk-analysis'):
        if value.get('supported') is False:
            yield value['reason'];return
        for word in ET.fromstring(value['analyzed_text']).iter('word'):
            if word.get('pronunciation'): yield f'TTSの発音：{word.text or ""} → {word.get("pronunciation")}'
    elif stage.endswith('-whisper'):
        yield '音声から認識した文章：' + value['text']
    elif stage.startswith('comparison-'):
        yield f'評価{value["llm_score"]:g}点、カナ文字誤り率{value["metrics"]["cer"]*100:.2f}％。{value["explanation"]}'
        yield '文字起こし側の読み：' + value['observed_reading']
        for row in value['errors']:
            yield f'食い違い候補「{row["surface"]}」：基準={row["expected_reading"]}／認識={row["observed_reading"] or "取得なし"}。根拠：{row["evidence"]}'
        if not value['errors']: yield 'この比較で食い違い候補はありません。'
    elif stage.endswith('secondary-review'):
        for provider in value.get('providers',[]):
            state={'ok':'応答取得','unavailable':'照会失敗','not_configured':'キー未設定','disabled':'無効'}.get(provider['status'],provider['status'])
            status=f'HTTP {provider["http_status"]}' if 'http_status' in provider else provider.get('error_type','')
            yield f'{provider["provider"]}：{state} {status}。モデル={provider.get("model","未確認")}、方式={provider.get("transport","未記録")}。'
            for row in provider.get('opinions',[]):
                yield f'{provider["provider"]}の意見「{row["surface"]}」＝{row["reading"]}。判断不能={row["uncertain"]}。理由：{row["reason"]}'
        if not value.get('providers'): yield '外部モデルへの照会対象はありません。'
    elif stage.endswith('adjudication'):
        sources={'user':'利用者の指定・回答','model_consensus':'一次案と独立2モデルの一致','model_majority':'モデル多数決による仮採用','tts_matches_reference':'TTSの発音と基準の一致'}
        states={'accepted':'採用','rejected':'登録しない','pending':'確認待ち','verification_failed':'登録後も不一致'}
        for row in value['decisions']:
            yield f'「{row["surface"]}」：一次案={"／".join(row["reference_readings"])}、TTS={"／".join(row["tts_readings"]) or "取得なし"}。'
            yield f'判断：{states.get(row["status"],row["status"])}。採用読み={row.get("accepted_reading") or "未確定"}。判断元={sources.get(row["source"],"未確定")}。理由：{row["reason"]}'
            for vote in row.get('votes',[]):yield f'有効票：{vote["provider"]} → {vote["reading"]}'
            for vote in row.get('abstentions',[]):yield f'棄権：{vote["provider"]}（{vote["reason"]}）'
            if row.get('needs_registration'):
                entry=row.get('registration')
                if entry: yield f'登録対象の語句：{entry["surface"]}＝{entry["reading"]}'
            elif row['status']=='accepted': yield '発音が採用読みと一致するため、辞書追加は不要です。'
        for question in value['questions']:
            yield f'確認が必要：{question["question"]} 候補：{"／".join(question["choices"])}。{question["reason"]}'
        if value['questions']: yield '辞書登録・再生成を保留しました。確認待ちで回答を保存し、「回答を反映して再開」で続行してください。'
        elif not value['decisions']: yield '新しい採用判断が必要な食い違いはありません。'
    elif stage=='registration-plan':
        yield f'採用済みの登録計画：{len(value["entries"])}件。'
        for row in value['entries']: yield f'追加する語句：{row["surface"]}＝{row["reading"]}'
        if not value['entries']: yield '登録が必要な候補はありません。辞書への追加は行いません。'
    elif stage=='dictionary-precheck':
        states={'new':'新規','already_registered':'登録済み・追加不要','duplicate_candidate':'候補内重複・追加省略','conflict':'読みの競合・追加不可'}
        for row in value['entries']:
            yield f'{row["surface"]}＝{row["reading"]}：{states[row["state"]]}。既存読み：{"／".join(row["existing_readings"]) or "なし"}'
        if value['has_conflicts']: yield '競合があるため全候補の登録と再生成を停止します。既存辞書は上書きしません。'
        elif not value['entries']: yield '追加候補は0件です。'
    elif stage=='registration':
        for row in value['entries']:
            state={'registered':'新規登録・読戻し確認済み','already_registered':'登録済み・追加省略','duplicate_candidate':'候補内重複・追加省略','failed':'登録失敗'}.get(row['state'],row['state'])
            yield f'{row["surface"]}＝{row["reading"]}：{state}。'
        if not value['entries']: yield '新規登録は0件です。現在の辞書で音声を再生成して評価します。'
    elif stage=='summary':
        yield f'同じ採用基準で評価：登録前{value["before"]["llm_score"]:g}点 → 登録後{value["after"]["llm_score"]:g}点。'
        yield f'カナ文字誤り率：{value["before"]["metrics"]["cer"]*100:.2f}％ → {value["after"]["metrics"]["cer"]*100:.2f}％。新規登録{sum(r.get("state")=="registered" for r in value["registration"]["entries"])}件。'
        yield 'これは自動比較の評価です。生成音声は「テスト再生」で確認できます。'


def render_event(event):
    timestamp=event.get('timestamp')
    moment=datetime.fromisoformat(timestamp).astimezone(timezone(timedelta(hours=9))).strftime('%H:%M:%S') if timestamp else '保存記録'
    return f'{moment}　{event["message"]}'


def emit(folder, stage, state='detail', message=None, redact=None):
    event={'type':'progress','timestamp':datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
           'stage':stage,'state':state,'message':message or f'{LABELS.get(stage,stage)}：{STATES.get(state,state)}'}
    if redact: event=redact(event)
    event['display']=render_event(event)
    folder.mkdir(parents=True,exist_ok=True)
    if not (folder/'progress.jsonl').exists():
        # 旧ジョブへ初めて追記する際も、既存工程の経緯を欠落させない。
        for previous in read(folder)['events']:
            previous={'type':'progress','state':'restored',**previous}
            if redact:previous=redact(previous)
            previous['display']=render_event(previous)
            with (folder/'progress.jsonl').open('a',encoding='utf-8',newline='\n') as stream:
                stream.write(json.dumps(previous,ensure_ascii=False)+'\n')
            with (folder/'progress.log').open('a',encoding='utf-8',newline='\n') as stream:
                stream.write(previous['display']+'\n')
    with (folder/'progress.jsonl').open('a',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(event,ensure_ascii=False)+'\n')
    with (folder/'progress.log').open('a',encoding='utf-8',newline='\n') as stream:
        stream.write(event['display']+'\n')
    print(json.dumps(event,ensure_ascii=False),flush=True)
    return event


def result(folder,stage,value,redact=None):
    for message in details(stage,value): emit(folder,stage,message=message,redact=redact)


def read(folder):
    path=folder/'progress.jsonl';events=[]
    if path.is_file():
        for line in path.read_text(encoding='utf-8',errors='replace').splitlines():
            try:
                event=json.loads(line)
                if isinstance(event,dict) and isinstance(event.get('message'),str): events.append(event)
            except json.JSONDecodeError: continue  # 実行中の末尾の未完了行は次回読込で取得する。
    reconstructed=not bool(events)
    if reconstructed:
        for stage in LABELS:
            artifact=folder/(stage+'.json')
            if artifact.is_file() and stage not in ('run','answer'):
                value=json.loads(artifact.read_text(encoding='utf-8-sig'))
                events.append({'stage':stage,'message':LABELS[stage]+'：保存済みの結果'})
                events.extend({'stage':stage,'message':message} for message in details(stage,value))
        if events: events.insert(0,{'stage':'run','message':'過去の工程JSONから復元したログです。当時の実行時刻・再開順は記録されていません。'})
    return {'events':events,'text':'\n'.join(render_event(event) for event in events),
            'reconstructed':reconstructed,'path':str(path) if path.is_file() else ''}
