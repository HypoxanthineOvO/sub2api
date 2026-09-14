#!/usr/bin/env python3
"""Fixed root RPC for the one configured application database, never a shell."""
import fcntl
import json
import os
from pathlib import Path
import select
import socket
import sys
import time

sys.dont_write_bytecode = True

LIB = Path('/usr/local/libexec/vsp-sub2api-db-maint')
STATE = Path('/var/lib/vsp-sub2api-db-maint')
CONFIG = STATE / 'config.json'
APP_STATE = Path('/var/lib/vsp-sub2api-release')


def check_owned(path):
    for p in (path, *path.parents):
        st = p.lstat()
        if p.is_symlink() or st.st_uid != 0 or st.st_mode & 0o022:
            raise RuntimeError('untrusted maintenance path')


def receive():
    body = b''; deadline = time.monotonic() + 5
    while b'\n' not in body and len(body) <= 16384:
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([sys.stdin], [], [], left)[0]: raise RuntimeError('request input timed out')
        block = os.read(sys.stdin.fileno(), 16385 - len(body))
        if not block: break
        body += block
    if len(body) > 16384: raise RuntimeError('request too large')
    return body


def main():
    if os.geteuid() != 0 or len(sys.argv) != 1 or socket.gethostname() != 'iZuf668tiyo0blc17ihbtyZ':
        raise RuntimeError('fixed Babel administrator entry required')
    check_owned(LIB); check_owned(CONFIG)
    sys.path.insert(0, str(LIB))
    from release_core import decode, canonical, TERMINAL
    from release_host import atomic, load, info, unit
    from release_inspect import runtime_environment
    from release_schema_data import Database, RedisCaches
    from operations import Operations, perform, validate, MaintenanceError
    cfg = load(CONFIG)
    if os.environ.get('SUDO_USER') != cfg['operator'] or os.environ.get('SUDO_UID') != str(cfg['operator_uid']):
        raise MaintenanceError('only the configured SSH operator may invoke this entry')
    request = validate(decode(receive()))
    def read_record(identity):
        path = STATE / 'audit' / (identity + '.json')
        return load(path) if path.exists() else None
    def save_record(identity, record):
        if len(canonical(record)) > 1024 * 1024: raise MaintenanceError('audit result exceeds size limit')
        atomic(STATE / 'audit' / (identity + '.json'), record)
    check_owned(APP_STATE / 'request.lock'); check_owned(STATE / 'operation.lock')
    with (APP_STATE / 'request.lock').open('r+') as release_lock, (STATE / 'operation.lock').open('r+') as lock:
        fcntl.flock(release_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if info('vsp-sub2api-release.service')['ActiveState'] not in {'inactive', 'failed'}:
            raise MaintenanceError('release or recovery is active; retry after it finishes')
        if (APP_STATE / 'request.json').exists():
            previous = load(APP_STATE / 'request.json')
            phase = load(APP_STATE / 'jobs' / (previous['job'] + '.json'))['phase']
            if phase not in TERMINAL or phase == 'recovery_failed': raise MaintenanceError('unresolved release; maintenance is blocked')
        ops = None
        if request['operation'] != 'audit':
            active = load(APP_STATE / 'active.json')
            values = runtime_environment(info(unit(active['slot']))['MainPID'])
            database = Database.maintenance(values)
            if database.identity() != cfg['binding']: raise MaintenanceError('database binding changed; refusing operation')
            ops = Operations(database, RedisCaches(values))
        result = perform(request, ops, read_record, save_record)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try: main()
    except Exception as error:
        # Never print database diagnostics, environment values or arbitrary tracebacks.
        safe = str(error) if type(error).__name__ in {'MaintenanceError', 'GuardRejected'} else type(error).__name__
        print(json.dumps({'error': safe, 'status': 'not_completed'}, ensure_ascii=False))
        raise SystemExit(1)
