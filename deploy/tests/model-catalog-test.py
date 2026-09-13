#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import subprocess
import shutil
import socket
import tempfile
import time
import unittest
import urllib.error
import urllib.request

spec = importlib.util.spec_from_file_location('catalog', Path(__file__).resolve().parents[1] / 'catalog/catalog.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class CatalogTests(unittest.TestCase):
    def test_preserves_all_metadata_and_models(self):
        data = {'version': 1, 'extra': {'future': True}, 'models': [
            {'id': 'offline-example', 'protocol': 'openai', 'capabilities': ['tool_use']},
            {'id': 'hidden-example', 'hidden': True, 'unknown': [1, 2]},
        ]}
        self.assertEqual(catalog.validate(json.dumps(data).encode()), data)

    def test_rejects_invalid_data(self):
        for raw in [b'{"models": [], "models": []}', b'{"models":[{"id":"x"},{"id":"x"}]}',
                    b'{"models":[{"id":"x","cost":{"input":NaN}}]}',
                    b'{"version":true,"models":[]}', b'{"models":[{"id":"x","contextWindow":true}]}',
                    b'{"models":[{"id":"x","cost":{"input":-1}}]}',
                    b'{"models":[{"id":"x","cost":{"tiers":[{}]}}]}',
                    b'{"models":[],"api_key":"secret"}',
                    b'{"models":[{"id":"x","protocol":"execute-code"}]}',
                    b'{"models":[{"id":"x","effortLevels":["low"],"defaultEffort":"high"}]}']:
            with self.subTest(raw=raw), self.assertRaises(ValueError): catalog.validate(raw)
        with self.assertRaises(ValueError): catalog.validate(b' ' * (catalog.MAX_BYTES + 1))

    def test_rejects_effort_regression(self):
        old = {'models': [{'id': 'x', 'effortRevision': 3, 'effortLevels': ['high']}]}
        new = {'models': [{'id': 'x', 'effortRevision': 2, 'effortLevels': ['low']}]}
        with self.assertRaises(ValueError): catalog.validate(json.dumps(new).encode(), old)

    def test_prepares_exact_committed_bytes_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); repo = root / 'repo'; repo.mkdir()
            def git(*args): return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, check=True)
            git('init'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.test')
            source = repo / 'model-catalog.json'; raw = b'{"version":1,"models":[{"id":"offline"}]}\n'; source.write_bytes(raw)
            git('add', '.'); git('commit', '-m', 'fixture')
            artifact = catalog.prepare(source, root / 'out')
            self.assertEqual((artifact / 'model-catalog.json').read_bytes(), raw)
            self.assertEqual(json.loads((artifact / 'manifest.json').read_text())['modelCount'], 1)
            with self.assertRaises(ValueError): catalog.prepare(source, root / 'out')
            source.write_text('{"models": []}')
            with self.assertRaises(ValueError): catalog.prepare(source, root / 'out')

    @unittest.skipUnless(shutil.which('nginx'), 'nginx is required for HTTP integration')
    def test_nginx_serves_public_json_with_cache_and_without_application(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = b'{"version":1,"models":[{"id":"offline","hidden":true}]}'
            data = root / 'catalog.json'; data.write_bytes(raw)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
            location = (Path(__file__).resolve().parents[1] / 'catalog/nginx-location.conf').read_text()
            location = location.replace('/etc/vsp-sub2api/model-catalog.json', str(data))
            config = root / 'nginx.conf'
            config.write_text(f'pid {root}/pid; error_log {root}/error.log; events {{}} http {{ access_log off; server {{ listen 127.0.0.1:{port}; {location} }} }}')
            process = subprocess.Popen([shutil.which('nginx'), '-p', str(root), '-c', str(config), '-e', str(root / 'error.log'), '-g', 'daemon off;'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            url = f'http://127.0.0.1:{port}/vsp/models'
            try:
                for _ in range(100):
                    try:
                        response = opener.open(url, timeout=1)
                        break
                    except urllib.error.URLError:
                        if process.poll() is not None: self.fail((root / 'error.log').read_text())
                        time.sleep(0.02)
                else: self.fail('private nginx did not become ready')
                with response:
                    self.assertEqual(response.read(), raw)
                    self.assertEqual(response.headers['Content-Type'], 'application/json')
                    self.assertEqual(response.headers['Access-Control-Allow-Origin'], '*')
                    self.assertEqual(response.headers['Cache-Control'], 'public, max-age=300')
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    opener.open(urllib.request.Request(url, data=b'no writes', method='POST'), timeout=1)
                self.assertEqual(denied.exception.code, 403)
                self.assertEqual(data.read_bytes(), raw)
            finally:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)


if __name__ == '__main__': unittest.main(verbosity=2)
