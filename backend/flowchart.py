"""外部スクリプトなしで読める、辞書改善ワークフローのSVG。"""
from html import escape


def render_flowchart():
    parts = ['<div class="flow-wrap"><svg viewBox="0 0 1420 1840" role="img" aria-labelledby="flow-title" xmlns="http://www.w3.org/2000/svg"><title id="flow-title">音声合成・複数モデル照会・確認待ち・辞書登録と評価のフローチャート</title><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="#426c79"/></marker></defs>']

    def node(x, y, width, lines, decision=False, pending=False):
        height = 90 if decision else 64
        fill = '#fff1d3' if pending else ('#e8f3ec' if decision else '#eef4fa')
        if decision:
            parts.append(f'<polygon points="{x+width/2},{y} {x+width},{y+height/2} {x+width/2},{y+height} {x},{y+height/2}" fill="{fill}" stroke="#648895"/>')
        else:
            parts.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="9" fill="{fill}" stroke="#648895"/>')
        start = y + height / 2 - (len(lines) - 1) * 12 + 7
        for index, line in enumerate(lines):
            parts.append(f'<text x="{x+width/2}" y="{start+index*24}" text-anchor="middle" fill="#192a3d" font-size="18">{escape(line)}</text>')

    def edge(path, label='', x=0, y=0):
        parts.append(f'<path d="{path}" fill="none" stroke="#426c79" stroke-width="2" marker-end="url(#arrow)"/>')
        if label:
            parts.append(f'<text x="{x}" y="{y}" font-size="17" fill="#385861">{escape(label)}</text>')

    nodes = [(20, ['原文＋登録済みユーザー辞書の全件テーブル']),
             (120, ['一次LLM：読みの仮説 1']),
             (220, ['選択したTTS：原文を音声合成してWAV化']),
             (320, ['Whisper：文字起こし 2 ／ 対応TTSの発音解析']),
             (420, ['1対2の暫定比較＋TTSの発音差を検出'])]
    for y, lines in nodes:
        node(400, y, 560, lines)
        edge(f'M680 {y+64}V{y+100}')
    node(430, 520, 500, ['読みの食い違いあり？'], decision=True)
    edge('M680 610V670', 'あり', 695, 646)
    edge('M430 565H260V950H400', 'なし・登録対象なし', 25, 552)
    node(400, 670, 560, ['Gemini API/CLI ／ SarashinaAPIへ独立照会', '原文・全件辞書・対象語のみを渡す'])
    edge('M680 734V775')
    node(430, 775, 500, ['一次案・外部2モデルの有効回答で', '同じ読みが2票以上？'], decision=True)
    edge('M680 865V920', 'はい', 695, 896)
    edge('M930 820H1030', '2票の一致なし', 985, 765)
    node(1030, 788, 360, ['質問・回答テンプレートを保存', '確認待ち／辞書登録なし'], pending=True)
    edge('M1210 852V920')
    node(1030, 920, 360, ['ユーザーが選択・修正・却下', '実際の回答で再開'], pending=True)
    edge('M1030 952H960')
    node(400, 920, 560, ['採用読みを基準へ反映', '多数決の仮採用とユーザー判断を区別'])
    edge('M680 984V1020')
    node(400, 1020, 560, ['採用した基準で登録前を再評価', '旧基準・旧点数は保持'])
    edge('M680 1084V1120')
    node(400, 1120, 560, ['最新の辞書で重複・競合を確認', '既登録は追加しない'])
    edge('M960 1152H1030', '競合', 976, 1140)
    node(1030, 1120, 360, ['読みの競合・登録前で停止', '辞書または候補を確認'], pending=True)
    edge('M680 1184V1220')
    node(400, 1220, 560, ['文脈を含む新規の採用語句だけを登録', 'VoiSona：UIA ／ 他API：専用辞書へ反映'])
    edge('M680 1284V1320')
    node(400, 1320, 560, ['登録後：原文を再びWAV化', 'Whisperで文字起こし 3'])
    edge('M680 1384V1420')
    node(400, 1420, 560, ['同じ採用基準で登録後を評価', '残った食い違いは独立再照会'])
    edge('M680 1484V1520')
    node(430, 1520, 500, ['未解決・登録不反映あり？'], decision=True)
    edge('M930 1565H1030', 'あり', 963, 1554)
    node(1030, 1533, 360, ['確認待ち・追加自動登録を停止', '回答後は保存済み音声を再評価'], pending=True)
    edge('M680 1610V1650', 'なし', 696, 1640)
    node(400, 1650, 560, ['一巡完了'])
    edge('M680 1714V1750')
    edge('M1210 1597V1782H960')
    node(400, 1750, 560, ['各工程の読み・判断・質問・点数・音声', 'JSON＋HTMLへ継続保存'])
    parts.append('</svg></div>')
    return ''.join(parts)
