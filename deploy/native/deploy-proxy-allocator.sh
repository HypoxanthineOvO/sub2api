#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 0 ]] || { echo 'deploy-proxy-allocator.sh takes no arguments.' >&2; exit 2; }
if [[ ${EUID} -ne 0 ]]; then
  echo 'deploy-proxy-allocator.sh must run as root.' >&2
  exit 1
fi

repo_root=${VSP_NATIVE_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
repo_root=$(realpath -e "$repo_root")
source_path="$repo_root/ops/llm-proxy/allocator.py"
allocator_root=/opt/vsp-sub2api/allocator
releases_root="$allocator_root/releases"
current_link="$allocator_root/current"
config=/etc/vsp-sub2api/production/allocator.json
state=/var/lib/vsp-sub2api/production/allocator/state.json
unit=vsp-proxy-allocator@production.service
unit_dropin=/etc/systemd/system/vsp-proxy-allocator@production.service.d/allocator-release.conf
lock_path=/run/lock/vsp-sub2api-allocator-deploy.lock
temp_dir=$(mktemp -d)
installed=false
committed=false
staged_release=
next_link="$current_link.next.$$"

cleanup() {
  rm -rf "$temp_dir"
  [[ -z $staged_release ]] || rm -rf "$staged_release"
  rm -f "$next_link"
}
trap cleanup EXIT

[[ -f $source_path && ! -L $source_path ]] || {
  echo "Allocator source must be a regular non-symlink file: $source_path" >&2
  exit 1
}
[[ -L $current_link ]] || { echo "Allocator current link is not installed: $current_link" >&2; exit 1; }
old_release=$(realpath -e "$current_link")
case $old_release in
  "$releases_root"/*) ;;
  *) echo "Refusing unexpected allocator release: $old_release" >&2; exit 1 ;;
esac
[[ -f $old_release/allocator.py && ! -L $old_release/allocator.py ]] || {
  echo "Current allocator release is invalid: $old_release" >&2
  exit 1
}
[[ -r $config ]] || { echo "Missing allocator config: $config" >&2; exit 1; }
grep -Fqx \
  'ExecStart=/usr/bin/python3 /opt/vsp-sub2api/allocator/current/allocator.py --config /etc/vsp-sub2api/%i/allocator.json --state /var/lib/vsp-sub2api/%i/allocator/state.json --lock /var/lib/vsp-sub2api/%i/allocator/allocator.lock --interval 60' \
  "$unit_dropin" || { echo "Allocator unit drop-in is missing or unexpected: $unit_dropin" >&2; exit 1; }
systemctl is-active --quiet "$unit" || { echo "$unit is not active; refusing to start a stopped service." >&2; exit 1; }
target=vsp-sub2api-production.target
target_was_active=false
if systemctl is-active --quiet "$target"; then
  target_was_active=true
fi
effective_exec=$(systemctl show -p ExecStart --value "$unit")
[[ $effective_exec == *'/usr/bin/python3 /opt/vsp-sub2api/allocator/current/allocator.py '* ]] || {
  echo "Effective allocator ExecStart is unexpected: $effective_exec" >&2
  exit 1
}
old_pid=$(systemctl show -p MainPID --value "$unit")
read -r old_updated old_run_id < <(python3 - "$state" <<'PY'
import json
import sys
from pathlib import Path

try:
    state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    state = {}
print(int(state.get("updated_at", 0)), state.get("run_id") or "-")
PY
)
journal_cursor=$(journalctl -u "$unit" -n 0 --show-cursor --no-pager \
  | sed -n 's/^-- cursor: //p' | tail -n 1)

exec 9>"$lock_path"
flock -n 9 || { echo 'Another allocator deployment is already running.' >&2; exit 1; }

candidate="$temp_dir/allocator.py"
install -o root -g root -m 0644 "$source_path" "$candidate"
python3 - "$candidate" "$config" <<'PY'
import ast
import json
import sys
from pathlib import Path

candidate = Path(sys.argv[1])
ast.parse(candidate.read_text(encoding="utf-8"), filename=str(candidate))
config = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
nodes = config.get("nodes")
slots = config.get("slots")
if not isinstance(nodes, list) or not isinstance(slots, dict) or set(slots) != {f"slot-{letter}" for letter in "abcde"}:
    raise SystemExit("allocator config must contain nodes and exactly slot-a through slot-e")
sources = {str(node.get("source", "")) for node in nodes if isinstance(node, dict)}
if not sources & {"lilis", "main"} or not sources & {"westdata", "family"}:
    raise SystemExit("allocator config must contain both primary and fallback sources")
PY

candidate_sha=$(sha256sum "$candidate" | awk '{print $1}')
release_dir="$releases_root/$candidate_sha"
if [[ ! -e $release_dir ]]; then
  staged_release="$releases_root/.${candidate_sha}.new.$$"
  install -d -o root -g root -m 0755 "$staged_release"
  install -o root -g root -m 0755 "$candidate" "$staged_release/allocator.py"
  mv -T "$staged_release" "$release_dir"
  staged_release=
fi
[[ -f $release_dir/allocator.py && ! -L $release_dir/allocator.py ]] || {
  echo "Allocator release is invalid: $release_dir" >&2
  exit 1
}
installed_sha=$(sha256sum "$release_dir/allocator.py" | awk '{print $1}')
[[ $candidate_sha == "$installed_sha" ]] || {
  echo "Allocator release checksum mismatch: $release_dir" >&2
  exit 1
}

rollback() {
  local status=${1:-1}
  trap - ERR INT TERM HUP
  set +e
  if [[ $installed == true && $committed != true ]]; then
    echo "Allocator deployment failed; restoring $old_release" >&2
    systemctl stop "$unit"
    rollback_previous_updated=$(python3 - "$state" <<'PY'
import json
import sys
from pathlib import Path
try:
    print(int(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("updated_at", 0)))
except (OSError, json.JSONDecodeError):
    print(0)
PY
)
    ln -s "$old_release" "$current_link.rollback.$$"
    mv -Tf "$current_link.rollback.$$" "$current_link"
    systemctl start "$unit"
    if systemctl is-active --quiet "$unit"; then
      python3 - "$rollback_previous_updated" "$config" "$state" <<'PY'
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

previous_updated = int(sys.argv[1])
config = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
state_path = Path(sys.argv[3])
selected_state = None
expected_selectors = {"LLM-PRIMARY", "LLM-BACKUP-1", "LLM-BACKUP-2"}
for _ in range(180):
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assignments = state.get("assignments", {})
        primary = [values.get("LLM-PRIMARY") for values in assignments.values()]
        if state.get("updated_at", 0) > previous_updated and set(assignments) == set(config["slots"]) \
                and all(isinstance(values, dict) and set(values) == expected_selectors for values in assignments.values()) \
                and len(primary) == len(set(primary)) == 5:
            selected_state = state
            break
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        pass
    time.sleep(1)
if selected_state is None:
    raise SystemExit("rollback allocator did not produce a fresh state")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for slot, values in selected_state["assignments"].items():
    port = int(config["slots"][slot]["controller_port"])
    for selector, expected_node in values.items():
        path = urllib.parse.quote(selector, safe="")
        with opener.open(f"http://127.0.0.1:{port}/proxies/{path}", timeout=2) as response:
            if json.load(response).get("now") != expected_node:
                raise SystemExit(f"rollback selector mismatch for {slot} {selector}")
    route_path = urllib.parse.quote("LLM-ROUTE", safe="")
    with opener.open(f"http://127.0.0.1:{port}/proxies/{route_path}", timeout=2) as response:
        if json.load(response).get("now") != "LLM-PRIMARY":
            raise SystemExit(f"rollback route is not PRIMARY for {slot}")
PY
      [[ $? -eq 0 ]] || echo 'Rollback release is active, but its fresh state could not be verified.' >&2
    else
      echo "Rollback restored the old release but $unit is not active." >&2
    fi
    if [[ $target_was_active == true ]] && ! systemctl is-active --quiet "$target"; then
      echo "Deployment stopped the $target; restarting it to restore the stack." >&2
      systemctl start "$target"
      systemctl is-active --quiet "$target" \
        || echo "Could not restore $target; start it manually." >&2
    fi
  fi
  exit "$status"
}
trap 'rollback $?' ERR
trap 'rollback 130' INT TERM HUP

ln -s "$release_dir" "$next_link"
installed=true
mv -Tf "$next_link" "$current_link"
systemctl restart "$unit"

python3 - "$old_updated" "$old_run_id" "$config" "$state" <<'PY'
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

old_updated = int(sys.argv[1])
old_run_id = sys.argv[2]
config = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
state_path = Path(sys.argv[4])
nodes = {node["name"]: node for node in config["nodes"]}
expected_slots = set(config["slots"])
expected_selectors = {"LLM-PRIMARY", "LLM-BACKUP-1", "LLM-BACKUP-2"}
primary_sources = {"lilis", "main"}
fallback_sources = {"westdata", "family"}

state = None
for _ in range(180):
    try:
        candidate = json.loads(state_path.read_text(encoding="utf-8"))
        assignments = candidate.get("assignments", {})
        probes = candidate.get("assignment_probe_ms", {})
        primary = [values.get("LLM-PRIMARY") for values in assignments.values()]
        backups = [
            values.get(selector)
            for values in assignments.values()
            for selector in ("LLM-BACKUP-1", "LLM-BACKUP-2")
        ]
        raw_delays = [
            probes.get(slot, {}).get(selector)
            for slot in assignments
            for selector in ("LLM-PRIMARY", "LLM-BACKUP-1", "LLM-BACKUP-2")
        ]
        if (
            candidate.get("updated_at", 0) > old_updated
            and isinstance(candidate.get("run_id"), str)
            and len(candidate["run_id"]) == 32
            and candidate["run_id"] != old_run_id
            and len(expected_slots) == 5
            and set(assignments) == expected_slots
            and all(isinstance(values, dict) and set(values) == expected_selectors for values in assignments.values())
            and all(nodes.get(name, {}).get("source") in primary_sources for name in primary)
            and all(nodes.get(name, {}).get("source") in fallback_sources for name in backups)
            and len(set(primary + backups)) == len(primary + backups) == 15
            and all(isinstance(delay, int) and delay > 0 for delay in raw_delays)
            and candidate.get("degraded") in {"normal", "shared-fault-domain"}
        ):
            state = candidate
            break
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        pass
    time.sleep(1)
else:
    raise SystemExit("new allocator state did not satisfy production invariants")

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
route_deadline = time.monotonic() + 90
pending = set(expected_slots)
while pending and time.monotonic() < route_deadline:
    for slot in tuple(pending):
        try:
            port = int(config["slots"][slot]["controller_port"])
            values = state["assignments"][slot]
            selectors_match = True
            for selector, expected_node in values.items():
                selector_path = urllib.parse.quote(selector, safe="")
                with opener.open(f"http://127.0.0.1:{port}/proxies/{selector_path}", timeout=2) as response:
                    selectors_match = selectors_match and json.load(response).get("now") == expected_node
            route_path = urllib.parse.quote("LLM-ROUTE", safe="")
            with opener.open(f"http://127.0.0.1:{port}/proxies/{route_path}", timeout=2) as response:
                active_route = json.load(response).get("now")
            if selectors_match and active_route == "LLM-PRIMARY":
                pending.remove(slot)
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            pass
    if pending:
        time.sleep(1)
if pending:
    raise SystemExit(f"slots did not converge to their new PRIMARY: {sorted(pending)}")

print(json.dumps({
    "updated_at": state["updated_at"],
    "degraded": state.get("degraded"),
    "primary_count": 5,
    "backup_count": 10,
    "unique_assignments": 15,
    "raw_delay_count": 15,
    "routes_on_primary": sorted(expected_slots),
}, separators=(",", ":")))
PY

systemctl is-active --quiet "$unit"
[[ $target_was_active == false ]] || systemctl is-active --quiet "$target"
new_pid=$(systemctl show -p MainPID --value "$unit")
[[ $new_pid =~ ^[1-9][0-9]*$ && $new_pid != "$old_pid" ]]
[[ $(readlink -f "$current_link") == "$release_dir" ]]
effective_exec=$(systemctl show -p ExecStart --value "$unit")
[[ $effective_exec == *'/usr/bin/python3 /opt/vsp-sub2api/allocator/current/allocator.py '* ]]
if [[ -n $journal_cursor ]] && \
    journalctl -u "$unit" --after-cursor="$journal_cursor" --no-pager -o cat | grep -Fq 'allocator error:'; then
  echo 'New allocator logged an error during deployment.' >&2
  false
fi
committed=true
trap - ERR INT TERM HUP

echo "Allocator $candidate_sha is live; previous release: $old_release"
