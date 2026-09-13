#!/usr/bin/env python3
"""Repair only the reviewed edge-probe failure, then resume the approved rollout."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys

ORIGINAL = Path('/var/backups/vsp-sub2api-launch-c2c9e5d1ce3c8b3d/payload')
LIB = Path('/usr/local/libexec/vsp-sub2api-release')
FAILED_JOB = 'dd44aa89607943869ca58dcb7ad9d58b'
OLD_HOST_SHA = 'e6f2ec47782eed054f210ce0e58407d6133a7c8db1f91e6fcf9ffa32a9281dcf'


def main():
    if os.geteuid() != 0 or socket.gethostname() != 'iZuf668tiyo0blc17ihbtyZ':
        raise SystemExit('Babel administrator required')
    # Reuse the frozen launch's validation/wait helpers, not its installer/main.
    sys.path.insert(0, str(ORIGINAL))
    from release_core import ReleaseError, digest, read_package
    from release_host import CONFIG, STATE, atomic, info, load, trusted, Host
    from release_launch import execute, wait_job, publish_catalog
    source = Path(__file__).resolve().parent
    trusted(source); trusted(ORIGINAL); trusted(LIB / 'release_host.py')
    plan = load(ORIGINAL / 'launch.json')
    for name, checksum in plan['files'].items():
        if Path(name).name != name or digest(ORIGINAL / name) != checksum:
            raise ReleaseError('original rollout bundle differs from approval')
    bridge = read_package(ORIGINAL / plan['bridge'])['id']
    candidate = read_package(ORIGINAL / plan['candidate'])['id']
    baseline = read_package(ORIGINAL / plan['baseline'])['id']
    with (STATE / 'request.lock').open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if info('vsp-sub2api-release.service')['ActiveState'] not in {'inactive', 'failed'}:
            raise ReleaseError('release executor is busy')
        current = load(STATE / 'request.json')
        failed = load(STATE / 'jobs' / (FAILED_JOB + '.json'))
        if current['job'] != FAILED_JOB or failed['phase'] != 'rolled_back' or failed.get('error') != 'HTTPError':
            raise ReleaseError('not the reviewed rolled-back transaction')
        active = load(STATE / 'active.json')
        if active != {'slot': 'blue', 'release': baseline, 'previous': None}:
            raise ReleaseError('active baseline changed; do not resume blindly')
        host = Host('resume-check'); host.healthy(active, direct=False)
        if digest(LIB / 'release_host.py') != OLD_HOST_SHA:
            raise ReleaseError('installed controller changed; refusing to overwrite it')
        shutil.copy2(LIB / 'release_host.py', source.parent / 'previous-release_host.py')
        shutil.copy2(CONFIG, source.parent / 'previous-config.json')
        updated = (source / 'release_host.py').read_bytes()
        temporary = LIB / 'release_host.py.resume-next'
        with temporary.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o644); stream.write(updated); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, LIB / 'release_host.py')
        cfg = load(CONFIG); cfg['allow_cloudflare_403_origin_probe'] = True; atomic(CONFIG, cfg)
        print('Controller repaired: only Cloudflare HTTP 403 may use verified origin; public access remains unverified.', flush=True)
    execute(LIB / 'release_initial.py', bridge, '--maintenance-window')
    wait_job('complete')
    execute(LIB / 'release_schema.py', 'stage', candidate, '--from-release', bridge,
            '--database', 'sub2api', '--maintenance-window', '--accept-restore', '--accept-model-allowlist',
            '--accept-cache-prefixes', '--accept-unrehearsed')
    job = wait_job('schema_ready')
    execute(LIB / 'release_schema.py', 'activate', job, '--maintenance-window')
    wait_job('complete')
    publish_catalog(ORIGINAL / 'model-catalog.json', plan['previous_catalog_sha256'], source.parent)
    print(json.dumps({'result': 'COMPLETE', 'active': load(STATE / 'active.json'), 'backup_job': job,
                      'public_access_verified': False, 'remaining': ['Cloudflare public access', 'BaseURL setting', 'DeepSeek custom price cards']}), flush=True)


if __name__ == '__main__':
    try: main()
    except Exception as error:
        print(f'Resume stopped ({type(error).__name__}): {error}', file=sys.stderr)
        raise SystemExit(1)
