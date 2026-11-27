from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from threading import BoundedSemaphore, Thread

from voisona_gateway import GatewayServer, serve


@contextmanager
def running(server):
    with server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.server.requests.append((self.path, self.headers.get('Authorization'),
                                     self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(201)
        self.send_header('Location', f'http://127.0.0.1:{self.server.server_port}/api/talk/v1/speech-syntheses/job-1')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"uuid":"job-1"}')

    def do_GET(self):
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Talk"')
        self.end_headers()

    def do_DELETE(self):
        self.send_response(204)
        self.end_headers()


def request(server, method, path, body=None, headers=None):
    connection = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
    try:
        connection.request(method, path, body, headers or {})
        reply = connection.getresponse()
        return reply.status, reply.headers, reply.read()
    finally:
        connection.close()


class GatewayTest(unittest.TestCase):
    def test_preserves_text_status_authentication_and_job_location(self):
        with running(ThreadingHTTPServer(('127.0.0.1', 0), Upstream)) as upstream:
            upstream.requests = []
            with running(GatewayServer(('127.0.0.1', 0), upstream.server_port, BoundedSemaphore(4))) as gateway:
                path = '/api/talk/v1/speech-syntheses?limit=1'
                body = '{"text":"  台詞。 "}'.encode()
                status, headers, data = request(gateway, 'POST', path, body,
                                                {'Authorization': 'Basic fixture', 'Content-Type': 'application/json'})
                self.assertEqual((status, data), (201, b'{"uuid":"job-1"}'))
                self.assertEqual(upstream.requests, [(path, 'Basic fixture', body)])
                location = headers['Location']
                self.assertEqual(location, '/api/talk/v1/speech-syntheses/job-1')
                self.assertEqual(request(gateway, 'DELETE', location)[0], 204)
                status, headers, _ = request(gateway, 'GET', '/api/talk/v1/voices/ui_ja_JP/2.0.0')
                self.assertEqual((status, headers['WWW-Authenticate']), (401, 'Basic realm="Talk"'))

    def test_rejects_browser_origin_and_missing_upstream(self):
        with ThreadingHTTPServer(('127.0.0.1', 0), Upstream, bind_and_activate=False) as upstream:
            upstream.server_bind()  # ポートを確保するがlistenしない。
            with running(GatewayServer(('127.0.0.1', 0), upstream.server_port, BoundedSemaphore(4))) as gateway:
                voices = '/api/talk/v1/voices'
                self.assertEqual(request(gateway, 'GET', voices, headers={'Host': 'example.invalid'})[0], 400)
                self.assertEqual(request(gateway, 'GET', voices, headers={'Origin': 'http://example.invalid'})[0], 403)
                local = {'Host': f'127.0.0.1:{gateway.server_port}'}
                self.assertEqual(request(gateway, 'GET', 'http://example.invalid' + voices, headers=local)[0], 404)
                self.assertEqual(request(gateway, 'GET', '/api/talk/v1/../voices')[0], 404)
                self.assertEqual(request(gateway, 'GET', voices)[0], 502)
        with self.assertRaisesRegex(ValueError, 'ポートを分けて'):
            serve(32766, 32766, lambda: None)
