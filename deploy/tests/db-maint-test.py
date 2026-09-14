#!/usr/bin/env python3
"""Maintenance protocol, private installer and real isolated PostgreSQL tests."""
import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import socket
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deploy/native'))
sys.path.insert(0, str(ROOT / 'deploy/dbmaint'))
from operations import Operations, MaintenanceError, GuardRejected, validate, perform, quote
from release_schema_data import Database, RedisCaches
from release_core import decode
from install_babel import remote_command, FILES


def request(op, **values): return {'operation': op, 'request_id': 'a' * 32, **values}


class Cache:
    def __init__(self): self.calls = []; self.fail = False
    def call(self, *parts):
        self.calls.append(parts)
        if self.fail and parts[0] == 'DEL': raise OSError('private detail')
        if parts[0] == 'HGETALL': return [b'usage_5h', b'3', b'window_5h', b'1789344000']
        return 1


class BoundaryTests(unittest.TestCase):
    def test_strict_typed_protocol_and_no_arbitrary_sql(self):
        invalid = [request('sql', sql='DROP DATABASE sub2api'), request('inspect', sql='SELECT 1'),
                   request('user', id=True), request('user', id=-1), request('user', id='1;DROP TABLE users'),
                   request('find-users', search='x\nforged audit'), request('audit', id='../../secret'),
                   request('user-role', id=1, expect_name='name', expect_role='user', role='root', reason='test'),
                   request('usage', scope='account', id=1, since='2026-09-14', until='2026-09-15'),
                   request('usage', scope='account', id=1, since='2026-09-01T00:00:00Z', until='2026-09-14T00:00:00Z')]
        for r in invalid:
            with self.subTest(r=r), self.assertRaises(MaintenanceError): validate(r)
        with self.assertRaises(Exception): decode('{"operation":"inspect","operation":"sql"}')
        for value in ('NaN', 'Infinity', -1, '0.000000001', True, '1;DROP TABLE users'):
            with self.assertRaises(MaintenanceError):
                validate(request('key-limits', id=1, user_id=2, expect_updated_at='2026-09-14T00:00:00Z', limits={'rate_limit_5h': value}, reason='test'))

    def test_installer_verifies_frozen_bytes_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); archive = root / 'bundle.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                for name in FILES:
                    raw = b"from pathlib import Path;Path(__file__).with_name('executed').write_text('ok')" if name == 'install.py' else b''
                    info = tarfile.TarInfo(name); info.size = len(raw); tar.addfile(info, io.BytesIO(raw))
            code = shlex.split(remote_command(archive))[-1].replace('/home/heyx/VSP-Sub2API/bundle.tar.gz', str(archive))
            code = code.replace('base.stat().st_uid==0', f'base.stat().st_uid=={os.getuid()}')
            for case in ('valid', 'tampered', 'symlink'):
                base = root / case; base.mkdir(mode=0o700)
                if case == 'tampered':
                    raw = archive.read_bytes(); archive.write_bytes(b'X' + raw[1:])
                elif case == 'symlink':
                    target = root / 'target'; archive.rename(target); archive.symlink_to(target)
                result = subprocess.run([sys.executable, '-I', '-c', code.replace("'/var/backups'", repr(str(base)))], capture_output=True, timeout=10)
                self.assertEqual(result.returncode == 0, case == 'valid')
                self.assertEqual(bool(list(base.rglob('executed'))), case == 'valid')

    def test_sudoers_is_only_the_fixed_no_argument_control(self):
        source = (ROOT / 'deploy/dbmaint/install.py').read_text()
        self.assertIn('NOPASSWD: {LIB}/control ""', source)
        self.assertNotIn('NOPASSWD: ALL', source)
        self.assertNotIn('systemctl', source)
        self.assertNotIn('GRANT ', source)


spec = importlib.util.spec_from_file_location('postgres_fixture', Path(__file__).with_name('upstream-migration-test.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)


class DatabaseTests(fixture.UpstreamMigrationTests):
    def setUp(self):
        super().setUp()
        self.sql("""CREATE TABLE users(id bigint primary key,username text,email text,role text,status text,notes text DEFAULT '',updated_at timestamptz DEFAULT now(),deleted_at timestamptz);
          INSERT INTO users(id,username,email,role,status) VALUES(1,'operator','op@example.test','admin','active'),(2,'李宇轩','li@example.test','user','active'),(3,'另一个用户','other@example.test','user','active');
          CREATE TABLE api_keys(id bigint primary key,user_id bigint,name text,status text,key text,quota numeric DEFAULT 0,quota_used numeric DEFAULT 0,
          rate_limit_5h numeric DEFAULT 10,rate_limit_1d numeric DEFAULT 20,rate_limit_7d numeric DEFAULT 30,
          usage_5h numeric DEFAULT 3,usage_1d numeric DEFAULT 4,usage_7d numeric DEFAULT 5,
          window_5h_start timestamptz,window_1d_start timestamptz,window_7d_start timestamptz,updated_at timestamptz DEFAULT now(),deleted_at timestamptz);
          INSERT INTO api_keys(id,user_id,name,status,key,window_5h_start) VALUES(10,2,'personal','active','SYNTHETIC_SECRET_NEVER_OUTPUT','2026-09-14T00:00:00Z');
          CREATE TABLE accounts(id bigint primary key,name text,notes text DEFAULT '',platform text,type text,status text,
          session_window_start timestamptz,session_window_end timestamptz,updated_at timestamptz DEFAULT now(),deleted_at timestamptz,extra jsonb,credentials jsonb);
          INSERT INTO accounts(id,name,platform,type,status,extra,credentials) VALUES(43,'李宇轩 GLM','zhipu','api_key','active',
          '{"zhipu_5h_reset_at":"2026-09-14T05:00:00Z","zhipu_5h_used_percent":20,"password":"SYNTHETIC_SECRET_NEVER_OUTPUT"}',
          '{"api_key":"SYNTHETIC_SECRET_NEVER_OUTPUT"}');
          CREATE TABLE usage_logs(user_id bigint,api_key_id bigint,account_id bigint,model text,created_at timestamptz,input_tokens bigint,output_tokens bigint,actual_cost numeric,ip_address text,user_agent text);
          INSERT INTO usage_logs VALUES(2,10,43,'glm','2026-09-14T01:00:00Z',10,20,0.1,'192.0.2.1','test'),
          (3,11,43,'glm','2026-09-14T02:00:00Z',20,30,0.2,'192.0.2.2','test'),
          (3,11,43,'glm','2026-09-14T05:00:00Z',1,2,0.3,'192.0.2.2','test');""")
        self.cache = Cache(); self.ops = Operations(Database(self.env), self.cache)
        self.records = {}
        self.read_record = lambda identity: copy.deepcopy(self.records.get(identity))
        self.save_record = lambda identity, value: self.records.__setitem__(identity, copy.deepcopy(value))

    def run_operation(self, r): return perform(r, self.ops, self.read_record, self.save_record)

    def promotion(self): return request('user-role', id=2, expect_name='李宇轩', expect_role='user', role='admin', reason='explicit user request')

    def test_safe_search_inspection_and_quote_roundtrip(self):
        for value in ("x'; DROP TABLE users; --", "\\'; SELECT 99; --", '中文'):
            self.assertEqual(self.ops.query(f'SELECT to_json({quote(value)}::text);'), value)
        users = self.ops.read(request('find-users', search='李宇轩'))
        self.assertEqual([u['id'] for u in users['matches']], [2])
        accounts = self.ops.read(request('find-accounts', search='李宇轩'))
        self.assertEqual([a['id'] for a in accounts['matches']], [43])
        for op, identity in (('user', 2), ('account', 43)):
            result = self.ops.read(request(op, id=identity))
            self.assertNotIn('SYNTHETIC_SECRET_NEVER_OUTPUT', json.dumps(result))

    def test_role_change_audit_and_targeted_cache_invalidation(self):
        result = self.run_operation(self.promotion())
        self.assertEqual(result['phase'], 'complete')
        self.assertEqual(result['result']['before']['role'], 'user')
        self.assertEqual(result['result']['after']['role'], 'admin')
        hashed = hashlib.sha256(b'SYNTHETIC_SECRET_NEVER_OUTPUT').hexdigest()
        self.assertIn(('DEL', 'apikey:auth:' + hashed), self.cache.calls)
        self.assertIn(('PUBLISH', 'auth:cache:invalidate', hashed), self.cache.calls)
        self.assertNotIn('SYNTHETIC_SECRET_NEVER_OUTPUT', json.dumps(self.records))

    def test_guards_reject_wrong_name_owner_and_last_admin(self):
        for r in ({**self.promotion(), 'expect_name': 'wrong'}, request('user-role', id=1, expect_name='operator', expect_role='admin', role='user', reason='test')):
            with self.assertRaises(GuardRejected): self.ops.mutate(r)
        with self.assertRaises(GuardRejected): self.ops.mutate(request('key-reset-window', id=10, user_id=3, window='5h', expect_start='2026-09-14T00:00:00Z', reason='test'))
        self.assertEqual(self.ops.query("SELECT to_json(role) FROM users WHERE id=1;"), 'admin')

    def test_duplicate_request_does_not_repeat_the_write(self):
        r = self.promotion(); first = self.run_operation(r)
        with patch.object(self.ops, 'mutate') as mutate:
            self.assertEqual(self.run_operation(r), first); mutate.assert_not_called()
        with self.assertRaises(MaintenanceError): self.run_operation({**r, 'role': 'user'})

    def test_cache_failure_is_committed_and_retry_does_not_repeat_sql(self):
        r = self.promotion(); self.cache.fail = True
        with self.assertRaises(MaintenanceError): self.run_operation(r)
        self.assertEqual(self.records[r['request_id']]['phase'], 'cache_pending')
        self.assertEqual(self.ops.query('SELECT to_json(role) FROM users WHERE id=2;'), 'admin')
        self.cache.fail = False
        with patch.object(self.ops, 'mutate') as mutate:
            self.assertEqual(self.run_operation(r)['phase'], 'complete'); mutate.assert_not_called()

    def test_ambiguous_commit_never_replayed(self):
        r = self.promotion()
        with patch.object(self.ops, 'mutate', side_effect=TimeoutError('unknown commit')):
            with self.assertRaises(MaintenanceError): self.run_operation(r)
        self.assertEqual(self.records[r['request_id']]['phase'], 'intent')
        with patch.object(self.ops, 'mutate') as mutate:
            with self.assertRaises(MaintenanceError): self.run_operation(r)
            mutate.assert_not_called()

    def test_limits_and_single_window_reset_preserve_other_usage(self):
        key = self.ops.read(request('user', id=2))['keys'][0]
        result = self.run_operation(request('key-limits', id=10, user_id=2, expect_updated_at=key['updated_at'], limits={'rate_limit_5h': '15.25'}, reason='test'))
        self.assertEqual(result['result']['after']['rate_limit_5h'], 15.25)
        with self.assertRaises(GuardRejected): self.ops.mutate(request('key-limits', id=10, user_id=2, expect_updated_at=key['updated_at'], limits={'rate_limit_5h': 9}, reason='stale'))
        r = request('key-reset-window', id=10, user_id=2, window='5h', expect_start=key['window_5h_start'], reason='test'); r['request_id'] = 'b' * 32
        result = self.run_operation(r)['result']['after']
        self.assertEqual((result['usage_5h'], result['usage_1d'], result['usage_7d']), (0, 4, 5))
        self.assertIsNone(result['window_5h_start'])
        self.assertIn(('DEL', 'apikey:rate:10'), self.cache.calls)

    def test_usage_attributes_other_user_and_end_is_exclusive(self):
        r = request('usage', scope='account', id=43, since='2026-09-14T00:00:00Z', until='2026-09-14T05:00:00Z')
        result = self.run_operation(r)['result']
        self.assertEqual((result['requests'], result['users']), (2, 2))
        self.assertEqual({row['user_id'] for row in result['groups']}, {2, 3})
        self.assertFalse(result['truncated'])
        self.assertNotIn('SYNTHETIC_SECRET_NEVER_OUTPUT', json.dumps(result))


@unittest.skipUnless(shutil.which('redis-server'), 'local redis-server required')
class RedisTests(unittest.TestCase):
    def test_real_targeted_deletion_preserves_unrelated_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            proc = subprocess.Popen(['redis-server', '--bind', '127.0.0.1', '--port', str(port), '--save', '', '--appendonly', 'no', '--dir', directory], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            cache = RedisCaches({'REDIS_HOST': '127.0.0.1', 'REDIS_PORT': '6379', 'REDIS_DB': '0'}); cache.port = port
            try:
                for _ in range(100):
                    try: cache.call('PING'); break
                    except OSError: time.sleep(0.02)
                secret = 'synthetic-private-key'; hashed = hashlib.sha256(secret.encode()).hexdigest()
                cache.call('SET', 'apikey:auth:' + hashed, 'stale')
                cache.call('SET', 'apikey:rate:10', 'stale')
                cache.call('SET', 'apikey:auth:unrelated', 'keep')
                cache.call('SET', 'apikey:rate:11', 'keep')
                cache.call('SET', 'other-service', 'keep')
                ops = Operations(None, cache)
                with patch.object(ops, 'query', return_value=[secret]), patch.object(cache, 'call', wraps=cache.call) as calls:
                    ops.invalidate(request('key-reset-window', id=10, user_id=2, window='5h', expect_start=None, reason='test'))
                    self.assertIn(('PUBLISH', 'auth:cache:invalidate', hashed), [c.args for c in calls.call_args_list])
                self.assertIsNone(cache.call('GET', 'apikey:auth:' + hashed))
                self.assertIsNone(cache.call('GET', 'apikey:rate:10'))
                for key in ('apikey:auth:unrelated', 'apikey:rate:11', 'other-service'):
                    self.assertEqual(cache.call('GET', key), b'keep')
            finally:
                proc.terminate(); proc.wait(timeout=5)


if __name__ == '__main__': unittest.main(verbosity=2)
