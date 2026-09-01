#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
installer="$repo_root/deploy/native/install-agent-deployer.sh"
deployer="$repo_root/deploy/native/deploy-proxy-allocator.sh"

bash -n "$installer"
bash -n "$deployer"

grep -Fq '[[ $# -eq 0 ]]' "$deployer"
grep -Fq 'flock -n 9' "$deployer"
grep -Fq 'allocator_root=/opt/vsp-sub2api/allocator' "$deployer"
grep -Fq 'current_link="$allocator_root/current"' "$deployer"
grep -Fq 'release_dir="$releases_root/$candidate_sha"' "$deployer"
grep -Fq 'unit=vsp-proxy-allocator@production.service' "$deployer"
grep -Fq 'target=vsp-sub2api-production.target' "$deployer"
grep -Fq 'target_was_active=false' "$deployer"
grep -Fq 'systemctl start "$target"' "$deployer"
grep -Fq '[[ $target_was_active == false ]] || systemctl is-active --quiet "$target"' "$deployer"
grep -Fq 'systemctl restart "$unit"' "$deployer"
grep -Fq 'assignment_probe_ms' "$deployer"
grep -Fq 'candidate["run_id"] != old_run_id' "$deployer"
grep -Fq 'candidate.get("updated_at", 0) > old_updated' "$deployer"
grep -Fq 'systemctl stop "$unit"' "$deployer"
grep -Fq 'systemctl start "$unit"' "$deployer"
grep -Fq 'set(values) == expected_selectors' "$deployer"
grep -Fq 'systemctl show -p ExecStart --value "$unit"' "$deployer"
grep -Fq 'journalctl -u "$unit" --after-cursor="$journal_cursor"' "$deployer"
grep -Fq "grep -Fq 'allocator error:'" "$deployer"
grep -Fq 'rollback()' "$deployer"
if grep -Fq '/opt/vsp-sub2api/current/ops/llm-proxy/allocator.py' "$deployer"; then
  echo 'daily allocator deployer must not modify the App current release' >&2
  exit 1
fi
grep -Fq '$operator_user ALL=(root) NOPASSWD: $allocator_wrapper' "$installer"
grep -Fq 'allocator_dropin_dir=/etc/systemd/system/vsp-proxy-allocator@production.service.d' "$installer"
grep -Fq 'ExecStart=/usr/bin/python3 /opt/vsp-sub2api/allocator/current/allocator.py' "$installer"
grep -Fq 'mv -T "$staged_allocator_release" "$allocator_release"' "$installer"
grep -Fq 'Allocator release checksum does not match its directory' "$installer"
grep -Fq 'systemctl show -p ExecStart --value vsp-proxy-allocator@production.service' "$installer"

if "$deployer" unexpected-argument >/dev/null 2>&1; then
  echo 'allocator deployer accepted an argument' >&2
  exit 1
fi

echo 'allocator agent deployer security contract test passed'
