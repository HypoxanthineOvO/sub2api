#!/usr/bin/env python3
"""One administrator installation. No database writes, restarts or role changes."""
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import sys

sys.dont_write_bytecode = True

RELEASE = Path('/usr/local/libexec/vsp-sub2api-release')
LIB = Path('/usr/local/libexec/vsp-sub2api-db-maint')
STATE = Path('/var/lib/vsp-sub2api-db-maint')
CLIENT = Path('/usr/local/bin/vsp-db-maint')
SUDOERS = Path('/etc/sudoers.d/vsp-sub2api-db-maint')
DEPENDENCIES = ('release_core.py', 'release_host.py', 'release_inspect.py', 'release_schema_data.py')


def main():
    if os.geteuid() != 0 or socket.gethostname() != 'iZuf668tiyo0blc17ihbtyZ': raise RuntimeError('Babel administrator required')
    source = Path(__file__).resolve().parent
    for path in (source, RELEASE):
        for p in (path, *path.parents):
            st = p.lstat()
            if p.is_symlink() or st.st_uid != 0 or st.st_mode & 0o022: raise RuntimeError('untrusted installer/dependency directory')
    sys.path.insert(0, str(RELEASE))
    from release_core import digest
    from release_host import atomic, load, trusted, info, unit, STATE as APP_STATE
    from release_inspect import runtime_environment
    from release_schema_data import Database
    for p in (LIB, STATE, CLIENT, SUDOERS):
        if p.exists() or p.is_symlink(): raise RuntimeError('maintenance installation already exists; refusing overwrite')
        trusted(p.parent)
    for name in DEPENDENCIES: trusted(RELEASE / name)
    for name in ('operations.py', 'control.py', 'client.py'): trusted(source / name)
    active = load(APP_STATE / 'active.json')
    values = runtime_environment(info(unit(active['slot']))['MainPID'])
    binding = Database.maintenance(values).identity()
    if binding['database'] != 'sub2api': raise RuntimeError('unexpected application database')
    operator = pwd.getpwnam('heyx')
    subprocess.run(['/usr/sbin/visudo', '-c'], check=True, capture_output=True)
    rule = f'heyx ALL=(root) NOPASSWD: {LIB}/control ""\n'
    created = []
    try:
        LIB.mkdir(mode=0o755); created.append(LIB)
        STATE.mkdir(mode=0o700); created.append(STATE)
        (STATE / 'audit').mkdir(mode=0o700); (STATE / 'operation.lock').touch(mode=0o600)
        for name in DEPENDENCIES:
            shutil.copyfile(RELEASE / name, LIB / name); (LIB / name).chmod(0o644)
        for name in ('operations.py', 'control.py', 'client.py'):
            shutil.copyfile(source / name, LIB / name); (LIB / name).chmod(0o644)
        launcher = LIB / 'control'
        launcher.write_text('#!/bin/sh\n[ "$#" -eq 0 ] || exit 2\nexec /usr/bin/python3 -I /usr/local/libexec/vsp-sub2api-db-maint/control.py\n'); launcher.chmod(0o755)
        atomic(STATE / 'config.json', {'operator': 'heyx', 'operator_uid': operator.pw_uid, 'binding': binding,
                                     'files': {p.name: digest(p) for p in LIB.iterdir() if p.is_file()}})
        candidate = STATE / 'sudoers.candidate'; candidate.write_text(rule); candidate.chmod(0o440)
        subprocess.run(['/usr/sbin/visudo', '-cf', str(candidate)], check=True, capture_output=True)
        with CLIENT.open('x') as stream: stream.write('#!/bin/sh\nexec /usr/bin/python3 -I /usr/local/libexec/vsp-sub2api-db-maint/client.py "$@"\n')
        created.append(CLIENT); CLIENT.chmod(0o755)
        with SUDOERS.open('x') as stream: stream.write(rule)
        created.append(SUDOERS); SUDOERS.chmod(0o440)
        subprocess.run(['/usr/sbin/visudo', '-cf', str(SUDOERS)], check=True, capture_output=True)
        subprocess.run(['/usr/sbin/runuser', '-u', 'heyx', '--', str(CLIENT), 'inspect'], check=True, capture_output=True, timeout=60)
    except Exception:
        for p in reversed(created):
            if p.is_dir(): shutil.rmtree(p)
            else: p.unlink(missing_ok=True)
        raise
    print(json.dumps({'result': 'INSTALLED', 'client': str(CLIENT), 'database': binding['database'],
                      'audit_directory': str(STATE / 'audit'), 'database_changes': False, 'services_restarted': False}))


if __name__ == '__main__':
    try: main()
    except Exception as error: raise SystemExit(f'Installation stopped ({type(error).__name__}); no application/database mutation was requested.')
