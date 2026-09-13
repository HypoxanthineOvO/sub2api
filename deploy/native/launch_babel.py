#!/usr/bin/env python3
"""User's interactive entry for an already-uploaded, immutable rollout bundle."""
import argparse
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys


def remote_command(archive):
    with archive.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    remote = '/home/heyx/VSP-Sub2API/' + archive.name
    size = archive.stat().st_size
    code = f'''
import hashlib,os,stat,subprocess,tarfile
from pathlib import Path
base=Path('/var/backups')
assert base.is_dir() and not base.is_symlink() and base.stat().st_uid==0 and not base.stat().st_mode & 0o022
root=base / 'vsp-sub2api-launch-{checksum[:16]}'
root.mkdir(mode=0o700)
fd=os.open({remote!r},os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
st=os.fstat(fd)
assert stat.S_ISREG(st.st_mode) and st.st_size=={size}
snapshot=root / 'bundle.tar'
h=hashlib.sha256()
with os.fdopen(fd,'rb') as src,snapshot.open('xb') as dst:
    left={size}
    while left:
        data=src.read(min(left,1024*1024))
        assert data
        dst.write(data);h.update(data);left-=len(data)
    assert not src.read(1)
assert h.hexdigest()=={checksum!r},'Bundle checksum mismatch'
payload=root / 'payload';payload.mkdir(mode=0o700)
with tarfile.open(snapshot) as tar:
    members=tar.getmembers()
    assert len(members)<100 and all(m.isfile() and Path(m.name).name==m.name for m in members)
    assert sum(m.size for m in members)<1024**3
    tar.extractall(payload,filter='data')
subprocess.run(['/usr/bin/python3','-I',str(payload/'release_launch.py')],check=True)
'''
    return shlex.join(['sudo', '/usr/bin/python3', '-I', '-c', code])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0: parser.error('run without local sudo')
    command = remote_command(args.archive.resolve())
    if args.dry_run: print(command); return
    if not sys.stdin.isatty(): parser.error('use an interactive terminal for Babel sudo')
    print('LIVE ROLLOUT: short downtime, private backup, upgrade and opening; enter Babel sudo password when prompted.', flush=True)
    subprocess.run(['ssh', '-t', '-o', 'BatchMode=yes', 'Babel', command], check=True)


if __name__ == '__main__': main()
