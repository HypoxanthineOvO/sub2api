#!/usr/bin/env python3
"""Regression checks for the proxy-plane retirement; no root or live services."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "deploy/native"
spec = importlib.util.spec_from_file_location("inspect_retirement", NATIVE / "inspect-retirement.py")
inspector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspector)


class RetirementTests(unittest.TestCase):
    def test_retired_entrypoints_are_absent(self):
        for name in ["cutover-production.sh", "restore-rehearsal.sh", "deploy-proxy-allocator.sh", "render_app_env.py", "deploy-app-release.sh", "switch-app-slot.sh", "install-agent-deployer.sh", "install.sh", "build.sh"]:
            self.assertFalse((NATIVE / name).exists(), name)

    def test_no_retired_code_is_packaged_or_privileged(self):
        for name in ["release_host.py", "install-release-control.py"]:
            text = (NATIVE / name).read_text()
            for retired in ["ops/llm-proxy", "ops/selected-node", "deploy-proxy-allocator.sh", "allocator_wrapper"]:
                self.assertNotIn(retired, text)

    def test_targets_have_no_slot_or_sidecar_dependencies(self):
        for path in (ROOT / "ops/systemd").glob("vsp-sub2api-*"):
            for line in path.read_text().splitlines():
                if line.startswith(("Requires=", "Wants=", "BindsTo=", "After=")):
                    for retired in ["slot-a", "slot-b", "slot-c", "slot-d", "slot-e", "slot-f", "vsp-proxy-allocator", "vsp-selected-node"]:
                        self.assertNotIn(retired, line, str(path))

    def test_general_proxy_remains_optional_and_available(self):
        target = (ROOT / "ops/systemd/vsp-sub2api-production.target").read_text()
        self.assertIn("Wants=vsp-mihomo-production@general.service", target)
        self.assertNotIn("Requires=vsp-mihomo", target)
        self.assertTrue((ROOT / "ops/systemd/vsp-mihomo-production@.service").exists())

    def test_selected_node_is_disabled_in_native_examples(self):
        for profile in ["production", "rehearsal"]:
            text = (NATIVE / f"config/sub2api.{profile}.env.example").read_text()
            self.assertIn("SELECTED_NODE_ENABLED=false", text)
            self.assertNotIn("SELECTED_NODE_TOKEN", text)
            self.assertNotIn("SELECTED_NODE_PROXY_SLOTS", text)

    def test_generic_product_support_is_not_removed(self):
        self.assertIn('viper.SetDefault("selected_node.enabled", false)', (ROOT / "backend/internal/config/config.go").read_text())
        self.assertTrue((ROOT / "frontend/src/api/labDashboard.ts").exists())

    def test_privileged_wrapper_requires_no_arguments(self):
        text = (NATIVE / "install-release-control.py").read_text()
        self.assertIn('NOPASSWD: {control} ""', text)
        self.assertIn('[ "$#" -eq 0 ] || exit 2', text)
        self.assertIn("sudoers.unlink(missing_ok=True)", text)

    def test_client_is_nonprivileged_and_no_shell_hook_is_allowed(self):
        text = (NATIVE / "release_client.py").read_text()
        self.assertIn('os.geteuid() == 0', text)
        self.assertIn('["sudo", "-n", CONTROL]', text)
        for name in ["release_core.py", "release_host.py", "release_control.py"]:
            self.assertNotIn("shell=True", (NATIVE / name).read_text())

    def test_inspector_redacts_credentials(self):
        text = "DATABASE_PASSWORD=do-not-print\nHTTP_PROXY=http://user:private@127.0.0.1:7890/path?token=hidden\nSELECTED_NODE_TOKEN=private\nSELECTED_NODE_ENABLED=true\n"
        result = inspector.environment_summary(text)
        self.assertEqual(set(result), {"HTTP_PROXY", "SELECTED_NODE_ENABLED"})
        self.assertEqual(result["HTTP_PROXY"]["port"], 7890)
        for secret in ["private", "hidden", "do-not-print"]:
            self.assertNotIn(secret, str(result))

    def test_inspector_detects_retired_ports_and_nul_separated_env(self):
        result = inspector.environment_summary("HTTP_PROXY=http://127.0.0.1:17907\0SELECTED_NODE_ENABLED=false\0", "\0")
        self.assertTrue(result["HTTP_PROXY"]["retired_port"])
        self.assertEqual(result["SELECTED_NODE_ENABLED"], "false")


if __name__ == "__main__":
    unittest.main(verbosity=2)
