#!/usr/bin/env bash
set -euo pipefail

native_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$native_dir/../.." && pwd)
temp_dir=$(mktemp -d)
trap 'rm -rf "$temp_dir"' EXIT

for file in "$(dirname "${BASH_SOURCE[0]}")"/*.sh; do
  bash -n "$file"
done

PYTHONPYCACHEPREFIX="$temp_dir/pycache" python3 -m py_compile \
  "$(dirname "${BASH_SOURCE[0]}")/../../ops/llm-proxy/allocator.py" \
  "$(dirname "${BASH_SOURCE[0]}")/../../ops/mihomo/render_profile.py" \
  "$(dirname "${BASH_SOURCE[0]}")/../../ops/selected-node/selected_node_aggregator.py" \
  "$(dirname "${BASH_SOURCE[0]}")/render_app_env.py"

test -s "$repo_root/backend/resources/model-pricing/model_prices_and_context_window.json"
grep -F 'install -m 0644 "$pricing_fallback"' "$native_dir/install.sh" >/dev/null
grep -F '"$release_dir/resources/model-pricing/model_prices_and_context_window.json"' \
  "$native_dir/install.sh" >/dev/null
test -x "$native_dir/switch-app-slot.sh"
test -x "$native_dir/install-blue-green-nginx.sh"
test -x "$native_dir/deploy-app-release.sh"
test -x "$native_dir/deploy-proxy-allocator.sh"
grep -Fq 'source-commit' "$native_dir/build.sh"
grep -Fq 'source-tree' "$native_dir/build.sh"
grep -Fq 'sub2api.sha256' "$native_dir/build.sh"
test -x "$native_dir/install-agent-deployer.sh"
grep -Fq '/usr/local/sbin/vsp-sub2api-allocator-deploy' "$native_dir/install-agent-deployer.sh"
grep -Fq 'NOPASSWD: $allocator_wrapper' "$native_dir/install-agent-deployer.sh"
grep -Fq 'unit=vsp-proxy-allocator@production.service' "$native_dir/deploy-proxy-allocator.sh"
grep -Fq 'allocator_root=/opt/vsp-sub2api/allocator' "$native_dir/deploy-proxy-allocator.sh"
grep -Fq 'release_dir="$releases_root/$candidate_sha"' "$native_dir/deploy-proxy-allocator.sh"
grep -Fq 'primary_sources = {"lilis", "main"}' "$native_dir/deploy-proxy-allocator.sh"
grep -Fq 'fallback_sources = {"westdata", "family"}' "$native_dir/deploy-proxy-allocator.sh"
grep -Fq 'assignment_probe_ms' "$native_dir/deploy-proxy-allocator.sh"
grep -Fq 'candidate["run_id"] != old_run_id' "$native_dir/deploy-proxy-allocator.sh"
grep -Fq 'candidate.get("updated_at", 0) > old_updated' "$native_dir/deploy-proxy-allocator.sh"
grep -Fq 'set(values) == expected_selectors' "$native_dir/deploy-proxy-allocator.sh"
grep -Fq 'rollback()' "$native_dir/deploy-proxy-allocator.sh"
grep -Fq 'ExecStart=/usr/bin/python3 /opt/vsp-sub2api/allocator/current/allocator.py' \
  "$native_dir/install-agent-deployer.sh"
test -s "$native_dir/nginx/blue.conf"
test -s "$native_dir/nginx/green.conf"
grep -Fqx 'ExecStart=/opt/vsp-sub2api/app-slots/%i/sub2api' \
  "$repo_root/ops/systemd/vsp-sub2api-app-slot@.service"
if grep -Eq '^(Requires|PartOf)=' "$repo_root/ops/systemd/vsp-sub2api-app-slot@.service"; then
  echo 'app slot unit must not control production data-plane units' >&2
  exit 1
fi
if grep -Fq 'Requires=vsp-sub2api-app@production.service' \
  "$repo_root/ops/systemd/vsp-sub2api-production.target"; then
  echo 'production target must not hard-code the legacy App unit' >&2
  exit 1
fi
for target_unit in vsp-sub2api-production.target vsp-sub2api-rehearsal.target; do
  profile=${target_unit#vsp-sub2api-}
  profile=${profile%.target}
  grep -Fx "Wants=vsp-proxy-allocator@$profile.service" \
    "$repo_root/ops/systemd/$target_unit" >/dev/null
  if grep -Eq "^(Requires|BindsTo)=.*vsp-proxy-allocator@$profile" \
    "$repo_root/ops/systemd/$target_unit"; then
    echo "$target_unit must not stop-propagate from the deploy-restarted allocator" >&2
    exit 1
  fi
done
grep -Fq 'SUB2API_DISABLE_AUTONOMOUS_WORKERS=$disable_workers' "$native_dir/install.sh"

cat >"$temp_dir/source.env" <<'EOF'
DATABASE_USER=sub2api
DATABASE_PASSWORD=test-only
DATABASE_DBNAME=sub2api
JWT_SECRET=test-only
TOTP_ENCRYPTION_KEY=test-only
SELECTED_NODE_TOKEN=test-only
PRICING_DATA_DIR=/wrong/data
PRICING_FALLBACK_FILE=/wrong/fallback.json
EOF

for profile in production rehearsal; do
  python3 "$native_dir/render_app_env.py" \
    --profile "$profile" \
    --source "$temp_dir/source.env" \
    --output "$temp_dir/$profile.env" >/dev/null
  grep -Fx "PRICING_DATA_DIR=/var/lib/vsp-sub2api/$profile/app/data" "$temp_dir/$profile.env" >/dev/null
  grep -Fx 'PRICING_FALLBACK_FILE=/opt/vsp-sub2api/current/resources/model-pricing/model_prices_and_context_window.json' \
    "$temp_dir/$profile.env" >/dev/null
  grep -Fx 'LAB_DASHBOARD_SCHEDULER_GROUP_ID=30' "$temp_dir/$profile.env" >/dev/null
done

grep -Fx 'SELECTED_NODE_ENDPOINT=http://127.0.0.1:19290/v1/selected-nodes' \
  "$temp_dir/production.env" >/dev/null
grep -Fx 'SELECTED_NODE_ENDPOINT=http://127.0.0.1:19190/v1/selected-nodes' \
  "$temp_dir/rehearsal.env" >/dev/null
PYTHONPATH="$repo_root/ops/mihomo" PYTHONPYCACHEPREFIX="$temp_dir/pycache" python3 - <<'PY'
from render_profile import PROFILE_PORTS

assert PROFILE_PORTS["production"]["selected_node"] == 19290
assert PROFILE_PORTS["rehearsal"]["selected_node"] == 19190
PY

echo 'native shell, Python, pricing, and Selected Node contract checks passed'
