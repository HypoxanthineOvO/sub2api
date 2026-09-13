#!/usr/bin/env python3
"""Fixed systemd service entry; recovery is also invoked by ExecStopPost."""
import fcntl
import os
from pathlib import Path
import socket
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_core import InitialEngine, Engine, ReleaseError, TERMINAL
from release_host import CONFIG, STATE, Host, atomic, load, trusted


def schema_operation(req, initial, recovering):
    from release_schema_core import SchemaEngine
    from release_schema_host import SchemaHost
    if recovering and initial['phase'] in TERMINAL: return
    host = None
    try:
        host = SchemaHost(req['job'], accept_unrehearsed=req.get('accept_unrehearsed', False))
        engine = SchemaEngine(host)
        if recovering:
            if initial.get('schema_rehearsal'):
                host.recover_rehearsal()
            elif 'old' in initial:
                engine.recover(force=req['operation'] == 'schema-abort')
            else:
                host.save_journal({'phase': 'rejected', 'error': 'interrupted_before_schema_transaction'})
        elif req['operation'] == 'schema-rehearse':
            host.save_journal({'phase': 'schema_rehearsing', 'schema_rehearsal': True})
            host.rehearse(req['database'])
        elif req['operation'] == 'schema-stage':
            host.import_package(req['release'])
            old = host.active()
            candidate = {'slot': 'green' if old['slot'] == 'blue' else 'blue', 'release': req['release']}
            engine.stage(candidate, req['expected_old'], req['database'])
        elif req['operation'] == 'schema-activate':
            engine.activate()
        elif req['operation'] == 'schema-abort':
            engine.abort()
        else:
            raise ReleaseError('unknown schema operation')
    except Exception:
        path = STATE / 'jobs' / (req['job'] + '.json')
        current = load(path)
        if recovering:
            current.update(phase='recovery_failed', error='schema_recovery_failed')
        elif 'old' not in current and not current.get('schema_rehearsal'):
            current.update(phase='rejected', error='schema_preflight_failed')
        else:
            current['error'] = 'schema_operation_failed'
        atomic(path, current)
        raise ReleaseError('schema operation failed; inspect status and private backup checkpoint') from None


def main():
    if os.geteuid() != 0: raise ReleaseError("runner is administrator-only")
    cfg = load(CONFIG)
    if socket.gethostname() != cfg["hostname"]: raise ReleaseError("wrong deployment host")
    if sys.argv[1:] not in ([], ["--recover"]): raise ReleaseError("invalid runner arguments")
    trusted(STATE / "operation.lock")
    with (STATE / "operation.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        req = load(STATE / "request.json")
        job_path = STATE / "jobs" / (req["job"] + ".json")
        initial = load(job_path)
        if req['operation'].startswith('schema-'):
            schema_operation(req, initial, '--recover' in sys.argv)
            return
        if "--recover" in sys.argv:
            if initial["phase"] in TERMINAL: return
            if "old" not in initial:
                atomic(job_path, {"phase": "rejected", "job": req["job"], "error": "interrupted_before_transaction"})
                return
            engine = InitialEngine if initial.get("maintenance") else Engine
            try:
                host = Host(req["job"], rolling_back=bool(initial.get("explicit_rollback")))
                if initial.get("explicit_rollback"): host.prepare(initial["old"])
                engine(host).recover()
            except Exception as error:
                result = load(job_path)
                if result["phase"] not in TERMINAL:
                    result.update(phase="recovery_failed", error=type(error).__name__)
                    atomic(job_path, result)
                raise
            return
        host = Host(req["job"], rolling_back=req["operation"] == "rollback")
        try:
            host.import_package(req["release"])
            active = host.active()
            candidate = {"slot": "green" if active["slot"] == "blue" else "blue", "release": req["release"]}
            if req["operation"] == "rollback":
                host.preflight(active, candidate)
                target = {**candidate, "previous": {"slot": active["slot"], "release": active["release"]}}
                host.save_journal({"phase": "switching", "explicit_rollback": True, "old": target, "new": active})
                host.prepare(target)
                Engine(host).recover()
                return
            engine = InitialEngine if req["operation"] == "initialize" else Engine
            engine(host).execute(candidate)
        except Exception as error:
            current = host.journal() or initial
            if "old" not in current:
                current["phase"] = "rejected"
            current["error"] = str(error) if isinstance(error, ReleaseError) else type(error).__name__
            host.save_journal(current)
            raise


if __name__ == "__main__":
    try: main()
    except (ReleaseError, OSError) as error: raise SystemExit(str(error))
    except Exception as error: raise SystemExit(f"executor failed ({type(error).__name__}; details redacted)")
