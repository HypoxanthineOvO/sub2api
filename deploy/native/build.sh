#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
dist="$repo_root/dist/native"
mkdir -p "$dist"
pnpm --dir "$repo_root/frontend" run build
(cd "$repo_root/backend" && CGO_ENABLED=0 go build -tags embed -trimpath -o "$dist/sub2api" ./cmd/server)
printf 'built %s\n' "$dist/sub2api"
