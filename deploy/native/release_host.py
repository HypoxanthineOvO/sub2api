"""Babel adapter for the release engine. Installed root-owned; fixed scope only."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.request

from release_core import Engine, ID, ReleaseError, canonical, decode, digest, read_package, validate_manifest

ROOT = Path("/opt/vsp-sub2api-managed")
STATE = Path("/var/lib/vsp-sub2api-release")
CONFIG = Path("/etc/vsp-sub2api-release.json")
SLOT_ENV = Path("/etc/vsp-sub2api-release")
INCOMING = Path("/home/heyx/VSP-Sub2API/incoming")
ACTIVE_LINK = Path("/etc/nginx/sub2api-upstreams/active.conf")
PORTS = {"blue": 19821, "green": 19822}


def run(*args, timeout=30):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
    if r.returncode:
        raise ReleaseError(f"{args[0]} {args[1] if len(args) > 1 else ''} failed (exit {r.returncode})")
    return r.stdout.strip()


def trusted(path):
    path = Path(path)
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ReleaseError(f"untrusted managed path: {item}")


def load(path):
    trusted(path)
    data = Path(path).read_bytes()
    if len(data) > 1024 * 1024:
        raise ReleaseError("state file too large")
    return decode(data)


def atomic(path, value, group=None):
    path = Path(path)
    trusted(path.parent)
    if path.is_symlink():
        raise ReleaseError("refusing a symlink state file")
    fd, name = tempfile.mkstemp(prefix=".release-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o640 if group is not None else 0o600)
            if group is not None: os.fchown(stream.fileno(), 0, group)
            stream.write(canonical(value) + b"\n")
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def slot_record(record):
    if not isinstance(record, dict) or record.get("slot") not in PORTS or not isinstance(record.get("release"), str) or not ID.fullmatch(record["release"]):
        raise ReleaseError("invalid slot state")
    return {"slot": record["slot"], "release": record["release"]}


def unit(slot):
    if slot not in PORTS: raise ReleaseError("invalid slot")
    return f"vsp-sub2api-app-slot@{slot}.service"


def info(name):
    return dict(line.split("=", 1) for line in run("systemctl", "show", name, "-p", "MainPID,ActiveState,UnitFileState,MemoryCurrent").splitlines() if "=" in line)


def nginx_workers():
    master = int(info("nginx.service")["MainPID"])
    if not master: raise ReleaseError("Nginx is not running")
    children = Path(f"/proc/{master}/task/{master}/children").read_text().split()
    result = []
    for pid in children:
        try:
            command = Path(f"/proc/{pid}/cmdline").read_bytes()
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            if b"nginx: worker process" in command:
                result.append([int(pid), fields[19]])
        except FileNotFoundError: pass
    if not result: raise ReleaseError("no Nginx worker generation could be identified")
    return result


def generation_alive(generation):
    pid, start = generation
    try: return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19] == start
    except FileNotFoundError: return False


def has_connections(port):
    for line in run("ss", "-Htn", "state", "established").splitlines():
        if any(field.rsplit(":", 1)[-1] == str(port) for field in line.split() if ":" in field):
            return True
    return False


def request(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request(url, headers={"Host": "api.vsplab.tech", "Connection": "close", "Cache-Control": "no-cache"}), timeout=5) as response:
        body = response.read(4097)
        if response.status != 200 or len(body) > 4096 or decode(body).get("status") != "ok":
            raise ReleaseError("health response is not ok")
        return response.headers


class Host:
    def __init__(self, job, rolling_back=False):
        self.cfg = load(CONFIG)
        self.job = job
        self.rolling_back = rolling_back
        self.job_path = STATE / "jobs" / (job + ".json")
        self.protected = {name: info(name)["MainPID"] for name in ("vsp-postgresql@production.service", "vsp-redis@production.service", "vsp-mihomo-production@general.service", "nginx.service", "cloudflared.service")}
        if any(pid == "0" for pid in self.protected.values()):
            raise ReleaseError("a protected service is not running")

    def active(self): return load(STATE / "active.json")
    def journal(self): return load(self.job_path) if self.job_path.exists() else None
    def save_journal(self, journal): atomic(self.job_path, {**journal, "job": self.job, "updated": time.time()})

    def manifest(self, record):
        return validate_manifest(load(ROOT / "releases" / slot_record(record)["release"] / "manifest.json"))

    def verify_protected(self):
        if any(info(name)["MainPID"] != pid for name, pid in self.protected.items()):
            raise ReleaseError("protected service changed during deployment")

    def import_package(self, release):
        if not ID.fullmatch(release): raise ReleaseError("invalid package ID")
        trusted(ROOT / "releases")
        target = ROOT / "releases" / release
        if target.exists():
            self.verify_release({"slot": "blue", "release": release})
            return
        directory = os.open(INCOMING, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if os.fstat(directory).st_uid != self.cfg["operator_uid"]: raise ReleaseError("untrusted incoming directory owner")
            fd = os.open(release + ".tar", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        finally: os.close(directory)
        with os.fdopen(fd, "rb") as source, tempfile.TemporaryDirectory(prefix=".import-", dir=ROOT / "releases") as temporary:
            st = os.fstat(source.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid != self.cfg["operator_uid"] or st.st_size > 320 * 1024 * 1024:
                raise ReleaseError("invalid incoming file")
            if shutil.disk_usage(ROOT).free < 2 * st.st_size + self.cfg["min_disk_free"]:
                raise ReleaseError("insufficient disk space for immutable staging and reserved database headroom")
            snapshot = Path(temporary) / "package.tar"
            with snapshot.open("xb") as output:
                remaining = st.st_size
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    if not block: raise ReleaseError("upload changed during copy")
                    output.write(block); remaining -= len(block)
                if source.read(1): raise ReleaseError("upload grew during copy")
            payload = Path(temporary) / "payload"; payload.mkdir()
            manifest = read_package(snapshot, payload)
            if manifest["id"] != release: raise ReleaseError("incoming release identity mismatch")
            for path in payload.rglob("*"):
                path.chmod(0o755 if path.is_dir() or path.name == "sub2api" else 0o644)
            payload.chmod(0o755)
            os.rename(payload, target)

    def verify_release(self, record):
        m = self.manifest(record)
        directory = ROOT / "releases" / record["release"]
        for name, expected in m["files"].items():
            path = directory / name; trusted(path)
            if not path.is_file() or path.stat().st_size != expected["size"] or digest(path) != expected["sha256"]:
                raise ReleaseError("installed release checksum mismatch")
        return m

    def preflight(self, old, new, allow_legacy=False):
        old, new = slot_record(old), slot_record(new)
        if old["slot"] == new["slot"] or old["release"] == new["release"]:
            raise ReleaseError("candidate must differ from active release and slot")
        self.verify_protected()
        previous = self.verify_release(old); candidate = self.verify_release(new)
        if candidate["worker_gate"] != 1 or (previous["worker_gate"] != 1 and not allow_legacy):
            raise ReleaseError("maintenance_required: normal publish/rollback requires worker-aware binaries on both sides")
        if allow_legacy and previous["worker_gate"] != 0: raise ReleaseError("initial maintenance is only for the legacy baseline")
        if previous["migrations"] != candidate["migrations"]:
            raise ReleaseError("migration_review_required: automatic schema changes are not permitted")
        if not self.rolling_back: self.healthy(old, direct=False)
        target_running = self.rolling_back and info(unit(new["slot"]))["MainPID"] != "0"
        if not target_running and has_connections(PORTS[new["slot"]]):
            raise ReleaseError("inactive slot still owns accepted connections")
        for path in Path("/proc").glob("[0-9]*/cmdline"):
            try:
                with path.open("rb") as stream: command = stream.read(4096)
            except FileNotFoundError: continue
            if not self.rolling_back and b"nginx: worker process is shutting down" in command: raise ReleaseError("a prior Nginx generation is still draining")
        owner = load(STATE / "workers.json").get("owner")
        expected = {"", old["slot"] + ":" + old["release"]} if allow_legacy else {old["slot"] + ":" + old["release"]}
        if not self.rolling_back and owner not in expected:
            raise ReleaseError("active worker ownership is not consistent")
        available = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))) * 1024
        reclaim = info(unit(new["slot"])).get("MemoryCurrent", "0")
        reclaim = int(reclaim) if reclaim.isdigit() else 0
        if not target_running and available + reclaim < self.cfg["candidate_memory"] + self.cfg["reserved_memory"]:
            raise ReleaseError("insufficient memory headroom for a candidate and warm rollback")
        if not self.rolling_back and shutil.disk_usage(ROOT).free < self.cfg["min_disk_free"]:
            raise ReleaseError("insufficient disk headroom")

    def write_slot(self, record, legacy_disabled=False):
        record = slot_record(record)
        slot, release = record["slot"], record["release"]
        target = ROOT / "releases" / release
        trusted(target)
        link = ROOT / "slots" / slot
        if link.exists() and not link.is_symlink(): raise ReleaseError("unexpected non-symlink slot")
        temporary = link.with_name(slot + ".next")
        if temporary.exists() or temporary.is_symlink(): temporary.unlink()
        temporary.symlink_to(target); os.replace(temporary, link)
        env = (f"SERVER_HOST=127.0.0.1\nSERVER_PORT={PORTS[slot]}\n"
               f"PRICING_FALLBACK_FILE={target}/resources/model-pricing/model_prices_and_context_window.json\n"
               f"SUB2API_DISABLE_AUTONOMOUS_WORKERS={int(legacy_disabled)}\n"
               f"SUB2API_DEPLOYMENT_CONTROL_DIR={STATE}\nSUB2API_DEPLOYMENT_INSTANCE={slot}:{release}\n")
        path = SLOT_ENV / (slot + ".env")
        fd, name = tempfile.mkstemp(prefix=".slot-", dir=SLOT_ENV)
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o640); os.fchown(stream.fileno(), 0, self.cfg["operator_gid"])
            stream.write(env); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)

    def prepare(self, candidate):
        slot = candidate["slot"]
        if self.rolling_back and info(unit(slot))["MainPID"] != "0":
            # A rollback must reuse its healthy target, not restart it or demand
            # that the currently broken version first become healthy.
            self.wait_healthy(candidate)
            return
        if has_connections(PORTS[slot]): raise ReleaseError("standby acquired a connection; refusing stop")
        if info(unit(slot))["ActiveState"] != "inactive": run("systemctl", "stop", unit(slot), timeout=100)
        self.write_slot(candidate)
        run("systemctl", "set-property", "--runtime", unit(slot), f"MemoryMax={self.cfg['candidate_memory']}", "MemorySwapMax=0")
        run("systemctl", "start", unit(slot), timeout=100)
        deadline = time.monotonic() + 60
        while True:
            try: self.healthy(candidate, direct=True); break
            except Exception:
                if time.monotonic() >= deadline: raise ReleaseError("candidate did not become ready")
                time.sleep(1)

    def healthy(self, record, direct):
        record = slot_record(record)
        if info(unit(record["slot"]))["ActiveState"] != "active": raise ReleaseError("application unit is not active")
        headers = request(f"http://127.0.0.1:{PORTS[record['slot']]}/health")
        if self.manifest(record)["worker_gate"] == 1 and headers.get("X-VSP-Deployment") != record["slot"] + ":" + record["release"]:
            raise ReleaseError("wrong application identity on slot")
        if not direct:
            headers = request("http://127.0.0.1:19820/health")
            if headers.get("X-VSP-Upstream") != f"127.0.0.1:{PORTS[record['slot']]}": raise ReleaseError("loaded Nginx route is not the expected slot")
        self.verify_protected()

    def transfer_workers(self, record):
        record = slot_record(record)
        self.set_worker_owner(record["slot"] + ":" + record["release"])

    def set_worker_owner(self, owner):
        # Recovery must not wait for an already-correct owner's long-running job.
        # The release runner serializes writers with operation.lock.
        if load(STATE / "workers.json").get("owner") == owner: return
        deadline = time.monotonic() + self.cfg["worker_timeout"]
        with (STATE / "workers.lock").open("r+") as lock:
            while True:
                try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); break
                except BlockingIOError:
                    if time.monotonic() >= deadline: raise ReleaseError("scheduled jobs did not finish; worker owner was not changed")
                    time.sleep(0.2)
            atomic(STATE / "workers.json", {"owner": owner}, self.cfg["operator_gid"])

    def stop_initial_old(self, record):
        if has_connections(PORTS[record["slot"]]):
            raise ReleaseError("old application still has connections; choose a quieter maintenance window")
        run("systemctl", "stop", unit(record["slot"]), timeout=100)
        if info(unit(record["slot"]))["MainPID"] != "0":
            raise ReleaseError("old application did not stop")

    def wait_healthy(self, record):
        deadline = time.monotonic() + 60
        while True:
            try: self.healthy(record, direct=True); return
            except Exception:
                if time.monotonic() >= deadline: raise ReleaseError("restored application did not become healthy")
                time.sleep(1)

    def restore_initial_app(self, old, candidate):
        # Only the explicit maintenance transaction may interrupt a routed App.
        # Stop the new workers completely before starting the legacy workers.
        if info(unit(candidate["slot"]))["MainPID"] != "0":
            run("systemctl", "stop", unit(candidate["slot"]), timeout=100)
        if info(unit(candidate["slot"]))["MainPID"] != "0":
            raise ReleaseError("new application still running; refusing duplicate legacy workers")
        self.set_worker_owner("")
        self.write_slot(old, legacy_disabled=False)
        run("systemctl", "start", unit(old["slot"]), timeout=100)
        self.wait_healthy(old)

    def route(self, record):
        slot = slot_record(record)["slot"]
        self.healthy(record, direct=True)
        workers = nginx_workers()
        trusted(ACTIVE_LINK.parent)
        temporary = ACTIVE_LINK.with_name("active.conf.release-next")
        if temporary.exists() or temporary.is_symlink(): temporary.unlink()
        temporary.symlink_to(ACTIVE_LINK.parent / (slot + ".conf"))
        os.replace(temporary, ACTIVE_LINK)
        run("nginx", "-t"); run("nginx", "-s", "reload")
        deadline = time.monotonic() + 15
        while True:
            try: self.healthy(record, direct=False); break
            except Exception:
                if time.monotonic() >= deadline: raise ReleaseError("Nginx reload did not expose the expected route")
                time.sleep(0.25)
        return workers

    def observe(self, candidate, generations):
        start = time.monotonic()
        while True:
            self.healthy(candidate, direct=False)
            elapsed = time.monotonic() - start
            if elapsed >= self.cfg["observe_seconds"] and not any(generation_alive(g) for g in generations): break
            if elapsed > self.cfg["drain_seconds"]: raise ReleaseError("old Nginx requests did not drain; refusing completion")
            time.sleep(1)
        headers = request("https://api.vsplab.tech/health")
        if headers.get("X-VSP-Deployment") != candidate["slot"] + ":" + candidate["release"]:
            raise ReleaseError("public ingress is not the candidate release")

    def commit(self, new, old):
        run("systemctl", "enable", unit(new["slot"]))
        run("systemctl", "disable", unit(old["slot"]))
        atomic(STATE / "active.json", {**slot_record(new), "previous": slot_record(old)})

    def restore_committed(self, old):
        run("systemctl", "enable", unit(old["slot"]))
        other = "green" if old["slot"] == "blue" else "blue"
        run("systemctl", "disable", unit(other))
        atomic(STATE / "active.json", old)
