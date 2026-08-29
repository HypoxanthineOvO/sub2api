#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
dist="$repo_root/dist/native"
temp_dir=$(mktemp -d)
trap 'rm -rf "$temp_dir"' EXIT

source_tree() {
  local index="$temp_dir/source.index"
  rm -f "$index"
  GIT_INDEX_FILE="$index" git -C "$repo_root" read-tree HEAD
  GIT_INDEX_FILE="$index" git -C "$repo_root" add -A -- backend frontend
  GIT_INDEX_FILE="$index" git -C "$repo_root" write-tree
}

source_commit=$(git -C "$repo_root" rev-parse HEAD)
source_tree_id=$(source_tree)
mkdir -p "$dist"
pnpm --dir "$repo_root/frontend" run build
(cd "$repo_root/backend" && CGO_ENABLED=0 go build -tags embed -trimpath -o "$dist/sub2api" ./cmd/server)
[[ $(git -C "$repo_root" rev-parse HEAD) == "$source_commit" ]] || {
  echo 'HEAD changed during build; refusing to mark the artifact.' >&2
  exit 1
}
[[ $(source_tree) == "$source_tree_id" ]] || {
  echo 'Source changed during build; refusing to mark the artifact.' >&2
  exit 1
}
printf '%s\n' "$source_commit" >"$dist/source-commit"
printf '%s\n' "$source_tree_id" >"$dist/source-tree"
sha256sum "$dist/sub2api" | awk '{print $1}' >"$dist/sub2api.sha256"
printf 'built %s\n' "$dist/sub2api"
