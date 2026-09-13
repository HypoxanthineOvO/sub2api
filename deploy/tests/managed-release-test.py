#!/usr/bin/env python3
"""Release package, RPC and durable recovery tests; no production/root access."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

NATIVE = Path(__file__).resolve().parents[1] / 'native'
sys.path.insert(0, str(NATIVE))
import release_core as core
from release_control import parse_request


def payload(root):
    (root / Path(core.PRICING).parent).mkdir(parents=True)
    binary = bytearray(128)
    binary[:6] = b'\x7fELF\x02\x01'
    binary[18:20] = b'>\0'
    (root / 'sub2api').write_bytes(binary)
    (root / core.PRICING).write_text('{}')
    return {'commit': 'a' * 40, 'tree': 'b' * 40, 'version': '0.2.1', 'created': '2026-09-12T00:00:00+00:00', 'platform': 'linux-amd64', 'worker_gate': 1, 'migrations': {'001_initial.sql': 'c' * 64}, 'toolchain': {'go': 'go1.25.1', 'node': 'v20', 'pnpm': '10'}}


class PackageTests(unittest.TestCase):
    def test_roundtrip_and_determinism(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root / 'src'; source.mkdir()
            m = core.create_package(source, root / 'a.tar', payload(source))
            core.create_package(source, root / 'b.tar', {k: v for k, v in m.items() if k not in {'format', 'id', 'files'}})
            self.assertEqual(core.digest(root / 'a.tar'), core.digest(root / 'b.tar'))
            target = root / 'out'; target.mkdir()
            self.assertEqual(core.read_package(root / 'a.tar', target), m)
            self.assertEqual((source / 'sub2api').read_bytes(), (target / 'sub2api').read_bytes())

    def test_reject_duplicate_json(self):
        with self.assertRaises(core.ReleaseError): core.decode(b'{"owner":"a","owner":"b"}')

    def test_reject_manifest_mutations(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            m = core.create_package(root, root / 'a.tar', payload(root))
            for key, value in [('worker_gate', True), ('platform', 'linux-arm64'), ('commit', '../bad'), ('id', '0' * 12 + '-' + '1' * 12), ('migrations', {}), ('files', {}), ('version', 'x\nENV=evil')]:
                modified = copy.deepcopy(m); modified[key] = value
                with self.subTest(key=key), self.assertRaises(core.ReleaseError): core.validate_manifest(modified)

    def test_letter_suffixed_migrations_are_supported(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); meta = payload(root)
            meta['migrations']['006b_guard_users_allowed_groups.sql'] = 'd' * 64
            self.assertEqual(core.create_package(root, root / 'a.tar', meta)['migrations'], meta['migrations'])

    def test_reject_extra_traversal_symlink_duplicate_and_bad_content(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root / 'src'; source.mkdir()
            m = core.create_package(source, root / 'good.tar', payload(source))
            for kind in ['traversal', 'symlink', 'duplicate', 'extra', 'corrupt']:
                bad = root / (kind + '.tar')
                with tarfile.open(bad, 'w', format=tarfile.USTAR_FORMAT) as tar:
                    for name in ['manifest.json', *core.FILES]:
                        data = (source / name).read_bytes()
                        if kind == 'corrupt' and name == 'sub2api': data = data[:-1] + b'x'
                        info = tarfile.TarInfo(name); info.size = len(data)
                        tar.addfile(info, io.BytesIO(data))
                    if kind != 'corrupt':
                        name = {'traversal': '../outside', 'symlink': 'link', 'duplicate': 'sub2api', 'extra': 'root-hook.sh'}[kind]
                        info = tarfile.TarInfo(name)
                        if kind == 'symlink': info.type = tarfile.SYMTYPE; info.linkname = '/etc/passwd'
                        tar.addfile(info, io.BytesIO())
                with self.subTest(kind=kind), self.assertRaises(core.ReleaseError): core.read_package(bad)
            self.assertFalse((root / 'outside').exists())

    def test_reject_wrong_binary_architecture(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); metadata = payload(root)
            (root / 'sub2api').write_bytes(b'#!/bin/sh\necho not-an-application\n')
            with self.assertRaises(core.ReleaseError): core.create_package(root, root / 'bad.tar', metadata)


class RPCTests(unittest.TestCase):
    def test_valid_requests(self):
        for request in [{'operation': 'status'}, {'operation': 'status', 'job': 'a' * 32}, {'operation': 'rollback'}, {'operation': 'deploy', 'release': 'a' * 12 + '-' + 'b' * 12}]:
            self.assertEqual(parse_request(json.dumps(request)), request)

    def test_reject_privilege_expansion(self):
        values = [[], {'operation': 'bootstrap'}, {'operation': 'restart', 'unit': 'nginx'}, {'operation': 'deploy', 'release': '../../etc/passwd'}, {'operation': 'deploy', 'release': 'a' * 12 + '-' + 'b' * 12, 'env': {'LD_PRELOAD': 'evil'}}, {'operation': 'status', 'job': '../other'}, {'operation': 'rollback', 'command': 'sh'}]
        for value in values:
            with self.subTest(value=value), self.assertRaises(core.ReleaseError): parse_request(json.dumps(value))

    def test_unprivileged_controller_cannot_run(self):
        if os.geteuid() == 0: self.skipTest('test is intended for the ordinary developer account')
        r = subprocess.run([sys.executable, '-I', str(NATIVE / 'release_control.py')], input='{"operation":"status"}\n', text=True, capture_output=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('authorized sudo launcher', r.stderr)


class FakeHost:
    old = {'slot': 'blue', 'release': 'a' * 12 + '-' + 'b' * 12}
    new = {'slot': 'green', 'release': 'c' * 12 + '-' + 'd' * 12}

    def __init__(self, failure=None):
        self.current = copy.deepcopy(self.old); self.route_target = copy.deepcopy(self.old)
        self.worker = copy.deepcopy(self.old); self.state = None; self.failure = failure; self.failed = False; self.events = []
        self.old_running = True; self.new_running = False

    def checkpoint(self, name):
        self.events.append(name)
        if name == self.failure and not self.failed:
            self.failed = True
            raise core.ReleaseError('injected ' + name)

    def active(self): return copy.deepcopy(self.current)
    def preflight(self, old, new): self.checkpoint('preflight')
    def save_journal(self, value): self.state = copy.deepcopy(value); self.checkpoint('save-' + value['phase'])
    def journal(self): return copy.deepcopy(self.state)
    def prepare(self, candidate): self.new_running = True; self.checkpoint('prepare')
    def healthy(self, target, direct):
        self.checkpoint(('candidate' if target['slot'] == 'green' else 'old') + ('-direct' if direct else '-ingress'))
    def transfer_workers(self, target): self.worker = copy.deepcopy(target); self.checkpoint('workers-' + target['slot'])
    def route(self, target): self.route_target = copy.deepcopy(target); self.checkpoint('route-' + target['slot']); return [123]
    def observe(self, target, generations): self.checkpoint('observe')
    def commit(self, new, old): self.current = copy.deepcopy(new); self.checkpoint('commit')
    def restore_committed(self, old): self.current = copy.deepcopy(old); self.checkpoint('restore')


class EngineTests(unittest.TestCase):
    def test_requested_rollback_has_no_transient_failure_result(self):
        h = FakeHost(); h.state = {'phase': 'switching', 'explicit_rollback': True, 'old': h.old, 'new': h.new}
        core.Engine(h).recover()
        self.assertEqual(h.state['phase'], 'complete')
        self.assertNotIn('save-rolled_back', h.events)

    def test_success_retains_hot_old_process(self):
        h = FakeHost(); core.Engine(h).execute(h.new)
        self.assertEqual(h.current, h.new); self.assertEqual(h.worker, h.new)
        self.assertEqual(h.state['phase'], 'complete'); self.assertTrue(h.old_running)

    def test_preflight_failure_has_no_mutation(self):
        h = FakeHost('preflight')
        with self.assertRaises(core.ReleaseError): core.Engine(h).execute(h.new)
        self.assertIsNone(h.state); self.assertFalse(h.new_running); self.assertEqual(h.current, h.old)

    def test_fault_matrix_returns_to_old_without_stopping_requests(self):
        for phase in ['prepare', 'candidate-direct', 'workers-green', 'route-green', 'observe', 'candidate-ingress', 'commit']:
            with self.subTest(phase=phase):
                h = FakeHost(phase)
                with self.assertRaises(core.ReleaseError): core.Engine(h).execute(h.new)
                self.assertEqual(h.current, h.old); self.assertEqual(h.route_target, h.old)
                self.assertEqual(h.worker, h.old); self.assertEqual(h.state['phase'], 'rolled_back')
                self.assertTrue(h.old_running); self.assertTrue(h.new_running)
                if phase == 'prepare': self.assertNotIn('route-blue', h.events)

    def test_recovery_failure_is_not_reported_as_success(self):
        h = FakeHost('old-direct'); h.state = {'phase': 'switching', 'old': h.old, 'new': h.new}
        with self.assertRaises(core.ReleaseError): core.Engine(h).recover()
        self.assertEqual(h.state['phase'], 'recovery_failed'); self.assertTrue(h.old_running)

    def test_separate_process_recovers_after_uncatchable_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'crash.py'
            state = Path(directory) / 'state.json'
            script.write_text('''import json,os,sys
sys.path.insert(0,sys.argv[1])
from release_core import Engine
from pathlib import Path
p=Path(sys.argv[2])
class H:
 def active(self):return {"slot":"blue","release":"old"}
 def preflight(self,*a):pass
 def save_journal(self,v):p.write_text(json.dumps(v))
 def journal(self):return json.loads(p.read_text())
 def prepare(self,*a):pass
 def healthy(self,*a,**kw):pass
 def transfer_workers(self,*a):pass
 def route(self,*a):
  if sys.argv[3]=="crash":os._exit(77)
  return []
 def restore_committed(self,*a):pass
h=H()
if sys.argv[3]=="crash":Engine(h).execute({"slot":"green","release":"new"})
else:Engine(h).recover()
''')
            first = subprocess.run([sys.executable, str(script), str(NATIVE), str(state), 'crash'])
            self.assertEqual(first.returncode, 77)
            self.assertEqual(json.loads(state.read_text())['phase'], 'switching')
            second = subprocess.run([sys.executable, str(script), str(NATIVE), str(state), 'recover'])
            self.assertEqual(second.returncode, 0)
            self.assertEqual(json.loads(state.read_text())['phase'], 'rolled_back')

    def test_systemd_service_is_detached_and_has_independent_recovery(self):
        text = (NATIVE.parents[1] / 'ops/systemd/vsp-sub2api-release.service').read_text()
        self.assertIn('Type=oneshot', text)
        self.assertIn('ExecStopPost=', text)
        self.assertIn('MemoryMax=256M', text)
        self.assertNotIn('PartOf=', text)
        self.assertNotIn('Requires=vsp-', text)


class FakeInitialHost(FakeHost):
    def __init__(self, failure=None):
        super().__init__(failure)
        self.legacy_workers = True

    def preflight(self, old, new, allow_legacy=False):
        if not allow_legacy: raise core.ReleaseError('maintenance acknowledgement required')
        self.checkpoint('preflight')

    def stop_initial_old(self, old):
        self.old_running = False; self.legacy_workers = False
        self.checkpoint('old-stopped')

    def transfer_workers(self, target):
        if self.legacy_workers and target == self.new: raise core.ReleaseError('worker overlap')
        super().transfer_workers(target)

    def observe(self, target, generations):
        if generations: raise core.ReleaseError('initial maintenance must not pretend to be a legacy hot handover')
        self.checkpoint('observe')

    def restore_initial_app(self, old, candidate):
        self.new_running = False; self.worker = None
        self.old_running = True; self.legacy_workers = True
        self.checkpoint('old-restored')


class InitialTests(unittest.TestCase):
    def test_initial_start_is_simple_stop_then_start_new_workers(self):
        h = FakeInitialHost(); core.InitialEngine(h).execute(h.new)
        self.assertFalse(h.old_running); self.assertFalse(h.legacy_workers)
        self.assertEqual(h.worker, h.new); self.assertEqual(h.state['phase'], 'complete')
        self.assertLess(h.events.index('old-stopped'), h.events.index('workers-green'))
        self.assertLess(h.events.index('workers-green'), h.events.index('route-green'))

    def test_initial_failure_matrix_restores_old_version(self):
        for point in ['prepare', 'candidate-direct', 'old-stopped', 'workers-green', 'route-green', 'observe', 'commit']:
            with self.subTest(point=point):
                h = FakeInitialHost(point)
                with self.assertRaises(core.ReleaseError): core.InitialEngine(h).execute(h.new)
                self.assertEqual(h.current, h.old); self.assertEqual(h.route_target, h.old)
                self.assertTrue(h.old_running); self.assertTrue(h.legacy_workers)
                self.assertFalse(h.new_running); self.assertEqual(h.state['phase'], 'rolled_back')

    def test_failed_restore_is_not_reported_as_success(self):
        h = FakeInitialHost('old-restored')
        h.state = {'phase': 'initial_switching', 'maintenance': True, 'old': h.old, 'new': h.new}
        with self.assertRaises(core.ReleaseError): core.InitialEngine(h).recover()
        self.assertEqual(h.state['phase'], 'recovery_failed')

    def test_initial_start_is_not_in_public_agent_rpc(self):
        with self.assertRaises(core.ReleaseError): parse_request('{"operation":"initialize","release":"aaaaaaaaaaaa-bbbbbbbbbbbb"}')


class ClientTests(unittest.TestCase):
    def test_cloudflare_origin_fallback_is_explicit_narrow_and_audited(self):
        import urllib.error
        import release_host as module
        candidate = {'slot': 'green', 'release': 'a' * 12 + '-' + 'b' * 12}
        expected = candidate['slot'] + ':' + candidate['release']
        def host(enabled):
            h = object.__new__(module.Host); h.cfg = {'observe_seconds': 0, 'drain_seconds': 1, 'allow_cloudflare_403_origin_probe': enabled}
            h.job = 'a' * 32; h.job_path = Path('/unused')
            return h
        for enabled, code, server in ((False, 403, 'cloudflare'), (True, 500, 'cloudflare'), (True, 403, 'nginx')):
            h = host(enabled)
            error = urllib.error.HTTPError('https://api.vsplab.tech/health', code, 'blocked', {'Server': server}, io.BytesIO())
            with patch.object(h, 'healthy'), patch.object(module, 'request', side_effect=error) as request:
                with self.assertRaises(urllib.error.HTTPError): h.observe(candidate, [])
                self.assertEqual(request.call_count, 1)
        h = host(True)
        error = urllib.error.HTTPError('https://api.vsplab.tech/health', 403, 'blocked', {'Server': 'cloudflare'}, io.BytesIO())
        with patch.object(h, 'healthy'), patch.object(h, 'journal', return_value={'phase': 'observing'}), patch.object(module, 'request', side_effect=[error, {'X-VSP-Deployment': expected}]) as request, patch.object(module, 'atomic') as saved:
            h.observe(candidate, [])
            self.assertEqual(request.call_args.args[0], 'http://127.0.0.1:8081/health')
            h.save_journal({'phase': 'complete'})
            self.assertEqual(saved.call_args.args[1]['public_probe'], {'status': 'cloudflare_403', 'origin_verified': True, 'public_access_verified': False})

    def test_cloudflare_fallback_still_rejects_wrong_origin_identity(self):
        import urllib.error
        import release_host as module
        h = object.__new__(module.Host)
        h.cfg = {'observe_seconds': 0, 'drain_seconds': 1, 'allow_cloudflare_403_origin_probe': True}
        error = urllib.error.HTTPError('https://api.vsplab.tech/health', 403, 'blocked', {'Server': 'cloudflare'}, io.BytesIO())
        with patch.object(h, 'healthy'), patch.object(module, 'request', side_effect=[error, {'X-VSP-Deployment': 'wrong'}]):
            with self.assertRaises(core.ReleaseError): h.observe({'slot': 'green', 'release': 'a'*12+'-'+'b'*12}, [])

    def test_manual_rollback_does_not_restart_a_running_target(self):
        import release_host as module
        h = module.Host.__new__(module.Host); h.rolling_back = True
        target = {'slot': 'blue', 'release': 'a'*12+'-'+'b'*12}
        with patch.object(module, 'info', return_value={'MainPID': '123', 'ActiveState': 'active'}), patch.object(h, 'wait_healthy') as ready, patch.object(module, 'run') as commands:
            h.prepare(target)
            ready.assert_called_once_with(target)
            commands.assert_not_called()

    def test_queued_is_not_reported_as_deployment_success(self):
        import release_client as client
        from types import SimpleNamespace
        responses = iter([
            {'phase': 'queued', 'job': 'a' * 32},
            {'job': {'phase': 'observing'}},
            {'job': {'phase': 'rolled_back'}},
        ])
        def call(*args, **kwargs): return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps(next(responses)))
        with patch.object(client.subprocess, 'run', side_effect=call), patch.object(client.time, 'sleep'), patch('sys.stdout', new=io.StringIO()):
            with self.assertRaises(core.ReleaseError): client.rpc('deploy', 'a' * 12 + '-' + 'b' * 12)

    def test_formal_build_refuses_dirty_checkout_before_building(self):
        import release_client as client
        def command(args, **kwargs):
            if 'rev-parse' in args: return 'a' * 40
            if 'status' in args: return ' M source.go'
            self.fail('a build command ran before the clean-tree check')
        with patch.object(client, 'command', side_effect=command):
            with self.assertRaises(core.ReleaseError): client.build('/tmp/not-a-real-repository', 'HEAD')


if __name__ == '__main__': unittest.main(verbosity=2)
