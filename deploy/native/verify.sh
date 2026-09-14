#!/usr/bin/env bash
set -euo pipefail
native_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$native_dir/../.." && pwd)
bash -n "$native_dir/vsp-release"
python3 - "$native_dir" <<'PY'
import ast, pathlib, sys
for path in pathlib.Path(sys.argv[1]).glob('*.py'):
    ast.parse(path.read_text(), filename=str(path))
PY
test -s "$repo_root/backend/resources/model-pricing/model_prices_and_context_window.json"
grep -Fqx 'ExecStart=/opt/vsp-sub2api-managed/slots/%i/sub2api' \
  "$repo_root/ops/systemd/vsp-sub2api-app-slot@.service"
if grep -Eq '^(Requires|PartOf)=' "$repo_root/ops/systemd/vsp-sub2api-app-slot@.service"; then
  echo 'App slot must not control data-plane units' >&2
  exit 1
fi
for test in native-retirement-test.py proxy-retirement-execution-test.py managed-release-test.py schema-release-test.py direct-launch-test.py db-maint-test.py; do
  PYTHONDONTWRITEBYTECODE=1 python3 "$repo_root/deploy/tests/$test"
done
echo 'release source, slot isolation, retirement and transaction checks passed'
