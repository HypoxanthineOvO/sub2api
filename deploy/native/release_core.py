"""Managed release format and transaction engine. No privileged shell hooks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tarfile

FORMAT = 1
PRICING = "resources/model-pricing/model_prices_and_context_window.json"
FILES = ("sub2api", PRICING)
ID = re.compile(r"[0-9a-f]{12}-[0-9a-f]{12}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
TERMINAL = {"complete", "rolled_back", "recovery_failed", "rejected"}


class ReleaseError(Exception):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(path):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseError("duplicate JSON key")
        result[key] = value
    return result


def decode(data):
    try:
        return json.loads(data, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as error:
        raise ReleaseError("invalid JSON") from error


def validate_manifest(m):
    keys = {"format", "id", "commit", "tree", "version", "created", "platform", "files", "migrations", "worker_gate", "toolchain"}
    if not isinstance(m, dict) or set(m) != keys or type(m["format"]) is not int or m["format"] != FORMAT:
        raise ReleaseError("unsupported manifest schema")
    if not isinstance(m["commit"], str) or not COMMIT.fullmatch(m["commit"]) or not isinstance(m["tree"], str) or not COMMIT.fullmatch(m["tree"]):
        raise ReleaseError("invalid source identity")
    if m["platform"] != "linux-amd64" or type(m["worker_gate"]) is not int or m["worker_gate"] not in (0, 1):
        raise ReleaseError("unsupported runtime capability")
    if not isinstance(m["files"], dict) or set(m["files"]) != set(FILES):
        raise ReleaseError("unexpected release files")
    for name, item in m["files"].items():
        limit = 300 * 1024 * 1024 if name == "sub2api" else 10 * 1024 * 1024
        if not isinstance(item, dict) or set(item) != {"sha256", "size"} or not isinstance(item["sha256"], str) or not SHA.fullmatch(item["sha256"]) or type(item["size"]) is not int or not 0 < item["size"] <= limit:
            raise ReleaseError("invalid file manifest")
    if not isinstance(m["migrations"], dict) or not m["migrations"] or len(m["migrations"]) > 4096:
        raise ReleaseError("invalid migration manifest")
    for name, checksum in m["migrations"].items():
        if not re.fullmatch(r"[0-9]+[a-z]?_[A-Za-z0-9_-]+\.sql", name) or not isinstance(checksum, str) or not SHA.fullmatch(checksum):
            raise ReleaseError("invalid migration entry")
    for key in ("version", "created"):
        if not isinstance(m[key], str) or not re.fullmatch(r"[A-Za-z0-9_.:+-]{1,80}", m[key]):
            raise ReleaseError("invalid version/timestamp")
    if not isinstance(m["toolchain"], dict) or set(m["toolchain"]) != {"go", "node", "pnpm"} or any(not isinstance(v, str) or len(v) > 150 or "\n" in v for v in m["toolchain"].values()):
        raise ReleaseError("invalid toolchain metadata")
    expected = m["commit"][:12] + "-" + hashlib.sha256(canonical(m["files"])).hexdigest()[:12]
    if m["id"] != expected:
        raise ReleaseError("release ID does not match payload identity")
    return m


def read_package(path, destination=None):
    """Read a bounded, uncompressed tar; never use extractall or honor tar modes."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 320 * 1024 * 1024:
        raise ReleaseError("release package missing or too large")
    manifest = None
    seen = set()
    with tarfile.open(path, "r:") as archive:
        for member in archive:
            if len(seen) >= 3 or member.name in seen or not member.isfile() or member.pax_headers or member.type != tarfile.REGTYPE:
                raise ReleaseError("unsupported/duplicate archive member")
            if member.name not in {"manifest.json", *FILES}:
                raise ReleaseError("unexpected archive path")
            seen.add(member.name)
            if manifest is None:
                if member.name != "manifest.json" or not 0 < member.size <= 512 * 1024:
                    raise ReleaseError("manifest must be first and bounded")
                manifest = validate_manifest(decode(archive.extractfile(member).read()))
                if destination:
                    (Path(destination) / "manifest.json").write_bytes(canonical(manifest) + b"\n")
                continue
            info = manifest["files"][member.name]
            if member.size != info["size"]:
                raise ReleaseError("archive size mismatch")
            source = archive.extractfile(member)
            target = None
            if destination:
                output = Path(destination) / member.name
                output.parent.mkdir(parents=True, exist_ok=True)
                target = output.open("xb")
            checksum = hashlib.sha256()
            count = 0
            prefix = b""
            try:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    count += len(block)
                    if count > info["size"]:
                        raise ReleaseError("payload exceeds declared size")
                    if not prefix:
                        prefix = block[:20]
                    checksum.update(block)
                    if target:
                        target.write(block)
            finally:
                if target:
                    target.close()
            if count != info["size"] or checksum.hexdigest() != info["sha256"]:
                raise ReleaseError("payload checksum mismatch")
            if member.name == "sub2api" and (prefix[:6] != b"\x7fELF\x02\x01" or prefix[18:20] != b">\x00"):
                raise ReleaseError("binary must be Linux x86-64 ELF")
    if seen != {"manifest.json", *FILES}:
        raise ReleaseError("incomplete release package")
    return manifest


def create_package(source, output, metadata):
    source, output = Path(source), Path(output)
    files = {name: {"sha256": digest(source / name), "size": (source / name).stat().st_size} for name in FILES}
    m = {"format": FORMAT, **metadata, "files": files}
    m["id"] = m["commit"][:12] + "-" + hashlib.sha256(canonical(files)).hexdigest()[:12]
    validate_manifest(m)
    (source / "manifest.json").write_bytes(canonical(m) + b"\n")
    if output.exists():
        raise ReleaseError("refusing to replace an existing artifact")
    with tarfile.open(output, "x", format=tarfile.USTAR_FORMAT) as archive:
        for name in ("manifest.json", *FILES):
            info = archive.gettarinfo(str(source / name), arcname=name)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.mode = 0o755 if name == "sub2api" else 0o644
            with (source / name).open("rb") as stream:
                archive.addfile(info, stream)
    read_package(output)
    return m


class Engine:
    """Durable last-known-good transaction. Adapter contains host operations.

    Every mutating operation is preceded by a durable journal write. Recovery
    always restores the saved old route; it never kills a serving process.
    Successful releases keep the previous process as a worker-gated hot standby.
    """
    def __init__(self, host):
        self.host = host

    def execute(self, candidate):
        h = self.host
        old = h.active()
        h.preflight(old, candidate)
        journal = {"phase": "preparing", "old": old, "new": candidate}
        h.save_journal(journal)
        try:
            h.prepare(candidate)
            h.healthy(candidate, direct=True)
            journal["phase"] = "workers"
            h.save_journal(journal)
            h.transfer_workers(candidate)
            h.healthy(candidate, direct=True)
            journal["phase"] = "switching"
            h.save_journal(journal)
            generations = h.route(candidate)
            journal["phase"] = "observing"
            h.save_journal(journal)
            h.observe(candidate, generations)
            h.healthy(candidate, direct=False)
            # No old process stop after final health: it remains available for rollback.
            h.commit(candidate, old)
            journal["phase"] = "complete"
            h.save_journal(journal)
        except Exception:
            self.recover()
            raise

    def recover(self):
        h = self.host
        journal = h.journal()
        if not journal or journal["phase"] in TERMINAL:
            return
        old = journal["old"]
        try:
            h.healthy(old, direct=True)
            if journal["phase"] not in {"preparing", "workers"}:
                h.route(old)
            h.healthy(old, direct=False)
            if journal["phase"] != "preparing":
                h.transfer_workers(old)
            h.restore_committed(old)
            journal["phase"] = "complete" if journal.get("explicit_rollback") else "rolled_back"
            h.save_journal(journal)
            # Leave the candidate alive. It may still own accepted HTTP requests;
            # after worker handover it cannot execute new autonomous jobs.
        except Exception:
            journal["phase"] = "recovery_failed"
            h.save_journal(journal)
            raise ReleaseError("recovery could not be verified; both applications were left untouched")


class InitialEngine:
    """One-time administrator maintenance window; short downtime is permitted.

    This is deliberately stop/start with restoration of the old version, not a
    legacy hot-worker migration. Ordinary Engine transactions remain unchanged.
    """
    def __init__(self, host): self.host = host

    def execute(self, candidate):
        h = self.host; old = h.active()
        h.preflight(old, candidate, allow_legacy=True)
        journal = {"phase": "initial_preparing", "maintenance": True, "old": old, "new": candidate}
        h.save_journal(journal)
        try:
            h.prepare(candidate)
            h.healthy(candidate, direct=True)
            journal["phase"] = "initial_switching"; h.save_journal(journal)
            h.stop_initial_old(old)
            h.transfer_workers(candidate)
            h.route(candidate)
            # The operator accepted a maintenance window, not zero-loss handling
            # of the old Nginx generation. Do not add a legacy hot-swap protocol.
            h.observe(candidate, [])
            h.healthy(candidate, direct=False)
            h.commit(candidate, old)
            journal["phase"] = "complete"; h.save_journal(journal)
        except Exception:
            self.recover()
            raise

    def recover(self):
        h = self.host; journal = h.journal()
        if not journal or journal["phase"] in TERMINAL: return
        old = journal["old"]
        try:
            h.restore_initial_app(old, journal["new"])
            if journal["phase"] != "initial_preparing": h.route(old)
            h.healthy(old, direct=False)
            h.restore_committed(old)
            journal["phase"] = "rolled_back"; h.save_journal(journal)
        except Exception:
            journal["phase"] = "recovery_failed"; h.save_journal(journal)
            raise ReleaseError("initial start/restore failed; administrator intervention is required")
