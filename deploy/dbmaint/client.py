#!/usr/bin/env python3
"""Passwordless client. User/Agent requests are data, not privileged commands."""
import argparse
import json
import os
import socket
import subprocess
import sys
import uuid

CONTROL = '/usr/local/libexec/vsp-sub2api-db-maint/control'


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--request-id', help='reuse only when retrying the exact same operation')
    sub = p.add_subparsers(dest='operation', required=True)
    sub.add_parser('inspect')
    for op in ('find-users', 'find-accounts'): sub.add_parser(op).add_argument('search')
    for op in ('user', 'account'): sub.add_parser(op).add_argument('id', type=int)
    sub.add_parser('audit').add_argument('id')
    c = sub.add_parser('usage'); c.add_argument('scope', choices=('account', 'user', 'key')); c.add_argument('id', type=int)
    c.add_argument('--since', required=True); c.add_argument('--until', required=True)
    c = sub.add_parser('user-role'); c.add_argument('id', type=int)
    c.add_argument('--expect-name', required=True); c.add_argument('--expect-role', choices=('user', 'admin'), required=True)
    c.add_argument('--role', choices=('user', 'admin'), required=True); c.add_argument('--reason', required=True)
    c = sub.add_parser('key-limits'); c.add_argument('id', type=int); c.add_argument('--user-id', type=int, required=True)
    c.add_argument('--expect-updated-at', required=True); c.add_argument('--reason', required=True)
    for window in ('5h', '1d', '7d'): c.add_argument('--limit-' + window)
    c = sub.add_parser('key-reset-window'); c.add_argument('id', type=int); c.add_argument('--user-id', type=int, required=True)
    c.add_argument('--window', choices=('5h', '1d', '7d'), required=True)
    c.add_argument('--expect-start', required=True, help='ISO time from the inspected DB row, or null')
    c.add_argument('--reason', required=True)
    return p


def main():
    if os.geteuid() == 0: raise SystemExit('do not run this client with sudo')
    request = vars(parser().parse_args())
    request['request_id'] = request['request_id'] or uuid.uuid4().hex
    if request['operation'] == 'key-limits':
        request['limits'] = {f'rate_limit_{w}': request[f'limit_{w}'] for w in ('5h', '1d', '7d') if request[f'limit_{w}'] is not None}
        for w in ('5h', '1d', '7d'): del request[f'limit_{w}']
    if request['operation'] == 'key-reset-window' and request['expect_start'] == 'null': request['expect_start'] = None
    args = ['sudo', '-n', CONTROL]
    if socket.gethostname() != 'iZuf668tiyo0blc17ihbtyZ': args = ['ssh', '-T', '-o', 'BatchMode=yes', 'Babel', *args]
    print('request_id=' + request['request_id'], file=sys.stderr, flush=True)
    result = subprocess.run(args, input=json.dumps(request, ensure_ascii=False) + '\n', text=True, capture_output=True, timeout=90)
    if result.stdout: print(result.stdout.strip())
    if result.returncode:
        if not result.stdout: print('Maintenance RPC unavailable. Check installation/access; no automatic sudo prompt.', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    try: main()
    except (OSError, subprocess.TimeoutExpired): raise SystemExit('Connection interrupted; inspect the printed request_id before retrying a write.')
