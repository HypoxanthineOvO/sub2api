"""Babel's fixed maintenance adapter. Not reachable through the Agent RPC."""
import hashlib
import os
from pathlib import Path
import shutil
import stat
import re
import time
import urllib.error
import urllib.request

from release_core import ReleaseError, canonical, digest
from release_host import Host, STATE, ROOT, ACTIVE_LINK, SLOT_ENV, PORTS, atomic, info, load, run, trusted, unit, nginx_workers, generation_alive, has_connections
from release_inspect import runtime_environment
from release_schema_data import Database, RedisCaches

BACKUPS = Path('/var/backups/vsp-sub2api-schema')
POLICY = Path('/usr/local/libexec/vsp-sub2api-release/schema_policy.json')
APP_DATA = Path('/var/lib/vsp-sub2api/production/app')
GATE_LINK = Path('/etc/nginx/sub2api-upstreams/maintenance.conf')
GATE_PORT = 19823


def api_route_hashes():
    hashes = {}
    for name, count in (('api.vsplab.cn', 1), ('api.vsplab.tech', 2)):
        path = (Path('/etc/nginx/sites-enabled') / name).resolve()
        trusted(path)
        text = re.sub(r'#[^\n]*', '', path.read_text())
        targets = re.findall(r'\bproxy_pass\s+([^;]+);', text)
        if len(targets) != count or any(target.strip() != 'http://sub2api_app' for target in targets):
            raise ReleaseError('API routing no longer matches the reviewed shared upstream')
        if re.search(r'\b(include|fastcgi_pass|uwsgi_pass|grpc_pass|scgi_pass)\s', text):
            raise ReleaseError('additional API routing configuration requires review')
        hashes[str(path)] = digest(path)
    upstream = Path('/etc/nginx/conf.d/sub2api-upstream.conf')
    trusted(upstream)
    text = re.sub(r'#[^\n]*', '', upstream.read_text())
    if re.findall(r'\binclude\s+([^;]+);', text) != [str(ACTIVE_LINK)] or re.search(r'\bserver\s', text):
        raise ReleaseError('unexpected shared upstream configuration')
    hashes[str(upstream)] = digest(upstream)
    trusted(GATE_LINK)
    if GATE_LINK.read_text().strip() != 'server 127.0.0.1:19823;':
        raise ReleaseError('maintenance upstream was changed')
    return hashes


def tree_digest(root):
    result = hashlib.sha256()
    for path in [root, *sorted(root.rglob('*'))]:
        st = path.lstat(); name = str(path.relative_to(root))
        if path.is_symlink(): value = ['link', os.readlink(path)]
        elif stat.S_ISDIR(st.st_mode): value = ['directory']
        elif stat.S_ISREG(st.st_mode): value = ['file', digest(path)]
        else: raise ReleaseError('unsupported special file in application state')
        result.update(canonical([name, stat.S_IMODE(st.st_mode), value]))
    return result.hexdigest()


def restore_app_tree(snapshot, target, archive, uid, gid):
    # Assemble privately, chown without following symlinks, then rename into place.
    # Never extract an archive as root through an existing user-writable tree.
    if target.is_symlink(): raise ReleaseError('application data path became a symlink')
    staging = archive.parent / 'restored-app'
    if staging.exists(): shutil.rmtree(staging)
    shutil.copytree(snapshot, staging, symlinks=True)
    for path in [staging, *staging.rglob('*')]:
        os.chown(path, uid, gid, follow_symlinks=False)
        if not path.is_symlink(): path.chmod(stat.S_IMODE(path.stat().st_mode) & 0o777)
    if target.exists():
        # Keep a failed attempt instead of silently deleting post-backup files.
        previous = archive if not archive.exists() else archive.with_name(archive.name + '-' + str(time.time_ns()))
        os.rename(target, previous)
    os.rename(staging, target)


class SchemaHost(Host):
    def __init__(self, job, *, accept_unrehearsed=False):
        super().__init__(job)
        self.accept_unrehearsed = accept_unrehearsed is True
        self.policy = load(POLICY)
        names = {'235_group_model_allowlist.sql', '236_group_model_allowlist_repair.sql', '237_add_minimax_platform.sql'}
        if self.policy.get('format') != 1 or set(self.policy.get('migrations', {})) != names:
            raise ReleaseError('invalid reviewed migration policy')
        for spec in self.policy['migrations'].values():
            if hashlib.sha256(spec['sql'].encode()).hexdigest() != spec['file_sha256'] or hashlib.sha256(spec['sql'].strip().encode()).hexdigest() != spec['ledger_sha256']:
                raise ReleaseError('reviewed SQL checksum mismatch')
        self.backup = BACKUPS / job
        current = self.journal()
        if current and current.get('protected'): self.protected = current['protected']
        if (self.backup / 'credentials.json').exists():
            self.credentials = load(self.backup / 'credentials.json')
        else:
            active = self.active()
            self.credentials = runtime_environment(info(unit(active['slot']))['MainPID'])
        self.db = Database.maintenance(self.credentials)
        self.caches = RedisCaches(self.credentials)
        self.route_hashes = load(self.backup / 'routes.json') if (self.backup / 'routes.json').exists() else None

    def save_journal(self, journal):
        super().save_journal({**journal, 'protected': self.protected, 'accept_unrehearsed': self.accept_unrehearsed})

    def check_migrations(self, previous, candidate):
        if previous['version'] != '0.2.1' or candidate['version'] != '0.2.4':
            raise ReleaseError('only the reviewed 0.2.1 to 0.2.4 upgrade is supported')
        expected = {name: spec['file_sha256'] for name, spec in self.policy['migrations'].items()}
        old, new = previous['migrations'], candidate['migrations']
        if set(new) - set(old) != set(expected) or any(new.get(k) != v for k, v in old.items()):
            raise ReleaseError('unexpected migration additions, removals or historical edits')
        if any(new.get(k) != v for k, v in expected.items()):
            raise ReleaseError('candidate migrations do not match the reviewed SQL')

    def binding(self):
        result = self.db.identity()
        if result['system_identifier'] is None:
            raise ReleaseError('verified database administrator privileges are required')
        return result

    def schema_preflight(self, old, new, expected_old, database):
        if old['release'] != expected_old: raise ReleaseError('active release changed since approval')
        self.preflight(old, new)
        if info(unit(new['slot']))['ActiveState'] != 'inactive':
            raise ReleaseError('schema staging requires an already stopped standby')
        if self.binding()['database'] != database: raise ReleaseError('database name differs from explicit approval')
        if any(name in self.db.ledger() for name in self.policy['migrations']):
            raise ReleaseError('target migrations already recorded; this is not a fresh upgrade')
        self.check_restore_rehearsal()
        for path in (APP_DATA.parent, BACKUPS, GATE_LINK): trusted(path)
        if APP_DATA.is_symlink() or APP_DATA.stat().st_uid != self.cfg['operator_uid']:
            raise ReleaseError('unexpected application data owner/path')
        if APP_DATA.stat().st_dev != BACKUPS.stat().st_dev:
            raise ReleaseError('this bounded file restore requires app state and backups on one filesystem')
        database_bytes = self.db.read('SELECT pg_database_size(current_database());')
        app_bytes = sum(p.lstat().st_size for p in APP_DATA.rglob('*') if p.is_file() and not p.is_symlink())
        if shutil.disk_usage(BACKUPS).free < 3 * database_bytes + 3 * app_bytes + self.cfg['min_disk_free']:
            raise ReleaseError('insufficient disk reserve for backups, rehearsal and restore')
        self.caches.call('PING')
        self.assert_no_pending_batches()
        self.route_hashes = api_route_hashes()
        # Persist credentials privately BEFORE any App can be stopped, including
        # interrupted backup attempts which have not touched the database yet.
        self.private_backup_dir()
        atomic(self.backup / 'routes.json', self.route_hashes)

    def check_restore_rehearsal(self):
        if self.accept_unrehearsed: return
        proof = load(STATE / 'schema-rehearsal.json')
        if proof['binding'] != self.binding() or proof['ledger'] != self.db.ledger() or proof.get('policy_sha') != hashlib.sha256(canonical(self.policy)).hexdigest() or time.time() - proof['verified_at'] > 86400:
            raise ReleaseError('a matching restore rehearsal from the last 24 hours is required')

    def assert_no_pending_batches(self):
        present = self.db.read("SELECT to_json(to_regclass('public.batch_image_jobs') IS NOT NULL);")
        if present:
            count = self.db.read("SELECT count(*) FROM batch_image_jobs WHERE status NOT IN ('completed','failed','cancelled','output_deleted');")
            if count: raise ReleaseError('batch image jobs are still pending; finish them before schema maintenance')

    def assert_gate_closed(self):
        current_routes = api_route_hashes()
        if self.route_hashes is not None and current_routes != self.route_hashes:
            raise ReleaseError('API routing changed during schema maintenance')
        if ACTIVE_LINK.resolve() != GATE_LINK.resolve(): raise ReleaseError('maintenance link is not active')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            opener.open(urllib.request.Request('http://127.0.0.1:19820/health', headers={'Connection': 'close'}), timeout=5)
        except urllib.error.HTTPError as error:
            matched = error.code == 503 and error.headers.get('X-VSP-Maintenance') == 'closed' and error.headers.get('X-VSP-Upstream') == f'127.0.0.1:{GATE_PORT}'
            error.close()
            if matched: return
        raise ReleaseError('loaded Nginx maintenance gate could not be verified')

    def close_gate_and_drain(self):
        self.verify_protected()
        workers = nginx_workers()
        reload_needed = False
        if ACTIVE_LINK.resolve() != GATE_LINK.resolve():
            temporary = ACTIVE_LINK.with_name('active.conf.schema-next')
            if temporary.exists() or temporary.is_symlink(): temporary.unlink()
            temporary.symlink_to(GATE_LINK); os.replace(temporary, ACTIVE_LINK)
            reload_needed = True
        try: self.assert_gate_closed()
        except Exception: reload_needed = True
        if reload_needed:
            run('nginx', '-t'); run('nginx', '-s', 'reload')
        else:
            # Include only already-shutting-down generations; current gate workers
            # must stay alive to serve maintenance responses.
            draining = []
            for worker in workers:
                try:
                    if b'shutting down' in Path(f'/proc/{worker[0]}/cmdline').read_bytes(): draining.append(worker)
                except FileNotFoundError: pass
            workers = draining
        deadline = time.monotonic() + self.cfg['drain_seconds']
        while True:
            try: self.assert_gate_closed(); gate_ok = True
            except Exception: gate_ok = False
            if gate_ok and not any(generation_alive(worker) for worker in workers) and not any(has_connections(port) for port in PORTS.values()): return
            if time.monotonic() >= deadline: raise ReleaseError('maintenance ingress did not drain; no App was forced down')
            time.sleep(0.5)

    def stop_schema_apps(self):
        self.assert_gate_closed()
        self.set_worker_owner('')
        for slot in PORTS:
            if has_connections(PORTS[slot]): raise ReleaseError('application still has accepted connections')
            run('systemctl', 'stop', unit(slot), timeout=100)
            if info(unit(slot))['MainPID'] != '0': raise ReleaseError('application did not stop')
        self.verify_protected()
        self.db.require_idle()

    def private_backup_dir(self):
        trusted(BACKUPS)
        self.backup.mkdir(mode=0o700, exist_ok=False)
        atomic(self.backup / 'credentials.json', self.credentials)
        env = Path('/etc/vsp-sub2api/production/app.env')
        trusted(env)
        shutil.copy2(env, self.backup / 'app.env'); (self.backup / 'app.env').chmod(0o600)

    def backup_schema_state(self, journal):
        self.db.require_idle()
        ledger, tables, counts = self.db.ledger(), self.db.tables(), self.db.counts()
        dump_sha = self.db.dump(self.backup / 'database.dump')
        cache_sha = self.caches.snapshot(self.backup / 'caches.jsonl')
        shutil.copytree(APP_DATA, self.backup / 'app', symlinks=True)
        data_sha = tree_digest(self.backup / 'app')
        if tree_digest(APP_DATA) != data_sha: raise ReleaseError('application files changed during the frozen backup')
        config_files = [STATE / 'active.json', STATE / 'workers.json']
        config_files.extend(Path(path) for path in self.route_hashes)
        if Path('/etc/vsp-sub2api/model-catalog.json').exists(): config_files.append(Path('/etc/vsp-sub2api/model-catalog.json'))
        for path in config_files:
            shutil.copy2(path, self.backup / path.name); (self.backup / path.name).chmod(0o600)
        atomic(self.backup / 'backup.json', {'binding': self.binding(), 'ledger': ledger, 'tables': tables, 'counts': counts,
                                           'dump_sha': dump_sha, 'cache_sha': cache_sha, 'app_sha': data_sha})
        journal['backup'] = str(self.backup)

    def assert_environment_unchanged(self):
        if digest(Path('/etc/vsp-sub2api/production/app.env')) != digest(self.backup / 'app.env'):
            raise ReleaseError('application environment changed during maintenance')

    def verify_migrated_database(self):
        saved = load(self.backup / 'backup.json')
        self.assert_environment_unchanged()
        if self.binding() != saved['binding']: raise ReleaseError('database binding changed')
        expected = {**saved['ledger'], **{name: spec['ledger_sha256'] for name, spec in self.policy['migrations'].items()}}
        if self.db.ledger() != expected or self.db.tables() != saved['tables']:
            raise ReleaseError('unexpected migrated schema/ledger')
        if not self.db.read("SELECT to_json(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='groups' AND column_name='model_allowlist'));"):
            raise ReleaseError('new model allowlist column missing')

    def restore_schema_state(self, journal):
        if journal.get('traffic_opened'): raise ReleaseError('database rollback forbidden after opening')
        self.assert_environment_unchanged()
        saved = load(self.backup / 'backup.json')
        if tree_digest(self.backup / 'app') != saved['app_sha']:
            raise ReleaseError('application file backup checksum mismatch')
        self.db.restore(self.backup / 'database.dump', saved['dump_sha'], saved['binding'], saved['tables'], saved['counts'], saved['ledger'])
        self.caches.restore(self.backup / 'caches.jsonl', saved['cache_sha'])
        restore_app_tree(self.backup / 'app', APP_DATA, self.backup / 'failed-app', self.cfg['operator_uid'], self.cfg['operator_gid'])

    def restore_schema_app(self, old):
        self.assert_environment_unchanged()
        self.write_slot(old)
        run('systemctl', 'start', unit(old['slot']), timeout=100)
        self.wait_healthy(old)
        self.transfer_workers(old)

    def commit_schema_baseline(self, new):
        run('systemctl', 'enable', unit(new['slot']))
        other = 'green' if new['slot'] == 'blue' else 'blue'
        run('systemctl', 'disable', unit(other))
        atomic(STATE / 'active.json', {**new, 'previous': None})

    def pause_schema_workers(self):
        self.set_worker_owner('')

    def rehearse(self, database):
        if self.binding()['database'] != database: raise ReleaseError('database name differs from approval')
        if set(self.policy['migrations']) & set(self.db.ledger()):
            raise ReleaseError('rehearsal requires the pre-upgrade migration ledger')
        database_bytes = self.db.read('SELECT pg_database_size(current_database());')
        if shutil.disk_usage(BACKUPS).free < 3 * database_bytes + self.cfg['min_disk_free']:
            raise ReleaseError('insufficient space for the private database rehearsal')
        self.private_backup_dir()
        binding, ledger = self.binding(), self.db.ledger()
        self.db.dump(self.backup / 'rehearsal.dump')
        result = self.db.rehearsal(self.backup / 'rehearsal.dump', '_vsp_restore_' + self.job, self.policy['migrations'])
        self.verify_protected()
        if self.binding() != binding or self.db.ledger() != ledger: raise ReleaseError('source schema changed during rehearsal')
        atomic(STATE / 'schema-rehearsal.json', {'binding': binding, 'ledger': ledger, 'policy_sha': hashlib.sha256(canonical(self.policy)).hexdigest(), 'verified_at': time.time(), **result})
        self.save_journal({'phase': 'complete', 'schema_rehearsal': True, **result})

    def recover_rehearsal(self):
        # No production App/gate/DB restore in this path. Only remove our private clone.
        from release_schema_data import identifier
        self.verify_protected()
        name = '_vsp_restore_' + self.job
        self.db.command('psql', '-X', '-w', '-v', 'ON_ERROR_STOP=1', '-c', f'DROP DATABASE IF EXISTS {identifier(name)};')
        self.save_journal({'phase': 'rejected', 'schema_rehearsal': True, 'error': 'rehearsal_interrupted'})
