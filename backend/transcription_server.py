"""TranscriptionServer v0.1.17のファイル認識クライアント。"""
from __future__ import annotations

from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from tts_backends import NoRedirect, field

PROVIDER = 'transcription-server'
DEFAULT_URL = 'http://127.0.0.1:8769'
KEY_ENV = 'READINGREPAIR_TRANSCRIPTION_SERVER_API_KEY'
PROTOCOL = 3
MIN_VERSION = (0, 1, 17)
MAX_AUDIO = 64 * 1024 * 1024
MODEL_ID = r'[A-Za-z0-9._-]+/[A-Za-z0-9._-]+'


def validate_settings(settings):
    provider = field(settings, 'asr_provider', 'local-whisper')
    if provider not in ('local-whisper', PROVIDER):
        raise ValueError('文字起こし方式は local-whisper または transcription-server です。')
    url = field(settings, 'transcription_server_url', DEFAULT_URL)
    if url or provider == PROVIDER:
        server_origin(url)
    model = field(settings, 'transcription_server_model')
    if model and not re.fullmatch(MODEL_ID, model):
        raise ValueError('TranscriptionServerのモデルは一覧にある engine/model 形式で指定してください。')


def server_origin(url):
    try:
        parts = urllib.parse.urlsplit(url)
        if (parts.scheme in ('http', 'https') and parts.hostname and
                '@' not in parts.netloc and parts.path in ('', '/') and '?' not in url and '#' not in url
                and not any(ch.isspace() or ord(ch) < 32 or ch == '\\' for ch in url)
                and parts.port != 0):
            return parts._replace(path='').geturl()
    except ValueError:
        pass
    raise ValueError('TranscriptionServerのURLはHTTP(S)のオリジンを指定してください。認証情報やパスは入力しないでください。')


class TranscriptionServer:
    def __init__(self, settings):
        validate_settings(settings)
        self.origin = server_origin(field(settings, 'transcription_server_url', DEFAULT_URL))
        self.model = field(settings, 'transcription_server_model')
        # 接続先を設定どおりに固定し、プロキシや別オリジンへトークン・音声を転送しない。
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, endpoint, auth=None, body=None, content_type=None, timeout=10):
        headers = {'Accept': 'application/json'}
        if auth:
            headers[auth[0]] = auth[1]
        if body is not None:
            headers['Content-Type'] = content_type
        request = urllib.request.Request(self.origin + endpoint, data=body, headers=headers)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                if response.status != 200:
                    return response.status, {}
                raw = response.read(8 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            return status, {}
        except (OSError, ValueError, HTTPException):
            raise ValueError(f'TranscriptionServerの {endpoint} に接続できません。接続先・証明書・待機時間を確認してください。') from None
        try:
            result = json.loads(raw) if len(raw) <= 8 * 1024 * 1024 else None
        except ValueError:
            result = None
        if not isinstance(result, dict):
            raise ValueError(f'TranscriptionServerの {endpoint} のJSON応答が不正です。')
        return 200, result

    @staticmethod
    def require_success(status, endpoint):
        if status in (401, 403):
            raise ValueError(f'TranscriptionServerの認証または接続許可に失敗しました（{endpoint}、HTTP {status}）。')
        if status == 503:
            raise ValueError(f'TranscriptionServerが受付を停止しています（{endpoint}、HTTP 503）。')
        if status != 200:
            raise ValueError(f'TranscriptionServerの {endpoint} に失敗しました（HTTP {status}）。')

    def preflight(self):
        health_path = '/api/health'
        status, health = self.request(health_path)
        bearer = None
        if status == 401:
            if not self.origin.startswith('https://'):
                raise ValueError('TranscriptionServerのBearer認証にはHTTPSの接続先を指定してください。')
            key = os.environ.get(KEY_ENV, '')
            if not key or any(ord(ch) < 33 or ord(ch) > 126 for ch in key):
                raise ValueError(f'TranscriptionServerの接続キーを環境変数 {KEY_ENV} に設定してください。')
            bearer = ('Authorization', 'Bearer ' + key)
            status, health = self.request(health_path, bearer)
        self.require_success(status, health_path)

        version = health.get('serverVersion')
        match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', version) if isinstance(version, str) else None
        capabilities = health.get('capabilities')
        if (health.get('appId') != 'meeting-transcriber' or health.get('protocolVersion') != PROTOCOL or
                not match or tuple(map(int, match.groups())) < MIN_VERSION or
                not isinstance(capabilities, dict) or capabilities.get('openaiAudio') is not True):
            raise ValueError('TranscriptionServer v0.1.17以降のプロトコル3と音声認識APIが必要です。')
        mode = health.get('authMode')
        if mode in ('local', 'lan') and bearer is None:
            token = health.get('token')
            if not isinstance(token, str) or not token or any(ord(ch) < 33 or ord(ch) > 126 for ch in token):
                raise ValueError('TranscriptionServerの一時トークンを取得できません。')
            auth = ('X-Local-Token', token)
        elif mode == 'bearer' and bearer is not None:
            auth = bearer
        else:
            raise ValueError('TranscriptionServerの認証方式を確認できません。')

        detail = f'v{version}、プロトコル{PROTOCOL}、認証 {mode}'
        if health.get('ready') is not True or health.get('acceptingJobs') is not True:
            state = '認識環境を準備中' if health.get('startupState') == 'preparing' else '認識の受付待ち'
            raise ValueError(f'TranscriptionServerは{state}です（{detail}）。')

        models_path = '/v1/models'
        status, catalog = self.request(models_path, auth)
        self.require_success(status, models_path)
        rows = catalog.get('data')
        if catalog.get('object') != 'list' or not isinstance(rows, list):
            raise ValueError('TranscriptionServerのモデル一覧の形式が不正です。')
        choices = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            model_id = row.get('id')
            if not isinstance(model_id, str) or not re.fullmatch(MODEL_ID, model_id):
                continue
            info = row.get('x_meeting')
            if not isinstance(info, dict):
                continue
            engine, model = model_id.split('/')
            if (info.get('engineId') != engine or info.get('modelId') != model or
                    info.get('task') != 'transcription' or info.get('runtimeReady') is not True):
                continue
            # 外部プロバイダーで日本語が固定されていない場合は、アプリ側で日本語を指定できない。
            caps = info.get('capabilities')
            languages = caps.get('languages') if isinstance(caps, dict) else None
            if not isinstance(languages, list) or 'ja' not in languages:
                continue
            if info.get('available') is True or info.get('availability') == 'download_on_first_use':
                choices[model_id] = info.get('availability')
        if self.model not in choices:
            examples = '、'.join(sorted(choices)[:12]) or 'なし'
            raise ValueError(f'TranscriptionServerの日本語認識モデルを確認してください（{detail}）。選択可能: {examples}')
        availability = '、初回にモデル取得の場合あり' if choices[self.model] == 'download_on_first_use' else ''
        return detail + f'、受付中、{self.model}{availability}', auth

    def transcribe(self, wav):
        _, auth = self.preflight()
        with Path(wav).open('rb') as audio:
            data = audio.read(MAX_AUDIO + 1)
        if not data or len(data) > MAX_AUDIO:
            raise ValueError('TranscriptionServerへ送る音声は空でない64 MiB以下のファイルを指定してください。')
        # 原文・基準読み・辞書を認識ヒントとして渡さない。
        boundary = 'ReadingRepair' + uuid.uuid4().hex
        fields = {'model': self.model, 'language': 'ja', 'response_format': 'verbose_json'}
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
            for name, value in fields.items()
        ]
        parts.extend((
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="reading-repair.wav"\r\n'
            'Content-Type: audio/wav\r\n\r\n'.encode(),
            data,
            f'\r\n--{boundary}--\r\n'.encode(),
        ))
        endpoint = '/v1/audio/transcriptions'
        status, result = self.request(endpoint, auth, b''.join(parts), f'multipart/form-data; boundary={boundary}', timeout=300)
        self.require_success(status, endpoint)
        transcript = result.get('text')
        segments = result.get('segments')
        if not isinstance(transcript, str) or not isinstance(segments, list):
            raise ValueError('TranscriptionServerの文字起こし応答に本文または区間がありません。')
        return {'text': transcript, 'segments': segments, 'language': result.get('language'),
                'duration': result.get('duration'), 'provider': PROVIDER, 'model': self.model}
