"""読みの不一致を根拠別に記録し、未確定のまま辞書へ書かない。"""
import hashlib
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import unicodedata
import xml.etree.ElementTree as ET


def width_key(text):
    """ASCII英数字の幅だけを統一する。丸数字等の意味は変えない。"""
    return ''.join(chr(ord(c) - 0xFEE0) if 'Ａ' <= c <= 'Ｚ' or 'ａ' <= c <= 'ｚ' or '０' <= c <= '９' else c for c in text)


def canonical(text):
    text = unicodedata.normalize('NFKC', text).replace('’', '').replace("'", '')
    text = ''.join(chr(ord(c) + 0x60) if 'ぁ' <= c <= 'ゖ' else c for c in text)
    groups = {'ア': 'アカガサザタダナハバパマヤラワァャヵ', 'イ': 'イキギシジチヂニヒビピミリヰィ',
              'ウ': 'ウクグスズツヅヌフブプムユルヴゥュ', 'エ': 'エケゲセゼテデネヘベペメレヱェヶ',
              'オ': 'オコゴソゾトドノホボポモヨロヲォョ'}
    vowels = {c: vowel for vowel, chars in groups.items() for c in chars}
    out, previous = [], ''
    for c in text:
        if c in " \t\r\n、。・":
            continue
        if c == 'ー':
            out.append(c); continue
        if c in vowels and c in (previous, 'ウ' if previous == 'オ' else '', 'イ' if previous == 'エ' else ''):
            out.append('ー')
        else:
            out.append(c)
        previous = vowels.get(c, '')
    return ''.join(out)


def tts_occurrences(original, analysis, surface):
    if analysis.get('supported') is False: return []
    original, surface = width_key(original), width_key(surface)
    words, pieces, cursor = [], [], 0
    for node in ET.fromstring(analysis['analyzed_text']).iter('word'):
        text = width_key(node.text or '')
        if not text:
            continue
        words.append((cursor, cursor + len(text), node.get('pronunciation', '')))
        pieces.append(text);cursor += len(text)
    # 数字の読み替え等で別の語が変化しても、後続の完全一致部分を対応づける。
    positions={}
    for block in SequenceMatcher(None,original,''.join(pieces),autojunk=False).get_matching_blocks():
        positions.update((block.a+i,block.b+i) for i in range(block.size))
    readings = []
    for match in re.finditer(re.escape(surface), original):
        mapped=[positions.get(i) for i in range(match.start(),match.end())]
        if not mapped or any(p is None for p in mapped) or mapped != list(range(mapped[0],mapped[0]+len(mapped))): return []
        start,end=mapped[0],mapped[-1]+1
        selected = [w for w in words if w[0] < end and w[1] > start]
        if not selected or selected[0][0]!=start or selected[-1][1]!=end or any(not w[2] for w in selected): return []
        readings.append(''.join(w[2] for w in selected).replace('’', '').replace("'", ''))
    return readings


def covered_by_phrases(original, surface, phrases):
    positions = list(re.finditer(re.escape(surface), original))
    return bool(positions) and all(any(phrase != surface and m.start() <= match.start() and m.end() >= match.end()
        for phrase in phrases for m in re.finditer(re.escape(phrase), original)) for match in positions)


def candidates(original, reference, comparison, analysis, phase='before', known_words=None):
    expected, errors = {}, {}
    for word in reference['words']:
        expected.setdefault(word['surface'], set()).add(word['reading'])
    for error in comparison['errors']:
        errors.setdefault(error['surface'], []).append(error)
    conflicts = {}
    for hint in known_words or []:
        if hint['surface'] not in expected and covered_by_phrases(original, hint['surface'], expected):
            continue
        if expected.get(hint['surface']) != {hint['reading']}:
            conflicts[hint['surface']] = hint['reading']
            expected.setdefault(hint['surface'], {hint['reading']})
    result = []
    for surface, readings in expected.items():
        actual = tts_occurrences(original, analysis, surface)
        proposed = sorted(readings)[0]
        tts_diff = any(canonical(reading) not in {canonical(v) for v in readings} for reading in actual)
        if surface not in errors and not tts_diff and surface not in conflicts:
            continue
        identifier = hashlib.sha256((phase + '\0' + original + '\0' + surface).encode()).hexdigest()[:20]
        result.append({'id': identifier, 'surface': surface, 'proposed_reading': proposed,
                       'reference_readings': sorted(readings), 'tts_readings': list(dict.fromkeys(actual)),
                       'asr_errors': errors.get(surface, []), 'tts_difference': tts_diff,
                       'registered_reading_conflict': conflicts.get(surface),
                       'phase': phase, 'context': original})
    return result


def load_answers(path, original, allowed_ids):
    if path is None:
        return {}
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    expected_hash = hashlib.sha256(original.encode()).hexdigest()
    if value.get('format') != 'voisona.reading-decisions.v1' or value.get('original_sha256') != expected_hash:
        raise ValueError('回答ファイルの形式または原文のハッシュが一致しません。')
    result = {}
    for answer in value.get('answers', []):
        if answer.get('id') not in allowed_ids or answer['id'] in result:
            raise ValueError('回答の対象が不明または重複しています。')
        if not answer.get('action'):
            continue
        if answer['action'] not in ('accept', 'reject') or not isinstance(answer.get('reason'), str) or not answer['reason'].strip():
            raise ValueError('回答のactionと採用・保留理由を記入してください。')
        if answer['action'] == 'accept' and not re.fullmatch(r'[ァ-ヺー]{1,160}', answer.get('reading', '')):
            raise ValueError('採用する読みは全角カタカナで記入してください。')
        registration = answer.get('registration')
        if registration and any(registration.values()):
            surface, reading = registration.get('surface'), registration.get('reading')
            if answer['action'] != 'accept' or not isinstance(surface, str) or not 1 <= len(surface) <= 80 or surface not in original or re.search(r'[\s\[\]"=,]', surface):
                raise ValueError('登録するまとまりは原文内の語句で指定してください。')
            if not isinstance(reading, str) or not re.fullmatch(r'[ァ-ヺー]{1,160}', reading):
                raise ValueError('まとまり全体の読みを全角カタカナで指定してください。')
        elif registration is not None:
            answer.pop('registration')
        result[answer['id']] = answer
    return result


def decide(items, review, answers):
    decisions, questions = [], []
    for item in items:
        local=item.get('locally_resolved_reading')
        opinions = []
        for provider in review['providers']:
            opinion = None if local else next((v for v in provider.get('opinions', []) if v['surface'] == item['surface']), None)
            opinions.append({'provider': provider['provider'], 'status': provider['status'], 'opinion': opinion,
                'model':provider.get('model',review.get('configuration',{}).get(provider['provider'],{}).get('model','未記録')),
                'http_status':provider.get('http_status')})
        answer = answers.get(item['id'])
        votes=[];abstentions=[]
        if local:abstentions.append({'provider':'primary','reason':'登録済み読みはローカル適用であり独立票ではありません'})
        elif len(item['reference_readings'])==1:votes.append({'provider':'primary','reading':item['reference_readings'][0]})
        else:abstentions.append({'provider':'primary','reason':'一次案の読みが一意ではありません'})
        for provider in opinions:
            opinion=provider['opinion']
            if provider['status']=='ok' and opinion and not opinion['uncertain']:
                votes.append({'provider':provider['provider'],'reading':opinion['reading']})
            else:abstentions.append({'provider':provider['provider'],'reason':'判断不能' if opinion and opinion.get('uncertain') else provider['status']})
        groups={}
        for vote in votes:groups.setdefault(canonical(vote['reading']),[]).append(vote)
        majority=next((group for group in groups.values() if len(group)>=2),[])
        source, reading, status = '', None, 'pending'
        if answer:
            source = 'user'
            status = 'accepted' if answer['action'] == 'accept' else 'rejected'
            reading = answer.get('reading') if status == 'accepted' else None
        elif local:
            agrees=item['tts_readings'] and all(canonical(v)==canonical(local) for v in item['tts_readings']) and {canonical(v) for v in item['reference_readings']}=={canonical(local)}
            source,reading,status=('registered_dictionary',local,'accepted') if agrees else ('registered_dictionary_mismatch',None,'pending')
        elif item['tts_readings'] and not item['tts_difference'] and len(item['reference_readings']) == 1 and not item.get('registered_reading_conflict'):
            # 読みが既に一致する場合、ASR差だけを理由に辞書を書き換えない。
            source, reading, status = 'tts_matches_reference', item['proposed_reading'], 'accepted'
        elif majority:
            source, reading, status = 'model_majority', majority[0]['reading'], 'accepted'
        needs_registration = status == 'accepted' and (not item['tts_readings'] or any(canonical(v) != canonical(reading) for v in item['tts_readings']))
        registration = (answer or {}).get('registration') if status == 'accepted' else None
        if registration and (item['surface'] not in registration['surface'] or canonical(reading) not in canonical(registration['reading'])):
            raise ValueError('登録するまとまりは対象語と採用読みを含む必要があります。')
        if status == 'accepted' and not registration:
            registration = {'surface': item['surface'], 'reading': reading}
        row = {**item, 'status': status, 'accepted_reading': reading, 'source': source,
               'reason': answer['reason'] if answer else ('登録済み読みをローカル適用。独立票へは加算しない。' if source=='registered_dictionary' else '登録済みの期待読みと実測が一致しないか確認できません。追加照会・重複登録をせず確認待ち。' if source=='registered_dictionary_mismatch' else '文字起こしとTTS解析を分けて記録' if source == 'tts_matches_reference' else f'有効票{len(votes)}票中{len(majority)}票が同じ読みのため、モデル多数決で仮採用' if source else f'有効票{len(votes)}票で同じ読みが2票以上一致しないため確認待ち'),
               'opinions': opinions, 'votes':votes,'abstentions':abstentions,'needs_registration': needs_registration, 'registration': registration}
        decisions.append(row)
        if status == 'pending':
            choices = list(dict.fromkeys(item['reference_readings'] + item['tts_readings'] + [p['opinion']['reading'] for p in opinions if p['opinion']]))
            questions.append({'id': item['id'], 'surface': item['surface'], 'question': f'「{item["surface"]}」は、この文ではどの読みが妥当ですか。',
                              'context': item['context'], 'choices': choices, 'opinions': opinions, 'votes':votes,'abstentions':abstentions,'reason': row['reason']})
    return {'decisions': decisions, 'questions': questions, 'status': 'pending_confirmation' if questions else 'resolved'}


def answer_template(original, questions):
    return {'format': 'voisona.reading-decisions.v1', 'original_sha256': hashlib.sha256(original.encode()).hexdigest(),
            'answers': [{'id': q['id'], 'surface': q['surface'], 'action': '', 'reading': '', 'reason': '',
                         'registration': {'surface': '', 'reading': ''}} for q in questions]}


def adopted_readings(decisions):
    return [row.get('registration') or {'surface': row['surface'], 'reading': row['accepted_reading']}
            for row in decisions if row['status'] == 'accepted']
