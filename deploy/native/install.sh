#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
prefix=${VSP_NATIVE_PREFIX:-/opt/vsp-sub2api}
config_root=${VSP_NATIVE_CONFIG_ROOT:-/etc/vsp-sub2api}
data_root=${VSP_NATIVE_DATA_ROOT:-/var/lib/vsp-sub2api}
release=${VSP_NATIVE_RELEASE:-$(git -C "$repo_root" rev-parse --short HEAD)}
release_dir="$prefix/releases/$release"
pricing_fallback="$repo_root/backend/resources/model-pricing/model_prices_and_context_window.json"
slot=${VSP_NATIVE_SLOT:-}
slot_mode=${VSP_NATIVE_SLOT_MODE:-canary}

if [[ ${EUID} -ne 0 ]]; then
  echo 'install.sh requires root; run it only after reviewing the paths.' >&2
  exit 1
fi

if [[ -n $slot ]]; then
  case $slot in
    blue) slot_port=19821 ;;
    green) slot_port=19822 ;;
    *) echo 'VSP_NATIVE_SLOT must be blue or green.' >&2; exit 1 ;;
  esac
  case $slot_mode in
    canary) disable_workers=1 ;;
    active) disable_workers=0 ;;
    *) echo 'VSP_NATIVE_SLOT_MODE must be canary or active.' >&2; exit 1 ;;
  esac
fi

install -d -m 0755 "$release_dir" "$config_root" "$data_root"
install -d -m 0755 "$prefix/app-slots"
install -d -m 0755 "$config_root/production" "$config_root/rehearsal"
install -d -m 0755 "$data_root/production" "$data_root/rehearsal"
install -m 0755 "$repo_root/dist/native/sub2api" "$release_dir/sub2api"
install -d -m 0755 "$release_dir/resources/model-pricing"
install -m 0644 "$pricing_fallback" \
  "$release_dir/resources/model-pricing/model_prices_and_context_window.json"
install -d -m 0755 "$release_dir/ops/llm-proxy" "$release_dir/ops/selected-node"
install -m 0755 "$repo_root/ops/llm-proxy/allocator.py" "$release_dir/ops/llm-proxy/allocator.py"
install -m 0755 "$repo_root/ops/selected-node/selected_node_aggregator.py" "$release_dir/ops/selected-node/selected_node_aggregator.py"

if [[ -n $slot ]]; then
  ln -sfn "$release_dir" "$prefix/app-slots/$slot"
  slot_env=$(mktemp)
  trap 'rm -f "$slot_env"' EXIT
  cat >"$slot_env" <<EOF
SERVER_PORT=$slot_port
PRICING_FALLBACK_FILE=$prefix/app-slots/$slot/resources/model-pricing/model_prices_and_context_window.json
SUB2API_DISABLE_AUTONOMOUS_WORKERS=$disable_workers
EOF
  install -o root -g vsp-admin -m 0640 \
    "$slot_env" "$config_root/production/app-$slot.env"
  echo "prepared $slot slot at release $release in $slot_mode mode on port $slot_port"
else
  ln -sfn "$release_dir" "$prefix/current"
fi
echo 'install.sh only lays out the reviewed binary and directories.'
echo 'It does not install units, initialize databases, restore data, or start services.'
