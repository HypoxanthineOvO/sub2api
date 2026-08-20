#!/usr/bin/env python3
"""Health-check and assign distinct Mihomo nodes to local LLM proxy slots."""

from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


HOME = Path.home()
CONFIG_PATH = HOME / ".config/llm-proxy/nodes.json"
STATE_PATH = HOME / ".local/state/llm-proxy/allocator.json"
LOCK_PATH = HOME / ".local/state/llm-proxy/allocator.lock"
TEST_URL = "https://chatgpt.com/cdn-cgi/trace"
SELECTORS = ("LLM-PRIMARY", "LLM-BACKUP-1", "LLM-BACKUP-2")
FAILURES_BEFORE_EVICT = 3
MAX_DELAY_MS = 4000
EWMA_NEW_WEIGHT = 0.4
STICKY_FACTOR = 0.75
MAIN_SOURCE_PENALTY_MS = 1200


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def api_request(port: int, path: str, method: str = "GET", payload: dict | None = None, timeout: float = 7) -> Any:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        body = response.read()
    return json.loads(body) if body else {}


def wait_for_controller(port: int, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            api_request(port, "/version", timeout=2)
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"Mihomo controller 127.0.0.1:{port} did not become ready")


def probe_node(port: int, node: dict[str, Any]) -> tuple[str, int | None, str | None]:
    encoded_name = urllib.parse.quote(node["name"], safe="")
    query = urllib.parse.urlencode({"url": TEST_URL, "timeout": 5000})
    try:
        result = api_request(port, f"/proxies/{encoded_name}/delay?{query}", timeout=7)
        delay = int(result.get("delay", 0))
        if delay <= 0 or delay > MAX_DELAY_MS:
            return node["name"], None, f"delay out of range: {delay}"
        return node["name"], delay, None
    except Exception as exc:
        return node["name"], None, str(exc)


def update_health(nodes: list[dict[str, Any]], controller_port: int, previous: dict[str, Any]) -> dict[str, Any]:
    old_health = previous.get("health", {})
    results: dict[str, tuple[int | None, str | None]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(nodes))) as executor:
        futures = [executor.submit(probe_node, controller_port, node) for node in nodes]
        for future in concurrent.futures.as_completed(futures):
            name, delay, error = future.result()
            results[name] = (delay, error)

    health: dict[str, Any] = {}
    now = int(time.time())
    for node in nodes:
        name = node["name"]
        delay, error = results.get(name, (None, "missing result"))
        old = old_health.get(name, {})
        if delay is not None:
            old_delay = old.get("delay_ms")
            smoothed = delay if old_delay is None else round(old_delay * (1 - EWMA_NEW_WEIGHT) + delay * EWMA_NEW_WEIGHT)
            health[name] = {
                "delay_ms": smoothed,
                "last_probe_ms": delay,
                "failures": 0,
                "healthy": True,
                "error": None,
                "checked_at": now,
            }
        else:
            failures = int(old.get("failures", 0)) + 1
            retained_delay = old.get("delay_ms")
            retained = retained_delay is not None and failures < FAILURES_BEFORE_EVICT
            health[name] = {
                "delay_ms": round(retained_delay * 1.25) if retained else None,
                "last_probe_ms": None,
                "failures": failures,
                "healthy": retained,
                "error": error,
                "checked_at": now,
            }
    return health


def assign_nodes(
    slots: list[str],
    nodes: list[dict[str, Any]],
    health: dict[str, Any],
    previous_assignments: dict[str, Any],
) -> tuple[dict[str, dict[str, str]], str]:
    node_by_name = {node["name"]: node for node in nodes}
    healthy = [node for node in nodes if health.get(node["name"], {}).get("healthy")]
    if not healthy:
        raise RuntimeError("no healthy LLM proxy nodes")

    assignments = {slot: {} for slot in slots}
    used_nodes: set[str] = set()
    domains_by_slot = {slot: set() for slot in slots}
    degraded = "normal"

    for selector in SELECTORS:
        domains_this_rank: set[str] = set()
        for slot in slots:
            old_name = previous_assignments.get(slot, {}).get(selector)
            unused_healthy_us = any(
                node.get("region") == "US" and node["name"] not in used_nodes
                for node in healthy
            )
            choices = []
            for node in healthy:
                name = node["name"]
                delay = float(health[name]["delay_ms"])
                score = delay
                if unused_healthy_us and node.get("region") != "US":
                    score += 100_000
                if int(node.get("priority", 1)) > 0:
                    score += MAIN_SOURCE_PENALTY_MS
                if name == old_name:
                    score *= STICKY_FACTOR
                if node["fault_domain"] in domains_this_rank:
                    score += 10_000
                if node["fault_domain"] in domains_by_slot[slot]:
                    score += 3_000
                if name in used_nodes:
                    score += 50_000
                choices.append((score, delay, name, node))
            _, _, name, node = min(choices)
            assignments[slot][selector] = name
            if name in used_nodes:
                degraded = "duplicate-node"
            elif node["fault_domain"] in domains_this_rank and degraded == "normal":
                degraded = "shared-fault-domain"
            used_nodes.add(name)
            domains_this_rank.add(node["fault_domain"])
            domains_by_slot[slot].add(node["fault_domain"])

    # Defensive check: every selected node must still exist in metadata.
    for slot_values in assignments.values():
        for name in slot_values.values():
            if name not in node_by_name:
                raise RuntimeError(f"unknown assigned node: {name}")
    return assignments, degraded


def apply_assignments(slot_config: dict[str, Any], assignments: dict[str, dict[str, str]]) -> None:
    for slot, selectors in assignments.items():
        port = int(slot_config[slot]["controller_port"])
        for selector, node in selectors.items():
            encoded = urllib.parse.quote(selector, safe="")
            api_request(port, f"/proxies/{encoded}", method="PUT", payload={"name": node}, timeout=5)


def run_once(config: dict[str, Any], previous: dict[str, Any], state_path: Path = STATE_PATH) -> dict[str, Any]:
    slots = sorted(config["slots"])
    first_controller = int(config["slots"][slots[0]]["controller_port"])
    for slot in slots:
        wait_for_controller(int(config["slots"][slot]["controller_port"]))
    health = update_health(config["nodes"], first_controller, previous)
    assignments, degraded = assign_nodes(slots, config["nodes"], health, previous.get("assignments", {}))
    apply_assignments(config["slots"], assignments)
    state = {
        "updated_at": int(time.time()),
        "test_url": TEST_URL,
        "degraded": degraded,
        "assignments": assignments,
        "health": health,
    }
    atomic_json(state_path, state)
    return state


def print_status(config: dict[str, Any], state: dict[str, Any]) -> None:
    nodes = {node["name"]: node for node in config.get("nodes", [])}
    print(f"LLM proxy allocator: {state.get('degraded', 'not initialized')}")
    updated = state.get("updated_at")
    if updated:
        print(f"updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(updated))}")
    for slot in sorted(config.get("slots", {})):
        mixed_port = config["slots"][slot]["mixed_port"]
        values = state.get("assignments", {}).get(slot, {})
        print(f"{slot} http/socks=127.0.0.1:{mixed_port}")
        for selector in SELECTORS:
            name = values.get(selector, "unassigned")
            node = nodes.get(name, {})
            delay = state.get("health", {}).get(name, {}).get("delay_ms")
            print(
                f"  {selector:<16} {name} delay={delay}ms "
                f"source={node.get('source', '?')} region={node.get('region', '?')} "
                f"ingress={node.get('resolved_ip', node.get('fault_domain', '?'))}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    config = read_json(args.config, {})
    if not config:
        print(f"missing config: {args.config}", file=sys.stderr)
        return 2
    previous = read_json(args.state, {})
    if args.status:
        print_status(config, previous)
        return 0

    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("allocator is already running", file=sys.stderr)
            return 1
        while True:
            try:
                state = run_once(config, previous, args.state)
                print_status(config, state)
                previous = state
            except Exception as exc:
                print(f"allocator error: {exc}", file=sys.stderr, flush=True)
            if args.once:
                return 0
            time.sleep(max(15, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
