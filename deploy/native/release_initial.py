#!/usr/bin/env python3
"""One-time maintenance-window start. NOT authorized by the Agent sudoers rule."""
import argparse
import fcntl
import os
from pathlib import Path
import socket
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_core import ID, TERMINAL, ReleaseError
from release_host import CONFIG, STATE, atomic, info, load, run, trusted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release")
    parser.add_argument("--maintenance-window", action="store_true", help="confirm an operator-chosen quiet window; brief downtime is permitted")
    args = parser.parse_args()
    if os.geteuid() != 0 or not args.maintenance_window or not ID.fullmatch(args.release): parser.error("administrator and explicit maintenance window required")
    cfg = load(CONFIG)
    if socket.gethostname() != cfg["hostname"]: raise ReleaseError("wrong deployment host")
    trusted(STATE / "request.lock")
    with (STATE / "request.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if info("vsp-sub2api-release.service")["ActiveState"] not in {"inactive", "failed"}: raise ReleaseError("executor is busy")
        if (STATE / "request.json").exists():
            previous = load(STATE / "request.json")
            phase = load(STATE / "jobs" / (previous["job"] + ".json"))["phase"]
            if phase not in TERMINAL or phase == "recovery_failed": raise ReleaseError("unresolved prior transaction")
        job = uuid.uuid4().hex
        atomic(STATE / "jobs" / (job + ".json"), {"phase": "queued", "job": job, "maintenance": True})
        atomic(STATE / "request.json", {"job": job, "operation": "initialize", "release": args.release})
        try: run("systemctl", "start", "--no-block", "vsp-sub2api-release.service")
        except Exception:
            atomic(STATE / "jobs" / (job + ".json"), {"phase": "rejected", "job": job, "error": "executor_start_failed"})
            raise
        print(f"Maintenance start queued: {job}. Inspect vsp-release status; queued is not success.")


if __name__ == "__main__":
    try: main()
    except (ReleaseError, OSError) as error: raise SystemExit(str(error))
