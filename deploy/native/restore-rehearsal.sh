#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo 'restore-rehearsal.sh requires root.' >&2
  exit 1
fi

case ${1:-} in
  --confirm-snapshot-and-restore)
    restore_mode=fresh
    ;;
  --resume-existing)
    restore_mode=resume
    ;;
  *)
    echo 'Usage: sudo bash deploy/native/restore-rehearsal.sh {--confirm-snapshot-and-restore|--resume-existing}' >&2
    echo 'Fresh mode snapshots and restores Docker data; resume mode reuses an existing stopped rehearsal restore.' >&2
    exit 2
    ;;
esac

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
config_root=/etc/vsp-sub2api/rehearsal
data_root=/var/lib/vsp-sub2api/rehearsal
pg_socket=/run/vsp-sub2api-rehearsal-postgresql
pg_port=55432
redis_port=56379
app_port=19822
production_app_port=19821
app_container=sub2api
pg_container=c8-next-postgres
redis_container=c8-next-redis
mihomo_source_root=/home/heyx/.config/mihomo-llm
allocator_source=/home/heyx/.config/llm-proxy/nodes.json
selected_node_source=/home/heyx/Workspace/Hypo/Hypo-LLM/ops/sub2api/selected-node-aggregator/config.release.local.json
required_release=${VSP_NATIVE_RELEASE:-}
installed_release=$(basename "$(readlink -f /opt/vsp-sub2api/current)")
timestamp=$(date +%Y%m%dT%H%M%S)
snapshot_dir="$data_root/snapshots/$timestamp"
temp_dir=$(mktemp -d /run/vsp-sub2api-rehearsal-restore.XXXXXX)
started_rehearsal=false

cleanup() {
  rm -rf "$temp_dir"
}

stop_on_error() {
  local status=$?
  if [[ $started_rehearsal == true ]]; then
    echo 'Restore failed; stopping rehearsal services started by this script.' >&2
    systemctl stop vsp-sub2api-rehearsal.target vsp-postgresql@rehearsal.service vsp-redis@rehearsal.service || true
  fi
  echo 'Rehearsal data may be partial; do not rerun. Return this output for a rehearsal-only reset.' >&2
  exit "$status"
}

trap cleanup EXIT
trap stop_on_error ERR

require_command() {
  command -v "$1" >/dev/null || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

for command in curl docker find grep install pg_isready pg_restore psql python3 redis-check-rdb redis-cli runuser seq ss systemctl tr xargs; do
  require_command "$command"
done
if [[ ! -x /home/heyx/.local/bin/mihomo ]]; then
  echo 'Missing reviewed Mihomo binary: /home/heyx/.local/bin/mihomo' >&2
  exit 1
fi
if [[ -z $required_release ]]; then
  echo 'VSP_NATIVE_RELEASE is required; pass the reviewed Git short commit from the invoking shell.' >&2
  exit 1
fi
if [[ $installed_release != "$required_release" ]]; then
  echo "Installed native release is $installed_release; expected $required_release. Run deploy/native/install.sh first." >&2
  exit 1
fi
installed_working_directory=$(systemctl show vsp-sub2api-app@rehearsal.service --property WorkingDirectory --value)
if [[ $installed_working_directory != "$data_root/app" ]]; then
  echo "Installed App WorkingDirectory is $installed_working_directory; expected $data_root/app. Install the reviewed unit and run daemon-reload." >&2
  exit 1
fi

for container in "$app_container" "$pg_container" "$redis_container"; do
  if [[ $(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null) != true ]]; then
    echo "Production container is not running: $container" >&2
    exit 1
  fi
done

if ! curl --noproxy '*' --silent --show-error --fail --max-time 5 \
  "http://127.0.0.1:$production_app_port/health" >/dev/null; then
  echo 'Production app health check failed; refusing to snapshot.' >&2
  exit 1
fi

if systemctl is-active --quiet vsp-sub2api-production.target; then
  echo 'Native production target is active; refusing an ambiguous restore.' >&2
  exit 1
fi
if systemctl is-active --quiet vsp-sub2api-rehearsal.target \
  || systemctl is-active --quiet vsp-postgresql@rehearsal.service \
  || systemctl is-active --quiet vsp-redis@rehearsal.service; then
  echo 'Rehearsal services are already active; stop them before restoring.' >&2
  exit 1
fi

for port in 19822 55432 56379 19190 18901 18902 18903 18904 18905 29191 29192 29193 29194 29195; do
  if ss -ltnH "sport = :$port" | grep -q .; then
    echo "Rehearsal port is already in use: $port" >&2
    exit 1
  fi
done

if [[ $(<"$data_root/postgresql/PG_VERSION") != 16 ]]; then
  echo 'Expected an initialized PostgreSQL 16 rehearsal cluster.' >&2
  exit 1
fi
if [[ $restore_mode == fresh ]]; then
  if find "$data_root/redis" -mindepth 1 -print -quit | grep -q .; then
    echo 'Rehearsal Redis directory is not empty; refusing to overwrite it.' >&2
    exit 1
  fi
elif [[ ! -f $data_root/redis/dump.rdb || ! -f $data_root/app/.installed ]]; then
  echo 'Existing rehearsal restore is incomplete; fresh reset is required.' >&2
  exit 1
fi
if [[ $restore_mode == resume ]]; then
  for config in "$config_root/app.env" "$config_root/allocator.json" "$config_root/selected-node.json" \
    "$config_root/mihomo/slot-a/config.yaml" "$config_root/mihomo/slot-b/config.yaml" \
    "$config_root/mihomo/slot-c/config.yaml" "$config_root/mihomo/slot-d/config.yaml" \
    "$config_root/mihomo/slot-e/config.yaml"; do
    if [[ ! -r $config ]]; then
      echo "Existing rehearsal configuration is missing or unreadable: $config" >&2
      exit 1
    fi
  done
  redis-check-rdb "$data_root/redis/dump.rdb" >/dev/null
  snapshot_dir=$(find "$data_root/snapshots" -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)
  if [[ -z $snapshot_dir ]]; then
    echo 'Existing rehearsal snapshot directory is missing.' >&2
    exit 1
  fi
fi

if [[ $restore_mode == fresh ]]; then
  for source in "$mihomo_source_root/slot-a/config.yaml" "$allocator_source" "$selected_node_source"; do
    if [[ ! -f $source ]]; then
      echo "Missing reviewed runtime source: $source" >&2
      exit 1
    fi
  done

  echo '[1/6] Rendering real loopback-only rehearsal configuration'
  docker inspect "$app_container" --format '{{range .Config.Env}}{{println .}}{{end}}' >"$temp_dir/container.env"
  python3 "$repo_root/deploy/native/render_app_env.py" \
    --profile rehearsal \
    --source "$temp_dir/container.env" \
    --output "$temp_dir/app.env" >/dev/null
  python3 "$repo_root/ops/mihomo/render_profile.py" \
    --profile rehearsal \
    --mihomo-source-root "$mihomo_source_root" \
    --allocator-source "$allocator_source" \
    --selected-node-source "$selected_node_source" \
    --output-root "$temp_dir/runtime" >/dev/null

  python3 - "$temp_dir/app.env" "$temp_dir/runtime/selected-node.json" <<'PY'
import json
import sys
from pathlib import Path

def read_env(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )

app = read_env(Path(sys.argv[1]))
selected = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
token = app.get("SELECTED_NODE_TOKEN", "")
if not token or token != selected.get("api_token") or "REPLACE" in token:
    raise SystemExit("Selected Node token contract does not match the production app")
if selected.get("bind_host") != "127.0.0.1" or selected.get("bind_port") != 19190:
    raise SystemExit("Selected Node rehearsal bind is not loopback:19190")
PY

  for slot in slot-a slot-b slot-c slot-d slot-e; do
    /home/heyx/.local/bin/mihomo -t \
      -d "$temp_dir/runtime/mihomo/$slot" \
      -f "$temp_dir/runtime/mihomo/$slot/config.yaml" >/dev/null
  done

  install -o root -g vsp-admin -m 0640 "$temp_dir/app.env" "$config_root/app.env"
  install -o root -g vsp-admin -m 0640 "$temp_dir/runtime/allocator.json" "$config_root/allocator.json"
  install -o root -g vsp-admin -m 0640 "$temp_dir/runtime/selected-node.json" "$config_root/selected-node.json"
  for slot in slot-a slot-b slot-c slot-d slot-e; do
    install -d -o root -g vsp-admin -m 0750 "$config_root/mihomo/$slot"
    install -o root -g vsp-admin -m 0640 \
      "$temp_dir/runtime/mihomo/$slot/config.yaml" "$config_root/mihomo/$slot/config.yaml"
  done

  database_user=$(sed -n 's/^DATABASE_USER=//p' "$config_root/app.env")
  database_name=$(sed -n 's/^DATABASE_DBNAME=//p' "$config_root/app.env")
  if [[ ! $database_user =~ ^[A-Za-z_][A-Za-z0-9_]*$ || ! $database_name =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo 'Rehearsal database user/name must be simple PostgreSQL identifiers.' >&2
    exit 1
  fi
  started_rehearsal=true
  systemctl start vsp-postgresql@rehearsal.service
  for _ in $(seq 1 60); do
    pg_isready -q -h "$pg_socket" -p "$pg_port" && break
    sleep 1
  done
  pg_isready -q -h "$pg_socket" -p "$pg_port"
  dirty_cluster=$(runuser -u postgres -- psql -X -qAt -h "$pg_socket" -p "$pg_port" -d postgres \
    --command="SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$database_name') OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$database_user');")
  if [[ $dirty_cluster != f ]]; then
    echo 'Fresh restore requires an empty rehearsal PostgreSQL cluster.' >&2
    exit 1
  fi

  echo '[2/6] Creating PostgreSQL logical snapshot'
  install -d -o root -g postgres -m 0750 "$snapshot_dir"
  docker exec "$pg_container" sh -lc \
    'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl' \
    >"$snapshot_dir/postgresql.dump"
  chown root:postgres "$snapshot_dir/postgresql.dump"
  chmod 0640 "$snapshot_dir/postgresql.dump"
  pg_restore --list "$snapshot_dir/postgresql.dump" >/dev/null

  echo '[3/6] Creating one synchronous Redis RDB snapshot'
  redis_reply=$(docker exec "$redis_container" env -u REDISCLI_AUTH redis-cli --raw SAVE | tr -d '\r')
  if [[ $redis_reply != OK ]]; then
    echo "Redis SAVE failed: $redis_reply" >&2
    exit 1
  fi
  docker cp "$redis_container:/data/dump.rdb" "$snapshot_dir/dump.rdb" >/dev/null
  redis-check-rdb "$snapshot_dir/dump.rdb" >/dev/null
  install -o redis -g redis -m 0600 "$snapshot_dir/dump.rdb" "$data_root/redis/dump.rdb"

  echo '[4/6] Starting isolated PostgreSQL and restoring the database'
  started_rehearsal=true
  systemctl start vsp-postgresql@rehearsal.service
  for _ in $(seq 1 60); do
    pg_isready -q -h "$pg_socket" -p "$pg_port" && break
    sleep 1
  done
  pg_isready -q -h "$pg_socket" -p "$pg_port"

  python3 - "$config_root/app.env" "$temp_dir/create-database.sql" "$temp_dir/remap-proxies.sql" <<'PY'
import json
import sys
from pathlib import Path

def read_env(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )

def ident(value: str) -> str:
    if not value or "\x00" in value or "\n" in value:
        raise ValueError("invalid PostgreSQL identifier")
    return '"' + value.replace('"', '""') + '"'

def literal(value: str) -> str:
    if "\x00" in value or "\n" in value:
        raise ValueError("invalid PostgreSQL literal")
    return "'" + value.replace("'", "''") + "'"

env = read_env(Path(sys.argv[1]))
user = ident(env["DATABASE_USER"])
password = literal(env["DATABASE_PASSWORD"])
database = ident(env["DATABASE_DBNAME"])
Path(sys.argv[2]).write_text(
    f"\\set ON_ERROR_STOP on\nCREATE ROLE {user} LOGIN PASSWORD {password};\n"
    f"CREATE DATABASE {database} OWNER {user};\n",
    encoding="utf-8",
)

mapping = json.loads(env["SELECTED_NODE_PROXY_SLOTS"])
ports = {"Slot A": 18901, "Slot B": 18902, "Slot C": 18903, "Slot D": 18904, "Slot E": 18905}
if set(mapping.values()) != set(ports) or len(mapping) != 5:
    raise ValueError("expected exactly five Selected Node proxy mappings")
rows = sorted((int(proxy_id), ports[name]) for proxy_id, name in mapping.items())
ids = ", ".join(str(proxy_id) for proxy_id, _ in rows)
cases = " ".join(f"WHEN {proxy_id} THEN {port}" for proxy_id, port in rows)
Path(sys.argv[3]).write_text(
    "\\set ON_ERROR_STOP on\n"
    "DO $$ BEGIN\n"
    f"  IF (SELECT count(*) FROM proxies WHERE id IN ({ids})) <> 5 THEN\n"
    "    RAISE EXCEPTION 'expected five rehearsal proxy rows';\n"
    "  END IF;\n"
    f"  UPDATE proxies SET host = '127.0.0.1', port = CASE id {cases} END "
    f"WHERE id IN ({ids});\n"
    "END $$;\n",
    encoding="utf-8",
)
PY
  chmod 0600 "$temp_dir/create-database.sql" "$temp_dir/remap-proxies.sql"
  runuser -u postgres -- psql -X -q -h "$pg_socket" -p "$pg_port" -d postgres \
    <"$temp_dir/create-database.sql"

  runuser -u postgres -- pg_restore --exit-on-error --no-owner --no-acl \
    --role "$database_user" -h "$pg_socket" -p "$pg_port" -d "$database_name" \
    "$snapshot_dir/postgresql.dump"
  runuser -u postgres -- psql -X -q -h "$pg_socket" -p "$pg_port" -d "$database_name" \
    <"$temp_dir/remap-proxies.sql"

  echo '[5/6] Starting rehearsal Redis and invalidating copied scheduler snapshots'
  systemctl start vsp-redis@rehearsal.service
  for _ in $(seq 1 30); do
    env -u REDISCLI_AUTH redis-cli -h 127.0.0.1 -p "$redis_port" ping 2>/dev/null | grep -qx PONG && break
    sleep 1
  done
  env -u REDISCLI_AUTH redis-cli -h 127.0.0.1 -p "$redis_port" ping | grep -qx PONG
  for pattern in 'sched:*' 'proxy:latency:*'; do
    env -u REDISCLI_AUTH redis-cli -h 127.0.0.1 -p "$redis_port" --scan --pattern "$pattern" \
      | xargs -r env -u REDISCLI_AUTH redis-cli -h 127.0.0.1 -p "$redis_port" UNLINK >/dev/null
  done
else
  echo '[resume] Reusing the stopped rehearsal PostgreSQL and Redis restore'
  started_rehearsal=true
  database_name=$(sed -n 's/^DATABASE_DBNAME=//p' "$config_root/app.env")
  if [[ ! $database_name =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo 'Rehearsal database name must be a simple PostgreSQL identifier.' >&2
    exit 1
  fi
  systemctl start vsp-postgresql@rehearsal.service
  for _ in $(seq 1 60); do
    pg_isready -q -h "$pg_socket" -p "$pg_port" && break
    sleep 1
  done
  pg_isready -q -h "$pg_socket" -p "$pg_port"
  restored_contract=$(runuser -u postgres -- psql -X -qAt -h "$pg_socket" -p "$pg_port" -d "$database_name" \
    --command="SELECT to_regclass('public.accounts') IS NOT NULL AND to_regclass('public.proxies') IS NOT NULL AND (SELECT count(*) FROM proxies WHERE (id, host, port) IN ((4, '127.0.0.1', 18901), (5, '127.0.0.1', 18902), (6, '127.0.0.1', 18903), (7, '127.0.0.1', 18904), (8, '127.0.0.1', 18905))) = 5;")
  if [[ $restored_contract != t ]]; then
    echo 'Existing rehearsal PostgreSQL restore does not satisfy the schema/proxy contract.' >&2
    exit 1
  fi
  systemctl start vsp-redis@rehearsal.service
  for _ in $(seq 1 30); do
    env -u REDISCLI_AUTH redis-cli -h 127.0.0.1 -p "$redis_port" ping 2>/dev/null | grep -qx PONG && break
    sleep 1
  done
  env -u REDISCLI_AUTH redis-cli -h 127.0.0.1 -p "$redis_port" ping | grep -qx PONG
fi

echo '[6/6] Starting the rehearsal target and waiting for health'
rm -f "$data_root/allocator/state.json"
allocator_started_at=$(date +%s)
systemctl start vsp-sub2api-rehearsal.target
for port in 18901 18902 18903 18904 18905 29191 29192 29193 29194 29195; do
  for _ in $(seq 1 30); do
    ss -ltnH "sport = :$port" | grep -q . && break
    sleep 1
  done
  ss -ltnH "sport = :$port" | grep -q .
done
for _ in $(seq 1 180); do
  if curl --noproxy '*' --silent --fail --max-time 3 \
    "http://127.0.0.1:$app_port/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl --noproxy '*' --silent --show-error --fail --max-time 5 \
  "http://127.0.0.1:$app_port/health" | grep -q '"status":"ok"'

python3 - "$data_root/allocator/state.json" "$allocator_started_at" <<'PY'
import json
import sys
import time
from pathlib import Path

state_path = Path(sys.argv[1])
started_at = int(sys.argv[2])
for _ in range(120):
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assignments = state.get("assignments", {})
        names = [assignments.get(f"slot-{letter}", {}).get("LLM-PRIMARY") for letter in "abcde"]
        health = state.get("health", {})
        if (
            state.get("updated_at", 0) >= started_at
            and all(names)
            and len(set(names)) == 5
            and all(health.get(name, {}).get("healthy") for name in names)
        ):
            break
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    time.sleep(1)
else:
    raise SystemExit("Allocator did not produce five healthy distinct rehearsal assignments")
PY

python3 - "$config_root/selected-node.json" <<'PY'
import json
import sys
import time
import urllib.request
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = {f"Slot {letter}" for letter in "ABCDE"}
for _ in range(90):
    try:
        request = urllib.request.Request("http://127.0.0.1:19190/v1/selected-nodes")
        request.add_header("Authorization", f"Bearer {config['api_token']}")
        with urllib.request.urlopen(request, timeout=5) as response:
            slots = json.load(response).get("slots", {})
        if set(slots) == expected and all(
            slot.get("status") in {"fresh", "stale"} for slot in slots.values()
        ):
            names = [slot.get("selected_node_name") for slot in slots.values()]
            if all(names) and len(set(names)) == 5:
                break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit("Selected Node did not return five available distinct rehearsal slots")
PY

for port in 18901 18902 18903 18904 18905; do
  curl --silent --show-error --fail --max-time 20 \
    --proxy "http://127.0.0.1:$port" https://chatgpt.com/cdn-cgi/trace \
    --output /dev/null
done

started_rehearsal=false
echo "Rehearsal is healthy at http://127.0.0.1:$app_port"
echo "Snapshot retained at $snapshot_dir"
echo 'Production containers and port 19821 were not changed.'
