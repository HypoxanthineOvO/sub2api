#!/usr/bin/env python3
"""Unprivileged build/upload/deploy client. Privileged changes use a fixed RPC."""
from __future__ import annotations

import argparse
import datetime
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_core import COMMIT, ID, PRICING, ReleaseError, create_package, digest, read_package

BABEL = "iZuf668tiyo0blc17ihbtyZ"
CONTROL = "/usr/local/libexec/vsp-sub2api-release/control"
INCOMING = Path("/home/heyx/VSP-Sub2API/incoming")


def command(args, cwd=None, capture=True, env=None, input=None):
    r = subprocess.run(args, cwd=cwd, text=True, input=input, capture_output=capture, env=env)
    if r.returncode:
        raise ReleaseError(f"{args[0]} failed (exit {r.returncode})")
    return r.stdout.strip() if capture else ""


def build(repo, commit):
    repo = Path(repo).resolve()
    git = lambda *args: command(["git", "-C", str(repo), *args])
    commit = git("rev-parse", "--verify", commit + "^{commit}")
    if not COMMIT.fullmatch(commit):
        raise ReleaseError("invalid commit")
    if git("status", "--porcelain"):
        raise ReleaseError("formal builds require a clean committed worktree")
    remote = git("ls-remote", "origin", "refs/heads/vsp/main").split()
    if not remote or remote[0] != commit:
        raise ReleaseError("formal builds require origin/vsp/main to point at the requested commit")
    outputs = repo / "dist/releases"
    outputs.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vsp-release-build-") as temporary:
        root = Path(temporary)
        src = root / "source"
        src.mkdir()
        archive = root / "source.tar"
        command(["git", "-C", str(repo), "archive", "--format=tar", "-o", str(archive), commit])
        with tarfile.open(archive) as tar:
            tar.extractall(src, filter="data")
        env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "no_proxy"}}
        env.update(CGO_ENABLED="0", GOOS="linux", GOARCH="amd64")
        toolchain = {"go": command(["go", "version"], cwd=src / "backend", env=env), "node": command(["node", "--version"], cwd=src / "frontend", env=env), "pnpm": command(["pnpm", "--version"], cwd=src / "frontend", env=env)}
        command(["pnpm", "install", "--frozen-lockfile", "--ignore-scripts"], cwd=src / "frontend", capture=False, env=env)
        command(["pnpm", "run", "build"], cwd=src / "frontend", capture=False, env=env)
        command(["go", "test", "./internal/service", "./cmd/server", "-run", "^TestDeployment", "-count=1"], cwd=src / "backend", capture=False, env=env)
        payload = root / "payload"
        (payload / Path(PRICING).parent).mkdir(parents=True)
        version = (src / "backend/cmd/server/VERSION").read_text().strip()
        created = git("show", "-s", "--format=%cI", commit)
        flags = f"-X main.Commit={commit} -X main.Date={created} -X main.BuildType=release"
        command(["go", "build", "-buildvcs=false", "-tags", "embed", "-trimpath", "-ldflags", flags, "-o", str(payload / "sub2api"), "./cmd/server"], cwd=src / "backend", capture=False, env=env)
        shutil.copyfile(src / "backend" / PRICING, payload / PRICING)
        migrations = {p.name: digest(p) for p in sorted((src / "backend/migrations").glob("*.sql"))}
        gate = src / "backend/internal/service/deployment_worker_gate_linux.go"
        capability = int(gate.is_file() and "const DeploymentWorkerGateVersion = 1" in gate.read_text())
        metadata = {"commit": commit, "tree": git("rev-parse", commit + "^{tree}"), "version": version, "created": created, "platform": "linux-amd64", "migrations": migrations, "worker_gate": capability, "toolchain": toolchain}
        package = root / "release.tar"
        m = create_package(payload, package, metadata)
        target = outputs / (m["id"] + ".tar")
        if target.exists():
            if digest(target) != digest(package):
                raise ReleaseError("existing release ID has different archive bytes")
        else:
            staged = outputs / (m["id"] + ".part-" + uuid.uuid4().hex)
            try:
                shutil.copyfile(package, staged)
                os.link(staged, target)
            finally:
                staged.unlink(missing_ok=True)
        print(target)


def rpc(operation, release=None):
    request = {"operation": operation}
    if release is not None:
        if not ID.fullmatch(release):
            raise ReleaseError("invalid release ID")
        request["release"] = release
    args = ["sudo", "-n", CONTROL]
    if socket.gethostname() != BABEL:
        args = ["ssh", "-T", "-o", "BatchMode=yes", "Babel", "sudo", "-n", CONTROL]
    def call(value):
        r = subprocess.run(args, input=json.dumps(value) + "\n", text=True, capture_output=True)
        if r.returncode:
            raise ReleaseError("release RPC failed; remote job may still be running; use status to inspect it: " + r.stderr[:500].strip())
        return json.loads(r.stdout)
    result = call(request)
    print(json.dumps(result), flush=True)
    if operation == "status": return
    job = result["job"]
    last_phase = "queued"
    deadline = time.monotonic() + 1500
    while time.monotonic() < deadline:
        time.sleep(2)
        result = call({"operation": "status", "job": job})
        phase = result["job"]["phase"]
        if phase != last_phase:
            print(json.dumps(result), flush=True)
            last_phase = phase
        if phase == "complete": return
        if phase in {"rolled_back", "rejected", "recovery_failed"}:
            raise ReleaseError(f"release {job} ended as {phase}; see the reported state")
        if result.get("executor") == "failed":
            raise ReleaseError(f"executor failed before recording a terminal result for {job}; operator review required")
    raise ReleaseError(f"client wait timed out for {job}; remote execution was not cancelled")


def baseline(repo, commit):
    """Package an existing production artifact without rebuilding or relabeling it as new."""
    repo = Path(repo).resolve()
    git = lambda *args: command(["git", "-C", str(repo), *args])
    commit = git("rev-parse", "--verify", commit + "^{commit}")
    old = repo / "dist/native"
    if git("rev-parse", commit + "^{tree}") != (old / "source-tree").read_text().strip():
        raise ReleaseError("baseline commit does not match the recorded production source tree")
    if digest(old / "sub2api") != (old / "sub2api.sha256").read_text().strip(): raise ReleaseError("historical binary checksum mismatch")
    with tempfile.TemporaryDirectory(prefix="vsp-baseline-") as directory:
        payload = Path(directory)
        (payload / Path(PRICING).parent).mkdir(parents=True)
        shutil.copyfile(old / "sub2api", payload / "sub2api")
        (payload / PRICING).write_bytes(subprocess.check_output(["git", "-C", str(repo), "show", commit + ":backend/" + PRICING]))
        names = git("ls-tree", "-r", "--name-only", commit, "--", "backend/migrations").splitlines()
        import hashlib
        migrations = {Path(name).name: hashlib.sha256(subprocess.check_output(["git", "-C", str(repo), "show", commit + ":" + name])).hexdigest() for name in names if name.endswith(".sql")}
        meta = {"commit": commit, "tree": git("rev-parse", commit + "^{tree}"), "version": git("show", commit + ":backend/cmd/server/VERSION"), "created": datetime.datetime.fromtimestamp((old / "sub2api").stat().st_mtime, datetime.timezone.utc).isoformat(), "platform": "linux-amd64", "migrations": migrations, "worker_gate": 0, "toolchain": {"go": "historical-unrecorded", "node": "historical-unrecorded", "pnpm": "historical-unrecorded"}}
        archive = payload / "baseline.tar"
        m = create_package(payload, archive, meta)
        output = repo / "dist/releases" / ("baseline-" + m["id"] + ".tar")
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists(): raise ReleaseError("baseline archive already exists")
        with archive.open("rb") as src, output.open("xb") as dst: shutil.copyfileobj(src, dst)
        print(output)


def upload(package):
    package = Path(package).resolve()
    m = read_package(package)
    name = m["id"] + ".part-" + uuid.uuid4().hex
    if socket.gethostname() == BABEL:
        raise ReleaseError("upload is a Genesis-side operation")
    command(["ssh", "-T", "-o", "BatchMode=yes", "Babel", "test", "-d", str(INCOMING)])
    command(["scp", "-q", "-o", "BatchMode=yes", str(package), f"Babel:{INCOMING}/{name}"], capture=False)
    command(["ssh", "-T", "-o", "BatchMode=yes", "Babel", "/usr/local/bin/vsp-release", "receive", name], capture=False)
    print(m["id"])


def receive(name):
    if socket.gethostname() != BABEL or ".part-" not in name:
        raise ReleaseError("receive is Babel-only")
    release, nonce = name.split(".part-", 1)
    if not ID.fullmatch(release) or not __import__("re").fullmatch(r"[a-f0-9]{32}", nonce):
        raise ReleaseError("invalid upload name")
    path = INCOMING / name
    if path.is_symlink() or read_package(path)["id"] != release:
        raise ReleaseError("upload identity mismatch")
    target = INCOMING / (release + ".tar")
    if target.exists():
        if digest(path) != digest(target):
            raise ReleaseError("a different upload already has this release ID")
        path.unlink()
    else:
        os.link(path, target) # No clobber, even for simultaneous agents.
        path.unlink()


def main():
    if os.geteuid() == 0: raise ReleaseError("do not run the client with sudo; only the fixed RPC is privileged")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="op", required=True)
    b = sub.add_parser("build"); b.add_argument("--repo", default=str(Path(__file__).resolve().parents[2])); b.add_argument("--commit", default="HEAD")
    b = sub.add_parser("baseline"); b.add_argument("--repo", default=str(Path(__file__).resolve().parents[2])); b.add_argument("--commit", required=True)
    sub.add_parser("upload").add_argument("package")
    sub.add_parser("receive").add_argument("name")
    sub.add_parser("deploy").add_argument("release")
    sub.add_parser("status"); sub.add_parser("rollback")
    args = parser.parse_args()
    if args.op in {"build", "baseline"} and socket.gethostname() == BABEL: raise ReleaseError("build/archive work belongs on Genesis, not production")
    if args.op == "build": build(args.repo, args.commit)
    elif args.op == "baseline": baseline(args.repo, args.commit)
    elif args.op == "upload": upload(args.package)
    elif args.op == "receive": receive(args.name)
    else: rpc(args.op, getattr(args, "release", None))


if __name__ == "__main__":
    try: main()
    except (ReleaseError, OSError, tarfile.TarError) as error: raise SystemExit(str(error))
