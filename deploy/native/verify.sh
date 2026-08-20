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
