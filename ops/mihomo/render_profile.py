#!/usr/bin/env python3
"""Render isolated VSP Sub2API Mihomo, allocator, and Selected Node configs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml


SLOTS = ("slot-a", "slot-b", "slot-c", "slot-d", "slot-e")
PROFILE_PORTS = {
    "production": {
        "mixed": range(17901, 17906),
        "controller": range(29091, 29096),
        "selected_node": 19090,
    },
    "rehearsal": {
        "mixed": range(18901, 18906),
        "controller": range(29191, 29196),
        "selected_node": 19190,
    },
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o600)


def render_mihomo(source_root: Path, output_root: Path, profile: str) -> None:
    ports = PROFILE_PORTS[profile]
    for slot, mixed_port, controller_port in zip(
        SLOTS, ports["mixed"], ports["controller"], strict=True
    ):
        source = source_root / slot / "config.yaml"
        config = yaml.safe_load(source.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError(f"expected YAML mapping: {source}")
        if config.get("bind-address") != "127.0.0.1" or config.get("allow-lan") is not False:
            raise ValueError(f"source Mihomo config is not loopback-only: {source}")
        config["mixed-port"] = mixed_port
        config["bind-address"] = "127.0.0.1"
        config["allow-lan"] = False
        config["external-controller"] = f"127.0.0.1:{controller_port}"
        rendered = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
        write_private(output_root / "mihomo" / slot / "config.yaml", rendered)


def render_allocator(source: Path, output_root: Path, profile: str) -> None:
    config = load_json(source)
    slots = config.get("slots")
    if not isinstance(slots, dict) or set(slots) != set(SLOTS):
        raise ValueError("allocator config must contain exactly slot-a through slot-e")
    ports = PROFILE_PORTS[profile]
    for slot, mixed_port, controller_port in zip(
        SLOTS, ports["mixed"], ports["controller"], strict=True
    ):
        slots[slot] = {"mixed_port": mixed_port, "controller_port": controller_port}
    write_private(output_root / "allocator.json", json.dumps(config, indent=2) + "\n")


def render_selected_node(source: Path, output_root: Path, profile: str) -> None:
    config = load_json(source)
    if config.get("bind_host") not in {"127.0.0.1", "172.17.0.1"}:
        raise ValueError("Selected Node source config must use loopback or the legacy Docker bridge")
    slots = config.get("slots")
    expected_names = tuple(f"Slot {letter}" for letter in "ABCDE")
    if not isinstance(slots, dict) or set(slots) != set(expected_names):
        raise ValueError("Selected Node config must contain exactly Slot A through Slot E")
    ports = PROFILE_PORTS[profile]
    config["bind_host"] = "127.0.0.1"
    config["bind_port"] = ports["selected_node"]
    for slot_name, controller_port in zip(expected_names, ports["controller"], strict=True):
        slot = slots[slot_name]
        if not isinstance(slot, dict):
            raise ValueError(f"invalid Selected Node slot: {slot_name}")
        slot["controller_url"] = f"http://127.0.0.1:{controller_port}"
    write_private(output_root / "selected-node.json", json.dumps(config, indent=2) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=sorted(PROFILE_PORTS), required=True)
    parser.add_argument("--mihomo-source-root", type=Path, required=True)
    parser.add_argument("--allocator-source", type=Path, required=True)
    parser.add_argument("--selected-node-source", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = args.output_root.resolve()
    render_mihomo(args.mihomo_source_root, output_root, args.profile)
    render_allocator(args.allocator_source, output_root, args.profile)
    render_selected_node(args.selected_node_source, output_root, args.profile)
    print(f"rendered {args.profile} profile at {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
