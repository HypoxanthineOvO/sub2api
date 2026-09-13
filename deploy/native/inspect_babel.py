#!/usr/bin/env python3
"""Run the committed read-only preflight on Babel; remote sudo is entered by the user."""
import argparse
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys
import uuid


def remote_command(payload, remote_path):
    checksum = hashlib.sha256(payload).hexdigest()
    # Verify the bytes read into memory, then execute those SAME bytes. Do not
    # re-open a user-writable file after verification in a privileged process.
    code = ("import hashlib,sys,os,stat;from pathlib import Path;"
            f"p=Path({str(remote_path)!r});fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK);"
            f"stat.S_ISREG(os.fstat(fd).st_mode) and os.fstat(fd).st_size=={len(payload)} or sys.exit('Invalid inspection file');"
            f"b=os.fdopen(fd,'rb').read({len(payload) + 1});"
            f"hashlib.sha256(b).hexdigest()=={checksum!r} or sys.exit('Inspection checksum mismatch');"
            "exec(compile(b,str(p),'exec'),{'__name__':'__main__','__file__':str(p)})")
    return shlex.join(['sudo', '/usr/bin/python3', '-I', '-c', code])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='print the exact transport command without connecting')
    args = parser.parse_args()
    if os.geteuid() == 0: parser.error('run without local sudo; remote sudo is requested separately')
    source = Path(__file__).resolve().with_name('release_inspect.py')
    payload = source.read_bytes()
    checksum = hashlib.sha256(payload).hexdigest()
    target = Path('/home/heyx/VSP-Sub2API/bin') / f'release-inspect-{checksum[:16]}-{uuid.uuid4().hex}.py'
    command = remote_command(payload, target)
    if args.dry_run:
        print(f'SHA-256: {checksum}\nDestination: Babel:{target}\n' + command)
        return
    if not sys.stdin.isatty(): parser.error('run in an interactive terminal so you can enter Babel sudo credentials')
    repo = source.parents[2]
    committed = subprocess.check_output(['git', '-C', str(repo), 'show', 'HEAD:deploy/native/release_inspect.py'])
    if payload != committed: parser.error('commit the reviewed inspection script before running it')
    print('Copying one read-only inspection script to Babel. No deployment, migration, installation or service restart.', flush=True)
    try:
        subprocess.run(['scp', '-q', '-o', 'BatchMode=yes', str(source), f'Babel:{target}'], check=True)
        subprocess.run(['ssh', '-t', '-o', 'BatchMode=yes', 'Babel', command], check=True)
    finally:
        subprocess.run(['ssh', '-o', 'BatchMode=yes', 'Babel', shlex.join(['rm', '-f', '--', str(target)])], check=False)


if __name__ == '__main__':
    try: main()
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit('Read-only inspection did not finish; no deployment was attempted.')
