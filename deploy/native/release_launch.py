#!/usr/bin/env python3
"""One-shot approved Babel rollout from a root-private, hash-verified bundle."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_core import ReleaseError, digest, read_package
from release_host import CONFIG, STATE, Host, info, load, trusted

LIB = Path('/usr/local/libexec/vsp-sub2api-release')


def execute(script, *args):
    subprocess.run(['/usr/bin/python3', '-I', str(script), *args], check=True)


def wait_job(expected):
    job = load(STATE / 'request.json')['job']
    deadline = time.monotonic() + 3700
    last = None
    reported = 0
    while time.monotonic() < deadline:
        state = load(STATE / 'jobs' / (job + '.json'))
        phase = state['phase']
        if phase != last or time.monotonic() - reported >= 30:
            print(f'[{job}] {phase}', flush=True); last = phase; reported = time.monotonic()
        settled = info('vsp-sub2api-release.service')['ActiveState'] in {'inactive', 'failed'}
        if settled and phase != 'queued':
            if phase == expected: return job
            raise ReleaseError(f'rollout stopped at {phase}; inspect vsp-release status before retrying')
        time.sleep(2)
    raise ReleaseError('executor is still running; do not interrupt or repeat the rollout')


def publish_catalog(source, expected_old, archive):
    target = Path('/etc/vsp-sub2api/model-catalog.json')
    trusted(target)
    if digest(target) != expected_old: raise ReleaseError('live model catalog changed since review')
    shutil.copy2(target, archive / 'previous-model-catalog.json')
    temporary = target.with_name('model-catalog.json.launch-next')
    with temporary.open('xb') as stream:
        os.fchmod(stream.fileno(), 0o644)
        stream.write(source.read_bytes()); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, target)
    if digest(target) != digest(source): raise ReleaseError('published catalog checksum mismatch')


def main():
    if os.geteuid() != 0 or socket.gethostname() != 'iZuf668tiyo0blc17ihbtyZ':
        raise ReleaseError('this one-shot rollout requires the Babel administrator')
    source = Path(__file__).resolve().parent
    trusted(source)
    plan = json.loads((source / 'launch.json').read_text())
    for name, checksum in plan['files'].items():
        if Path(name).name != name or digest(source / name) != checksum:
            raise ReleaseError('launch bundle checksum mismatch')
    if CONFIG.exists(): raise ReleaseError('controller already installed; inspect current state rather than repeating installation')
    manifests = {key: read_package(source / plan[key]) for key in ('baseline', 'bridge', 'candidate')}
    baseline, bridge, candidate = (manifests[key] for key in ('baseline', 'bridge', 'candidate'))
    if baseline['worker_gate'] != 0 or bridge['worker_gate'] != 1 or candidate['worker_gate'] != 1:
        raise ReleaseError('unexpected worker capabilities')
    if baseline['migrations'] != bridge['migrations'] or bridge['version'] != '0.2.1' or candidate['version'] != '0.2.4':
        raise ReleaseError('unexpected bridge/candidate lineage')
    print('Installing reviewed controller; existing application remains running.', flush=True)
    execute(source / 'install-release-control.py', '--baseline', str(source / plan['baseline']))
    # Pin the operator-owned directory FD; never follow a mutable user path as
    # root. The controller independently snapshots and validates these packages.
    cfg = load(CONFIG)
    directory = os.open('/home/heyx/VSP-Sub2API/incoming', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.fstat(directory).st_uid != cfg['operator_uid']: raise ReleaseError('unexpected incoming directory owner')
        for key in ('bridge', 'candidate'):
            fd = os.open(manifests[key]['id'] + '.tar', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            with os.fdopen(fd, 'wb') as output, (source / plan[key]).open('rb') as incoming:
                shutil.copyfileobj(incoming, output, 1024 * 1024)
                output.flush(); os.fsync(output.fileno())
                os.fchown(output.fileno(), cfg['operator_uid'], cfg['operator_gid'])
    finally: os.close(directory)
    print('Starting the same-schema bridge; brief downtime is authorized.', flush=True)
    execute(LIB / 'release_initial.py', bridge['id'], '--maintenance-window')
    wait_job('complete')
    # Let the previous Nginx workers exit before the existing schema preflight.
    time.sleep(5)
    print('Backing up production and staging v0.2.4. Restore rehearsal explicitly waived.', flush=True)
    execute(LIB / 'release_schema.py', 'stage', candidate['id'], '--from-release', bridge['id'],
            '--database', 'sub2api', '--maintenance-window', '--accept-restore',
            '--accept-model-allowlist', '--accept-cache-prefixes', '--accept-unrehearsed')
    job = wait_job('schema_ready')
    print('Schema and candidate health verified.', flush=True)
    print('Opening the new service under the approved direct-rollout decision.', flush=True)
    execute(LIB / 'release_schema.py', 'activate', job, '--maintenance-window')
    wait_job('complete')
    host = Host('launch-verify'); host.healthy(host.active(), direct=False)
    print('Application is live; publishing the reviewed model catalog.', flush=True)
    publish_catalog(source / 'model-catalog.json', plan['previous_catalog_sha256'], source.parent)
    print(json.dumps({'result': 'COMPLETE', 'active': host.active(), 'catalog_sha256': digest(source / 'model-catalog.json'),
                      'backup_job': job, 'remaining': ['verify public endpoints and UI', 'official BaseURL setting and custom DeepSeek price cards']}), flush=True)


if __name__ == '__main__':
    try: main()
    except Exception as error:
        print(str(error) if isinstance(error, ReleaseError) else f'Launch stopped ({type(error).__name__}); preserve backups and inspect status.', file=sys.stderr)
        raise SystemExit(1)
