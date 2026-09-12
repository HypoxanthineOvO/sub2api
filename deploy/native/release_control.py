#!/usr/bin/env python3
"""Root-owned no-argument RPC. sudoers must authorize ONLY its fixed launcher."""
import fcntl
import json
import os
from pathlib import Path
import select
import socket
import sys
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_core import ID, TERMINAL, ReleaseError, decode
from release_host import CONFIG, STATE, atomic, info, load, run, trusted


def parse_request(body):
    request = decode(body)
    if not isinstance(request, dict): raise ReleaseError("invalid request")
    operation = request.get("operation")
    if operation == "deploy":
        if set(request) != {"operation", "release"} or not isinstance(request["release"], str) or not ID.fullmatch(request["release"]): raise ReleaseError("invalid deploy request")
    elif operation == "status":
        if set(request) not in ({"operation"}, {"operation", "job"}): raise ReleaseError("invalid status request")
        if "job" in request and (not isinstance(request["job"], str) or not __import__("re").fullmatch(r"[a-f0-9]{32}", request["job"])): raise ReleaseError("invalid job ID")
    elif operation == "rollback":
        if set(request) != {"operation"}: raise ReleaseError("invalid rollback request")
    else: raise ReleaseError("operation not authorized")
    return request


def main():
    if os.geteuid() != 0: raise ReleaseError("controller requires its authorized sudo launcher")
    cfg = load(CONFIG)
    if socket.gethostname() != cfg["hostname"]: raise ReleaseError("wrong deployment host")
    if len(sys.argv) != 1: raise ReleaseError("controller takes no arguments")
    body = b""
    deadline = time.monotonic() + 5
    while b"\n" not in body and len(body) <= 4096:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([sys.stdin], [], [], remaining)[0]: raise ReleaseError("request input timed out")
        block = os.read(sys.stdin.fileno(), 4097 - len(body))
        if not block: break
        body += block
    if len(body) > 4096: raise ReleaseError("request too large")
    req = parse_request(body)
    trusted(STATE / "request.lock")
    with (STATE / "request.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        active = load(STATE / "active.json")
        current = load(STATE / "request.json") if (STATE / "request.json").exists() else None
        if req["operation"] == "status":
            job = req.get("job", (current or {}).get("job"))
            result = load(STATE / "jobs" / (job + ".json")) if job else {"phase": "idle"}
            print(json.dumps({"active": active, "job": result, "executor": info("vsp-sub2api-release.service")["ActiveState"]}))
            return
        if current:
            previous = load(STATE / "jobs" / (current["job"] + ".json"))
            if previous["phase"] == "recovery_failed": raise ReleaseError("manual recovery required before another release")
            if previous["phase"] not in TERMINAL: raise ReleaseError("another release is queued or running")
        if info("vsp-sub2api-release.service")["ActiveState"] not in {"inactive", "failed"}: raise ReleaseError("release executor is still running or recovering")
        if req["operation"] == "rollback":
            if not active.get("previous"): raise ReleaseError("no previous release recorded")
            release = active["previous"]["release"]
        else: release = req["release"]
        job = uuid.uuid4().hex
        request = {"job": job, "operation": req["operation"], "release": release}
        atomic(STATE / "jobs" / (job + ".json"), {"phase": "queued", "job": job})
        atomic(STATE / "request.json", request)
        try: run("systemctl", "start", "--no-block", "vsp-sub2api-release.service")
        except Exception:
            atomic(STATE / "jobs" / (job + ".json"), {"phase": "rejected", "job": job, "error": "executor_start_failed"})
            raise
        print(json.dumps({"phase": "queued", "job": job}))


if __name__ == "__main__":
    try: main()
    except (ReleaseError, OSError) as error: raise SystemExit(str(error))
    except Exception as error: raise SystemExit(f"request failed ({type(error).__name__}; details redacted)")
