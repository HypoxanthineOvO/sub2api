#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
repo_root=$(realpath -e "$repo_root")
operator_user=${VSP_DEPLOY_OPERATOR_USER:-${SUDO_USER:-}}
libexec=/usr/local/libexec/vsp-sub2api
app_wrapper=/usr/local/sbin/vsp-sub2api-deploy
allocator_wrapper=/usr/local/sbin/vsp-sub2api-allocator-deploy
sudoers=/etc/sudoers.d/vsp-sub2api-deploy
allocator_root=/opt/vsp-sub2api/allocator
allocator_current="$allocator_root/current"
allocator_source=/opt/vsp-sub2api/current/ops/llm-proxy/allocator.py
allocator_dropin_dir=/etc/systemd/system/vsp-proxy-allocator@production.service.d
allocator_dropin="$allocator_dropin_dir/allocator-release.conf"

if [[ ${EUID} -ne 0 ]]; then
  echo 'install-agent-deployer.sh must run as root.' >&2
  exit 1
fi
if [[ -z $operator_user || $operator_user == root ]] || ! id "$operator_user" >/dev/null 2>&1; then
  echo 'Set VSP_DEPLOY_OPERATOR_USER to the non-root deployment operator.' >&2
  exit 1
fi

for command in realpath sha256sum systemctl visudo; do
  command -v "$command" >/dev/null || { echo "Missing command: $command" >&2; exit 1; }
done
for script in deploy-app-release.sh deploy-proxy-allocator.sh install.sh switch-app-slot.sh; do
  bash -n "$repo_root/deploy/native/$script"
done

temp_dir=$(mktemp -d)
trap 'rm -rf "$temp_dir"' EXIT
quoted_repo=$(printf '%q' "$repo_root")
cat >"$temp_dir/vsp-sub2api-deploy" <<EOF
#!/usr/bin/env bash
set -euo pipefail
[[ \$# -eq 0 ]] || { echo 'vsp-sub2api-deploy takes no arguments.' >&2; exit 2; }
exec env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \\
  VSP_NATIVE_REPO_ROOT=$quoted_repo \\
  VSP_NATIVE_DEPLOY_LIBEXEC=$libexec \\
  $libexec/deploy-app-release.sh
EOF
cat >"$temp_dir/vsp-sub2api-allocator-deploy" <<EOF
#!/usr/bin/env bash
set -euo pipefail
[[ \$# -eq 0 ]] || { echo 'vsp-sub2api-allocator-deploy takes no arguments.' >&2; exit 2; }
exec env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  VSP_NATIVE_REPO_ROOT=$quoted_repo \
  $libexec/deploy-proxy-allocator.sh
EOF
cat >"$temp_dir/sudoers" <<EOF
$operator_user ALL=(root) NOPASSWD: $app_wrapper
$operator_user ALL=(root) NOPASSWD: $allocator_wrapper
EOF
cat >"$temp_dir/allocator-release.conf" <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/python3 /opt/vsp-sub2api/allocator/current/allocator.py --config /etc/vsp-sub2api/%i/allocator.json --state /var/lib/vsp-sub2api/%i/allocator/state.json --lock /var/lib/vsp-sub2api/%i/allocator/allocator.lock --interval 60
EOF
visudo -cf "$temp_dir/sudoers" >/dev/null

[[ -f $allocator_source && ! -L $allocator_source ]] || {
  echo "Missing bootstrap allocator: $allocator_source" >&2
  exit 1
}
install -d -o root -g root -m 0755 "$allocator_root" "$allocator_root/releases"
if [[ ! -e $allocator_current && ! -L $allocator_current ]]; then
  allocator_sha=$(sha256sum "$allocator_source" | awk '{print $1}')
  allocator_release="$allocator_root/releases/$allocator_sha"
  if [[ ! -e $allocator_release ]]; then
    staged_allocator_release="$allocator_root/releases/.${allocator_sha}.new.$$"
    install -d -o root -g root -m 0755 "$staged_allocator_release"
    install -o root -g root -m 0755 "$allocator_source" "$staged_allocator_release/allocator.py"
    staged_sha=$(sha256sum "$staged_allocator_release/allocator.py" | awk '{print $1}')
    [[ $staged_sha == "$allocator_sha" ]] || { echo 'Bootstrap allocator checksum changed while copying.' >&2; exit 1; }
    mv -T "$staged_allocator_release" "$allocator_release"
  fi
  ln -s "$allocator_release" "$allocator_current.next.$$"
  mv -Tf "$allocator_current.next.$$" "$allocator_current"
fi
[[ -L $allocator_current ]] || { echo "Unexpected allocator current path: $allocator_current" >&2; exit 1; }
allocator_release=$(realpath -e "$allocator_current")
case $allocator_release in
  "$allocator_root"/releases/*) ;;
  *) echo "Unexpected allocator release: $allocator_release" >&2; exit 1 ;;
esac
[[ -f $allocator_release/allocator.py && ! -L $allocator_release/allocator.py ]] || {
  echo "Invalid allocator release: $allocator_release" >&2
  exit 1
}
allocator_release_sha=$(sha256sum "$allocator_release/allocator.py" | awk '{print $1}')
[[ ${allocator_release##*/} == "$allocator_release_sha" ]] || {
  echo "Allocator release checksum does not match its directory: $allocator_release" >&2
  exit 1
}

install -d -o root -g root -m 0755 "$libexec"
install -o root -g root -m 0755 \
  "$repo_root/deploy/native/deploy-app-release.sh" \
  "$repo_root/deploy/native/deploy-proxy-allocator.sh" \
  "$repo_root/deploy/native/install.sh" \
  "$repo_root/deploy/native/switch-app-slot.sh" \
  "$libexec/"
install -o root -g root -m 0755 "$temp_dir/vsp-sub2api-deploy" "$app_wrapper"
install -o root -g root -m 0755 "$temp_dir/vsp-sub2api-allocator-deploy" "$allocator_wrapper"
install -d -o root -g root -m 0755 "$allocator_dropin_dir"
install -o root -g root -m 0644 "$temp_dir/allocator-release.conf" "$allocator_dropin"
install -o root -g root -m 0440 "$temp_dir/sudoers" "$sudoers"
visudo -cf "$sudoers" >/dev/null
systemctl daemon-reload
effective_exec=$(systemctl show -p ExecStart --value vsp-proxy-allocator@production.service)
[[ $effective_exec == *'/usr/bin/python3 /opt/vsp-sub2api/allocator/current/allocator.py '* ]] || {
  echo "Effective allocator ExecStart is unexpected after daemon-reload: $effective_exec" >&2
  exit 1
}

echo "Installed constrained agent deploy commands for $operator_user:"
echo "  $app_wrapper"
echo "  $allocator_wrapper"
