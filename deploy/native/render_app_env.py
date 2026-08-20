#!/usr/bin/env python3
"""Render a native Sub2API app env from an existing container env."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


PROFILES = {
    "production": {
        "SERVER_HOST": "127.0.0.1",
        "SERVER_PORT": "19821",
        "DATABASE_HOST": "127.0.0.1",
        "DATABASE_PORT": "5432",
        "REDIS_HOST": "127.0.0.1",
        "REDIS_PORT": "6379",
        "SELECTED_NODE_ENDPOINT": "http://127.0.0.1:19090/v1/selected-nodes",
        "DATA_DIR": "/var/lib/vsp-sub2api/production/app",
        "PRICING_DATA_DIR": "/var/lib/vsp-sub2api/production/app/data",
        "PRICING_FALLBACK_FILE": "/opt/vsp-sub2api/current/resources/model-pricing/model_prices_and_context_window.json",
        "SUB2API_DISABLE_AUTONOMOUS_WORKERS": "0",
    },
    "rehearsal": {
        "SERVER_HOST": "127.0.0.1",
        "SERVER_PORT": "19822",
        "DATABASE_HOST": "127.0.0.1",
        "DATABASE_PORT": "55432",
        "REDIS_HOST": "127.0.0.1",
        "REDIS_PORT": "56379",
        "SELECTED_NODE_ENDPOINT": "http://127.0.0.1:19190/v1/selected-nodes",
        "DATA_DIR": "/var/lib/vsp-sub2api/rehearsal/app",
        "PRICING_DATA_DIR": "/var/lib/vsp-sub2api/rehearsal/app/data",
        "PRICING_FALLBACK_FILE": "/opt/vsp-sub2api/current/resources/model-pricing/model_prices_and_context_window.json",
        "SUB2API_DISABLE_AUTONOMOUS_WORKERS": "1",
        "TOKEN_REFRESH_ENABLED": "false",
        "GATEWAY_CN_PROVIDERS_BALANCE_CHECK_ENABLED": "false",
        "CHANNEL_MONITOR_V2_DISABLE_AGGREGATOR": "1",
    },
}


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def render(source: Path, output: Path, profile: str) -> None:
    values = read_env(source)
    required = {
        "DATABASE_USER",
        "DATABASE_PASSWORD",
        "DATABASE_DBNAME",
        "JWT_SECRET",
        "TOTP_ENCRYPTION_KEY",
        "SELECTED_NODE_TOKEN",
    }
    missing = sorted(key for key in required if not values.get(key))
    if missing:
        raise ValueError(f"source env is missing required values: {', '.join(missing)}")
    values.update(PROFILES[profile])
    values["GIN_MODE"] = "release"
    values["SELECTED_NODE_ENABLED"] = "true"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(f"{key}={values[key]}\n" for key in sorted(values)), encoding="utf-8")
    os.chmod(output, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(args.source, args.output, args.profile)
    print(f"rendered {args.profile} app env at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
