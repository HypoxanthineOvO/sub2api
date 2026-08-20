#!/usr/bin/env python3
"""Read-only Mihomo selected-node aggregator with bounded stale caching."""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import hmac
import ipaddress
import json
import logging
import os
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable


MAX_SLOT_NAME_BYTES = 128
MAX_SELECTOR_BYTES = 256
MAX_NODE_NAME_BYTES = 256
MAX_TOKEN_LENGTH = 4096
MAX_SLOTS = 32
LOGGER = logging.getLogger("selected_node_aggregator")
LOGGER.addHandler(logging.NullHandler())


class ConfigError(ValueError):
    """Raised when the service configuration violates a security boundary."""


@dataclasses.dataclass(frozen=True)
class SlotConfig:
    controller_url: str
    controller_token: str | None
    selector: str


@dataclasses.dataclass(frozen=True)
class Config:
    bind_host: str
    bind_port: int
    api_token: str
    timeout_ms: int
    client_timeout_ms: int
    max_concurrent_requests: int
    max_controller_body_bytes: int
    fresh_ttl_seconds: float
    stale_ttl_seconds: float
    slots: dict[str, SlotConfig]


@dataclasses.dataclass
class CachedSlot:
    node: str
    observed_at_epoch: float


class RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _request, _file_pointer, _code, _message, _headers, _new_url):
        return None


def _required_string(value: object, field: str, max_length: int) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ConfigError(f"{field} must be a non-empty string of at most {max_length} characters")
    if any(ord(char) < 32 for char in value):
        raise ConfigError(f"{field} contains control characters")
    return value


def _optional_string(value: object, field: str, max_length: int) -> str | None:
    if value is None or value == "":
        return None
    return _required_string(value, field, max_length)


def _required_utf8_text(value: object, field: str, max_bytes: int) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a non-empty UTF-8 string")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ConfigError(f"{field} must be valid UTF-8") from exc
    if len(encoded) > max_bytes:
        raise ConfigError(f"{field} must be at most {max_bytes} UTF-8 bytes")
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise ConfigError(f"{field} contains control characters")
    return value


def _bounded_int(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ConfigError(f"{field} must be an integer in [{minimum}, {maximum}]")
    return value


def _bounded_number(value: object, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
        raise ConfigError(f"{field} must be a number in [{minimum}, {maximum}]")
    return float(value)


def _validate_bind_host(value: object) -> str:
    host = _required_string(value, "bind_host", 64)
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ConfigError("bind_host must be a literal loopback IP") from exc
    if not address.is_loopback:
        raise ConfigError("bind_host must be a literal loopback IP")
    return host


def _validate_controller_url(value: object, field: str) -> str:
    raw = _required_string(value, field, 512)
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise ConfigError(f"{field} must be an unauthenticated http loopback URL")
    try:
        address = ipaddress.ip_address(parsed.hostname)
        port = parsed.port
    except ValueError as exc:
        raise ConfigError(f"{field} must use a loopback IP and valid port") from exc
    if not address.is_loopback:
        raise ConfigError(f"{field} must use a loopback IP")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ConfigError(f"{field} must not include a path, query, or fragment")
    if port is not None and not 1 <= port <= 65535:
        raise ConfigError(f"{field} has an invalid port")
    return raw.rstrip("/")


def load_config(path: str | os.PathLike[str]) -> Config:
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError("unable to read valid JSON configuration") from exc
    if not isinstance(data, dict):
        raise ConfigError("configuration root must be an object")

    slots_data = data.get("slots")
    if not isinstance(slots_data, dict) or not slots_data or len(slots_data) > MAX_SLOTS:
        raise ConfigError(f"slots must be a non-empty object with at most {MAX_SLOTS} entries")
    slots: dict[str, SlotConfig] = {}
    for raw_name, raw_slot in slots_data.items():
        name = _required_utf8_text(raw_name, "slot name", MAX_SLOT_NAME_BYTES)
        if not isinstance(raw_slot, dict):
            raise ConfigError(f"slot {name!r} must be an object")
        slots[name] = SlotConfig(
            controller_url=_validate_controller_url(raw_slot.get("controller_url"), f"slots.{name}.controller_url"),
            controller_token=_optional_string(
                raw_slot.get("controller_token"), f"slots.{name}.controller_token", MAX_TOKEN_LENGTH
            ),
            selector=_required_utf8_text(raw_slot.get("selector"), f"slots.{name}.selector", MAX_SELECTOR_BYTES),
        )

    return Config(
        bind_host=_validate_bind_host(data.get("bind_host")),
        bind_port=_bounded_int(data.get("bind_port"), "bind_port", 0, 65535),
        api_token=_required_string(data.get("api_token"), "api_token", MAX_TOKEN_LENGTH),
        timeout_ms=_bounded_int(data.get("timeout_ms", 1000), "timeout_ms", 50, 10_000),
        client_timeout_ms=_bounded_int(data.get("client_timeout_ms", 2000), "client_timeout_ms", 100, 30_000),
        max_concurrent_requests=_bounded_int(
            data.get("max_concurrent_requests", 32), "max_concurrent_requests", 1, 256
        ),
        max_controller_body_bytes=_bounded_int(
            data.get("max_controller_body_bytes", 16_384), "max_controller_body_bytes", 64, 1_048_576
        ),
        fresh_ttl_seconds=_bounded_number(data.get("fresh_ttl_seconds", 5), "fresh_ttl_seconds", 5, 10),
        stale_ttl_seconds=_bounded_number(data.get("stale_ttl_seconds", 60), "stale_ttl_seconds", 10, 60),
        slots=slots,
    )


def _observed_at(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")


class SelectedNodeAggregator:
    def __init__(
        self,
        config: Config,
        *,
        clock: Callable[[], float] = time.time,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.clock = clock
        self.logger = logger or LOGGER
        self._condition = threading.Condition()
        self._refreshing = False
        self._last_attempt_epoch: float | None = None
        self._cache: dict[str, CachedSlot] = {}

    def _fetch_slot(self, name: str, slot: SlotConfig) -> tuple[str, str | None]:
        encoded_selector = urllib.parse.quote(slot.selector, safe="")
        headers = {"Accept": "application/json"}
        if slot.controller_token:
            headers["Authorization"] = f"Bearer {slot.controller_token}"
        request = urllib.request.Request(
            f"{slot.controller_url}/proxies/{encoded_selector}", headers=headers, method="GET"
        )
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), RejectRedirectHandler())
            with opener.open(request, timeout=self.config.timeout_ms / 1000) as response:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > self.config.max_controller_body_bytes:
                            return name, None
                    except ValueError:
                        return name, None
                raw = response.read(self.config.max_controller_body_bytes + 1)
            if len(raw) > self.config.max_controller_body_bytes:
                return name, None
            payload = json.loads(raw)
            node = payload.get("now") if isinstance(payload, dict) else None
            if not isinstance(node, str) or not node:
                return name, None
            try:
                encoded_node = node.encode("utf-8")
            except UnicodeEncodeError:
                return name, None
            if len(encoded_node) > MAX_NODE_NAME_BYTES:
                return name, None
            if any(unicodedata.category(char) == "Cc" for char in node):
                return name, None
            return name, node
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return name, None

    def _refresh(self, observed_epoch: float) -> None:
        results: dict[str, str | None] = {}
        worker_count = min(len(self.config.slots), 16)
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="selected-node") as pool:
            futures = {
                pool.submit(self._fetch_slot, name, slot): name for name, slot in self.config.slots.items()
            }
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    _, node = future.result()
                except Exception:  # A programming/runtime failure in one worker must not hide healthy slots.
                    self.logger.warning("selected-node worker failed for slot=%r category=internal", name)
                    node = None
                results[name] = node

        with self._condition:
            for name in self.config.slots:
                node = results.get(name)
                if node is not None:
                    self._cache[name] = CachedSlot(node=node, observed_at_epoch=observed_epoch)
                else:
                    self.logger.warning("selected-node refresh failed for slot=%r", name)
            self._last_attempt_epoch = observed_epoch

    def _render(self, now: float) -> dict[str, object]:
        slots: dict[str, dict[str, object]] = {}
        for name, slot in self.config.slots.items():
            cached = self._cache.get(name)
            status = "unavailable"
            node = None
            observed_at = None
            if cached is not None:
                age = max(0.0, now - cached.observed_at_epoch)
                observed_at = _observed_at(cached.observed_at_epoch)
                if age <= self.config.fresh_ttl_seconds:
                    status = "fresh"
                    node = cached.node
                elif age <= self.config.stale_ttl_seconds:
                    status = "stale"
                    node = cached.node
            slots[name] = {
                "selected_node_name": node,
                "selected_node_selector": slot.selector,
                "observed_at": observed_at,
                "status": status,
            }
        return {"slots": slots}

    def get_snapshot(self) -> dict[str, object]:
        now = self.clock()
        with self._condition:
            if self._last_attempt_epoch is not None and now - self._last_attempt_epoch < self.config.fresh_ttl_seconds:
                return self._render(now)
            if self._refreshing:
                while self._refreshing:
                    self._condition.wait()
                return self._render(self.clock())
            self._refreshing = True

        try:
            self._refresh(now)
        finally:
            with self._condition:
                self._refreshing = False
                self._condition.notify_all()
        with self._condition:
            return self._render(self.clock())


class SelectedNodeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    request_queue_size = 64


def _handler_class(config: Config, aggregator: SelectedNodeAggregator):
    concurrency_gate = threading.BoundedSemaphore(config.max_concurrent_requests)

    class Handler(BaseHTTPRequestHandler):
        server_version = "selected-node-aggregator"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(config.client_timeout_ms / 1000)

        def _json(self, status: int, payload: dict[str, object], extra_headers: dict[str, str] | None = None):
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != "/v1/selected-nodes":
                self._json(404, {"error": "not_found"})
                return
            authorization = self.headers.get("Authorization", "")
            expected = f"Bearer {config.api_token}"
            if not hmac.compare_digest(authorization, expected):
                self._json(401, {"error": "unauthorized"}, {"WWW-Authenticate": "Bearer"})
                return
            if not concurrency_gate.acquire(blocking=False):
                self._json(503, {"error": "busy"}, {"Retry-After": "1"})
                return
            try:
                try:
                    payload = aggregator.get_snapshot()
                except Exception:
                    aggregator.logger.warning("selected-node request failed category=internal")
                    self._json(503, {"error": "unavailable"}, {"Retry-After": "1"})
                    return
                self._json(200, payload)
            finally:
                concurrency_gate.release()

        def _method_not_allowed(self):
            if self.path != "/v1/selected-nodes":
                self._json(404, {"error": "not_found"})
                return
            self._json(405, {"error": "method_not_allowed"}, {"Allow": "GET"})

        do_POST = _method_not_allowed
        do_PUT = _method_not_allowed
        do_PATCH = _method_not_allowed
        do_DELETE = _method_not_allowed
        do_HEAD = _method_not_allowed
        do_OPTIONS = _method_not_allowed

        def log_message(self, format_string, *args):
            aggregator.logger.info("http client=%s status=%s", self.client_address[0], args[1] if len(args) > 1 else "-")

    return Handler


def make_server(config: Config, aggregator: SelectedNodeAggregator | None = None) -> SelectedNodeHTTPServer:
    service = aggregator or SelectedNodeAggregator(config)
    return SelectedNodeHTTPServer((config.bind_host, config.bind_port), _handler_class(config, service))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=os.environ.get("SELECTED_NODE_AGGREGATOR_CONFIG"))
    args = parser.parse_args(argv)
    if not args.config:
        parser.error("--config or SELECTED_NODE_AGGREGATOR_CONFIG is required")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        logging.error("configuration rejected: %s", exc)
        return 2
    server = make_server(config)
    logging.info("selected-node aggregator listening on %s:%d", config.bind_host, server.server_port)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

