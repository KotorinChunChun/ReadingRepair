"""TranscriptionServerと読み照合のHTTP契約。実サービスや利用者の辞書を使わない。"""
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
import tempfile
import unittest
from unittest.mock import patch

import lab
from transcription_server import TranscriptionServer, validate_settings


@contextmanager
def transcription_service(mode='lan', health_changes=None, model_changes=None, post_status=200):
    calls = []
    token = 'mock-ephemeral-token'
    model = {'id': 'whisper/small', 'x_meeting': {
        'engineId': 'whisper', 'modelId': 'small', 'task': 'transcription',
        'runtimeReady': True, 'available': False, 'availability': 'download_on_first_use',
        'capabilities': {'languages': ['ja', 'en']}, **(model_changes or {}),
    }}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def reply(self, value, status=200):
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def do_GET(self):
            calls.append((self.path, self.headers.get('X-Local-Token')))
            if self.path == '/api/health':
                self.reply({'appId': 'meeting-transcriber', 'serverVersion': '0.1.17',
                            'protocolVersion': 3, 'capabilities': {'openaiAudio': True},
                            'ready': True, 'acceptingJobs': True, 'authMode': mode, 'token': token,
                            **(health_changes or {})})
            elif self.path == '/v1/models':
                if self.headers.get('X-Local-Token') == token:
                    self.reply({'object': 'list', 'data': [model]})
                else:
                    self.reply({}, 403)
            else:
                self.reply({}, 404)

        def do_POST(self):
            calls.append((self.path, self.headers.get('X-Local-Token')))
            body = self.rfile.read(int(self.headers['Content-Length']))
            content_type = self.headers['Content-Type']
            message = BytesParser(policy=policy.default).parsebytes(
                b'Content-Type: ' + content_type.encode() + b'\r\n\r\n' + body)
            calls.append({part.get_param('name', header='content-disposition'): part.get_payload(decode=True)
                          for part in message.iter_parts()})
            if self.headers.get('X-Local-Token') != token:
                self.reply({}, 403)
                return
            if post_status != 200:
                self.reply({'error': {'message': token + ' server error detail'}}, post_status)
                return
            self.reply({'text': 'ジョーズ', 'language': 'ja', 'segments': [], 'duration': .01})

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': .02})
        thread.start()
        try:
            yield {'asr_provider': 'transcription-server', 'transcription_server_model': 'whisper/small',
                   'transcription_server_url': f'http://127.0.0.1:{server.server_port}'}, calls
        finally:
            server.shutdown()
            thread.join()


class TranscriptionServerTests(unittest.TestCase):
    def test_local_and_lan_use_health_token_and_audio_only(self):
        for mode in ('local', 'lan'):
            with self.subTest(mode=mode), transcription_service(mode=mode) as (settings, calls):
                with tempfile.TemporaryDirectory() as folder:
                    audio = Path(folder) / 'source name.wav'
                    audio.write_bytes(b'RIFF fixture')
                    transcript = TranscriptionServer(settings).transcribe(audio)
                self.assertEqual(transcript['text'], 'ジョーズ')
                self.assertEqual(transcript['model'], 'whisper/small')
                self.assertEqual(calls[:3], [('/api/health', None),
                                            ('/v1/models', 'mock-ephemeral-token'),
                                            ('/v1/audio/transcriptions', 'mock-ephemeral-token')])
                self.assertEqual(calls[3], {'file': b'RIFF fixture', 'model': b'whisper/small',
                                            'language': b'ja', 'response_format': b'verbose_json'})
                self.assertNotIn('mock-ephemeral-token', str(transcript))

    def test_preflight_blocks_upload_before_model_or_server_is_ready(self):
        scenarios = [
            ({'protocolVersion': 2}, {}, 'プロトコル3', 1),
            ({'serverVersion': '0.1.16'}, {}, 'v0.1.17', 1),
            ({'ready': False, 'startupState': 'preparing'}, {}, '準備中', 1),
            ({'acceptingJobs': False}, {}, '受付待ち', 1),
            ({'token': ''}, {}, '一時トークン', 1),
            ({}, {'availability': 'install_required'}, '選択可能: なし', 2),
            ({}, {'capabilities': {'languages': ['en']}}, '選択可能: なし', 2),
            ({}, {'task': 'diarization'}, '選択可能: なし', 2),
        ]
        for health, model, message, requests in scenarios:
            with self.subTest(health=health, model=model), transcription_service(health_changes=health, model_changes=model) as (settings, calls):
                with self.assertRaisesRegex(ValueError, message):
                    TranscriptionServer(settings).transcribe('never-opened.wav')
                self.assertEqual(len(calls), requests)

    def test_http_errors_report_status_without_body_or_retry(self):
        for status in (403, 503, 502, 307):
            with self.subTest(status=status), transcription_service(post_status=status) as (settings, calls):
                with tempfile.TemporaryDirectory() as folder:
                    audio = Path(folder) / 'probe.wav'
                    audio.write_bytes(b'RIFF fixture')
                    with self.assertRaisesRegex(ValueError, f'HTTP {status}') as error:
                        TranscriptionServer(settings).transcribe(audio)
                self.assertNotIn('mock-ephemeral-token', str(error.exception))
                self.assertEqual(len(calls), 4)

    def test_bearer_key_is_only_used_after_https_health_challenge(self):
        settings = {'asr_provider': 'transcription-server', 'transcription_server_url': 'https://asr.example',
                    'transcription_server_model': 'whisper/base'}
        health = {'appId': 'meeting-transcriber', 'serverVersion': '0.1.17', 'protocolVersion': 3,
                  'authMode': 'bearer', 'ready': True, 'acceptingJobs': True, 'capabilities': {'openaiAudio': True}}
        info = {'engineId': 'whisper', 'modelId': 'base', 'task': 'transcription', 'runtimeReady': True,
                'available': True, 'capabilities': {'languages': ['ja']}}
        models = {'object': 'list', 'data': [{'id': 'whisper/base', 'x_meeting': info}]}
        with patch.dict('os.environ', {'READINGREPAIR_TRANSCRIPTION_SERVER_API_KEY': 'test-key'}):
            server = TranscriptionServer(settings)
            with patch.object(server, 'request', side_effect=[(401, {}), (200, health), (200, models)]) as request:
                detail, auth = server.preflight()
                self.assertEqual(auth, ('Authorization', 'Bearer test-key'))
                self.assertNotIn('test-key', detail)
                self.assertEqual([call.args for call in request.call_args_list], [
                    ('/api/health',), ('/api/health', auth), ('/v1/models', auth)])
            server = TranscriptionServer({**settings, 'transcription_server_url': 'http://asr.example'})
            with patch.object(server, 'request', return_value=(401, {})) as request:
                with self.assertRaisesRegex(ValueError, 'HTTPS'):
                    server.preflight()
                request.assert_called_once_with('/api/health')

    def test_credentials_cannot_be_entered_in_url(self):
        for url in ('http://key@localhost:8769', 'https://localhost/?token=key', 'http://localhost/api/health'):
            with self.assertRaisesRegex(ValueError, 'オリジン'):
                validate_settings({'asr_provider': 'transcription-server', 'transcription_server_url': url})

    def test_default_and_older_settings_keep_local_whisper(self):
        with patch('lab.Whisper') as whisper, patch('lab.transcription_server.TranscriptionServer') as remote:
            self.assertIs(lab.recognizer({'whisper_model': 'old-model'}), whisper.return_value)
            whisper.assert_called_once_with('old-model', '')
            remote.assert_not_called()
