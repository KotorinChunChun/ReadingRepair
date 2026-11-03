"""TTS能力・辞書・音声合成の共通境界。解析非対応を明示する。"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request
import urllib.error
import urllib.parse
import wave
from reviewers import read_env

ENGINES = ('voisona', 'http-wav')

def field(settings, name, default=''):
    return settings.get(name, default) if isinstance(settings, dict) else getattr(settings, name, default)

def dictionary_path(settings):
    key = 'api_dictionary_file' if field(settings, 'tts_engine', 'voisona') == 'http-wav' else 'dictionary_file'
    return Path(field(settings, key))

def registration_command(here):
    # 開発DLLと自己完結配布EXE。凍結Pythonでも__file__の抽出先へ依存しない。
    import sys
    root = Path(sys.executable).resolve().parent.parent if getattr(sys, 'frozen', False) else Path(here).parent
    exe = root / 'registration/ReadingRepair.Registration.exe'
    if exe.is_file(): return [str(exe)]
    dll = root / 'Registration/bin/Debug/net10.0-windows/ReadingRepair.Registration.dll'
    if not dll.is_file():
        dll = Path(here) / 'Registration/bin/Debug/net10.0-windows/Registration.dll'
    if not dll.is_file(): raise ValueError('辞書登録ヘルパーを先にビルドしてください。')
    return ['dotnet', str(dll)]

class VoiSonaBackend:
    id = 'voisona'
    capabilities = {'native_dictionary': True, 'analysis': True, 'dictionary_mode': 'native'}
    def __init__(self, settings, native_factory):
        self.settings = settings
        self.native_factory = native_factory
        self._api = None
    @property
    def api(self):
        if self._api is None:
            self._api = self.native_factory(Path(field(self.settings,'tts_env') or Path(field(self.settings,'project_root','.'))/'.env'),field(self.settings,'voice'),field(self.settings,'voice_version'))
        return self._api
    def preflight(self): return {'engine':self.id, 'capabilities':self.capabilities, 'voices':self.api.call('GET','voices')['items']}
    def analyze(self,text): return self.api.analyze(text)
    def synthesize(self,text,path): return self.api.synthesize(text,path)
    def register(self,run_dir,text,entries):
        import lab
        return lab.register_entries(run_dir,dictionary_path(self.settings),text,entries)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

class HttpWavBackend:
    id = 'http-wav'
    capabilities = {'native_dictionary':False, 'analysis':False, 'dictionary_mode':'text-substitution'}
    def __init__(self,settings):
        self.settings = settings
        values = read_env(Path(field(settings,'tts_env')))
        self.endpoint = os.environ.get('READINGREPAIR_TTS_URL',values.get('TTS_URL',''))
        address = urllib.parse.urlsplit(self.endpoint)
        if not address.hostname or address.username or address.password or address.query or address.fragment or (address.scheme!='https' and not (address.scheme=='http' and address.hostname in ('127.0.0.1','localhost','::1'))):
            raise ValueError('HTTP TTSのURLはHTTPSまたはループバックHTTPで、認証値・クエリを含めないでください。')
        try: self.body = json.loads(values.get('TTS_BODY_JSON','{"input":"{text}","voice":"{voice}","response_format":"wav"}'))
        except json.JSONDecodeError: raise ValueError('TTS_BODY_JSONはJSONオブジェクトで指定してください。') from None
        if not isinstance(self.body,dict) or '{text}' not in json.dumps(self.body): raise ValueError('TTS_BODY_JSONには{text}を含むJSONオブジェクトを指定してください。')
        self.key = os.environ.get('READINGREPAIR_TTS_API_KEY',values.get('TTS_API_KEY',''))
        self.path = dictionary_path(settings)
        if self.path.suffix.lower() != '.json': raise ValueError('HTTP TTSには専用JSON辞書を指定してください。VoiSonaの辞書は変更しません。')
        if not self.path.exists():
            import lab
            lab.save(self.path,{'format':'readingrepair.dictionary.v1','entries':[]})
    def preflight(self):
        return {'engine':self.id,'capabilities':self.capabilities,'configured':True,'connection':'音声生成時に接続を検証','voices':[field(self.settings,'voice')]}
    def analyze(self,text):
        return {'supported':False,'engine':self.id,'reason':'このエンジンは発音解析APIを提供しません。Whisperによる文字起こしを評価します。','analyzed_text':''}
    def transformed_text(self,text):
        import lab
        snapshot = lab.dictionary_snapshot(self.path,text)
        # 長い語句を優先し、置換したカタカナを再び置換しない。
        rows = snapshot['table']['rows']; mapping={}
        from adjudication import width_key
        for _,surface,reading,_ in rows: mapping.setdefault(width_key(surface),reading)
        if not mapping: return text
        pattern = re.compile('|'.join(re.escape(s) for s in sorted(mapping,key=len,reverse=True)))
        pieces=[];cursor=0
        for match in pattern.finditer(width_key(text)):
            pieces.extend((text[cursor:match.start()],mapping[match[0]]));cursor=match.end()
        return ''.join(pieces)+text[cursor:]
    def synthesize(self,text,path):
        import lab
        lab.check_cancel()
        converted=self.transformed_text(text)
        substitutions={'{text}':converted,'{voice}':field(self.settings,'voice'),'{voice_version}':field(self.settings,'voice_version')}
        def render(value):
            if isinstance(value,str):
                # 元文に別プレースホルダーがあっても再解釈しない。
                return re.sub(r'\{(?:text|voice|voice_version)\}',lambda m:substitutions[m[0]],value)
            if isinstance(value,list):return [render(v) for v in value]
            if isinstance(value,dict):return {k:render(v) for k,v in value.items()}
            return value
        headers={'Content-Type':'application/json','Accept':'audio/wav'}
        if self.key:headers['Authorization']='Bearer '+self.key
        request=urllib.request.Request(self.endpoint,json.dumps(render(self.body),ensure_ascii=False).encode(),headers,method='POST')
        try:
            with urllib.request.build_opener(NoRedirect()).open(request,timeout=120) as response:
                data=response.read(64*1024*1024+1)
        except urllib.error.HTTPError as error:
            code=error.code;error.close()
            raise RuntimeError(f'HTTP TTSがHTTP {code}を返しました。応答本文は保存しません。') from None
        except Exception as error:raise RuntimeError('HTTP TTSへ接続できません。接続先・認証設定を確認してください。'+type(error).__name__) from None
        if len(data)>64*1024*1024:raise ValueError('TTS音声が64MiBを超えました。')
        import io
        try:
            with wave.open(io.BytesIO(data),'rb') as audio:
                if audio.getcomptype()!='NONE' or audio.getnframes()==0 or len(audio.readframes(audio.getnframes())) != audio.getnframes()*audio.getnchannels()*audio.getsampwidth():raise ValueError()
        except (wave.Error,EOFError,ValueError):raise ValueError('TTS応答が有効な非圧縮WAVではありません。response_formatを確認してください。') from None
        path.write_bytes(data)
        lab.save(path.with_suffix('.tts-input.json'),{'engine':self.id,'dictionary_mode':'text-substitution','text':converted,'original_sha256':hashlib.sha256(text.encode()).hexdigest(),'dictionary_sha256':lab.dictionary_snapshot(self.path,'')['dictionary_sha256']})
    def register(self,run_dir,text,entries):
        import lab
        checked=lab.dictionary_precheck(self.path,entries)
        lab.versioned_save(run_dir,'dictionary-precheck.json',checked)
        if checked['has_conflicts']:raise ValueError('既存のAPI用辞書と読みが競合しています。')
        value=lab.load(self.path)
        lab.versioned_save(run_dir,'api-dictionary-before.json',value)
        for row in checked['entries']:
            if row['state']=='new':value['entries'].append({'surface':row['surface'],'reading':row['reading']})
        lab.save(self.path,value)
        verified=lab.dictionary_precheck(self.path,entries)
        if verified['has_conflicts'] or any(row['state']=='new' for row in verified['entries']):raise RuntimeError('API用辞書の読戻しを確認できませんでした。')
        return {'method':'ReadingRepair JSON辞書・音声化前の語句置換','engine':self.id,'entries':[{**row,'elapsedMs':None,'state':'registered' if row['state']=='new' else row['state']} for row in checked['entries']]}

def create(settings,native_factory=None):
    engine=field(settings,'tts_engine','voisona')
    if engine=='http-wav': return HttpWavBackend(settings)
    if engine=='voisona':
        if native_factory is None:
            import lab
            native_factory=lab.TalkApi
        return VoiSonaBackend(settings,native_factory)
    raise ValueError('未対応のTTSエンジンです。voisona / http-wavを指定してください。')
