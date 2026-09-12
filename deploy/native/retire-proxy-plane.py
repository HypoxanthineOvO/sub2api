#!/usr/bin/env python3
"""Retire only the reviewed VSP proxy plane; default is a read-only plan.

Requires an interactive administrator invocation, not a permanent sudoers rule.
Archives removed paths, never purges databases/releases, never restarts the App.
"""

from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import time


HOSTS = {"genesis": "genesis", "babel": "iZuf668tiyo0blc17ihbtyZ"}
SLOTS = tuple(f"slot-{letter}" for letter in "abcdef")
SIDECARS = ("vsp-proxy-allocator@production.service", "vsp-selected-node@production.service", "vsp-proxy-dashboard.service")
BABEL_RETIRE = SIDECARS + tuple(f"vsp-mihomo-production@{slot}.service" for slot in SLOTS)
GENESIS_RETIRE = tuple(
    f"{kind}@{profile}.service"
    for profile in ("production", "rehearsal")
    for kind in ("vsp-proxy-allocator", "vsp-selected-node", "vsp-postgresql", "vsp-redis", "vsp-sub2api-app")
) + tuple(f"vsp-mihomo-{profile}@{slot}.service" for profile in ("production", "rehearsal") for slot in SLOTS) + (
    "vsp-mihomo-production@general.service", "vsp-sub2api-app-slot@blue.service",
    "vsp-sub2api-app-slot@green.service", "vsp-sub2api-production.target", "vsp-sub2api-rehearsal.target",
)
PROTECTED = ("vsp-sub2api-app-slot@blue.service", "vsp-postgresql@production.service", "vsp-redis@production.service", "vsp-mihomo-production@general.service", "nginx.service", "cloudflared.service")
OLD_TASKS = ("refresh_xyz.sh", "revive_daily.sh")
OLD_OPS = {"apply_sub_pool.py", "apply_sub_pool.py.pre-hell-backup", "apply_sub_pool_v2.py", "fix_allocator_apply.sh", "node_registry.py", "patch_allocator.sh", "proxy_dashboard_api.py", "refresh_xyz.sh", "revive_daily.sh", "revive_test.py", "update_sub_nodes.py", "__pycache__"}
RETIRED_REF = re.compile(r"vsp-(?:proxy-allocator|selected-node|proxy-dashboard)|mihomo-(?:production|rehearsal)@slot-[a-f]|/opt/vsp-sub2api/ops/|/mihomo/_subpool")
TARGET = """[Unit]
Description=VSP Sub2API native production stack
Requires=vsp-postgresql@production.service vsp-redis@production.service
Wants=vsp-mihomo-production@general.service
After=network-online.target

[Install]
WantedBy=multi-user.target
Alias=vsp-sub2api.target
"""


def run(*args, input=None, extra_env=None, allow_missing=False):
    env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C", **(extra_env or {})}
    result = subprocess.run(args, input=input, capture_output=True, text=True, timeout=45, env=env)
    if result.returncode and not (allow_missing and result.returncode == 1 and "no crontab" in result.stderr.lower()):
        raise RuntimeError(f"{args[0]} {args[1] if len(args) > 1 else ''} failed (exit {result.returncode}; details withheld to protect credentials)")
    return result.stdout


def properties(unit):
    return dict(line.split("=", 1) for line in run("systemctl", "show", unit, "--property=Id,ActiveState,MainPID,UnitFileState,Requires,BindsTo,RequiredBy,BoundBy,ConsistsOf").splitlines() if "=" in line)


def clean_env(content):
    # Do not try to parse or reserialize unrelated secrets / systemd quoting.
    if any(line.rstrip().endswith("\\") for line in content.splitlines()):
        raise RuntimeError("multiline app environment needs manual review")
    kept = [line for line in content.splitlines() if not re.match(r"^\s*SELECTED_NODE_[A-Z_]+\s*=", line)]
    return "\n".join(kept).rstrip() + "\nSELECTED_NODE_ENABLED=false\n"


def clean_cron(content):
    kept, removed = [], []
    for number, line in enumerate(content.splitlines(keepends=True), 1):
        if line.lstrip().startswith("#"):
            kept.append(line)
            continue
        if not any(name in line for name in OLD_TASKS):
            if RETIRED_REF.search(line):
                raise RuntimeError(f"unreviewed root cron reference at line {number}")
            kept.append(line)
            continue
        parts = line.strip().split(None, 5)
        if len(parts) != 6:
            raise RuntimeError(f"unsupported root cron schedule at line {number}")
        pattern = r"(?:(?:/bin/|/usr/bin/)?bash\s+)?/opt/vsp-sub2api/ops/(refresh_xyz\.sh|revive_daily\.sh)(?:\s+(?:[12]?>{1,2}\s*(?:/dev/null|/var/log/vsp-[A-Za-z0-9_.-]+)|2>&1))*\s*"
        match = re.fullmatch(pattern, parts[5])
        if not match:
            raise RuntimeError(f"unsupported root cron command at line {number}; nothing removed")
        removed.append({"line": number, "script": match.group(1)})
    return "".join(kept), removed


def matching_links(units):
    result = []
    for directory in Path("/etc/systemd/system").iterdir():
        if directory.is_dir() and not directory.is_symlink() and directory.name.endswith((".wants", ".requires")):
            for path in directory.iterdir():
                if path.name in units:
                    if not path.is_symlink():
                        raise RuntimeError(f"unexpected non-symlink dependency: {path}")
                    result.append(path)
    return result


def planned_paths(host):
    base = Path("/etc/systemd/system")
    units = BABEL_RETIRE if host == "babel" else GENESIS_RETIRE
    names = ["vsp-proxy-allocator@.service", "vsp-selected-node@.service"]
    if host == "babel":
        names.append("vsp-proxy-dashboard.service")
    else:
        names += ["vsp-mihomo-production@.service", "vsp-mihomo-rehearsal@.service", "vsp-postgresql@.service", "vsp-redis@.service", "vsp-sub2api-app@.service", "vsp-sub2api-app-slot@.service", "vsp-sub2api-production.target", "vsp-sub2api-rehearsal.target", "vsp-sub2api.target", "vsp-sub2api-production.target.bak.20260906-184036"]
    paths = matching_links(units) + [base / name for name in names]
    for unit in units:
        paths.extend((base / unit, base / f"{unit}.d"))
    for profile in (("production",) if host == "babel" else ("production", "rehearsal")):
        config = Path("/etc/vsp-sub2api") / profile
        data = Path("/var/lib/vsp-sub2api") / profile
        paths += [config / "allocator.json", config / "selected-node.json", data / "allocator"]
        paths += [config / "mihomo" / slot for slot in SLOTS]
        paths += [data / "mihomo" / slot for slot in SLOTS]
        paths.append(data / "mihomo/_subpool")
        if config.exists():
            paths.extend(p for p in config.iterdir() if p.name.startswith(("allocator.json.", "selected-node.json.")) and not p.is_dir())
    if host == "babel":
        ops = Path("/opt/vsp-sub2api/ops")
        if ops.exists() and {p.name for p in ops.iterdir()} - OLD_OPS:
            raise RuntimeError("unreviewed files in Babel ops directory; refusing to archive it")
        paths.append(ops)
    else:
        paths += [Path(p) for p in ("/usr/local/sbin/vsp-sub2api-deploy", "/usr/local/sbin/vsp-sub2api-allocator-deploy", "/etc/sudoers.d/vsp-sub2api-deploy", "/opt/vsp-sub2api/allocator")]
        # The same libexec directory contains a retained database diagnostic tool.
        paths += [Path("/usr/local/libexec/vsp-sub2api") / name for name in ("deploy-app-release.sh", "deploy-proxy-allocator.sh", "install.sh", "switch-app-slot.sh")]
    # Parent and child paths are not both archived. Missing paths support safe reruns.
    unique = sorted(set(paths), key=lambda p: (len(p.parts), str(p)))
    result = []
    for path in unique:
        if (path.exists() or path.is_symlink()) and not any(parent in path.parents for parent in result):
            result.append(path)
    return result


def database_binding_check():
    import yaml
    config = yaml.safe_load(Path("/var/lib/vsp-sub2api/production/app/config.yaml").read_text())["database"]
    query = "SELECT count(*) FROM accounts WHERE deleted_at IS NULL AND (proxy_id IS NOT NULL OR proxy_fallback_origin_id IS NOT NULL)"
    result = run("psql", "-X", "-w", "-A", "-t", "-h", "127.0.0.1", "-p", "5432", "-U", str(config.get("user", "sub2api")), "-d", str(config.get("dbname", "sub2api")), "-c", query, extra_env={"PGPASSWORD": str(config["password"]), "PGCONNECT_TIMEOUT": "5", "PGOPTIONS": "-c default_transaction_read_only=on -c statement_timeout=10000"})
    if result.strip() != "0":
        raise RuntimeError("accounts still have proxy/fallback bindings; refusing retirement")


def health_check():
    for url, extra in (("http://127.0.0.1:19821/health", ()), ("http://127.0.0.1:8081/health", ("-H", "Host: api.vsplab.tech"))):
        body = run("curl", "--noproxy", "*", "-fsS", "--max-time", "10", *extra, url)
        if json.loads(body).get("status") != "ok":
            raise RuntimeError("application/origin health is not ok")


def protected_processes(host):
    if host == "babel":
        result = {}
        for unit in PROTECTED:
            info = properties(unit)
            if info["ActiveState"] != "active" or info.get("MainPID", "0") == "0":
                raise RuntimeError(f"protected service is not running: {unit}")
            result[unit] = info["MainPID"]
        health_check()
        return result
    uid = run("id", "-u", "heyx").strip()
    pid = run("runuser", "-u", "heyx", "--", "env", f"XDG_RUNTIME_DIR=/run/user/{uid}", "systemctl", "--user", "show", "mihomo.service", "-p", "MainPID", "--value").strip()
    if not pid.isdigit() or int(pid) == 0:
        raise RuntimeError("Genesis user Mihomo is not running")
    return {"user:mihomo.service": pid}


def assert_no_running_maintenance():
    for path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            args = path.read_bytes().split(b"\0")
        except (FileNotFoundError, ProcessLookupError):
            continue
        task_names = OLD_OPS - {"proxy_dashboard_api.py", "__pycache__"}
        absolute_task = any(arg.startswith(b"/opt/vsp-sub2api/ops/") and Path(os.fsdecode(arg)).name in task_names for arg in args)
        relative_task = any(os.fsdecode(arg) in task_names for arg in args)
        try:
            relative_task = relative_task and (path.parent / "cwd").resolve() == Path("/opt/vsp-sub2api/ops")
        except OSError:
            relative_task = False
        if absolute_task or relative_task or any(b"/mihomo/_subpool/" in arg for arg in args):
            raise RuntimeError(f"retired maintenance still running (PID {path.parent.name}); wait for it to finish, do not kill it blindly")


def assert_no_slot_connections():
    ports = {17901, 17902, 17903, 17904, 17905, 17907}
    for line in run("ss", "-Htn", "state", "established").splitlines():
        for field in line.split():
            if ":" in field and field.rsplit(":", 1)[-1].isdigit() and int(field.rsplit(":", 1)[-1]) in ports:
                raise RuntimeError("a retired slot still has an established TCP connection; leave it running and retry after drain")


class Archive:
    def __init__(self, host):
        root = Path("/var/backups/vsp-sub2api-retirement")
        if root.is_symlink():
            raise RuntimeError("archive root must not be a symlink")
        root.mkdir(mode=0o700, exist_ok=True)
        if root.stat().st_uid != 0 or stat.S_IMODE(root.stat().st_mode) & 0o077:
            raise RuntimeError("archive root must be root-owned with mode 0700")
        self.path = Path(tempfile.mkdtemp(prefix=f"{host}-{datetime.datetime.now().strftime('%Y%m%dT%H%M%S')}-", dir=root))
        self.events = []
        print(f"ARCHIVE={self.path}", flush=True)

    def record(self, action, path):
        self.events.append({"action": action, "path": str(path)})
        (self.path / "actions.json").write_text(json.dumps(self.events, indent=2) + "\n")
        print(f"{action}: {path}", flush=True)

    def destination(self, path):
        dest = self.path / "files" / path.relative_to("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest

    def remove(self, path):
        if not path.exists() and not path.is_symlink():
            return
        dest = self.destination(path)
        if dest.exists() or dest.is_symlink():
            raise RuntimeError(f"archive collision: {path}")
        self.record("archive-intent", path)
        shutil.move(str(path), str(dest))
        self.record("archived", path)

    def edit(self, path, content):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"refusing to edit non-regular file: {path}")
        original = path.stat()
        shutil.copy2(path, self.destination(path))
        fd, name = tempfile.mkstemp(prefix=".vsp-retirement-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(original.st_mode))
                os.fchown(stream.fileno(), original.st_uid, original.st_gid)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            self.record("edit-intent", path)
            os.replace(name, path)
            self.record("edited", path)
        finally:
            Path(name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, choices=HOSTS)
    parser.add_argument("--execute", action="store_true", help="perform the displayed, fixed-scope retirement")
    args = parser.parse_args()
    if socket.gethostname() != HOSTS[args.host] or os.geteuid() != 0:
        parser.error("run with sudo on the selected host")
    os.umask(0o077)
    # Lock the installed script inode without creating a file in plan mode.
    with open(__file__, "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        execute(args)


def execute(args):
    host = args.host
    units = BABEL_RETIRE if host == "babel" else GENESIS_RETIRE
    before = protected_processes(host)
    cron_before = run("crontab", "-l", "-u", "root", allow_missing=True)
    cron_after, cron_removed = clean_cron(cron_before)
    if host == "genesis":
        for unit in units:
            info = properties(unit)
            if info["ActiveState"] not in {"inactive", "failed"} or info.get("MainPID", "0") != "0":
                raise RuntimeError(f"Genesis native service is unexpectedly running: {unit}")
    else:
        import yaml
        database_binding_check()
        general = yaml.safe_load(Path("/etc/vsp-sub2api/production/mihomo/general/config.yaml").read_text())
        if general.get("proxy-providers") or "/mihomo/_subpool" in json.dumps(general):
            raise RuntimeError("general proxy has unreviewed provider dependencies")
        assert_no_running_maintenance()
    paths = planned_paths(host)
    env_changes = {}
    for profile in (("production",) if host == "babel" else ("production", "rehearsal")):
        directory = Path("/etc/vsp-sub2api") / profile
        for name in ("app.env", "app-blue.env", "app-green.env"):
            path = directory / name
            if path.exists():
                content = path.read_text()
                if name == "app.env" or re.search(r"^SELECTED_NODE_", content, re.MULTILINE):
                    env_changes[path] = (content, clean_env(content))
    print(json.dumps({"host": host, "execute": args.execute, "retire_units": units, "archive_paths": [str(p) for p in paths], "environment_files": [str(p) for p in env_changes], "remove_root_cron": cron_removed, "protected_pids": before, "database_writes": False, "application_restart": False}, indent=2), flush=True)
    if not args.execute:
        return
    archive = Archive(host)
    try:
        if run("crontab", "-l", "-u", "root", allow_missing=True) != cron_before:
            raise RuntimeError("root crontab changed during preflight")
        if cron_removed:
            (archive.path / "root-crontab.before").write_text(cron_before)
            (archive.path / "root-crontab.after").write_text(cron_after)
            run("crontab", "-u", "root", "-", input=cron_after)
            archive.record("cron-updated", "root-crontab")
        if host == "babel":
            # Disabling a schedule does not terminate an already-running job.
            time.sleep(2)
            assert_no_running_maintenance()
            database_binding_check()
            archive.edit(Path("/etc/systemd/system/vsp-sub2api-production.target"), TARGET)
        for path, (original, replacement) in env_changes.items():
            if path.read_text() != original:
                raise RuntimeError(f"environment changed during preflight: {path}")
            archive.edit(path, replacement)
        # Remove enablement/dependency links BEFORE stopping providers of Requires=.
        for path in matching_links(units):
            archive.remove(path)
        if host == "genesis":
            # All native units were verified stopped; remove the whole retired unit set.
            for path in paths:
                if str(path).startswith("/etc/systemd/system/"):
                    archive.remove(path)
        run("systemctl", "daemon-reload")
        for unit in units:
            info = properties(unit)
            dependents = set(" ".join(info.get(key, "") for key in ("RequiredBy", "BoundBy", "ConsistsOf")).split())
            if host == "babel" and dependents - set(units):
                raise RuntimeError(f"external services still depend on {unit}; no stop issued for it")
        if host == "babel":
            if properties("vsp-sub2api-production.target")["ActiveState"] != "active":
                raise RuntimeError("production target is not active")
            for unit in units:
                if unit.startswith("vsp-mihomo-"):
                    assert_no_slot_connections()
                if properties(unit)["ActiveState"] not in {"inactive", "failed"}:
                    archive.record("stop-intent", unit)
                    run("systemctl", "stop", unit)
                    archive.record("stopped", unit)
                    if protected_processes(host) != before:
                        raise RuntimeError("a protected PID changed after stopping a retired service")
        for unit in units:
            info = properties(unit)
            if info["ActiveState"] not in {"inactive", "failed"} or info.get("MainPID", "0") != "0":
                raise RuntimeError(f"retired service is still running: {unit}")
        if protected_processes(host) != before:
            raise RuntimeError("a protected PID changed; review before continuing")
        for path in paths:
            archive.remove(path)
        run("systemctl", "daemon-reload")
        if host == "genesis":
            run("visudo", "-c")
        if protected_processes(host) != before:
            raise RuntimeError("a protected PID changed during final checks")
        archive.record("complete", host)
        print("COMPLETE: reviewed services retired; protected processes unchanged.")
        print("App env changes take effect on its next planned release; no App restart performed.")
        print("Database proxy records, application releases, databases, general proxy and unrelated containers were preserved.")
    except BaseException:
        archive.record("incomplete", host)
        print(f"STOPPED ON ERROR. Review {archive.path}/actions.json before retrying. No automatic whole-stack rollback or restart was attempted.", flush=True)
        raise


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(str(error))
