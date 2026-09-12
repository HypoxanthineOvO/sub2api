#!/usr/bin/env python3
"""Real unprivileged Nginx, private ports/certificates, synthetic backends only."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

NATIVE = Path(__file__).resolve().parents[1] / 'native'
sys.path.insert(0, str(NATIVE))
import release_host as host


class NginxIntegrationTests(unittest.TestCase):
    def setUp(self):
        for tool in ['nginx', 'openssl', 'curl']:
            if not shutil.which(tool): self.skipTest(tool + ' unavailable')
        if 'HTTP2' not in subprocess.check_output(['curl', '-V'], text=True): self.skipTest('curl has no HTTP/2 support')
        self.directory = tempfile.TemporaryDirectory(prefix='vsp-release-nginx-')
        self.root = Path(self.directory.name)
        self.started = threading.Event(); self.release = threading.Event()
        self.servers = []
        for label in ['blue', 'green']:
            started, release = self.started, self.release
            def factory(name):
                class Handler(BaseHTTPRequestHandler):
                    protocol_version = 'HTTP/1.1'
                    def log_message(self, *args): pass
                    def do_GET(self):
                        if self.path == '/slow':
                            body = (name + '-begin\n' + name + '-end\n').encode()
                            self.send_response(200); self.send_header('Content-Length', str(len(body))); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                            self.wfile.write((name + '-begin\n').encode()); self.wfile.flush(); started.set()
                            release.wait(12)
                            self.wfile.write((name + '-end\n').encode()); self.wfile.flush()
                        else:
                            body = name.encode(); self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
                    def do_POST(self):
                        self.rfile.read(int(self.headers.get('Content-Length', '0')))
                        body = name.encode(); self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
                return Handler
            server = ThreadingHTTPServer(('127.0.0.1', 0), factory(label))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.servers.append(server)
        self.http_port = self.free_port(); self.tls_port = self.free_port()
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(self.root/'key.pem'), '-out', str(self.root/'cert.pem'), '-days', '1', '-subj', '/CN=release.test', '-addext', 'subjectAltName=DNS:release.test'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.conf = self.root / 'nginx.conf'
        self.write_config(0)
        self.log = (self.root / 'stderr.log').open('wb')
        self.nginx = subprocess.Popen(['nginx', '-p', str(self.root), '-c', str(self.conf), '-g', 'daemon off;'], stdout=self.log, stderr=self.log)
        self.wait_route('blue')

    @staticmethod
    def free_port():
        with socket.socket() as s: s.bind(('127.0.0.1', 0)); return s.getsockname()[1]

    def write_config(self, index):
        port = self.servers[index].server_port
        self.conf.write_text(f'''pid {self.root}/nginx.pid;
error_log {self.root}/error.log notice;
worker_processes 1;
events {{ worker_connections 64; }}
http {{
  access_log off;
  client_body_temp_path {self.root}/body;
  proxy_temp_path {self.root}/proxy;
  upstream app {{ server 127.0.0.1:{port}; }}
  server {{
    listen 127.0.0.1:{self.http_port};
    listen 127.0.0.1:{self.tls_port} ssl http2;
    server_name release.test;
    ssl_certificate {self.root}/cert.pem;
    ssl_certificate_key {self.root}/key.pem;
    location / {{ proxy_pass http://app; proxy_buffering off; proxy_request_buffering on; }}
  }}
}}
''')

    def wait_route(self, wanted):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.nginx.poll() is not None:
                raise AssertionError((self.root/'stderr.log').read_text())
            try:
                conn = http.client.HTTPConnection('127.0.0.1', self.http_port, timeout=.5)
                conn.request('GET', '/health', headers={'Connection': 'close'})
                body = conn.getresponse().read().decode(); conn.close()
                if body == wanted: return
            except OSError: pass
            time.sleep(.05)
        self.fail('route did not become ' + wanted)

    def switch(self):
        with patch.object(host, 'info', return_value={'MainPID': str(self.nginx.pid)}):
            old = host.nginx_workers()
        self.write_config(1)
        subprocess.run(['nginx', '-t', '-p', str(self.root), '-c', str(self.conf)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['nginx', '-s', 'reload', '-p', str(self.root), '-c', str(self.conf)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.wait_route('green')
        return old

    def wait_drained(self, generations):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if not any(host.generation_alive(g) for g in generations): return
            time.sleep(.05)
        self.fail('old Nginx generation did not drain')

    def tearDown(self):
        if not hasattr(self, 'directory'): return
        self.release.set()
        if hasattr(self, 'nginx') and self.nginx.poll() is None:
            self.nginx.send_signal(signal.SIGQUIT)
            try: self.nginx.wait(timeout=5)
            except subprocess.TimeoutExpired: self.nginx.terminate(); self.nginx.wait(timeout=5)
        for server in self.servers: server.shutdown(); server.server_close()
        if hasattr(self, 'log'): self.log.close()
        self.directory.cleanup()

    def test_http2_stream_survives_switch(self):
        child = subprocess.Popen(['curl', '--noproxy', '*', '--http2', '--cacert', str(self.root/'cert.pem'), '--resolve', f'release.test:{self.tls_port}:127.0.0.1', '-fsS', '--max-time', '15', '-w', 'HTTP=%{http_version}', f'https://release.test:{self.tls_port}/slow'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertTrue(self.started.wait(5), 'stream was not started')
            generations = self.switch()
            self.assertTrue(any(host.generation_alive(g) for g in generations))
            self.release.set()
            output, error = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, error)
            self.assertEqual(output, b'blue-begin\nblue-end\nHTTP=2')
            self.wait_drained(generations)
        finally:
            self.release.set()
            if child.poll() is None: child.terminate(); child.wait(timeout=5)

    def test_pending_upload_requires_nginx_generation_drain(self):
        conn = socket.create_connection(('127.0.0.1', self.http_port), timeout=5)
        try:
            conn.sendall(b'POST /upload HTTP/1.1\r\nHost: release.test\r\nContent-Length: 8\r\nConnection: close\r\n\r\n')
            time.sleep(.15)
            self.assertFalse(host.has_connections(self.servers[0].server_port), 'backend should not yet see the buffered request')
            generations = self.switch()
            self.assertTrue(any(host.generation_alive(g) for g in generations))
            conn.sendall(b'12345678')
            response = bytearray()
            while True:
                chunk = conn.recv(4096)
                if not chunk: break
                response.extend(chunk)
            self.assertIn(b'200 OK', response); self.assertTrue(response.endswith(b'blue'))
            self.wait_drained(generations)
        finally: conn.close()

    def test_invalid_configuration_does_not_replace_loaded_route(self):
        self.conf.write_text('invalid directive;\n')
        r = subprocess.run(['nginx', '-t', '-p', str(self.root), '-c', str(self.conf)], capture_output=True)
        self.assertNotEqual(r.returncode, 0)
        self.wait_route('blue')


if __name__ == '__main__': unittest.main(verbosity=2)
