#!/usr/bin/env python3
"""Prepare/upload reviewed code, then ask for sudo once in the user's terminal."""
import argparse
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import uuid

FILES = ('operations.py', 'control.py', 'client.py', 'install.py')


def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def remote_command(archive):
    checksum = sha(archive); size = archive.stat().st_size
    if not 0 < size < 512 * 1024: raise ValueError('unexpected installer size')
    target = '/home/heyx/VSP-Sub2API/' + archive.name
    code = f'''
import hashlib,os,stat,subprocess,tarfile
from pathlib import Path
base=Path('/var/backups')
assert not base.is_symlink() and base.stat().st_uid==0 and not base.stat().st_mode & 0o022
root=base/'vsp-sub2api-db-install-{checksum[:16]}'
root.mkdir(mode=0o700)
fd=os.open({target!r},os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
st=os.fstat(fd)
assert stat.S_ISREG(st.st_mode) and st.st_size=={size}
with os.fdopen(fd,'rb') as stream: data=stream.read({size+1})
assert len(data)=={size} and hashlib.sha256(data).hexdigest()=={checksum!r}
snapshot=root/'installer.tar.gz';snapshot.write_bytes(data)
payload=root/'payload';payload.mkdir(mode=0o700)
with tarfile.open(snapshot) as tar:
    members=tar.getmembers()
    assert len(members)==4 and set(m.name for m in members)=={set(FILES)!r}
    assert all(m.isfile() and m.size<256*1024 for m in members)
    tar.extractall(payload,filter='data')
subprocess.run(['/usr/bin/python3','-I',str(payload/'install.py')],check=True)
'''
    return shlex.join(['sudo', '/usr/bin/python3', '-I', '-c', code])


def prepare():
    source = Path(__file__).resolve().parent; repo = source.parents[1]
    commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    for name in FILES:
        committed = subprocess.check_output(['git', '-C', str(repo), 'show', f'HEAD:deploy/dbmaint/{name}'])
        if committed != (source / name).read_bytes(): raise ValueError('commit the reviewed maintenance sources before packaging')
    target = repo / 'dist/dbmaint' / f'vsp-db-maint-{commit[:12]}.tar.gz'
    target.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(target, 'x:gz') as tar:
        for name in FILES:
            p = source / name; info = tarfile.TarInfo(name); info.mode = 0o644; info.size = p.stat().st_size
            with p.open('rb') as stream: tar.addfile(info, stream)
    checksum = sha(target)
    remote = '/home/heyx/VSP-Sub2API/' + target.name; part = remote + '.part-' + uuid.uuid4().hex
    subprocess.run(['scp', '-q', '-o', 'BatchMode=yes', str(target), 'Babel:' + part], check=True)
    code = f"from pathlib import Path;import hashlib,os;p=Path({part!r});assert hashlib.file_digest(p.open('rb'),'sha256').hexdigest()=={checksum!r};os.link(p,{remote!r});p.unlink();print('Uploaded and verified installer')"
    subprocess.run(['ssh', '-T', '-o', 'BatchMode=yes', 'Babel', shlex.join(['/usr/bin/python3', '-c', code])], check=True)
    print(f'ARCHIVE {target}\nSHA256 {checksum}\nINSTALL python3 {source / "install_babel.py"} install {target}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='operation', required=True)
    sub.add_parser('prepare')
    c = sub.add_parser('install'); c.add_argument('archive', type=Path); c.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    if os.geteuid() == 0: p.error('run without local sudo')
    if args.operation == 'prepare': prepare(); return
    command = remote_command(args.archive.resolve())
    if args.dry_run: print(command); return
    if not sys.stdin.isatty(): p.error('run in your interactive terminal for the one-time Babel sudo password')
    print('Installing the fixed database maintenance entry. No app restart, role change or quota reset during installation.', flush=True)
    subprocess.run(['ssh', '-t', '-o', 'BatchMode=yes', 'Babel', command], check=True)


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, subprocess.CalledProcessError): raise SystemExit('Database maintenance setup did not complete; preserve the output and do not retry blindly.')
