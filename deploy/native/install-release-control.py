#!/usr/bin/env python3
"""One-time administrator installation; never restarts App/data/proxy services.

Requires a baseline archive of the currently running binary. The resulting
controller refuses automatic deployment while active.worker_gate=0. The first
new version is started once in an administrator-confirmed maintenance window.
"""
from __future__ import annotations

import argparse
import datetime
import grp
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_core import ReleaseError, digest, read_package
from release_host import CONFIG, ROOT, SLOT_ENV, STATE, Host, atomic, info, run, trusted

LIB = Path("/usr/local/libexec/vsp-sub2api-release")
SOURCES = ("release_core.py", "release_host.py", "release_control.py", "release_runner.py", "release_client.py", "release_initial.py")
PROBE = """# Internal release verifier; never exposed beyond loopback.
server {
    listen 127.0.0.1:19820;
    server_name localhost;
    location = /health {
        proxy_pass http://sub2api_app;
        proxy_set_header Host api.vsplab.tech;
        proxy_buffering off;
        proxy_hide_header X-VSP-Upstream;
        add_header X-VSP-Upstream $upstream_addr always;
    }
    location / { return 404; }
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or socket.gethostname() != "iZuf668tiyo0blc17ihbtyZ": parser.error("administrator installation must run on Babel")
    targets = [CONFIG, ROOT, STATE, LIB, SLOT_ENV, Path("/usr/local/bin/vsp-release"), Path("/etc/systemd/system/vsp-sub2api-release.service"), Path("/etc/nginx/conf.d/vsp-release-probe.conf"), Path("/etc/sudoers.d/vsp-sub2api-release")]
    if any(p.exists() or p.is_symlink() for p in targets): parser.error("managed paths already exist; do not overwrite an installation")
    for parent in (ROOT.parent, STATE.parent, LIB.parent, Path("/usr/local/bin"), Path("/etc/systemd/system"), Path("/etc/nginx/conf.d"), Path("/etc/sudoers.d")):
        trusted(parent)
    source = Path(__file__).resolve().parent
    if any(not (source / name).is_file() for name in SOURCES): parser.error("installer must be delivered with its reviewed Python sources")
    release_unit = source / "vsp-sub2api-release.service"
    if not release_unit.exists(): release_unit = source.parents[1] / "ops/systemd/vsp-sub2api-release.service"
    if not release_unit.is_file(): parser.error("missing reviewed release systemd unit")
    slot_unit = source / "vsp-sub2api-app-slot@.service"
    if not slot_unit.exists(): slot_unit = source.parents[1] / "ops/systemd/vsp-sub2api-app-slot@.service"
    if not slot_unit.is_file(): parser.error("missing reviewed application systemd unit")
    user = pwd.getpwnam("heyx"); group = grp.getgrnam("vsp-admin")
    before = {u: info(u)["MainPID"] for u in ("vsp-sub2api-app-slot@blue.service", "vsp-postgresql@production.service", "vsp-redis@production.service", "vsp-mihomo-production@general.service", "nginx.service", "cloudflared.service")}
    if any(pid == "0" for pid in before.values()) or info("vsp-sub2api-app-slot@green.service")["ActiveState"] != "inactive": parser.error("expected active blue and stopped green")
    if Path("/etc/nginx/sub2api-upstreams/active.conf").resolve().name != "blue.conf": parser.error("expected blue ingress")
    if ":19820 " in run("ss", "-lnt"): parser.error("internal probe port is occupied")
    run("nginx", "-t"); run("visudo", "-c")
    manifest = read_package(args.baseline)
    if manifest["worker_gate"] != 0: parser.error("this one-time installer expects the existing legacy baseline; managed adoption must be reviewed separately")
    if digest(Path(f"/proc/{before['vsp-sub2api-app-slot@blue.service']}/exe")) != manifest["files"]["sub2api"]["sha256"]: parser.error("baseline is not the currently running binary")
    from release_core import PRICING
    if digest(Path("/opt/vsp-sub2api/app-slots/blue") / PRICING) != manifest["files"][PRICING]["sha256"]: parser.error("baseline pricing fallback differs from the existing release")
    archive = Path("/var/backups/vsp-sub2api-release-install") / datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    archive.mkdir(mode=0o700, parents=True, exist_ok=False)
    unit_path = Path("/etc/systemd/system/vsp-sub2api-app-slot@.service")
    probe_path = Path("/etc/nginx/conf.d/vsp-release-probe.conf")
    sudoers = Path("/etc/sudoers.d/vsp-sub2api-release")
    if probe_path.exists() or sudoers.exists(): parser.error("refusing to replace unrelated probe/permission files")
    shutil.copy2(unit_path, archive / unit_path.name)
    cfg = {"hostname": socket.gethostname(), "operator_user": user.pw_name, "operator_uid": user.pw_uid, "operator_gid": group.gr_gid,
           "candidate_memory": 512 * 1024**2, "reserved_memory": 256 * 1024**2, "min_disk_free": 1024**3, "observe_seconds": 30, "drain_seconds": 660, "worker_timeout": 180}
    for directory in (ROOT, ROOT / "releases", ROOT / "slots", STATE, STATE / "jobs", SLOT_ENV, LIB):
        directory.mkdir(mode=0o755, parents=True)
        os.chown(directory, 0, 0); directory.chmod(0o755)
    os.chown(STATE, 0, group.gr_gid); STATE.chmod(0o750)
    atomic(CONFIG, cfg)
    for name in ("request.lock", "operation.lock", "workers.lock"):
        path = STATE / name; path.touch(mode=0o640)
        os.chown(path, 0, group.gr_gid)
    atomic(STATE / "workers.json", {"owner": ""}, group.gr_gid)
    baseline = ROOT / "releases" / manifest["id"]; baseline.mkdir()
    read_package(args.baseline, baseline)
    for path in baseline.rglob("*"): path.chmod(0o755 if path.is_dir() or path.name == "sub2api" else 0o644)
    active = {"slot": "blue", "release": manifest["id"], "previous": None}
    atomic(STATE / "active.json", active)
    host = Host("install"); host.write_slot(active, legacy_disabled=False)
    for name in SOURCES:
        shutil.copyfile(source / name, LIB / name); (LIB / name).chmod(0o644)
    control = LIB / "control"
    control.write_text('#!/bin/sh\n[ "$#" -eq 0 ] || exit 2\nexec /usr/bin/python3 -I /usr/local/libexec/vsp-sub2api-release/release_control.py\n'); control.chmod(0o755)
    client = Path("/usr/local/bin/vsp-release")
    if client.exists(): raise ReleaseError("refusing existing user entrypoint")
    client.write_text('#!/bin/sh\nexec /usr/bin/python3 -I /usr/local/libexec/vsp-sub2api-release/release_client.py "$@"\n'); client.chmod(0o755)
    incoming = Path(user.pw_dir) / "VSP-Sub2API/incoming"
    if not incoming.exists() and not incoming.is_symlink(): run("runuser", "-u", "heyx", "--", "/bin/mkdir", "-m", "0700", "--", str(incoming))
    if incoming.is_symlink() or not incoming.is_dir() or incoming.lstat().st_uid != user.pw_uid: raise ReleaseError("untrusted incoming directory")
    shutil.copyfile(release_unit, "/etc/systemd/system/vsp-sub2api-release.service")
    try:
        shutil.copyfile(slot_unit, unit_path); unit_path.chmod(0o644)
        probe_path.write_text(PROBE); probe_path.chmod(0o644)
        run("systemctl", "daemon-reload")
        run("nginx", "-t"); run("nginx", "-s", "reload")
        deadline = time.monotonic() + 15
        while True:
            try: host.healthy(active, direct=False); break
            except Exception:
                if time.monotonic() >= deadline: raise ReleaseError("probe did not become healthy after reload")
                time.sleep(0.25)
        rule = f'heyx ALL=(root) NOPASSWD: {control} ""\n'
        with tempfile.NamedTemporaryFile("w", prefix="vsp-sudoers-") as candidate:
            candidate.write(rule); candidate.flush(); run("visudo", "-cf", candidate.name)
        sudoers.write_text(rule); sudoers.chmod(0o440); run("visudo", "-cf", str(sudoers))
        if any(info(u)["MainPID"] != pid for u, pid in before.items()): raise ReleaseError("protected PID changed during installation")
    except Exception:
        sudoers.unlink(missing_ok=True)
        shutil.copy2(archive / unit_path.name, unit_path)
        probe_path.unlink(missing_ok=True)
        run("systemctl", "daemon-reload"); run("nginx", "-t"); run("nginx", "-s", "reload")
        raise
    print(f"Installed restricted controller. Baseline {manifest['id']}; archive {archive}")
    if manifest["worker_gate"] != 1:
        print("INITIAL MAINTENANCE REQUIRED: choose a quiet window and use release_initial.py. Automatic deployment remains blocked until then.")


if __name__ == "__main__":
    try: main()
    except (ReleaseError, OSError) as error: raise SystemExit(str(error))
    except Exception as error: raise SystemExit(f"installation failed ({type(error).__name__}; inspect the archive before retrying)")
