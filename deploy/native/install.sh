#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
prefix=${VSP_NATIVE_PREFIX:-/opt/vsp-sub2api}
config_root=${VSP_NATIVE_CONFIG_ROOT:-/etc/vsp-sub2api}
data_root=${VSP_NATIVE_DATA_ROOT:-/var/lib/vsp-sub2api}
release=${VSP_NATIVE_RELEASE:-$(git -C "$repo_root" rev-parse --short HEAD)}
release_dir="$prefix/releases/$release"
pricing_fallback="$repo_root/backend/resources/model-pricing/model_prices_and_context_window.json"

if [[ ${EUID} -ne 0 ]]; then
  echo 'install.sh requires root; run it only after reviewing the paths.' >&2
  exit 1
fi

install -d -m 0755 "$release_dir" "$config_root" "$data_root"
install -d -m 0755 "$config_root/production" "$config_root/rehearsal"
install -d -m 0755 "$data_root/production" "$data_root/rehearsal"
install -m 0755 "$repo_root/dist/native/sub2api" "$release_dir/sub2api"
install -d -m 0755 "$release_dir/resources/model-pricing"
install -m 0644 "$pricing_fallback" \
  "$release_dir/resources/model-pricing/model_prices_and_context_window.json"
install -d -m 0755 "$release_dir/ops/llm-proxy" "$release_dir/ops/selected-node"
install -m 0755 "$repo_root/ops/llm-proxy/allocator.py" "$release_dir/ops/llm-proxy/allocator.py"
install -m 0755 "$repo_root/ops/selected-node/selected_node_aggregator.py" "$release_dir/ops/selected-node/selected_node_aggregator.py"
ln -sfn "$release_dir" "$prefix/current"
echo 'install.sh only lays out the reviewed binary and directories.'
echo 'It does not install units, initialize databases, restore data, or start services.'
