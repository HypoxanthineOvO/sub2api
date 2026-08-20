#!/usr/bin/env bash
set -euo pipefail

for file in "$(dirname "${BASH_SOURCE[0]}")"/*.sh; do
  bash -n "$file"
done

python3 -m py_compile \
  "$(dirname "${BASH_SOURCE[0]}")/../../ops/llm-proxy/allocator.py" \
  "$(dirname "${BASH_SOURCE[0]}")/../../ops/mihomo/render_profile.py" \
  "$(dirname "${BASH_SOURCE[0]}")/../../ops/selected-node/selected_node_aggregator.py" \
  "$(dirname "${BASH_SOURCE[0]}")/render_app_env.py"

echo 'native shell and Python syntax checks passed'
