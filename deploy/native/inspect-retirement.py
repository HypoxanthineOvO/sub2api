#!/usr/bin/env python3
"""Read-only, redacted preflight for retiring the old VSP proxy plane.

Run as root to inspect protected app environments, cron and process metadata.
This tool never changes files, queries business data, or starts/stops services.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
from urllib.parse import urlsplit


HOSTS = {"genesis": "genesis", "babel": "iZuf668tiyo0blc17ihbtyZ"}
RETIRED = re.compile(
    r"allocator|selected.node|mihomo-llm|llm-proxy|proxy_dashboard|"
    r"apply_sub_pool|refresh_xyz|revive_daily|revive_test|update_sub_nodes|"
    r"slot-[a-f]|1790[1-57]|2909[1-6]|1929[01]",
    re.IGNORECASE,
)
ENV_KEYS = {
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
    "all_proxy", "SELECTED_NODE_ENABLED", "SELECTED_NODE_ENDPOINT",
    "SELECTED_NODE_PROXY_SLOTS",
}


def command(*args: str) -> str:
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=15,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
    )
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed (exit {result.returncode})")
    return result.stdout


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def environment_summary(text: str, separator: str = "\n") -> dict:
    summary = {}
    for line in text.split(separator):
        key, sep, value = line.strip().partition("=")
        if not sep or key not in ENV_KEYS:
            continue
        value = value.strip().strip("\"'")
        if key == "SELECTED_NODE_ENABLED":
            summary[key] = value if value.lower() in {"true", "false", "0", "1"} else "other"
        elif key == "SELECTED_NODE_PROXY_SLOTS":
            summary[key] = {"configured": bool(value and value != "{}")}
        else:
            try:
                url = urlsplit(value)
                summary[key] = {
                    "scheme": url.scheme, "host": url.hostname, "port": url.port,
                    "retired_port": url.port in {17901, 17902, 17903, 17904, 17905, 17907, 19290, 19291, 29091, 29092, 29093, 29094, 29095, 29096},
                }
            except ValueError:
                summary[key] = "unparseable (value redacted)"
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, choices=HOSTS)
    args = parser.parse_args()
    if socket.gethostname() != HOSTS[args.host]:
        parser.error("host does not match the selected environment")
    if os.geteuid() != 0:
        parser.error("run with sudo to obtain the protected, read-only preflight")

    report = {"host": args.host, "mode": "read-only", "errors": []}
    units = [
        "vsp-sub2api-production.target", "vsp-sub2api-rehearsal.target",
        "vsp-sub2api-app-slot@blue.service", "vsp-sub2api-app-slot@green.service",
        "vsp-sub2api-app@production.service", "vsp-sub2api-app@rehearsal.service",
        "vsp-postgresql@production.service", "vsp-redis@production.service",
        "vsp-mihomo-production@general.service", "vsp-proxy-allocator@production.service",
        "vsp-selected-node@production.service", "vsp-proxy-dashboard.service",
    ] + [f"vsp-mihomo-production@slot-{letter}.service" for letter in "abcdef"]
    properties = ["Id", "LoadState", "ActiveState", "UnitFileState", "MainPID", "Requires", "Wants", "PartOf", "TriggeredBy", "DropInPaths"]
    report["units"] = command("systemctl", "show", *units, "--property=" + ",".join(properties))
    report["environments"] = {}
    report["other_retired_environment_keys"] = {}
    for profile in ["production", "rehearsal"]:
        root = Path("/etc/vsp-sub2api") / profile
        for name in ["app.env", "app-blue.env", "app-green.env"]:
            path = root / name
            if path.exists():
                content = read_text(path)
                report["environments"][str(path)] = environment_summary(content)
                report["other_retired_environment_keys"][str(path)] = [
                    key for line in content.splitlines()
                    for key, sep, value in [line.strip().partition("=")]
                    if sep and key not in ENV_KEYS and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
                    and RETIRED.search(value)
                ]
    report["running_app_environments"] = {}
    for slot in ["blue", "green"]:
        pid = command("systemctl", "show", f"vsp-sub2api-app-slot@{slot}.service", "-p", "MainPID", "--value").strip()
        if pid.isdigit() and int(pid):
            try:
                report["running_app_environments"][slot] = environment_summary(read_text(Path(f"/proc/{pid}/environ")), "\0")
            except OSError:
                report["errors"].append(f"cannot inspect {slot} process environment")
    report["reference_files"] = []
    candidates = [Path("/etc/crontab")]
    for directory in ["/etc/cron.d", "/etc/cron.daily", "/etc/systemd/system", "/etc/nginx/sites-enabled", "/etc/nginx/conf.d", "/etc/sudoers.d"]:
        root = Path(directory)
        if root.exists():
            candidates.extend(root.rglob("*"))
    for path in sorted(set(candidates)):
        try:
            if path.is_file() and RETIRED.search(read_text(path)):
                report["reference_files"].append(str(path))
        except OSError:
            report["errors"].append(f"cannot inspect {path}")
    cron = subprocess.run(["crontab", "-l", "-u", "root"], capture_output=True, text=True, timeout=10)
    report["root_cron_retired_jobs"] = [
        i for i, line in enumerate(cron.stdout.splitlines(), 1)
        if not line.lstrip().startswith("#") and RETIRED.search(line)
    ]
    if cron.returncode not in (0, 1):
        report["errors"].append("root crontab could not be inspected")
    report["listeners"] = [
        line for line in command("ss", "-lntp").splitlines()
        if re.search(r":(?:7890|7892|1790[1-7]|1929[01]|1982[12]|2909[0-6])\b", line)
    ]
    report["notes"] = [
        "No service or configuration changes were made.",
        "Reference files and root cron line numbers require review before deletion.",
        "General proxy, app, PostgreSQL, Redis, Nginx and Tunnel must remain running.",
        "Retirement does not authorize deleting databases, account records, backups or shared containers.",
    ]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
