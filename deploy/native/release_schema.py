#!/usr/bin/env python3
"""Administrator-only schema rehearsal/staging/acceptance. Never in Agent sudoers."""
import argparse
import fcntl
import os
from pathlib import Path
import re
import socket
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_core import ID, TERMINAL, ReleaseError
from release_host import CONFIG, STATE, atomic, info, load, run


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='operation', required=True)
    r = sub.add_parser('rehearse'); r.add_argument('--database', required=True)
    s = sub.add_parser('stage'); s.add_argument('release'); s.add_argument('--from-release', required=True)
    s.add_argument('--database', required=True); s.add_argument('--maintenance-window', action='store_true', required=True)
    s.add_argument('--accept-restore', action='store_true', required=True)
    s.add_argument('--accept-model-allowlist', action='store_true', required=True)
    s.add_argument('--accept-cache-prefixes', action='store_true', required=True)
    for op in ('activate', 'abort'):
        c = sub.add_parser(op); c.add_argument('job'); c.add_argument('--maintenance-window', action='store_true', required=True)
        if op == 'abort': c.add_argument('--accept-restore', action='store_true', required=True)
    return p


def main():
    args = parser().parse_args()
    if os.geteuid() != 0: raise ReleaseError('schema maintenance requires explicit administrator execution')
    cfg = load(CONFIG)
    if socket.gethostname() != cfg['hostname']: raise ReleaseError('wrong schema-maintenance host')
    if getattr(args, 'database', None) and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,62}', args.database):
        raise ReleaseError('invalid database identifier')
    if args.operation == 'stage' and (not ID.fullmatch(args.release) or not ID.fullmatch(args.from_release)):
        raise ReleaseError('invalid approved release identity')
    with (STATE / 'request.lock').open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if info('vsp-sub2api-release.service')['ActiveState'] not in {'inactive', 'failed'}:
            raise ReleaseError('release executor is busy')
        current = load(STATE / 'request.json') if (STATE / 'request.json').exists() else None
        if args.operation in ('activate', 'abort'):
            if not re.fullmatch(r'[a-f0-9]{32}', args.job) or not current or current['job'] != args.job:
                raise ReleaseError('not the current schema job')
            journal = load(STATE / 'jobs' / (args.job + '.json'))
            if not journal.get('schema_maintenance') or journal['phase'] != 'schema_ready' or journal.get('traffic_opened'):
                raise ReleaseError('schema job is not awaiting closed-gate review')
            request = {**current, 'operation': 'schema-' + args.operation}
        else:
            if current:
                phase = load(STATE / 'jobs' / (current['job'] + '.json'))['phase']
                if phase not in TERMINAL or phase == 'recovery_failed': raise ReleaseError('unresolved prior release')
            job = uuid.uuid4().hex
            request = {'job': job, 'operation': 'schema-' + args.operation, 'database': args.database}
            if args.operation == 'stage': request.update(release=args.release, expected_old=args.from_release)
            atomic(STATE / 'jobs' / (job + '.json'), {'phase': 'queued', 'job': job, 'schema_rehearsal': args.operation == 'rehearse'})
        atomic(STATE / 'request.json', request)
        try: run('systemctl', 'start', '--no-block', 'vsp-sub2api-release.service')
        except Exception:
            if args.operation not in ('activate', 'abort'):
                atomic(STATE / 'jobs' / (request['job'] + '.json'), {'phase': 'rejected', 'job': request['job'], 'error': 'executor_start_failed'})
            raise
        print(f"Queued {request['operation']}: {request['job']}. Use vsp-release status; queued is not success.")


if __name__ == '__main__':
    try: main()
    except Exception as error: raise SystemExit(str(error) if isinstance(error, ReleaseError) else f'schema entry failed ({type(error).__name__}); details withheld')
