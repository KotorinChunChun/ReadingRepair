"""VoiSona Talk REST APIを同じPC内で中継する。"""
from contextlib import ExitStack
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import shutil
import socket
from threading import BoundedSemaphore, Thread
from urllib.parse import urlsplit


API_PATH = re.compile(r'/api/talk/v1(?:/[a-zA-Z0-9_-][a-zA-Z0-9_.-]*)*/?')
REQUEST_HEADERS = ('Authorization', 'Content-Type', 'Accept', 'Accept-Encoding')
RESPONSE_HEADERS = {
    'content-type', 'content-length', 'content-encoding', 'content-disposition',
    'www-authenticate', 'retry-after', 'cache-control', 'etag', 'last-modified',
}
MAX_BODY = 1024 * 1024


class GatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        # URL、認証情報、原文はログへ保存しない。
        pass

    def error(self, status, message):
        data = message.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def forward(self):
        self.close_connection = True
        host = self.headers.get('Host', '').lower()
        if self.headers.get_all('Host') != [self.headers.get('Host')] or host not in self.server.allowed_hosts:
            return self.error(400, 'ループバックのホスト名を指定してください。')
        if any(origin.lower() != 'http://' + host for origin in self.headers.get_all('Origin', [])):
            return self.error(403, '異なるオリジンからは呼び出せません。')

        path = self.path.partition('?')[0]
        if not API_PATH.fullmatch(path) or '#' in self.path:
            return self.error(404, 'VoiSona Talk APIのパスを指定してください。')
        if path == '/api/talk/v1/readingrepair-health' and self.command == 'GET':
            return self.error(200, 'ReadingRepair VoiSona gateway')

        lengths = self.headers.get_all('Content-Length', [])
        if (self.headers.get_all('Transfer-Encoding') or len(lengths) > 1 or
                (lengths and not re.fullmatch(r'[0-9]{1,10}', lengths[0]))):
            return self.error(400, 'Content-Lengthが必要です。')
        size = int(lengths[0]) if lengths else 0
        if size > MAX_BODY:
            return self.error(413, '要求本文が大きすぎます。')
        if any(len(self.headers.get_all(name, [])) > 1 for name in REQUEST_HEADERS):
            return self.error(400, '要求ヘッダーが重複しています。')
        try:
            body = self.rfile.read(size) if lengths else None
        except TimeoutError:
            return self.error(408, '要求本文を受信できませんでした。')
        if body is not None and len(body) != size:
            return self.error(400, '要求本文が途中で終了しました。')

        headers = {name: self.headers[name] for name in REQUEST_HEADERS if name in self.headers}
        upstream = HTTPConnection('127.0.0.1', self.server.upstream_port, timeout=30)
        try:
            try:
                upstream.request(self.command, self.path, body=body, headers=headers)
                response = upstream.getresponse()
            except TimeoutError:
                return self.error(504, 'VoiSona Talk APIが応答しませんでした。')
            except (OSError, HTTPException, ValueError):
                return self.error(502, 'VoiSona Talk APIへ接続できません。')

            self.send_response_only(response.status)
            for name, value in response.getheaders():
                if name.lower() in RESPONSE_HEADERS and not (response.chunked and name.lower() == 'content-length'):
                    self.send_header(name, value)
            location = response.getheader('Location')
            if location:
                local = self.local_location(location)
                if local:
                    self.send_header('Location', local)
            self.send_header('Connection', 'close')
            self.end_headers()
            if self.command != 'HEAD':
                shutil.copyfileobj(response, self.wfile, length=65536)
        except (OSError, HTTPException):
            # 送信中の切断では応答を打ち切る。POSTは再送しない。
            pass
        finally:
            upstream.close()

    def local_location(self, location):
        if location.startswith('/') and not location.startswith('//'):
            return location if API_PATH.fullmatch(location.partition('?')[0]) else None
        try:
            url = urlsplit(location)
            if (url.scheme == 'http' and url.netloc in {
                    f'127.0.0.1:{self.server.upstream_port}', f'localhost:{self.server.upstream_port}',
                    f'[::1]:{self.server.upstream_port}'}
                    and API_PATH.fullmatch(url.path) and not url.fragment):
                return url.path + ('?' + url.query if url.query else '')
        except ValueError:
            pass
        return None

    do_GET = do_HEAD = do_POST = do_DELETE = do_PUT = do_PATCH = forward


class GatewayServer(ThreadingHTTPServer):
    allow_reuse_address = False
    request_queue_size = 32

    def __init__(self, address, upstream_port, slots):
        self.upstream_port = upstream_port
        self.slots = slots
        super().__init__(address, GatewayHandler)
        self.allowed_hosts = {f'{host}:{self.server_port}' for host in ('127.0.0.1', 'localhost', '[::1]')}

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        if self.address_family == socket.AF_INET6:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        super().server_bind()

    def get_request(self):
        client, address = super().get_request()
        client.settimeout(10)
        return client, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # 例外の標準ログに要求の詳細を出さない。
        pass


class IPv6GatewayServer(GatewayServer):
    address_family = socket.AF_INET6


def serve(listen_port, upstream_port, ready):
    if not (1024 <= listen_port <= 65535 and 1 <= upstream_port <= 65535):
        raise ValueError('待受ポートは1024～65535、転送先ポートは1～65535を指定してください。')
    if listen_port == upstream_port:
        raise ValueError('待受ポートとVoiSona Talk本体のポートを分けてください。')

    slots = BoundedSemaphore(32)
    with ExitStack() as stack:
        try:
            ipv4 = stack.enter_context(GatewayServer(('127.0.0.1', listen_port), upstream_port, slots))
            ipv6 = (stack.enter_context(IPv6GatewayServer(('::1', listen_port), upstream_port, slots))
                    if socket.has_ipv6 else None)
        except OSError as error:
            raise ValueError(f'ループバックのポート {listen_port} を確保できません（{error.errno}）。') from None
        if ipv6:
            listener = Thread(target=ipv6.serve_forever, daemon=True)
            listener.start()
            stack.callback(listener.join)
            stack.callback(ipv6.shutdown)
        ready()
        try:
            ipv4.serve_forever()
        except KeyboardInterrupt:
            pass
