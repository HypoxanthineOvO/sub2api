#!/usr/bin/env python3
"""Health-check and assign distinct Mihomo nodes to local LLM proxy slots."""

from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import json
import os
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


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
PRIMARY_SOURCES = frozenset(("lilis", "main"))
FALLBACK_SOURCES = frozenset(("westdata", "family"))
LOCAL_VERIFY_BATCH_SIZE = 8
LOCAL_VERIFY_BUDGET_SECONDS = 45
PROCESS_RUN_ID = secrets.token_hex(16)


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


def probe_node(
    port: int,
    node: dict[str, Any],
    probe_timeout_ms: int = 5000,
    request_timeout: float = 7,
) -> tuple[str, int | None, str | None]:
    encoded_name = urllib.parse.quote(node["name"], safe="")
    query = urllib.parse.urlencode({"url": TEST_URL, "timeout": probe_timeout_ms})
    try:
        result = api_request(port, f"/proxies/{encoded_name}/delay?{query}", timeout=request_timeout)
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
    verify_candidates: Callable[[str, list[dict[str, Any]]], set[str]] | None = None,
) -> tuple[dict[str, dict[str, str]], str]:
    node_by_name = {node["name"]: node for node in nodes}
    known_sources = PRIMARY_SOURCES | FALLBACK_SOURCES
    healthy = [
        node
        for node in nodes
        if health.get(node["name"], {}).get("healthy") and str(node.get("source", "")) in known_sources
    ]
    if not healthy:
        raise RuntimeError("no healthy LLM proxy nodes")

    assignments = {slot: {} for slot in slots}
    used_nodes: set[str] = set()
    domains_by_slot = {slot: set() for slot in slots}
    duplicate_node = False
    shared_fault_domain = False
    primary_pool_unavailable = False

    for selector in SELECTORS:
        domains_this_rank: set[str] = set()
        for slot in slots:
            old_name = previous_assignments.get(slot, {}).get(selector)
            choices = []
            for node in healthy:
                name = node["name"]
                delay = float(health[name]["delay_ms"])
                score = delay
                if name == old_name:
                    score *= STICKY_FACTOR
                if node["fault_domain"] in domains_this_rank:
                    score += 10_000
                if node["fault_domain"] in domains_by_slot[slot]:
                    score += 3_000
                if name in used_nodes:
                    score += 50_000
                source = str(node.get("source", ""))
                preferred_sources = PRIMARY_SOURCES if selector == "LLM-PRIMARY" else FALLBACK_SOURCES
                alternate_sources = FALLBACK_SOURCES if selector == "LLM-PRIMARY" else PRIMARY_SOURCES
                if source in preferred_sources:
                    pool_rank = 0
                elif source in alternate_sources:
                    pool_rank = 1
                else:
                    pool_rank = 2
                choices.append((pool_rank, score, delay, name, node))

            selected = None
            ordered = sorted(choices)
            for pool_rank in (0, 1):
                pool_choices = [choice for choice in ordered if choice[0] == pool_rank]
                for offset in range(0, len(pool_choices), LOCAL_VERIFY_BATCH_SIZE):
                    batch = pool_choices[offset : offset + LOCAL_VERIFY_BATCH_SIZE]
                    if verify_candidates is None:
                        selected = batch[0] if batch else None
                    else:
                        verified = verify_candidates(slot, [choice[-1] for choice in batch])
                        selected = next((choice for choice in batch if choice[-1]["name"] in verified), None)
                    if selected is not None:
                        break
                if selected is not None:
                    break
            if selected is None:
                raise RuntimeError(f"no healthy node passed verification for {slot} {selector}")
            pool_rank, _, _, name, node = selected
            assignments[slot][selector] = name
            if name in used_nodes:
                duplicate_node = True
            if node["fault_domain"] in domains_this_rank:
                shared_fault_domain = True
            if selector == "LLM-PRIMARY" and pool_rank > 0:
                primary_pool_unavailable = True
            used_nodes.add(name)
            domains_this_rank.add(node["fault_domain"])
            domains_by_slot[slot].add(node["fault_domain"])

    # Defensive check: every selected node must still exist in metadata.
    for slot_values in assignments.values():
        for name in slot_values.values():
            if name not in node_by_name:
                raise RuntimeError(f"unknown assigned node: {name}")
    if primary_pool_unavailable:
        degraded = "primary-pool-unavailable"
    elif duplicate_node:
        degraded = "duplicate-node"
    elif shared_fault_domain:
        degraded = "shared-fault-domain"
    else:
        degraded = "normal"
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
    verification_cache: dict[tuple[str, str], int | None] = {}
    verification_deadline = time.monotonic() + LOCAL_VERIFY_BUDGET_SECONDS

    def verify_candidates(slot: str, candidates: list[dict[str, Any]]) -> set[str]:
        missing = [node for node in candidates if (slot, node["name"]) not in verification_cache]
        remaining = verification_deadline - time.monotonic()
        if missing and remaining > 0:
            port = int(config["slots"][slot]["controller_port"])
            request_timeout = max(0.1, remaining)
            probe_timeout_ms = max(50, min(5000, int(max(0.05, remaining - 0.1) * 1000)))
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(LOCAL_VERIFY_BATCH_SIZE, len(missing))) as executor:
                futures = [
                    executor.submit(probe_node, port, node, probe_timeout_ms, request_timeout)
                    for node in missing
                ]
                for future in concurrent.futures.as_completed(futures):
                    name, delay, _ = future.result()
                    verification_cache[(slot, name)] = delay
        return {
            node["name"]
            for node in candidates
            if verification_cache.get((slot, node["name"])) is not None
        }

    assignments, degraded = assign_nodes(
        slots,
        config["nodes"],
        health,
        previous.get("assignments", {}),
        verify_candidates,
    )
    apply_assignments(config["slots"], assignments)
    assignment_probe_ms = {
        slot: {
            selector: verification_cache.get((slot, node_name))
            for selector, node_name in slot_assignments.items()
        }
        for slot, slot_assignments in assignments.items()
    }
    state = {
        "run_id": PROCESS_RUN_ID,
        "updated_at": int(time.time()),
        "test_url": TEST_URL,
        "degraded": degraded,
        "assignments": assignments,
        "assignment_probe_ms": assignment_probe_ms,
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
            delay = state.get("assignment_probe_ms", {}).get(slot, {}).get(selector)
            if delay is None and "assignment_probe_ms" not in state:
                delay = state.get("health", {}).get(name, {}).get("last_probe_ms")
            displayed_delay = f"{delay}ms" if delay is not None else "unavailable"
            print(
                f"  {selector:<16} {name} delay={displayed_delay} "
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
