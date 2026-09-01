from __future__ import annotations

import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "allocator.py"
SPEC = importlib.util.spec_from_file_location("llm_proxy_allocator", MODULE_PATH)
allocator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(allocator)


def node(name: str, source: str, delay: int, domain: str | None = None) -> tuple[dict, dict]:
    metadata = {
        "name": name,
        "source": source,
        "region": "US",
        "priority": 0,
        "fault_domain": domain or name,
    }
    health = {
        "delay_ms": delay,
        "last_probe_ms": delay,
        "healthy": True,
    }
    return metadata, health


def fixture(*definitions: tuple[str, str, int, str | None]) -> tuple[list[dict], dict]:
    nodes = []
    health = {}
    for definition in definitions:
        metadata, item_health = node(*definition)
        nodes.append(metadata)
        health[metadata["name"]] = item_health
    return nodes, health


class PoolRoleTests(unittest.TestCase):
    def test_primary_uses_lilis_and_backups_use_westdata_regardless_of_delay(self):
        nodes, health = fixture(
            ("owner", "lilis", 900, None),
            ("fallback-fast", "westdata", 10, None),
            ("fallback-slow", "westdata", 20, None),
        )

        assignments, degraded = allocator.assign_nodes(["slot-a"], nodes, health, {})

        self.assertEqual("owner", assignments["slot-a"]["LLM-PRIMARY"])
        self.assertEqual(
            {"fallback-fast", "fallback-slow"},
            {
                assignments["slot-a"]["LLM-BACKUP-1"],
                assignments["slot-a"]["LLM-BACKUP-2"],
            },
        )
        self.assertEqual("normal", degraded)

    def test_previous_westdata_primary_cannot_override_owner_pool(self):
        nodes, health = fixture(
            ("owner", "main", 900, None),
            ("old-primary", "family", 10, None),
            ("fallback-2", "family", 20, None),
        )
        previous = {"slot-a": {"LLM-PRIMARY": "old-primary"}}

        assignments, _ = allocator.assign_nodes(["slot-a"], nodes, health, previous)

        self.assertEqual("owner", assignments["slot-a"]["LLM-PRIMARY"])

    def test_primary_falls_back_only_when_all_owner_candidates_fail_local_verification(self):
        nodes, health = fixture(
            ("owner-1", "lilis", 10, None),
            ("owner-2", "lilis", 20, None),
            ("fallback-1", "westdata", 30, None),
            ("fallback-2", "westdata", 40, None),
            ("fallback-3", "westdata", 50, None),
        )

        assignments, degraded = allocator.assign_nodes(
            ["slot-c"],
            nodes,
            health,
            {},
            lambda _slot, candidates: {
                candidate["name"] for candidate in candidates if candidate["source"] == "westdata"
            },
        )

        self.assertEqual("fallback-1", assignments["slot-c"]["LLM-PRIMARY"])
        self.assertEqual("primary-pool-unavailable", degraded)

    def test_slot_local_failure_tries_another_owner_node_before_fallback(self):
        nodes, health = fixture(
            ("owner-bad", "lilis", 10, None),
            ("owner-good", "lilis", 20, None),
            ("fallback-1", "westdata", 1, None),
            ("fallback-2", "westdata", 2, None),
        )
        checked = []

        def verify(slot, candidates):
            checked.extend((slot, candidate["name"]) for candidate in candidates)
            return {candidate["name"] for candidate in candidates if candidate["name"] != "owner-bad"}

        assignments, _ = allocator.assign_nodes(["slot-e"], nodes, health, {}, verify)

        self.assertEqual("owner-good", assignments["slot-e"]["LLM-PRIMARY"])
        self.assertEqual(
            [("slot-e", "owner-bad"), ("slot-e", "owner-good")],
            checked[:2],
        )

    def test_unknown_source_does_not_enter_pool(self):
        nodes, health = fixture(
            ("unknown-fast", "typo", 1, None),
            ("owner", "lilis", 100, None),
            ("fallback-1", "westdata", 200, None),
            ("fallback-2", "westdata", 300, None),
        )

        assignments, _ = allocator.assign_nodes(["slot-a"], nodes, health, {})

        self.assertNotIn("unknown-fast", assignments["slot-a"].values())


class DelayTests(unittest.TestCase):
    def test_health_keeps_raw_probe_separate_from_smoothed_scheduling_delay(self):
        nodes, _ = fixture(("owner", "lilis", 100, None))
        previous = {"health": {"owner": {"delay_ms": 100, "failures": 0}}}
        original_probe = allocator.probe_node
        allocator.probe_node = lambda _port, _node: ("owner", 300, None)
        try:
            health = allocator.update_health(nodes, 29091, previous)
        finally:
            allocator.probe_node = original_probe

        self.assertEqual(180, health["owner"]["delay_ms"])
        self.assertEqual(300, health["owner"]["last_probe_ms"])

    def test_status_displays_raw_probe_and_marks_failed_probe_unavailable(self):
        config = {
            "slots": {"slot-a": {"mixed_port": 17901}},
            "nodes": [
                {"name": "owner", "source": "lilis", "region": "US", "fault_domain": "owner"},
                {"name": "backup-1", "source": "westdata", "region": "XX", "fault_domain": "b1"},
                {"name": "backup-2", "source": "westdata", "region": "XX", "fault_domain": "b2"},
            ],
        }
        state = {
            "assignments": {
                "slot-a": {
                    "LLM-PRIMARY": "owner",
                    "LLM-BACKUP-1": "backup-1",
                    "LLM-BACKUP-2": "backup-2",
                }
            },
            "health": {
                "owner": {"delay_ms": 180, "last_probe_ms": 300},
                "backup-1": {"delay_ms": 250, "last_probe_ms": None},
                "backup-2": {"delay_ms": 350},
            },
        }

        output = io.StringIO()
        with redirect_stdout(output):
            allocator.print_status(config, state)

        rendered = output.getvalue()
        self.assertIn("owner delay=300ms", rendered)
        self.assertNotIn("owner delay=180ms", rendered)
        self.assertIn("backup-1 delay=unavailable", rendered)
        self.assertIn("backup-2 delay=unavailable", rendered)

    def test_status_prefers_raw_probe_from_the_assigned_slot(self):
        config = {
            "slots": {"slot-c": {"mixed_port": 17903}},
            "nodes": [{"name": "owner", "source": "lilis", "region": "US", "fault_domain": "owner"}],
        }
        state = {
            "assignments": {"slot-c": {selector: "owner" for selector in allocator.SELECTORS}},
            "assignment_probe_ms": {"slot-c": {selector: 777 for selector in allocator.SELECTORS}},
            "health": {"owner": {"delay_ms": 180, "last_probe_ms": 300}},
        }

        output = io.StringIO()
        with redirect_stdout(output):
            allocator.print_status(config, state)

        self.assertIn("owner delay=777ms", output.getvalue())
        self.assertNotIn("owner delay=300ms", output.getvalue())


class RunOnceTests(unittest.TestCase):
    def test_local_probe_timeout_is_bounded_by_remaining_round_budget(self):
        nodes, health = fixture(
            ("owner", "lilis", 100, None),
            ("fallback-1", "westdata", 200, None),
            ("fallback-2", "westdata", 210, None),
        )
        config = {
            "slots": {"slot-a": {"mixed_port": 17901, "controller_port": 29091}},
            "nodes": nodes,
        }
        request_timeouts = []
        original_probe = allocator.probe_node
        original_update_health = allocator.update_health
        original_wait = allocator.wait_for_controller
        original_apply = allocator.apply_assignments
        original_atomic = allocator.atomic_json
        original_monotonic = allocator.time.monotonic

        def probe(_port, candidate, _probe_timeout_ms, request_timeout):
            request_timeouts.append(request_timeout)
            return candidate["name"], 100, None

        monotonic_values = iter((100.0, 144.8, 144.9, 144.95))
        allocator.probe_node = probe
        allocator.update_health = lambda _nodes, _port, _previous: health
        allocator.wait_for_controller = lambda _port: None
        allocator.apply_assignments = lambda _slots, _assignments: None
        allocator.atomic_json = lambda _path, _state: None
        allocator.time.monotonic = lambda: next(monotonic_values)
        try:
            allocator.run_once(config, {}, Path("unused-state.json"))
        finally:
            allocator.probe_node = original_probe
            allocator.update_health = original_update_health
            allocator.wait_for_controller = original_wait
            allocator.apply_assignments = original_apply
            allocator.atomic_json = original_atomic
            allocator.time.monotonic = original_monotonic

        self.assertTrue(request_timeouts)
        self.assertTrue(all(timeout <= 0.21 for timeout in request_timeouts))

    def test_candidate_verification_uses_each_slots_controller(self):
        nodes, _ = fixture(
            ("owner-1", "lilis", 100, None),
            ("owner-2", "lilis", 110, None),
            ("fallback-1", "westdata", 200, None),
            ("fallback-2", "westdata", 210, None),
            ("fallback-3", "westdata", 220, None),
            ("fallback-4", "westdata", 230, None),
        )
        config = {
            "slots": {
                "slot-a": {"mixed_port": 17901, "controller_port": 29091},
                "slot-c": {"mixed_port": 17903, "controller_port": 29093},
            },
            "nodes": nodes,
        }
        probe_calls = []
        original_probe = allocator.probe_node
        original_wait = allocator.wait_for_controller
        original_apply = allocator.apply_assignments
        original_atomic = allocator.atomic_json

        def probe(port, candidate, *_timeouts):
            probe_calls.append((port, candidate["name"]))
            if port == 29093 and candidate["name"] == "owner-2":
                return candidate["name"], None, "slot-local failure"
            return candidate["name"], candidate["name"].endswith("1") and 100 or 200, None

        allocator.probe_node = probe
        allocator.wait_for_controller = lambda _port: None
        allocator.apply_assignments = lambda _slots, _assignments: None
        allocator.atomic_json = lambda _path, _state: None
        try:
            state = allocator.run_once(config, {}, Path("unused-state.json"))
        finally:
            allocator.probe_node = original_probe
            allocator.wait_for_controller = original_wait
            allocator.apply_assignments = original_apply
            allocator.atomic_json = original_atomic

        self.assertEqual("owner-1", state["assignments"]["slot-a"]["LLM-PRIMARY"])
        self.assertEqual("owner-1", state["assignments"]["slot-c"]["LLM-PRIMARY"])
        self.assertEqual(allocator.PROCESS_RUN_ID, state["run_id"])
        self.assertEqual(100, state["assignment_probe_ms"]["slot-c"]["LLM-PRIMARY"])
        self.assertIn((29091, "owner-1"), probe_calls)
        self.assertIn((29093, "owner-2"), probe_calls)
        self.assertIn((29093, "owner-1"), probe_calls)


if __name__ == "__main__":
    unittest.main()
