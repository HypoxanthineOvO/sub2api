#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: sudo $0 <blue|green>" >&2
  exit 2
}

[[ $# -eq 1 ]] || usage
slot=$1
case $slot in
  blue)
    target_port=19821
    old_port=19822
    ;;
  green)
    target_port=19822
    old_port=19821
    ;;
  *) usage ;;
esac

if [[ ${EUID} -ne 0 ]]; then
  echo 'switch-app-slot.sh must run as root.' >&2
  exit 1
fi

active_link=/etc/nginx/sub2api-upstreams/active.conf
target=/etc/nginx/sub2api-upstreams/$slot.conf
drain_timeout=${VSP_APP_DRAIN_TIMEOUT:-660}

[[ $drain_timeout =~ ^[0-9]+$ ]] || {
  echo 'VSP_APP_DRAIN_TIMEOUT must be a non-negative integer.' >&2
  exit 1
}
[[ -f $target ]] || { echo "Missing Nginx upstream fragment: $target" >&2; exit 1; }
[[ -L $active_link ]] || { echo "Active upstream is not a symlink: $active_link" >&2; exit 1; }

for _ in $(seq 1 10); do
  if curl --noproxy '*' --silent --fail --max-time 3 \
    "http://127.0.0.1:$target_port/health" | grep -q '"status":"ok"'; then
    target_healthy=true
    break
  fi
  sleep 1
done
[[ ${target_healthy:-false} == true ]] || {
  echo "Target slot $slot is not healthy on port $target_port; Nginx was not changed." >&2
  exit 1
}

old_target=$(readlink -f "$active_link")
case $old_target in
  /etc/nginx/sub2api-upstreams/blue.conf|/etc/nginx/sub2api-upstreams/green.conf) ;;
  *) echo "Refusing unexpected active upstream target: $old_target" >&2; exit 1 ;;
esac

replace_link() {
  local link_target=$1
  local next_link=${active_link}.next.$$
  ln -s "$link_target" "$next_link"
  mv -Tf "$next_link" "$active_link"
}

rollback_nginx() {
  echo "Restoring Nginx upstream to $old_target" >&2
  replace_link "$old_target"
  if nginx -t; then
    nginx -s reload || true
  fi
}

replace_link "$target"
if ! nginx -t; then
  rollback_nginx
  exit 1
fi
if ! nginx -s reload; then
  rollback_nginx
  exit 1
fi
if ! curl --noproxy '*' --silent --show-error --fail --max-time 10 \
  --resolve api.vsplab.cn:443:127.0.0.1 \
  https://api.vsplab.cn/health | grep -q '"status":"ok"'; then
  echo 'Nginx reloaded but the HTTPS health check failed.' >&2
  rollback_nginx
  exit 1
fi

echo "Nginx now routes new connections to $slot on port $target_port."

deadline=$((SECONDS + drain_timeout))
while (( SECONDS <= deadline )); do
  connections=$(ss -Htn state established | awk -v endpoint="127.0.0.1:$old_port" \
    '$4 == endpoint || $5 == endpoint { count++ } END { print count + 0 }')
  if (( connections == 0 )); then
    echo "Old port $old_port is drained."
    exit 0
  fi
  sleep 2
done

echo "Nginx switch succeeded, but $connections connection(s) remain on old port $old_port." >&2
echo 'Leave the old App running and retry the drain check later; do not force-stop it.' >&2
exit 3
