import contextlib
import io
import json
import logging
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from selected_node_aggregator import (  # noqa: E402
    ConfigError,
    SelectedNodeAggregator,
    load_config,
    make_server,
)


class MutableClock:
    def __init__(self, value=1_800_000_000.0):
        self.value = value

    def __call__(self):
        return self.value


class ControllerState:
    def __init__(self, node="香港-HKT-01"):
        self.node = node
        self.status = 200
        self.delay = 0.0
        self.raw_body = None
        self.paths = []
        self.auth_headers = []
        self.lock = threading.Lock()


def controller_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            with state.lock:
                state.paths.append(self.path)
                state.auth_headers.append(self.headers.get("Authorization"))
            if state.delay:
                time.sleep(state.delay)
            body = state.raw_body
            if body is None:
                body = json.dumps({"now": state.node}).encode()
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    return Handler


def redirect_handler(target_url):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", target_url)
            self.end_headers()

        def log_message(self, *_args):
            pass

    return Handler


@contextlib.contextmanager
def running_server(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextlib.contextmanager
def running_existing_server(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def config_dict(controller_port, **overrides):
    config = {
        "bind_host": "127.0.0.1",
        "bind_port": 0,
        "api_token": "aggregator-secret",
        "timeout_ms": 500,
        "max_controller_body_bytes": 1024,
        "fresh_ttl_seconds": 5,
        "stale_ttl_seconds": 60,
        "slots": {
            "Slot A": {
                "controller_url": f"http://127.0.0.1:{controller_port}",
                "controller_token": "controller-secret",
                "selector": "AUTO 香港/主线",
            }
        },
    }
    config.update(overrides)
    return config


def loaded_config(data):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        json.dump(data, handle)
        path = handle.name
    try:
        return load_config(path)
    finally:
        os.unlink(path)


def request_json(url, token="aggregator-secret", method="GET"):
    request = urllib.request.Request(url, method=method)
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=2) as response:
        return response.status, json.load(response)


class ConfigValidationTests(unittest.TestCase):
    def test_concurrent_request_limit_defaults_and_bounds(self):
        self.assertEqual(loaded_config(config_dict(9090)).max_concurrent_requests, 32)
        for value in (0, 257):
            with self.subTest(value=value):
                with self.assertRaises(ConfigError):
                    loaded_config(config_dict(9090, max_concurrent_requests=value))

    def test_slot_and_selector_limits_are_utf8_bytes_and_reject_control_characters(self):
        valid = config_dict(9090)
        valid["slots"] = {"Slot A": valid["slots"]["Slot A"]}
        self.assertIn("Slot A", loaded_config(valid).slots)

        oversized_slot = config_dict(9090)
        oversized_slot["slots"] = {"界" * 43: oversized_slot["slots"]["Slot A"]}
        oversized_selector = config_dict(9090)
        oversized_selector["slots"]["Slot A"]["selector"] = "界" * 86
        controlled_slot = config_dict(9090)
        controlled_slot["slots"] = {"bad\u007fslot": controlled_slot["slots"]["Slot A"]}
        for data in (oversized_slot, oversized_selector, controlled_slot):
            with self.subTest(slots=list(data["slots"])):
                with self.assertRaises(ConfigError):
                    loaded_config(data)

    def test_rejects_wildcard_lan_and_external_controller_bindings(self):
        invalid = [
            config_dict(9090, bind_host="0.0.0.0"),
            config_dict(9090, bind_host="192.168.1.10"),
            config_dict(9090, slots={"Slot A": {
                "controller_url": "http://example.com:9090",
                "controller_token": "x",
                "selector": "AUTO",
            }}),
        ]
        for data in invalid:
            with self.subTest(data=data):
                with self.assertRaises(ConfigError):
                    loaded_config(data)

    def test_allows_only_loopback_and_requires_token(self):
        with self.assertRaises(ConfigError):
            loaded_config(config_dict(9090, bind_host="172.17.0.1"))
        with self.assertRaises(ConfigError):
            loaded_config(config_dict(9090, api_token=""))

    def test_controller_token_is_optional_for_loopback_controller_without_secret(self):
        data = config_dict(9090)
        del data["slots"]["Slot A"]["controller_token"]
        slot = loaded_config(data).slots["Slot A"]
        self.assertIsNone(slot.controller_token)


class AggregatorIntegrationTests(unittest.TestCase):
    def test_controller_fetch_ignores_environment_proxy(self):
        direct = ControllerState("direct-node")
        proxy = ControllerState("proxy-node")
        with running_server(controller_handler(direct)) as controller, running_server(controller_handler(proxy)) as proxy_server:
            environment = {
                "HTTP_PROXY": f"http://127.0.0.1:{proxy_server.server_port}",
                "HTTPS_PROXY": f"http://127.0.0.1:{proxy_server.server_port}",
                "NO_PROXY": "",
                "no_proxy": "",
            }
            with mock.patch.dict(os.environ, environment, clear=False):
                payload = SelectedNodeAggregator(loaded_config(config_dict(controller.server_port))).get_snapshot()
        self.assertEqual(payload["slots"]["Slot A"]["selected_node_name"], "direct-node")
        self.assertEqual(proxy.paths, [])
        self.assertEqual(proxy.auth_headers, [])

    def test_omits_authorization_header_when_controller_has_no_secret(self):
        state = ControllerState("香港-HKT-01")
        with running_server(controller_handler(state)) as controller:
            data = config_dict(controller.server_port)
            del data["slots"]["Slot A"]["controller_token"]
            aggregator = SelectedNodeAggregator(loaded_config(data))

            snapshot = aggregator.get_snapshot()

        self.assertEqual(snapshot["slots"]["Slot A"]["selected_node_name"], "香港-HKT-01")
        self.assertEqual(state.auth_headers, [None])

    def test_http_concurrency_limit_returns_503_without_extra_refresh_and_recovers(self):
        state = ControllerState("香港-HKT-01")
        state.delay = 0.5
        with running_server(controller_handler(state)) as controller:
            config = loaded_config(config_dict(
                controller.server_port,
                max_concurrent_requests=1,
                timeout_ms=1000,
            ))
            with running_existing_server(make_server(config, SelectedNodeAggregator(config))) as server:
                url = f"http://127.0.0.1:{server.server_port}/v1/selected-nodes"
                first_result = []
                first = threading.Thread(target=lambda: first_result.append(request_json(url)))
                first.start()
                deadline = time.monotonic() + 1
                while len(state.paths) < 1 and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.assertEqual(len(state.paths), 1, "first request did not reach the fake Controller")

                started = time.monotonic()
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    request_json(url)
                self.assertEqual(raised.exception.code, 503)
                self.assertLess(time.monotonic() - started, 0.35)
                self.assertEqual(len(state.paths), 1, "rejected request must not start another refresh")

                first.join(timeout=2)
                self.assertEqual(first_result[0][0], 200)
                status, _payload = request_json(url)
                self.assertEqual(status, 200)

    def test_controller_redirect_is_rejected_without_contacting_target(self):
        target = ControllerState("redirected-node")
        with running_server(controller_handler(target)) as target_server:
            target_url = f"http://127.0.0.1:{target_server.server_port}/redirect-target"
            with running_server(redirect_handler(target_url)) as redirect_server:
                aggregator = SelectedNodeAggregator(loaded_config(config_dict(redirect_server.server_port)))
                payload = aggregator.get_snapshot()
        self.assertEqual(payload["slots"]["Slot A"]["status"], "unavailable")
        self.assertEqual(target.paths, [])
        self.assertEqual(target.auth_headers, [])

    def test_auth_path_method_url_encoding_and_secret_redaction(self):
        state = ControllerState()
        with running_server(controller_handler(state)) as controller:
            config = loaded_config(config_dict(controller.server_port))
            aggregator = SelectedNodeAggregator(config)
            with running_existing_server(make_server(config, aggregator)) as server:
                base = f"http://127.0.0.1:{server.server_port}"
                for token in (None, "wrong-secret"):
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        request_json(base + "/v1/selected-nodes", token=token)
                    self.assertEqual(raised.exception.code, 401)

                status, payload = request_json(base + "/v1/selected-nodes")
                self.assertEqual(status, 200)
                self.assertEqual(payload["slots"]["Slot A"]["selected_node_name"], "香港-HKT-01")
                self.assertEqual(payload["slots"]["Slot A"]["selected_node_selector"], "AUTO 香港/主线")
                self.assertEqual(payload["slots"]["Slot A"]["status"], "fresh")
                serialized = json.dumps(payload, ensure_ascii=False)
                for secret in ("aggregator-secret", "controller-secret", str(controller.server_port)):
                    self.assertNotIn(secret, serialized)
                self.assertEqual(state.paths, ["/proxies/AUTO%20%E9%A6%99%E6%B8%AF%2F%E4%B8%BB%E7%BA%BF"])
                self.assertEqual(state.auth_headers, ["Bearer controller-secret"])

                with self.assertRaises(urllib.error.HTTPError) as raised:
                    request_json(base + "/not-found")
                self.assertEqual(raised.exception.code, 404)
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    request_json(base + "/v1/selected-nodes", method="POST")
                self.assertEqual(raised.exception.code, 405)

    def test_parallel_partial_success_does_not_leak_raw_errors(self):
        good = ControllerState("新加坡-SG-02")
        good.delay = 0.15
        bad = ControllerState()
        bad.delay = 0.15
        bad.status = 500
        bad.raw_body = b'raw-secret-controller-failure'
        with running_server(controller_handler(good)) as good_server, running_server(controller_handler(bad)) as bad_server:
            data = config_dict(good_server.server_port)
            data["slots"]["Slot B"] = {
                "controller_url": f"http://127.0.0.1:{bad_server.server_port}",
                "controller_token": "bad-controller-secret",
                "selector": "AUTO-B",
            }
            aggregator = SelectedNodeAggregator(loaded_config(data))
            started = time.monotonic()
            payload = aggregator.get_snapshot()
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 0.27)
            self.assertEqual(payload["slots"]["Slot A"]["status"], "fresh")
            self.assertEqual(payload["slots"]["Slot B"]["status"], "unavailable")
            serialized = json.dumps(payload)
            self.assertNotIn("raw-secret", serialized)
            self.assertNotIn("bad-controller-secret", serialized)

    def test_cache_coalesces_refresh_and_keeps_bounded_stale_value(self):
        state = ControllerState("日本-NRT-03")
        clock = MutableClock()
        with running_server(controller_handler(state)) as controller:
            aggregator = SelectedNodeAggregator(loaded_config(config_dict(controller.server_port)), clock=clock)
            first = aggregator.get_snapshot()
            second = aggregator.get_snapshot()
            self.assertEqual(first, second)
            self.assertEqual(len(state.paths), 1)

            clock.value += 6
            state.status = 503
            stale = aggregator.get_snapshot()
            self.assertEqual(stale["slots"]["Slot A"]["status"], "stale")
            self.assertEqual(stale["slots"]["Slot A"]["selected_node_name"], "日本-NRT-03")

            clock.value += 61
            unavailable = aggregator.get_snapshot()
            self.assertEqual(unavailable["slots"]["Slot A"]["status"], "unavailable")
            self.assertIsNone(unavailable["slots"]["Slot A"]["selected_node_name"])

            state.status = 200
            state.delay = 0.15
            clock.value += 6
            before = len(state.paths)
            results = []
            workers = [threading.Thread(target=lambda: results.append(aggregator.get_snapshot())) for _ in range(6)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=2)
            self.assertEqual(len(results), 6)
            self.assertEqual(len(state.paths), before + 1)

    def test_oversize_bad_json_and_invalid_node_are_unavailable(self):
        cases = [
            b"x" * 2048,
            b"{not-json",
            json.dumps({"now": "x" * 300}).encode(),
            json.dumps({"now": "界" * 86}).encode(),
            json.dumps({"now": "bad\u007fnode"}).encode(),
            json.dumps({"now": ""}).encode(),
        ]
        state = ControllerState()
        with running_server(controller_handler(state)) as controller:
            for raw in cases:
                with self.subTest(raw=raw[:20]):
                    state.raw_body = raw
                    aggregator = SelectedNodeAggregator(loaded_config(config_dict(controller.server_port)))
                    payload = aggregator.get_snapshot()
                    self.assertEqual(payload["slots"]["Slot A"]["status"], "unavailable")
                    self.assertIsNone(payload["slots"]["Slot A"]["selected_node_name"])

    def test_logs_never_include_tokens_or_raw_controller_body(self):
        state = ControllerState()
        state.status = 500
        state.raw_body = b"raw-controller-secret-body"
        stream = io.StringIO()
        logger = logging.getLogger("selected-node-test")
        logger.handlers = [logging.StreamHandler(stream)]
        logger.setLevel(logging.INFO)
        logger.propagate = False
        with running_server(controller_handler(state)) as controller:
            aggregator = SelectedNodeAggregator(loaded_config(config_dict(controller.server_port)), logger=logger)
            aggregator.get_snapshot()
        log_text = stream.getvalue()
        self.assertNotIn("controller-secret", log_text)
        self.assertNotIn("raw-controller-secret-body", log_text)


if __name__ == "__main__":
    unittest.main()
