#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
prefix=${VSP_NATIVE_PREFIX:-/opt/vsp-sub2api}
config_root=${VSP_NATIVE_CONFIG_ROOT:-/etc/vsp-sub2api}
data_root=${VSP_NATIVE_DATA_ROOT:-/var/lib/vsp-sub2api}

if [[ ${EUID} -ne 0 ]]; then
  echo 'install.sh requires root; run it only after reviewing the paths.' >&2
  exit 1
fi

install -d -m 0755 "$prefix/releases" "$config_root" "$data_root"
install -d -m 0755 "$config_root/production" "$config_root/rehearsal"
install -d -m 0755 "$data_root/production" "$data_root/rehearsal"
install -m 0755 "$repo_root/dist/native/sub2api" "$prefix/releases/sub2api"
ln -sfn "$prefix/releases/sub2api" "$prefix/current"
echo 'install.sh only lays out the reviewed binary and directories.'
echo 'It does not install units, initialize databases, restore data, or start services.'
