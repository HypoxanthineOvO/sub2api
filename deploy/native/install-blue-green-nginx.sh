#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
upstream_dir=/etc/nginx/sub2api-upstreams
upstream_config=/etc/nginx/conf.d/sub2api-upstream.conf
site_config=/etc/nginx/sites-enabled/api.vsplab.cn

if [[ ${EUID} -ne 0 ]]; then
  echo 'install-blue-green-nginx.sh must run as root.' >&2
  exit 1
fi

for source in \
  "$repo_root/deploy/native/nginx/blue.conf" \
  "$repo_root/deploy/native/nginx/green.conf" \
  "$repo_root/deploy/native/nginx/sub2api-upstream.conf" \
  "$repo_root/deploy/native/nginx/api.vsplab.cn.conf"
do
  [[ -f $source ]] || { echo "Missing source file: $source" >&2; exit 1; }
done
[[ ! -e $upstream_config ]] || {
  echo "Refusing to overwrite existing Nginx upstream config: $upstream_config" >&2
  exit 1
}

for port in 19821 19822; do
  curl --noproxy '*' --silent --show-error --fail --max-time 5 \
    "http://127.0.0.1:$port/health" | grep -q '"status":"ok"' || {
      echo "App health check failed on port $port; Nginx was not changed." >&2
      exit 1
    }
done

backup=$(mktemp /tmp/api.vsplab.cn.bluegreen.XXXXXX)
cp "$site_config" "$backup"

restore_site() {
  cp "$backup" "$site_config"
  rm -f "$upstream_config" "$upstream_dir/active.conf" \
    "$upstream_dir/blue.conf" "$upstream_dir/green.conf"
  rmdir "$upstream_dir" 2>/dev/null || true
  if nginx -t; then
    nginx -s reload || true
  fi
  rm -f "$backup"
}

install -d -m 0755 "$upstream_dir"
install -m 0644 "$repo_root/deploy/native/nginx/blue.conf" "$upstream_dir/blue.conf"
install -m 0644 "$repo_root/deploy/native/nginx/green.conf" "$upstream_dir/green.conf"
ln -sfn "$upstream_dir/blue.conf" "$upstream_dir/active.conf"
install -m 0644 "$repo_root/deploy/native/nginx/sub2api-upstream.conf" "$upstream_config"
install -m 0644 "$repo_root/deploy/native/nginx/api.vsplab.cn.conf" "$site_config"

if ! nginx -t; then
  echo 'Nginx test failed; restoring the original site.' >&2
  restore_site
  exit 1
fi
if ! nginx -s reload; then
  echo 'Nginx reload failed; restoring the original site.' >&2
  restore_site
  exit 1
fi
if ! curl --noproxy '*' --silent --show-error --fail --max-time 10 \
  --resolve api.vsplab.cn:443:127.0.0.1 \
  https://api.vsplab.cn/health | grep -q '"status":"ok"'; then
  echo 'HTTPS health check failed after reload; restoring the original site.' >&2
  restore_site
  exit 1
fi

rm -f "$backup"
echo 'Nginx blue-green upstream installed; active remains blue on port 19821.'
