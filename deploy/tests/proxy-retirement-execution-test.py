#!/usr/bin/env python3
"""Pure-function and simulated execution tests; never operates on host services."""

import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("retire", ROOT / "deploy/native/retire-proxy-plane.py")
retire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retire)


class RetirementExecutionTests(unittest.TestCase):
    def test_env_preserves_proxy_and_secrets_exactly(self):
        text = 'HTTP_PROXY=http://127.0.0.1:7890\nALL_PROXY=socks5h://127.0.0.1:7892\nPASSWORD="a b#$x"\nSELECTED_NODE_ENABLED=true\nSELECTED_NODE_TOKEN=private\nSELECTED_NODE_PROXY_SLOTS={"4":"Slot A"}\n'
        result = retire.clean_env(text)
        self.assertEqual(result, text.split('SELECTED_NODE_ENABLED=')[0] + 'SELECTED_NODE_ENABLED=false\n')
        self.assertEqual(result, retire.clean_env(result))

    def test_multiline_env_refuses(self):
        with self.assertRaises(RuntimeError):
            retire.clean_env('PASSWORD=abc\\\nmore\n')

    def test_cron_preserves_other_jobs(self):
        text = '# keep this comment\n0 */6 * * * /opt/vsp-sub2api/ops/refresh_xyz.sh\n15 4 * * * bash /opt/vsp-sub2api/ops/revive_daily.sh >> /var/log/vsp-revive.log 2>&1\n0 1 * * * /usr/local/bin/backup-database\n'
        result, removed = retire.clean_cron(text)
        self.assertEqual(result, '# keep this comment\n0 1 * * * /usr/local/bin/backup-database\n')
        self.assertEqual([r['script'] for r in removed], ['refresh_xyz.sh', 'revive_daily.sh'])

    def test_combined_cron_job_refuses(self):
        with self.assertRaises(RuntimeError):
            retire.clean_cron('0 1 * * * /opt/vsp-sub2api/ops/refresh_xyz.sh && /important/other-job\n')

    def test_unknown_old_task_refuses(self):
        with self.assertRaises(RuntimeError):
            retire.clean_cron('0 1 * * * /opt/vsp-sub2api/ops/unknown.py\n')

    def test_selected_node_template_target_dependency_removed(self):
        self.assertNotIn('selected-node', retire.TARGET)
        self.assertNotIn('slot-', retire.TARGET)
        self.assertIn('Requires=vsp-postgresql@production.service vsp-redis@production.service', retire.TARGET)
        self.assertIn('Wants=vsp-mihomo-production@general.service', retire.TARGET)

    def test_protected_services_never_in_babel_stop_set(self):
        self.assertFalse(set(retire.BABEL_RETIRE) & set(retire.PROTECTED))
        self.assertEqual(len(retire.BABEL_RETIRE), 9)

    def test_slot_connections_block_retirement_but_17906_does_not(self):
        with patch.object(retire, 'run', return_value='0 0 127.0.0.1:17907 127.0.0.1:40000'):
            with self.assertRaises(RuntimeError):
                retire.assert_no_slot_connections()
        with patch.object(retire, 'run', return_value='0 0 127.0.0.1:17906 127.0.0.1:40000'):
            retire.assert_no_slot_connections()

    def test_archive_edit_preserves_mode_and_original(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            source = root / 'app.env'
            source.write_text('original-secret\n')
            source.chmod(0o600)
            archive = retire.Archive.__new__(retire.Archive)
            archive.path = root / 'archive'
            archive.path.mkdir()
            archive.events = []
            archive.edit(source, 'new\n')
            self.assertEqual(source.read_text(), 'new\n')
            self.assertEqual(source.stat().st_mode & 0o777, 0o600)
            self.assertEqual(archive.destination(source).read_text(), 'original-secret\n')

    def test_archive_symlink_never_moves_its_target(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            target = root / 'keep'
            target.write_text('protected')
            link = root / 'old-link'
            link.symlink_to(target)
            archive = retire.Archive.__new__(retire.Archive)
            archive.path = root / 'archive'
            archive.path.mkdir()
            archive.events = []
            archive.remove(link)
            self.assertFalse(link.is_symlink())
            self.assertEqual(target.read_text(), 'protected')
            self.assertTrue(archive.destination(link).is_symlink())

    def test_genesis_keeps_database_diagnostic_libexec(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            libexec = root / 'usr/local/libexec/vsp-sub2api'
            libexec.mkdir(parents=True)
            for name in ['agent-db-diagnose.sh', 'deploy-app-release.sh', 'deploy-proxy-allocator.sh', 'install.sh', 'switch-app-slot.sh']:
                (libexec / name).write_text('fixture')
            real_path = Path
            def mapped_path(value):
                return root / real_path(value).relative_to('/')
            with patch.object(retire, 'Path', mapped_path), patch.object(retire, 'matching_links', return_value=[]):
                paths = retire.planned_paths('genesis')
            self.assertNotIn(libexec, paths)
            self.assertNotIn(libexec / 'agent-db-diagnose.sh', paths)
            self.assertIn(libexec / 'deploy-proxy-allocator.sh', paths)

    def simulate(self, *, execute=True, external_dependency=False, connections=False, stop_failure=False):
        events = []
        states = {u: 'active' for u in retire.BABEL_RETIRE}
        state = {'detached': False}
        cron = '0 */6 * * * /opt/vsp-sub2api/ops/refresh_xyz.sh\n'
        current_cron = [cron]
        real_path = Path
        with tempfile.TemporaryDirectory() as directory:
            root = real_path(directory)

            def path(value):
                value = real_path(value)
                return root / value.relative_to('/') if value.is_absolute() else value

            config = path('/etc/vsp-sub2api/production')
            (config / 'mihomo/general').mkdir(parents=True)
            (config / 'mihomo/general/config.yaml').write_text('proxies: []\n')
            (config / 'app.env').write_text('SELECTED_NODE_ENABLED=true\n')

            def run(*args, **kwargs):
                events.append(('command', args))
                if args[:2] == ('crontab', '-l'):
                    return current_cron[0]
                if args[:3] == ('crontab', '-u', 'root'):
                    current_cron[0] = kwargs['input']
                if args[:2] == ('systemctl', 'stop'):
                    if stop_failure:
                        raise RuntimeError('simulated stop failure')
                    states[args[2]] = 'inactive'
                return ''

            def properties(unit):
                active = states.get(unit, 'active')
                dependency = 'unrelated.service' if external_dependency and unit in retire.BABEL_RETIRE else ''
                return {'ActiveState': active, 'MainPID': '1' if active == 'active' and not unit.endswith('.target') else '0', 'RequiredBy': dependency}

            class Archive:
                def __init__(self, host):
                    self.path = root / 'archive'
                    self.path.mkdir()
                    events.append(('archive-created', host))

                def edit(self, target, content):
                    events.append(('edit', str(target)))
                    if target.name == 'vsp-sub2api-production.target':
                        state['detached'] = True

                def remove(self, target):
                    events.append(('remove', str(target)))

                def record(self, action, target):
                    events.append((action, str(target)))

            def no_connections():
                if connections:
                    raise RuntimeError('simulated live proxy connection')

            with contextlib.ExitStack() as stack:
                for name, replacement in {
                    'Path': path, 'Archive': Archive, 'run': run, 'properties': properties,
                    'protected_processes': lambda host: {'keep': '42'},
                    'database_binding_check': lambda: events.append(('db-readonly', None)),
                    'assert_no_running_maintenance': lambda: None,
                    'assert_no_slot_connections': no_connections,
                    'planned_paths': lambda host: [root / 'retired-data'],
                    'matching_links': lambda units: [root / 'old-link'],
                }.items():
                    stack.enter_context(patch.object(retire, name, replacement))
                stack.enter_context(patch.object(retire.time, 'sleep', lambda _: None))
                stack.enter_context(patch.dict('sys.modules', {'yaml': SimpleNamespace(safe_load=lambda _: {})}))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                try:
                    retire.execute(SimpleNamespace(host='babel', execute=execute))
                except RuntimeError as error:
                    return events, str(error)
        return events, None

    def test_plan_never_changes_state(self):
        events, error = self.simulate(execute=False)
        self.assertIsNone(error)
        self.assertFalse(any(event[0] in {'archive-created', 'edit', 'remove'} for event in events))
        self.assertFalse(any(e == ('command', ('systemctl', 'stop', u)) for e in events for u in retire.BABEL_RETIRE))

    def test_execution_detaches_then_stops_then_archives(self):
        events, error = self.simulate()
        self.assertIsNone(error)
        first_stop = next(i for i, e in enumerate(events) if e[0] == 'command' and e[1][:2] == ('systemctl', 'stop'))
        target_edit = next(i for i, e in enumerate(events) if e[0] == 'edit' and e[1].endswith('vsp-sub2api-production.target'))
        reload = events.index(('command', ('systemctl', 'daemon-reload')))
        self.assertLess(target_edit, reload)
        self.assertLess(reload, first_stop)
        stopped = [e[1][2] for e in events if e[0] == 'command' and e[1][:2] == ('systemctl', 'stop')]
        self.assertEqual(stopped, list(retire.BABEL_RETIRE))
        self.assertFalse(set(stopped) & set(retire.PROTECTED))

    def test_external_dependency_aborts_before_any_stop(self):
        events, error = self.simulate(external_dependency=True)
        self.assertIn('external services', error)
        self.assertFalse(any(e[0] == 'command' and e[1][:2] == ('systemctl', 'stop') for e in events))
        self.assertIn(('incomplete', 'babel'), events)

    def test_live_slot_connection_leaves_slots_running(self):
        events, error = self.simulate(connections=True)
        self.assertIn('live proxy connection', error)
        stopped = [e[1][2] for e in events if e[0] == 'command' and e[1][:2] == ('systemctl', 'stop')]
        self.assertEqual(stopped, list(retire.SIDECARS))
        self.assertFalse(any(e[0] == 'remove' and e[1].endswith('retired-data') for e in events))

    def test_stop_failure_does_not_archive_running_service_data(self):
        events, error = self.simulate(stop_failure=True)
        self.assertIn('stop failure', error)
        self.assertFalse(any(e[0] == 'remove' and e[1].endswith('retired-data') for e in events))
        self.assertIn(('incomplete', 'babel'), events)


if __name__ == '__main__':
    unittest.main(verbosity=2)
