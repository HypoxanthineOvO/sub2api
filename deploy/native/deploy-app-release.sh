#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
prefix=${VSP_NATIVE_PREFIX:-/opt/vsp-sub2api}
config_root=${VSP_NATIVE_CONFIG_ROOT:-/etc/vsp-sub2api}
soak_seconds=${VSP_CANARY_SOAK_SECONDS:-15}
drain_timeout=${VSP_DEPLOY_DRAIN_TIMEOUT:-120}
switch_script="$repo_root/deploy/native/switch-app-slot.sh"

repo_git() {
  git -c safe.directory="$repo_root" -C "$repo_root" "$@"
}

if [[ ${EUID} -ne 0 ]]; then
  echo 'deploy-app-release.sh must run as root.' >&2
  exit 1
fi
[[ $soak_seconds =~ ^[0-9]+$ ]] || {
  echo 'VSP_CANARY_SOAK_SECONDS must be a non-negative integer.' >&2
  exit 1
}
[[ $drain_timeout =~ ^[0-9]+$ ]] || {
  echo 'VSP_DEPLOY_DRAIN_TIMEOUT must be a non-negative integer.' >&2
  exit 1
}

for path in \
  "$repo_root/dist/native/sub2api" \
  "$repo_root/dist/native/source-commit" \
  "$repo_root/deploy/native/install.sh" \
  "$switch_script" \
  /etc/nginx/sub2api-upstreams/active.conf \
  /etc/nginx/sub2api-upstreams/blue.conf \
  /etc/nginx/sub2api-upstreams/green.conf \
  /etc/systemd/system/vsp-sub2api-app-slot@.service
do
  [[ -e $path ]] || { echo "Missing required path: $path" >&2; exit 1; }
done

repo_git diff --quiet
repo_git diff --cached --quiet
untracked_sources=$(repo_git ls-files --others --exclude-standard -- backend frontend)
if [[ -n $untracked_sources ]]; then
  echo 'Untracked backend/frontend source files must be resolved before deployment.' >&2
  exit 1
fi
head_commit=$(repo_git rev-parse HEAD)
built_commit=$(tr -d '[:space:]' <"$repo_root/dist/native/source-commit")
[[ $built_commit == "$head_commit" ]] || {
  echo "Build is for $built_commit, but HEAD is $head_commit; run build.sh again." >&2
  exit 1
}
release=${head_commit:0:9}

active_target=$(readlink -f /etc/nginx/sub2api-upstreams/active.conf)
case $active_target in
  /etc/nginx/sub2api-upstreams/blue.conf)
    old_slot=blue
    old_port=19821
    new_slot=green
    new_port=19822
    ;;
  /etc/nginx/sub2api-upstreams/green.conf)
    old_slot=green
    old_port=19822
    new_slot=blue
    new_port=19821
    ;;
  *) echo "Unexpected active upstream: $active_target" >&2; exit 1 ;;
esac

old_service="vsp-sub2api-app-slot@$old_slot.service"
new_service="vsp-sub2api-app-slot@$new_slot.service"
systemctl is-active --quiet "$old_service" || {
  echo "Active slot service is not running: $old_service" >&2
  exit 1
}
systemctl is-enabled --quiet "$old_service" || {
  echo "Active slot service is not enabled for boot: $old_service" >&2
  exit 1
}
curl --noproxy '*' --silent --fail --max-time 5 \
  "http://127.0.0.1:$old_port/health" >/dev/null

wait_for_new_health() {
  for _ in $(seq 1 30); do
    if curl --noproxy '*' --silent --fail --max-time 3 \
      "http://127.0.0.1:$new_port/health" | grep -q '"status":"ok"'; then
      return 0
    fi
    sleep 1
  done
  return 1
}

install_slot() {
  local mode=$1
  env VSP_NATIVE_RELEASE="$release" VSP_NATIVE_SLOT="$new_slot" \
    VSP_NATIVE_SLOT_MODE="$mode" VSP_NATIVE_PREFIX="$prefix" \
    VSP_NATIVE_CONFIG_ROOT="$config_root" \
    bash "$repo_root/deploy/native/install.sh"
}

routing_is_old() {
  [[ $(readlink -f /etc/nginx/sub2api-upstreams/active.conf) == \
    "/etc/nginx/sub2api-upstreams/$old_slot.conf" ]] \
    && systemctl is-active --quiet "$old_service" \
    && curl --noproxy '*' --silent --fail --max-time 5 \
      "http://127.0.0.1:$old_port/health" >/dev/null
}

route_to_old() {
  VSP_APP_DRAIN_TIMEOUT="$drain_timeout" bash "$switch_script" "$old_slot" || true
  routing_is_old
}

new_is_drained() {
  local connections
  connections=$(ss -Htn state established | awk -v endpoint="127.0.0.1:$new_port" \
    '$4 == endpoint || $5 == endpoint { count++ } END { print count + 0 }')
  (( connections == 0 ))
}

restore_old() {
  route_to_old || return 1
  systemctl enable "$old_service" || return 1
  systemctl disable "$new_service" || return 1
  if new_is_drained; then
    systemctl stop "$new_service" || true
  else
    echo 'New slot still has established connections; leaving it running but disabled.' >&2
  fi
}

committed=false
handle_interrupt() {
  trap - INT TERM HUP
  echo 'Deployment interrupted.' >&2
  if [[ $committed != true ]]; then
    if restore_old; then
      echo 'Traffic was returned to the old slot.' >&2
    else
      echo 'Traffic could not be verified on the old slot; leaving both App services running.' >&2
    fi
  fi
  exit 130
}
trap handle_interrupt INT TERM HUP

echo "Staging $release in inactive slot $new_slot."
install_slot canary
systemctl restart "$new_service"
if ! wait_for_new_health; then
  systemctl stop "$new_service" || true
  echo "Canary slot $new_slot did not become healthy; active slot was not changed." >&2
  exit 1
fi

if ! VSP_APP_DRAIN_TIMEOUT="$drain_timeout" bash "$switch_script" "$new_slot"; then
  if restore_old; then
    echo 'Canary switch failed; traffic was returned to the old slot.' >&2
  else
    echo 'Canary switch failed and traffic could not be verified on the old slot; leaving both App services running.' >&2
  fi
  exit 1
fi

canary_ok=true
for _ in $(seq 1 "$soak_seconds"); do
  if ! curl --noproxy '*' --silent --fail --max-time 3 \
    "http://127.0.0.1:$new_port/health" >/dev/null; then
    canary_ok=false
    break
  fi
  sleep 1
done
if [[ $canary_ok != true ]]; then
  if restore_old; then
    echo 'Canary health failed; traffic was returned to the old slot.' >&2
  else
    echo 'Canary health failed and traffic could not be verified on the old slot; leaving both App services running.' >&2
  fi
  exit 1
fi

if ! VSP_APP_DRAIN_TIMEOUT="$drain_timeout" bash "$switch_script" "$old_slot"; then
  echo 'Could not verify that the canary slot drained after returning traffic; leaving both App services running.' >&2
  exit 1
fi

install_slot active
systemctl restart "$new_service"
if ! wait_for_new_health; then
  systemctl stop "$new_service" || true
  echo 'Promoted slot did not become healthy; the old slot remains active.' >&2
  exit 1
fi

if ! VSP_APP_DRAIN_TIMEOUT="$drain_timeout" bash "$switch_script" "$new_slot"; then
  if restore_old; then
    echo 'Final switch failed; traffic was returned to the old slot.' >&2
  else
    echo 'Final switch failed and traffic could not be verified on the old slot; leaving both App services running.' >&2
  fi
  exit 1
fi

if ! systemctl enable "$new_service" || ! systemctl disable "$old_service"; then
  if restore_old; then
    echo 'Could not persist slot enablement; traffic was returned to the old slot.' >&2
  else
    echo 'Could not persist slot enablement and traffic could not be returned; leaving both App services running.' >&2
  fi
  exit 1
fi
committed=true
if ! systemctl stop "$old_service"; then
  echo 'New slot is live and enabled, but the drained old slot could not be stopped.' >&2
  exit 1
fi

systemctl is-active --quiet "$new_service"
systemctl is-enabled --quiet "$new_service"
systemctl is-active --quiet "$old_service" && {
  echo "Old slot is still active: $old_service" >&2
  exit 1
}
[[ $(readlink -f /etc/nginx/sub2api-upstreams/active.conf) == \
  "/etc/nginx/sub2api-upstreams/$new_slot.conf" ]]
curl --noproxy '*' --silent --fail --max-time 10 \
  --resolve api.vsplab.cn:443:127.0.0.1 \
  https://api.vsplab.cn/health | grep -q '"status":"ok"'

trap - INT TERM HUP
echo "Release $release is live in $new_slot; $old_slot is stopped and retained for rollback."
