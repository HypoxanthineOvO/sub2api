#!/usr/bin/env python3
"""Maintenance fault matrix and real isolated PostgreSQL/Redis recovery tests."""
import copy
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

NATIVE = Path(__file__).resolve().parents[1] / 'native'
sys.path.insert(0, str(NATIVE))
from release_core import ReleaseError
from release_control import parse_request
from release_inspect import database_environment, read_query
from release_schema import parser
from release_schema_core import SchemaEngine
from release_schema_data import Database, RedisCaches
from release_schema_host import SchemaHost, restore_app_tree, tree_digest
from release_host import generation_alive
from inspect_babel import remote_command


class FakeHost:
    old = {'slot': 'green', 'release': 'a' * 12 + '-' + 'b' * 12, 'previous': None}
    new = {'slot': 'blue', 'release': 'c' * 12 + '-' + 'd' * 12}
    def __init__(self, failure=None):
        self.current = copy.deepcopy(self.old); self.record = None; self.events = []
        self.failure = failure; self.failed = False; self.gate = False; self.old_running = True
        self.schema = 'old'; self.data = 'original'; self.owner = 'old'
    def event(self, name):
        self.events.append(name)
        if self.failure == name and not self.failed:
            self.failed = True; raise ReleaseError('injected failure')
    def active(self): return copy.deepcopy(self.current)
    def journal(self): return copy.deepcopy(self.record)
    def save_journal(self, record): self.record = copy.deepcopy(record)
    def schema_preflight(self, old, new, expected_old, database):
        self.event('preflight')
        if old['release'] != expected_old: raise ReleaseError('changed old release')
    def close_gate_and_drain(self): self.event('gate'); self.gate = True
    def assert_gate_closed(self):
        if not self.gate: raise ReleaseError('gate open')
    def stop_schema_apps(self): self.assert_gate_closed(); self.event('stop'); self.old_running = False; self.owner = ''
    def backup_schema_state(self, journal): self.event('backup'); self.saved = self.data
    def prepare(self, new): self.schema = 'new'; self.data = 'test writes'; self.event('start')
    def healthy(self, record, direct): self.event('healthy')
    def verify_migrated_database(self): self.event('database-check')
    def restore_schema_state(self, journal): self.event('restore'); self.schema = 'old'; self.data = self.saved
    def restore_schema_app(self, old): self.event('restore-app'); self.old_running = True; self.owner = 'old'
    def transfer_workers(self, record): self.event('workers'); self.owner = 'new'
    def pause_schema_workers(self): self.owner = ''
    def route(self, record): self.event('route'); self.gate = False
    def restore_committed(self, old): self.current = copy.deepcopy(old)
    def commit_schema_baseline(self, new): self.event('commit'); self.current = {**new, 'previous': None}
    def observe(self, new, generations): self.event('observe')


class EngineTests(unittest.TestCase):
    def stage(self, host): SchemaEngine(host).stage(host.new, host.old['release'], 'example')
    def test_stage_waits_closed_without_starting_workers(self):
        h = FakeHost(); self.stage(h)
        self.assertEqual(h.record['phase'], 'schema_ready'); self.assertTrue(h.gate)
        self.assertEqual(h.owner, ''); self.assertEqual(h.current, h.old)
        SchemaEngine(h).recover()
        self.assertEqual(h.record['phase'], 'schema_ready')
        SchemaEngine(h).activate()
        self.assertEqual(h.record['phase'], 'complete'); self.assertFalse(h.gate)
        self.assertIsNone(h.current['previous'])

    def test_faults_restore_only_after_the_database_may_have_changed(self):
        for failure in ('gate', 'stop', 'backup', 'start', 'healthy', 'database-check'):
            with self.subTest(failure=failure):
                h = FakeHost(failure)
                with self.assertRaises(ReleaseError): self.stage(h)
                self.assertEqual(h.record['phase'], 'rolled_back')
                self.assertEqual(h.schema, 'old'); self.assertEqual(h.data, 'original')
                self.assertTrue(h.old_running); self.assertFalse(h.gate)
                self.assertEqual('restore' in h.events, failure in ('start', 'healthy', 'database-check'))
                if failure == 'gate': self.assertNotIn('stop', h.events)

    def test_preflight_failure_has_no_mutation(self):
        h = FakeHost('preflight')
        with self.assertRaises(ReleaseError): self.stage(h)
        self.assertEqual(h.events, ['preflight']); self.assertIsNone(h.record)

    def test_explicit_abort_restores_backup(self):
        h = FakeHost(); self.stage(h); SchemaEngine(h).abort()
        self.assertEqual(h.record['phase'], 'rolled_back'); self.assertEqual(h.data, 'original')

    def test_restore_failure_keeps_maintenance_closed(self):
        h = FakeHost(); self.stage(h); h.failure = 'restore'
        with self.assertRaises(ReleaseError): SchemaEngine(h).abort()
        self.assertEqual(h.record['phase'], 'recovery_failed'); self.assertTrue(h.gate)

    def test_opening_fault_never_restores_the_database(self):
        for failure in ('commit', 'workers', 'route', 'observe'):
            with self.subTest(failure=failure):
                h = FakeHost(); self.stage(h); h.failure = failure
                with self.assertRaises(ReleaseError): SchemaEngine(h).activate()
                self.assertTrue(h.record['traffic_opened']); self.assertEqual(h.record['phase'], 'recovery_failed')
                self.assertTrue(h.gate); self.assertNotIn('restore', h.events)
                with self.assertRaises(ReleaseError): SchemaEngine(h).abort()

    def test_interrupted_opening_finishes_forward_only(self):
        h = FakeHost(); self.stage(h); h.record.update(phase='schema_opening', traffic_opened=True)
        SchemaEngine(h).recover()
        self.assertEqual(h.record['phase'], 'complete'); self.assertNotIn('restore', h.events)

    def test_interrupted_restore_repeats_safely(self):
        h = FakeHost(); self.stage(h); h.record['phase'] = 'schema_restoring'
        SchemaEngine(h).recover()
        self.assertEqual(h.record['phase'], 'rolled_back')
        events = list(h.events); SchemaEngine(h).recover(); self.assertEqual(events, h.events)

    def test_crash_while_reopening_old_never_replays_the_database_restore(self):
        h = FakeHost(); self.stage(h)
        h.schema = 'old'; h.data = 'new customer write after restore'
        h.record.update(phase='schema_reopening_old', database_restored=True)
        SchemaEngine(h).recover()
        self.assertEqual(h.record['phase'], 'rolled_back')
        self.assertEqual(h.data, 'new customer write after restore')
        self.assertNotIn('restore', h.events)


class BoundaryTests(unittest.TestCase):
    def test_build_metadata_uses_the_exported_go_module_toolchain(self):
        source = ast.parse((NATIVE / 'release_client.py').read_text())
        calls = [node for node in ast.walk(source) if isinstance(node, ast.Call) and node.args and ast.unparse(node.args[0]) == "['go', 'version']"]
        self.assertEqual(len(calls), 1)
        cwd = next(keyword.value for keyword in calls[0].keywords if keyword.arg == 'cwd')
        self.assertEqual(ast.dump(cwd), ast.dump(ast.parse("src / 'backend'", mode='eval').body))

    def test_rehearsal_cannot_name_the_source_or_an_unrelated_database(self):
        database = Database({'PGDATABASE': 'example'})
        with patch.object(database, 'command') as command:
            for name in ('example', 'postgres', 'other_project', '_vsp_restore_bad'):
                with self.assertRaises(ReleaseError): database.rehearsal(Path('unused'), name, {})
            command.assert_not_called()

    def test_remote_inspection_checks_the_exact_bytes_it_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'inspect.py'; marker = Path(directory) / 'ran'
            payload = f"from pathlib import Path;Path({str(marker)!r}).write_text('ok')".encode()
            source.write_bytes(payload)
            args = shlex.split(remote_command(payload, source))
            result = subprocess.run([sys.executable, *args[2:]], capture_output=True)
            self.assertEqual(result.returncode, 0); self.assertEqual(marker.read_text(), 'ok')
            marker.unlink(); source.write_bytes(payload + b'\n# altered')
            result = subprocess.run([sys.executable, *args[2:]], capture_output=True)
            self.assertNotEqual(result.returncode, 0); self.assertFalse(marker.exists())
            target = Path(directory) / 'target.py'; target.write_bytes(payload)
            source.unlink(); source.symlink_to(target)
            result = subprocess.run([sys.executable, *args[2:]], capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0); self.assertFalse(marker.exists())
            source.unlink(); os.mkfifo(source)
            result = subprocess.run([sys.executable, *args[2:]], capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0); self.assertFalse(marker.exists())

    def test_agent_rpc_does_not_authorize_schema_operations(self):
        for op in ('schema-stage', 'schema-rehearse', 'schema-activate', 'schema-abort'):
            with self.assertRaises(ReleaseError): parse_request(json.dumps({'operation': op}))
        with self.assertRaises(SystemExit): parser().parse_args(['stage', 'x', '--from-release', 'y', '--database', 'example'])

    def test_inspection_database_connection_is_read_only_and_secrets_are_not_errors(self):
        values = {'DATABASE_HOST': '127.0.0.1', 'DATABASE_PORT': '5432', 'DATABASE_USER': 'example', 'DATABASE_DBNAME': 'example', 'DATABASE_PASSWORD': 'DO_NOT_PRINT'}
        env = database_environment(values)
        with patch('release_inspect.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 1, '', 'DO_NOT_PRINT')
            with self.assertRaises(ValueError) as error: read_query(env, 'SELECT 1;')
            self.assertNotIn('DO_NOT_PRINT', str(error.exception))
            self.assertIn('default_transaction_read_only=on', run.call_args.kwargs['env']['PGOPTIONS'])
        with self.assertRaises(ValueError): database_environment({**values, 'DATABASE_HOST': 'elsewhere.example'})

    def test_reviewed_policy_matches_exact_source_and_runner_checksums(self):
        policy = json.loads((NATIVE / 'schema_policy.json').read_text())
        for name, spec in policy['migrations'].items():
            raw = (NATIVE.parents[1] / 'backend/migrations' / name).read_bytes()
            self.assertEqual(spec['file_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(spec['ledger_sha256'], hashlib.sha256(raw.decode().strip().encode()).hexdigest())
        h = object.__new__(SchemaHost); h.policy = policy
        old = {'version': '0.2.1', 'migrations': {'old.sql': 'a'}}
        new = {'version': '0.2.4', 'migrations': {'old.sql': 'a', **{k: v['file_sha256'] for k, v in policy['migrations'].items()}}}
        h.check_migrations(old, new)
        for changed in ({**new['migrations'], 'old.sql': 'b'}, {**new['migrations'], 'unreviewed.sql': 'c'}):
            with self.assertRaises(ReleaseError): h.check_migrations(old, {**new, 'migrations': changed})

    def test_app_restore_does_not_follow_symlinks_or_erase_failed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); snapshot = root / 'snapshot'; snapshot.mkdir()
            outside = root / 'outside'; outside.write_text('untouched')
            (snapshot / 'link').symlink_to(outside)
            (snapshot / 'data').write_text('old')
            target = root / 'app'; target.mkdir(); (target / 'data').write_text('new')
            before = tree_digest(snapshot)
            restore_app_tree(snapshot, target, root / 'failed-app', os.getuid(), os.getgid())
            self.assertEqual(outside.read_text(), 'untouched'); self.assertTrue((target / 'link').is_symlink())
            self.assertEqual((target / 'data').read_text(), 'old'); self.assertEqual((root / 'failed-app/data').read_text(), 'new')
            self.assertEqual(tree_digest(snapshot), before)


spec = importlib.util.spec_from_file_location('migration_fixture', Path(__file__).with_name('upstream-migration-test.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)


class DatabaseTests(fixture.UpstreamMigrationTests):
    def test_adapter_checkpoint_restores_database_and_application_files_together(self):
        self.platform_fixture()
        self.sql("CREATE TABLE groups(models_list_config JSONB NOT NULL DEFAULT '{}'); CREATE TABLE users(id INT,balance NUMERIC); INSERT INTO users VALUES(1,12.5); CREATE TABLE schema_migrations(filename TEXT PRIMARY KEY,checksum TEXT);")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); app = root / 'app'; app.mkdir(); (app / 'config').write_text('old')
            env = root / 'app.env'; env.write_text('DATABASE_DBNAME=fixture')
            state = root / 'state'; state.mkdir()
            for name in ('active.json', 'workers.json'): (state / name).write_text('{}')
            h = object.__new__(SchemaHost); h.db = Database(self.env); h.backup = root / 'job'
            h.credentials = {'test': 'private'}; h.route_hashes = {}
            h.cfg = {'operator_uid': os.getuid(), 'operator_gid': os.getgid()}
            class Caches:
                restored = False
                def snapshot(self, path): path.write_bytes(b''); return hashlib.sha256(b'').hexdigest()
                def restore(self, path, sha): self.restored = True
            h.caches = Caches()
            real_path = Path
            def paths(value):
                if str(value) == '/etc/vsp-sub2api/production/app.env': return env
                if str(value) == '/etc/vsp-sub2api/model-catalog.json': return root / 'absent-catalog'
                return real_path(value)
            def write(path, value): path.write_text(json.dumps(value)); path.chmod(0o600)
            with patch('release_schema_host.APP_DATA', app), patch('release_schema_host.BACKUPS', root), patch('release_schema_host.STATE', state), patch('release_schema_host.Path', paths), patch('release_schema_host.trusted'), patch('release_schema_host.atomic', side_effect=write), patch('release_schema_host.load', side_effect=lambda p: json.loads(p.read_text())):
                h.private_backup_dir(); h.backup_schema_state({})
                self.sql('UPDATE users SET balance=1;'); (app / 'config').write_text('new')
                h.restore_schema_state({'traffic_opened': False})
            self.assertEqual(self.sql('SELECT balance FROM users;').stdout.strip(), b'12.5')
            self.assertEqual((app / 'config').read_text(), 'old')
            self.assertEqual((h.backup / 'failed-app/config').read_text(), 'new')
            self.assertTrue(h.caches.restored)

    def test_real_pending_job_guard_uses_boolean_json_and_terminal_states(self):
        host = object.__new__(SchemaHost); host.db = Database(self.env)
        host.assert_no_pending_batches()
        self.sql("CREATE TABLE batch_image_jobs(status TEXT); INSERT INTO batch_image_jobs VALUES ('completed'),('failed'),('cancelled'),('output_deleted');")
        host.assert_no_pending_batches()
        self.sql("INSERT INTO batch_image_jobs VALUES ('running');")
        with self.assertRaises(ReleaseError): host.assert_no_pending_batches()

    def test_actual_dump_migrate_restore_and_private_rehearsal(self):
        self.platform_fixture()
        self.sql('''CREATE TABLE groups(models_list_config JSONB NOT NULL DEFAULT '{}');
          INSERT INTO groups VALUES ('{"enabled":true,"models":["example-model"]}');
          CREATE TABLE users(id INT PRIMARY KEY,balance NUMERIC); INSERT INTO users VALUES (1,12.5);
          CREATE TABLE schema_migrations(filename TEXT PRIMARY KEY, checksum TEXT NOT NULL);''')
        database = Database(self.env)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'database.dump'
            binding, tables, counts, ledger = database.identity(), database.tables(), database.counts(), database.ledger()
            self.sql("ALTER DATABASE postgres SET application_name='before-snapshot';")
            checksum = database.dump(path)
            self.sql("ALTER DATABASE postgres SET application_name='live-setting';")
            policy = json.loads((NATIVE / 'schema_policy.json').read_text())
            database.rehearsal(path, '_vsp_restore_' + 'f' * 32, policy['migrations'])
            self.assertIn('application_name=live-setting', database.read("SELECT to_json(setconfig) FROM pg_db_role_setting WHERE setdatabase=(SELECT oid FROM pg_database WHERE datname=current_database()) AND setrole=0;"))
            self.assertEqual(database.counts(), counts)
            for name in policy['migrations']: self.migration(name)
            for name, spec in policy['migrations'].items():
                self.sql(f"INSERT INTO schema_migrations VALUES ('{name}','{spec['ledger_sha256']}');")
            host = object.__new__(SchemaHost); host.db = database; host.policy = policy; host.backup = Path(directory)
            with patch('release_schema_host.load', return_value={'binding': binding, 'ledger': ledger, 'tables': tables}), patch('release_schema_host.digest', return_value='unchanged'):
                host.verify_migrated_database()
            self.sql('UPDATE users SET balance=1;')
            database.restore(path, checksum, binding, tables, counts, ledger)
            self.assertEqual(self.sql('SELECT balance FROM users;').stdout.strip(), b'12.5')
            self.assertEqual(self.sql("SELECT models_list_config->'models'->>0 FROM groups;").stdout.strip(), b'example-model')
            with self.assertRaises(ReleaseError): database.restore(path, 'wrong', binding, tables, counts, ledger)
            self.assertEqual(self.sql('SELECT balance FROM users;').stdout.strip(), b'12.5')


@unittest.skipUnless(shutil.which('redis-server'), 'redis-server required')
class CacheTests(unittest.TestCase):
    def test_real_cache_snapshot_restores_only_reviewed_namespaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
            process = subprocess.Popen(['redis-server', '--bind', '127.0.0.1', '--port', str(port), '--save', '', '--appendonly', 'no', '--dir', directory], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            cache = RedisCaches({'REDIS_HOST': '127.0.0.1', 'REDIS_PORT': '6379', 'REDIS_DB': '0'}); cache.port = port
            try:
                for _ in range(100):
                    try: cache.call('PING'); break
                    except OSError: time.sleep(0.02)
                cache.call('SET', 'sched:epoch:example', '3')
                cache.call('SET', 'billing:balance:1', '12.5', 'PX', 60000)
                cache.call('SET', 'unrelated:service', 'keep')
                cache.call('SET', 'batch_image:queue:inflight:1', 'keep')
                path = root / 'cache.jsonl'; checksum = cache.snapshot(path)
                cache.call('SET', 'sched:epoch:example', '99'); cache.call('SET', 'sched:new', 'new')
                cache.call('SET', 'billing:balance:1', '1'); cache.call('SET', 'unrelated:service', 'new unrelated')
                cache.restore(path, checksum)
                self.assertEqual(cache.call('GET', 'sched:epoch:example'), b'3')
                self.assertEqual(cache.call('GET', 'billing:balance:1'), b'12.5')
                self.assertIsNone(cache.call('GET', 'sched:new'))
                self.assertEqual(cache.call('GET', 'unrelated:service'), b'new unrelated')
                self.assertEqual(cache.call('GET', 'batch_image:queue:inflight:1'), b'keep')
                self.assertGreater(cache.call('PTTL', 'billing:balance:1'), 0)
                with self.assertRaises(ReleaseError): cache.restore(path, 'invalid')
            finally:
                process.terminate(); process.wait(timeout=5)


@unittest.skipUnless(shutil.which('nginx'), 'nginx required')
class GateTests(unittest.TestCase):
    def test_all_api_entrypoints_share_the_503_gate_but_other_sites_do_not(self):
        spec = importlib.util.spec_from_file_location('installer_fixture', NATIVE / 'install-release-control.py')
        installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sockets = []
            try:
                for _ in range(7):
                    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); sockets.append(sock)
                ports = [sock.getsockname()[1] for sock in sockets]
            finally:
                for sock in sockets: sock.close()
            probe, maintenance, old, *entries = ports
            active = root / 'active.conf'; active.write_text(f'server 127.0.0.1:{old};\n')
            config = root / 'nginx.conf'
            servers = ''.join(f'server {{ listen 127.0.0.1:{port}; location / {{ proxy_pass http://sub2api_app; }} }}' for port in entries[:3])
            servers += f'server {{ listen 127.0.0.1:{entries[3]}; return 200 "unrelated"; }}'
            servers += f'server {{ listen 127.0.0.1:{old}; return 200 "old-app"; }}'
            probe_text = installer.PROBE.replace('19820', str(probe)).replace('19823', str(maintenance))
            config.write_text(f'pid {root}/pid; error_log {root}/error.log; events {{}} http {{ access_log off; upstream sub2api_app {{ include {active}; }} {servers} {probe_text} }}')
            args = [shutil.which('nginx'), '-p', str(root), '-c', str(config), '-e', str(root / 'error.log')]
            process = subprocess.Popen([*args, '-g', 'daemon off;'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def response(port):
                try:
                    with opener.open(f'http://127.0.0.1:{port}/health', timeout=1) as result: return result.status, result.headers, result.read()
                except urllib.error.HTTPError as error:
                    with error: return error.code, error.headers, error.read()
            try:
                for _ in range(100):
                    try: response(probe); break
                    except OSError: time.sleep(0.02)
                for port in entries[:3]: self.assertEqual(response(port)[2], b'old-app')
                old_workers = []
                for pid in Path(f'/proc/{process.pid}/task/{process.pid}/children').read_text().split():
                    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
                    old_workers.append([int(pid), fields[19]])
                candidate = root / 'candidate.conf'; candidate.write_text(f'server 127.0.0.1:{maintenance};\n'); os.replace(candidate, active)
                subprocess.run([*args, '-s', 'reload'], check=True, capture_output=True)
                for _ in range(250):
                    if not any(generation_alive(worker) for worker in old_workers) and all(response(port)[0] == 503 for port in [probe, *entries[:3]]): break
                    time.sleep(0.02)
                else: self.fail('old Nginx generation did not drain to the maintenance gate')
                for port in [probe, *entries[:3]]:
                    status, headers, body = response(port)
                    self.assertEqual(status, 503); self.assertEqual(headers['X-VSP-Maintenance'], 'closed')
                    self.assertEqual(json.loads(body)['status'], 'maintenance')
                self.assertEqual(response(entries[3])[2], b'unrelated')
            finally:
                process.terminate(); process.wait(timeout=5)


if __name__ == '__main__': unittest.main(verbosity=2)
