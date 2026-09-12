# Retired: Docker-to-native production cutover

The one-time August 2026 Docker-to-native migration is historical. Production
now runs on Babel. Its five-slot allocator, selected-node sidecar, migration SQL,
and snapshot/restore entrypoints were removed on 2026-09-12.

Do not rerun the historical migration to upgrade, recover, or retire services.
The old scripts stop applications, restore databases, and recreate the retired
proxy plane. They are not a Babel maintenance procedure.

Historical source remains available in Git at commit `63e0a0f02`. Historical
execution notes in `.pipeline/cycles/native-blue-green-release/` remain unchanged.

For the current cleanup boundary and outstanding host work, see
[RETIREMENT.md](RETIREMENT.md). Existing application-slot mechanics are documented
in [BLUE-GREEN.md](BLUE-GREEN.md); the remote delivery workflow is still pending.
