#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
dist="$repo_root/dist/native"

source_is_clean() {
  git -C "$repo_root" diff --quiet \
    && git -C "$repo_root" diff --cached --quiet \
    && [[ -z $(git -C "$repo_root" ls-files --others --exclude-standard -- backend frontend) ]]
}

if ! source_is_clean; then
  echo 'Tracked changes or untracked backend/frontend sources must be resolved before building.' >&2
  exit 1
fi
source_commit=$(git -C "$repo_root" rev-parse HEAD)
mkdir -p "$dist"
pnpm --dir "$repo_root/frontend" run build
(cd "$repo_root/backend" && CGO_ENABLED=0 go build -tags embed -trimpath -o "$dist/sub2api" ./cmd/server)
[[ $(git -C "$repo_root" rev-parse HEAD) == "$source_commit" ]] || {
  echo 'HEAD changed during build; refusing to mark the artifact.' >&2
  exit 1
}
source_is_clean || {
  echo 'Source changed during build; refusing to mark the artifact.' >&2
  exit 1
}
printf '%s\n' "$source_commit" >"$dist/source-commit"
printf 'built %s\n' "$dist/sub2api"
