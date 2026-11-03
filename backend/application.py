"""読み自己修復アプリの共通CLI。画面とCLIで設定・状態・判断を共有する。"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
from types import SimpleNamespace
import uuid

import lab
import progress_log
import llm_records
import tts_backends
from adjudication import load_answers,tts_occurrences
from reviewers import Config

WORKSPACE = Path(sys.executable).resolve().parent.parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
JOB_PATTERN = r'reading-repair-\d{8}-\d{6}-[0-9a-f]{8}'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def normalize_text(text):
    if not isinstance(text, str): raise ValueError('原文は文字列で入力してください。')
    return text.replace('\r\n', '\n').replace('\r', '\n').strip()


@contextmanager
def exclusive(path):
    """プロセス終了でも解放されるOSロック。ロックファイルの削除は不要。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('a+b')
    stream.seek(0,2)
    if stream.tell()==0: stream.write(b'0');stream.flush()
    stream.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise ValueError('別の自己修復を実行中です。完了または停止後に再開してください。') from None
    try:
        yield
    finally:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


class Application:
    def __init__(self, workspace=WORKSPACE, settings_file=None):
        self.workspace = Path(workspace).resolve()
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ReadingRepair'
        self.settings_file = Path(settings_file) if settings_file else base / 'settings.json'

    def defaults(self):
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ReadingRepair'
        return {'python': sys.executable, 'project_root': str(self.workspace),
                'runs_root':str(base/'runs'), 'whisper_model':'C:/AI/Models/Speech/Whisper/VoisonaTalkAI/small',
                'whisper_site_packages':'', 'reviewer_env':'C:/AI/env/ReadingRepair/reviewers.env',
                'dictionary_file':str(Path(os.environ.get('APPDATA',''))/'Techno-Speech/VoiSona Talk/Talker/user_dict_ja_jp.dic'),
                'api_dictionary_file':str(base/'dictionaries/http-wav/default.json'),
                'tts_engine':'voisona', 'tts_profile':'default', 'tts_env':'C:/AI/env/ReadingRepair/tts.env',
                'llm_model':'gpt-5.6-luna','voice':'ui_ja_JP','voice_version':'2.0.0',
                'gemini_transport':'api','review_timeout':45}

    def settings(self):
        values = self.defaults()
        if self.settings_file.is_file():
            saved = lab.load(self.settings_file)
            if not isinstance(saved, dict) or set(saved) - set(values):
                raise ValueError('設定ファイルに対応していない項目があります。')
            values.update(saved)
        return self.validate_settings(values)

    def validate_settings(self, values):
        defaults = self.defaults()
        if not isinstance(values, dict) or set(values) != set(defaults):
            raise ValueError('設定項目が一致しません。キーは外部.envへ保存してください。')
        for key, value in values.items():
            if key == 'review_timeout':
                if type(value) is not int or not 1 <= value <= 600:
                    raise ValueError('照会時間は1～600秒で指定してください。')
            elif not isinstance(value, str) or '\x00' in value or len(value) > 2048:
                raise ValueError('設定値の形式が不正です。')
        for key in ('python', 'project_root', 'runs_root', 'whisper_model', 'reviewer_env', 'dictionary_file', 'llm_model', 'voice', 'voice_version'):
            if not values[key].strip():
                raise ValueError(f'{key}を指定してください。')
        if values['tts_engine'] not in tts_backends.ENGINES: raise ValueError('TTSエンジンはvoisona / http-wavです。')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',values['tts_profile']):raise ValueError('TTSプロファイルは英数字・ハイフン・アンダースコアで指定してください。')
        if values['gemini_transport'] not in ('api', 'cli'):
            raise ValueError('Gemini接続はapiまたはcliです。')
        return values

    def save_settings(self, payload):
        values = self.settings()
        if 'tts_profile' in payload and payload['tts_profile'] != values['tts_profile'] and 'api_dictionary_file' not in payload:
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',str(payload['tts_profile'])):raise ValueError('TTSプロファイルの形式が不正です。')
            base=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'ReadingRepair/dictionaries/http-wav'
            values['api_dictionary_file']=str(base/(payload['tts_profile']+'.json'))
        values.update(payload)
        self.validate_settings(values)
        lab.save(self.settings_file, values)
        return values

    def root(self):
        return Path(self.settings()['runs_root']).resolve()

    def lock_file(self, settings=None):
        dictionary = os.path.normcase(str(tts_backends.dictionary_path(settings or self.settings()).resolve()))
        name = hashlib.sha256(dictionary.encode()).hexdigest()[:24]
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ReadingRepair/locks'
        return base / (name + '.lock')

    def directory(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(JOB_PATTERN, identifier):
            raise ValueError('実行IDが不正です。')
        root = self.root(); path = root / identifier
        if path.is_symlink() or path.resolve().parent != root:
            raise ValueError('実行フォルダーの参照先が不正です。')
        if not (path / 'app-job.json').is_file():
            raise ValueError('指定された実行がありません。')
        return path

    def create(self, payload):
        text = normalize_text(payload.get('text', ''))
        if not text or len(text) > 4000:
            raise ValueError('原文は1～4000文字で入力してください。')
        mode = payload.get('mode', 'repair')
        if mode not in ('repair', 'verify'):
            raise ValueError('実行モードが不正です。')
        known = payload.get('known_readings', [])
        if not isinstance(known, list) or len(known) > 100:
            raise ValueError('指定する読みは100件までです。')
        seen = set(); cleaned = []
        for entry in known:
            surface = entry.get('surface', '')
            if not surface or surface not in text or surface in seen:
                raise ValueError('指定読みの表記が原文にないか重複しています。')
            reading = lab.kana(entry.get('reading'))
            cleaned.append({'surface': surface, 'reading': reading}); seen.add(surface)
        settings = self.settings()
        identifier = datetime.now().strftime('reading-repair-%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
        path = self.root() / identifier; path.mkdir(parents=True, exist_ok=False)
        (path / 'input.txt').write_text(text, encoding='utf-8', newline='\n')
        job = {'format': 'voisona.reading-repair-job.v1', 'id': identifier, 'created_at': now(), 'updated_at': now(),
               'status': 'ready', 'mode': mode, 'settings': settings, 'known_readings': cleaned,
               'text_sha256': hashlib.sha256(text.encode()).hexdigest(), 'text_contract': 'lf.v1', 'source': '利用者が入力した原文と指定読み'}
        lab.save(path / 'app-job.json', job)
        return self.status(identifier)

    def input_text(self, path, job, repair=False):
        raw = (path / 'input.txt').read_bytes()
        stored = raw.decode('utf-8')
        digest = lambda value: hashlib.sha256(value.encode('utf-8')).hexdigest()
        expected = job['text_sha256']
        if job.get('text_contract') == 'lf.v1':
            text = normalize_text(stored)
            if digest(text) == expected: return text
        else:
            # 旧Windows保存の改行変換だけを戻す。元ハッシュの一致なしに復元しない。
            originals = (stored.strip(), stored.replace('\r\n', '\n').strip())
            original = next((value for value in originals if digest(value) == expected), None)
            if original is not None:
                text = normalize_text(original)
                if repair and not (path / 'manifest.json').exists():
                    if raw != text.encode('utf-8'):
                        history = path / 'decision-history'; history.mkdir(exist_ok=True)
                        backup = history / ('input-before-normalization-' + uuid.uuid4().hex + '.bin')
                        backup.write_bytes(raw)
                        (path / 'input.txt').write_text(text, encoding='utf-8', newline='\n')
                    job.update(text_contract='lf.v1', text_sha256=digest(text))
                    job['input_normalization'] = {'previous_text_sha256': expected, 'normalized_text_sha256': digest(text)}
                    lab.versioned_save(path, 'app-job.json', job)
                if digest(text) == job['text_sha256'] or not repair: return text
        raise ValueError('保存された原文が変更されています。新しい実行を作成してください。')

    def status(self, identifier, include_progress=True):
        path = self.directory(identifier); job = lab.load(path / 'app-job.json')
        manifest = lab.load(path / 'manifest.json') if (path / 'manifest.json').is_file() else {}
        questions = []
        for name in ('confirmation-questions.json', 'post-confirmation-questions.json'):
            if (path / name).is_file(): questions += lab.load(path / name)['questions']
        for name in ('adjudication.json','post-adjudication.json'):
            if not (path/name).is_file(): continue
            decisions={row['id']:row for row in lab.load(path/name)['decisions']}
            for question in questions:
                if question['id'] in decisions:
                    row=decisions[question['id']]
                    question['primary_readings']=row['reference_readings']
                    question['tts_readings']=row['tts_readings']
                    question['primary_model']=job['settings']['llm_model']
                    phase='after-3' if row.get('phase')=='after' else 'before-2'
                    analysis=path/(phase+'-talk-analysis.json')
                    question['tts_status']='recorded' if row['tts_readings'] else 'not_recorded'
                    if not row['tts_readings'] and analysis.is_file():
                        question['tts_readings']=tts_occurrences(self.input_text(path,job),lab.load(analysis),row['surface'])
                        question['tts_status']='unsupported' if lab.load(analysis).get('supported') is False else 'recalculated' if question['tts_readings'] else 'unmapped'
                    transcript=path/(phase+'-whisper.json')
                    question['whisper_recorded']=transcript.is_file()
                    question['whisper_text']=lab.load(transcript)['text'] if transcript.is_file() else ''
                    question['votes']=row.get('votes',[]);question['abstentions']=row.get('abstentions',[])
                    review_path=path/(('post-' if phase=='after-3' else '')+'secondary-review.json')
                    if review_path.is_file():
                        review=lab.load(review_path)
                        providers={p['provider']:p for p in review.get('providers',[])}
                        for opinion in question.get('opinions',[]):
                            provider=providers.get(opinion['provider'],{})
                            opinion['model']=provider.get('model',review.get('configuration',{}).get(opinion['provider'],{}).get('model','未記録'))
                            opinion['http_status']=provider.get('http_status')
        result = {**job, 'current_stage': manifest.get('current_stage', ''),
                  'completed_stages': manifest.get('completed_stages', []), 'questions': questions,
                  'report': str(path / 'report/index.html') if (path / 'report/index.html').is_file() else '',
                  'audio_before': str(path / 'before-2.wav') if (path / 'before-2.wav').is_file() else '',
                  'audio_after': str(path / 'after-3.wav') if (path / 'after-3.wav').is_file() else '',
                  'original': self.input_text(path, job)}
        if result['status'] == 'running':
            try:
                with exclusive(self.lock_file(job['settings'])): result['status'] = 'interrupted'
            except ValueError:
                if (path / 'cancel.request').exists(): result['status'] = 'stop_requested'
        if (path / 'summary.json').is_file(): result['summary'] = lab.load(path / 'summary.json')
        if (path / 'user-answers.json').is_file(): result['user_answers'] = lab.load(path / 'user-answers.json')['answers']
        if (path / 'dictionary-precheck.json').is_file(): result['dictionary_precheck'] = lab.load(path / 'dictionary-precheck.json')
        if include_progress: result['progress'] = self.log(identifier)
        for key,names in (('before_score',('comparison-final-before.json','comparison-adopted-before.json','comparison-1-2.json')),
                          ('after_score',('comparison-final-after.json','comparison-1-3.json'))):
            for name in names:
                if (path/name).is_file():
                    result[key]=lab.load(path/name)['llm_score'];break
        return result

    def history(self):
        root = self.root()
        if not root.exists(): return []
        result = []
        for directory in sorted(root.glob('reading-repair-*'), reverse=True):
            if not re.fullmatch(JOB_PATTERN, directory.name) or directory.is_symlink(): continue
            try:
                job = self.status(directory.name, include_progress=False)
                result.append({k: job.get(k) for k in ('id', 'created_at', 'updated_at', 'status', 'mode', 'original', 'report', 'summary', 'before_score','after_score')})
            except (ValueError, OSError, KeyError, json.JSONDecodeError): continue
        return result

    def answer(self, identifier, payload):
        path = self.directory(identifier)
        with exclusive(self.lock_file(lab.load(path / 'app-job.json')['settings'])):
            job = self.status(identifier)
            if job['status'] not in ('pending_confirmation', 'candidates_ready', 'dictionary_conflict'):
                raise ValueError('確認待ちまたは候補作成済みの実行を選択してください。')
            allowed = {q['id'] for q in job['questions']}
            for name in ('adjudication.json', 'post-adjudication.json'):
                if (path / name).is_file(): allowed.update(r['id'] for r in lab.load(path / name)['decisions'])
            value = {'format': 'voisona.reading-decisions.v1', 'original_sha256': job['text_sha256'], 'answers': payload.get('answers', [])}
            temporary = path / 'answers.validation.json'
            lab.save(temporary, value)
            validated = load_answers(temporary, job['original'], allowed)
            if not validated: raise ValueError('採用または却下する回答を入力してください。')
            saved = lab.load(path / 'user-answers.json') if (path / 'user-answers.json').is_file() else {**value, 'answers': []}
            merged = {r['id']: r for r in saved['answers']}
            merged.update(validated); saved['answers'] = list(merged.values())
            lab.versioned_save(path, 'user-answers.json', saved)
            for row in validated.values():
                entry=row.get('registration')
                message=f'利用者が「{row.get("surface") or row["id"]}」を{"採用" if row["action"]=="accept" else "登録しない"}と回答。読み={row.get("reading") or "指定なし"}。理由：{row["reason"]}'
                if entry:message+=f'。登録する語句：{entry["surface"]}＝{entry["reading"]}'
                self.emit_log(path,job,'answer',message)
        return self.status(identifier)

    def emit_log(self,path,job,stage,message):
        try: redact=Config.load(Path(job['settings']['reviewer_env'])).redact
        except (ValueError,OSError):redact=None
        return progress_log.emit(path,stage,message=message,redact=redact)

    def log(self,identifier):
        return progress_log.read(self.directory(identifier))

    def llm_log(self,identifier):
        path=self.directory(identifier);job=lab.load(path/'app-job.json')
        value=llm_records.read(path,job['settings']['llm_model'])
        try:return Config.load(Path(job['settings']['reviewer_env'])).redact(value)
        except (ValueError,OSError):return value

    def cancel(self, identifier):
        path = self.directory(identifier)
        job = self.status(identifier)
        if job['status'] not in ('running', 'stop_requested'):
            raise ValueError('実行中の処理がありません。')
        (path / 'cancel.request').write_text('stop', encoding='ascii')
        return {'id': identifier, 'status': 'stop_requested'}

    def execute(self, identifier, retry_reviewers=False, apply=False):
        path = self.directory(identifier)
        with exclusive(self.lock_file(lab.load(path / 'app-job.json')['settings'])):
            job = lab.load(path / 'app-job.json'); settings = job['settings']
            if job['status'] == 'completed': return self.status(identifier)
            if retry_reviewers:
                latest = self.settings()
                revised = {**settings, **{k:latest[k] for k in ('reviewer_env','gemini_transport','review_timeout')}}
                if revised != settings:
                    job['settings'] = settings = revised
                    lab.versioned_save(path, 'app-job.json', job)
            if apply:
                job['mode'] = 'repair'
            self.input_text(path, job, repair=True)
            (path / 'cancel.request').unlink(missing_ok=True)
            job.pop('error_type',None);job.pop('message',None)
            job.update(status='running', updated_at=now()); lab.versioned_save(path, 'app-job.json', job)
            environment = {'VOISONA_REPAIR_CANCEL_FILE': str(path / 'cancel.request'),
                           'GEMINI_REVIEW_TRANSPORT': settings['gemini_transport'],
                           'REVIEW_TIMEOUT_SECONDS': str(settings['review_timeout'])}
            previous = {k: os.environ.get(k) for k in environment}; os.environ.update(environment)
            args = SimpleNamespace(project_root=Path(settings['project_root']), text_file=path / 'input.txt', run_dir=path,
                llm_model=settings['llm_model'], whisper_model=Path(settings['whisper_model']),
                whisper_site_packages=Path(settings['whisper_site_packages']) if settings['whisper_site_packages'] else None,
                voice=settings['voice'], voice_version=settings['voice_version'], dictionary_file=Path(settings['dictionary_file']),
                reviewer_env=Path(settings['reviewer_env']), answers_file=path / 'user-answers.json' if (path / 'user-answers.json').is_file() else None,
                resume=(path / 'manifest.json').exists(), apply=job['mode'] == 'repair', prepare_only=job['mode'] == 'verify',
                retry_reviewers=retry_reviewers, user_readings=job['known_readings'], app_managed=True,
                tts_engine=settings.get('tts_engine','voisona'), tts_profile=settings.get('tts_profile','default'),
                tts_env=settings.get('tts_env',''), api_dictionary_file=settings.get('api_dictionary_file',''))
            try:
                lab.run(args)
                job['status'] = lab.load(path / 'manifest.json')['status']
                job.pop('error_type', None)
            except InterruptedError:
                job['status'] = 'cancelled'
            except Exception as error:
                job.update(status='failed', error_type=type(error).__name__)
                if isinstance(error, (ValueError, RuntimeError)): job['message']=str(error)[:400]
            finally:
                for key, value in previous.items():
                    if value is None: os.environ.pop(key, None)
                    else: os.environ[key] = value
                job['updated_at'] = now(); lab.save(path / 'app-job.json', job)
                if (path / 'manifest.json').is_file():
                    try: lab.export_current_history(path)
                    except Exception: pass
        return self.status(identifier)

    def audio(self, identifier, phase, play=False):
        path = self.directory(identifier) / ('before-2.wav' if phase == 'before' else 'after-3.wav')
        if not path.is_file(): raise ValueError('この段階の音声はまだ生成されていません。')
        result = {'path': str(path), **lab.wav_info(path)}
        if play:
            if os.name != 'nt': raise ValueError('音声再生はWindowsで使用してください。')
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME)
        return result

    def export(self, identifier):
        path = self.directory(identifier)
        if not (path / 'manifest.json').is_file(): raise ValueError('まだ検証記録がありません。')
        lab.export_current_history(path)
        return {'report':str(path / 'report/index.html')}

    def dictionary(self):
        tts_backends.create(self.settings())
        return {**lab.dictionary_view(tts_backends.dictionary_path(self.settings())), 'engine':self.settings()['tts_engine']}

    def check_dictionary(self, payload):
        entries = payload.get('entries')
        if not entries: raise ValueError('追加する表記と読みを入力してください。')
        tts_backends.create(self.settings())
        return lab.dictionary_precheck(tts_backends.dictionary_path(self.settings()), entries)

    def add_dictionary(self, payload):
        expected = payload.get('dictionary_sha256', '')
        if not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected):
            raise ValueError('先に追加候補を確認してください。')
        settings = self.settings()
        with exclusive(self.lock_file(settings)):
            if not payload.get('entries'): raise ValueError('追加する表記と読みを入力してください。')
            backend = tts_backends.create(settings)
            checked = lab.dictionary_precheck(tts_backends.dictionary_path(settings), payload['entries'])
            if checked['dictionary_sha256'] != expected:
                return {'status':'dictionary_changed','precheck':checked,'message':'確認後に辞書が変更されました。最新の辞書で再確認してください。'}
            if checked['has_conflicts']: return {'status':'dictionary_conflict','precheck':checked}
            if not checked['can_register']: return {'status':'already_registered','precheck':checked}
            identifier = datetime.now().strftime('dictionary-additions-%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
            folder = Path(settings['runs_root']).resolve() / identifier
            entries = [{k:row[k] for k in ('surface','reading')} for row in checked['entries']]
            lab.save(folder/'request.json', {'entries':entries,'dictionary_sha256':expected,'source':'利用者が確認して追加した辞書候補'})
            registration = backend.register(folder,'\n'.join(row['surface'] for row in entries),entries)
            return {'status':'registered','precheck':checked,'registration':registration,'dictionary':lab.dictionary_view(tts_backends.dictionary_path(settings)),'record':str(folder)}

    def doctor(self):
        values = self.settings(); checks = []
        def check(name, ok, detail, required=True):
            checks.append({'name': name, 'status': 'ok' if ok else ('error' if required else 'warning'), 'detail': detail})
        check('Python', Path(values['python']).is_file() or bool(shutil.which(values['python'])), values['python'])
        check('一次LLMモジュール', (Path(sys.executable).parent/'CodexClient.psm1').is_file() if getattr(sys,'frozen',False) else (lab.HERE/'CodexClient.psm1').is_file(), 'ReadingRepair同梱モジュール')
        check('PowerShell 7',bool(shutil.which('pwsh')),'pwshが必要です。')
        check('Codex CLI',bool(shutil.which('codex')) or (Path.home()/'.codex/.sandbox-bin/codex.exe').is_file(),'ログイン済みCodex CLIを使用します。')
        packages = values['whisper_site_packages']
        if packages:
            import site
            site.addsitedir(packages)
        check('Whisperライブラリ', importlib.util.find_spec('faster_whisper') is not None, packages or '現在のPython環境')
        check('Whisperモデル', (Path(values['whisper_model']) / 'model.bin').is_file(), values['whisper_model'])
        if values['tts_engine']=='voisona':
            try: check('辞書登録ヘルパー',True,' '.join(tts_backends.registration_command(lab.HERE)))
            except ValueError as error: check('辞書登録ヘルパー',False,str(error))
        try:
            backend=tts_backends.create(values)
            check('TTSエンジン',True,json.dumps(backend.preflight(),ensure_ascii=False))
            dictionary=lab.dictionary_snapshot(tts_backends.dictionary_path(values),'')
            check('ユーザー辞書',True,f'{len(dictionary["table"]["rows"])}件')
        except Exception as error:check('TTSと辞書',False,str(error) if isinstance(error,(ValueError,RuntimeError)) else type(error).__name__)
        try:
            cfg = Config.load(Path(values['reviewer_env']))
            for name, provider in cfg.public().items():
                if isinstance(provider, dict): check(name, provider['enabled'] and provider['key_configured'], 'キー設定済み' if provider['key_configured'] else '未設定時は確認待ちになります。', False)
        except Exception as error: check('外部モデル設定', False, type(error).__name__, False)
        return {'ready': not any(c['status'] == 'error' for c in checks), 'checks': checks}


def main():
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('settings', 'save-settings', 'doctor', 'create', 'execute', 'status', 'history', 'answer', 'stop', 'audio', 'export', 'dictionary', 'check-dictionary', 'add-dictionary', 'log', 'llm-log', 'engines', 'synthesize', 'transcribe', 'version'))
    parser.add_argument('--workspace', type=Path, default=WORKSPACE)
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--job')
    parser.add_argument('--stdin', action='store_true', help='JSON要求を標準入力から読む')
    parser.add_argument('--request', type=Path)
    parser.add_argument('--text-file', type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--audio-file',type=Path)
    parser.add_argument('--mode', choices=('repair', 'verify'), default='repair')
    parser.add_argument('--retry-reviewers', action='store_true')
    parser.add_argument('--apply', action='store_true', help='検証済み候補の適用を許可して再開する')
    parser.add_argument('--phase', choices=('before','after'), default='after')
    parser.add_argument('--play', action='store_true')
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin) if args.stdin else lab.load(args.request) if args.request else {}
        app = Application(args.workspace, args.settings)
        if args.command == 'version':result={'name':'ReadingRepair','version':'0.0.1'}
        elif args.command == 'engines': result=[{'id':tts_backends.VoiSonaBackend.id,**tts_backends.VoiSonaBackend.capabilities},{'id':tts_backends.HttpWavBackend.id,**tts_backends.HttpWavBackend.capabilities}]
        elif args.command == 'synthesize':
            if not args.text_file or not args.output:raise ValueError('--text-fileと--outputを指定してください。')
            text=normalize_text(args.text_file.read_text(encoding='utf-8-sig'))
            if not 1<=len(text)<=4000:raise ValueError('原文は1～4000文字です。')
            if args.output.exists():raise ValueError('出力先が既に存在します。')
            args.output.parent.mkdir(parents=True,exist_ok=True)
            settings=app.settings()
            with exclusive(app.lock_file(settings)):
                backend=tts_backends.create(settings);backend.synthesize(text,args.output.resolve())
                result={'engine':settings['tts_engine'],'path':str(args.output.resolve()),**lab.wav_info(args.output),'analysis':backend.analyze(text)}
            if args.play:
                import winsound
                winsound.PlaySound(str(args.output.resolve()),winsound.SND_FILENAME)
        elif args.command == 'transcribe':
            if not args.audio_file:raise ValueError('--audio-fileを指定してください。')
            settings=app.settings();result=lab.Whisper(settings['whisper_model'],settings['whisper_site_packages']).transcribe(args.audio_file)
        elif args.command == 'settings': result = app.settings()
        elif args.command == 'save-settings': result = app.save_settings(payload)
        elif args.command == 'doctor': result = app.doctor()
        elif args.command == 'create':
            if args.text_file: payload.update(text=args.text_file.read_text(encoding='utf-8-sig'), mode=args.mode)
            result = app.create(payload)
        elif args.command == 'execute': result = app.execute(args.job, args.retry_reviewers, args.apply)
        elif args.command == 'status': result = app.status(args.job)
        elif args.command == 'history': result = app.history()
        elif args.command == 'answer': result = app.answer(args.job, payload)
        elif args.command == 'audio': result = app.audio(args.job, args.phase, args.play)
        elif args.command == 'export': result = app.export(args.job)
        elif args.command == 'dictionary': result = app.dictionary()
        elif args.command == 'check-dictionary': result = app.check_dictionary(payload)
        elif args.command == 'add-dictionary': result = app.add_dictionary(payload)
        elif args.command == 'log': result = app.log(args.job)
        elif args.command == 'llm-log': result = app.llm_log(args.job)
        else: result = app.cancel(args.job)
        print(json.dumps({'type': 'result', 'result': result}, ensure_ascii=False), flush=True)
        return 0 if not isinstance(result, dict) or result.get('status') != 'failed' else 1
    except ValueError as error:
        print(json.dumps({'type': 'error', 'message': str(error)}, ensure_ascii=False), flush=True)
        return 2
    except Exception as error:
        print(json.dumps({'type': 'error', 'message': '処理に失敗しました。設定と依存の診断を確認してください。', 'error_type': type(error).__name__}, ensure_ascii=False), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
