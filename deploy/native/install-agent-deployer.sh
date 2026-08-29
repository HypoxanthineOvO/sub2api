#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
repo_root=$(realpath -e "$repo_root")
operator_user=${VSP_DEPLOY_OPERATOR_USER:-${SUDO_USER:-}}
libexec=/usr/local/libexec/vsp-sub2api
wrapper=/usr/local/sbin/vsp-sub2api-deploy
sudoers=/etc/sudoers.d/vsp-sub2api-deploy

if [[ ${EUID} -ne 0 ]]; then
  echo 'install-agent-deployer.sh must run as root.' >&2
  exit 1
fi
if [[ -z $operator_user || $operator_user == root ]] || ! id "$operator_user" >/dev/null 2>&1; then
  echo 'Set VSP_DEPLOY_OPERATOR_USER to the non-root deployment operator.' >&2
  exit 1
fi

for command in realpath visudo; do
  command -v "$command" >/dev/null || { echo "Missing command: $command" >&2; exit 1; }
done
for script in deploy-app-release.sh install.sh switch-app-slot.sh; do
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
cat >"$temp_dir/sudoers" <<EOF
$operator_user ALL=(root) NOPASSWD: $wrapper
EOF
visudo -cf "$temp_dir/sudoers" >/dev/null

install -d -o root -g root -m 0755 "$libexec"
install -o root -g root -m 0755 \
  "$repo_root/deploy/native/deploy-app-release.sh" \
  "$repo_root/deploy/native/install.sh" \
  "$repo_root/deploy/native/switch-app-slot.sh" \
  "$libexec/"
install -o root -g root -m 0755 "$temp_dir/vsp-sub2api-deploy" "$wrapper"
install -o root -g root -m 0440 "$temp_dir/sudoers" "$sudoers"
visudo -cf "$sudoers" >/dev/null

echo "Installed constrained agent deploy command for $operator_user: $wrapper"
