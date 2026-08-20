#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  VSP_NATIVE_RELEASE=<reviewed-short-commit> bash deploy/native/cutover-production.sh --dry-run
  sudo env VSP_NATIVE_RELEASE=<reviewed-short-commit> \
    bash deploy/native/cutover-production.sh --execute --confirm-stop-production-and-switch-19821

Dry-run is read-only. Execute stops the production Docker App and old proxy control
plane, restores frozen Docker data into native PostgreSQL/Redis, and starts the
native App on 19821. Execute requires separate S4 authorization.
EOF
  exit 2
}

mode=${1:-}
confirmation=${2:-}
case $mode in
  --dry-run) ;;
  --execute)
    [[ $confirmation == --confirm-stop-production-and-switch-19821 ]] || usage
    ;;
  *) usage ;;
esac

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
release=${VSP_NATIVE_RELEASE:-}
prefix=/opt/vsp-sub2api
config_root=/etc/vsp-sub2api/production
data_root=/var/lib/vsp-sub2api/production
backup_root=/var/backups/vsp-sub2api
app_container=sub2api
pg_container=c8-next-postgres
redis_container=c8-next-redis
selected_node_container=sub2api-selected-node
app_port=19821
pg_port=5432
redis_port=6379
selected_node_port=19290
mihomo_source_root=/home/heyx/.config/mihomo-llm
allocator_source=/home/heyx/.config/llm-proxy/nodes.json
selected_node_source=/home/heyx/Workspace/Hypo/Hypo-LLM/ops/sub2api/selected-node-aggregator/config.release.local.json
operator_user=heyx
operator_uid=$(id -u "$operator_user")
temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/vsp-sub2api-production-cutover.XXXXXX")
phase=PREFLIGHT
commit_boundary=false
cutover_started=false

cleanup() {
  rm -rf "$temp_dir"
}

user_systemctl() {
  if [[ ${EUID} -eq 0 ]]; then
    runuser -u "$operator_user" -- env XDG_RUNTIME_DIR="/run/user/$operator_uid" systemctl --user "$@"
  else
    systemctl --user "$@"
  fi
}

wait_for_legacy_proxy_plane() {
  for port in 17901 17902 17903 17904 17905 29091 29092 29093 29094 29095; do
    for _ in $(seq 1 100); do
      ss -ltnH "sport = :$port" | grep -q . && break
      sleep 0.2
    done
    ss -ltnH "sport = :$port" | grep -q . || return 1
  done
  for port in 17901 17902 17903 17904 17905; do
    curl --silent --show-error --fail --max-time 20 \
      --proxy "http://127.0.0.1:$port" https://chatgpt.com/cdn-cgi/trace --output /dev/null || return 1
  done
  python3 - "$temp_dir/container.env" <<'PY' || return 1
import json
import sys
import time
import urllib.request
from pathlib import Path

env = dict(
    line.split("=", 1)
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    if line and not line.startswith("#") and "=" in line
)
token = env.get("SELECTED_NODE_TOKEN", "")
if not token:
    raise SystemExit(1)
request = urllib.request.Request("http://172.17.0.1:19090/v1/selected-nodes")
request.add_header("Authorization", f"Bearer {token}")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for _ in range(60):
    try:
        with opener.open(request, timeout=5) as response:
            slots = json.load(response).get("slots", {})
        names = [slot.get("selected_node_name") for slot in slots.values()]
        if set(slots) == {f"Slot {letter}" for letter in "ABCDE"} \
                and all(names) and len(set(names)) == 5:
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit(1)
PY
}

rollback_with_status() {
  local status=$1
  trap - ERR INT TERM HUP
  if [[ $mode == --execute && $cutover_started == true && $commit_boundary == false ]]; then
    echo "Cutover failed in phase $phase; restoring the frozen Docker data plane." >&2
    systemctl stop vsp-sub2api-production.target vsp-sub2api-app@production.service \
      vsp-selected-node@production.service vsp-proxy-allocator@production.service \
      vsp-mihomo-production@slot-a.service vsp-mihomo-production@slot-b.service \
      vsp-mihomo-production@slot-c.service vsp-mihomo-production@slot-d.service \
      vsp-mihomo-production@slot-e.service vsp-postgresql@production.service \
      vsp-redis@production.service >/dev/null 2>&1 || true
    user_systemctl start mihomo-llm@slot-a.service mihomo-llm@slot-b.service \
      mihomo-llm@slot-c.service mihomo-llm@slot-d.service mihomo-llm@slot-e.service >/dev/null 2>&1 || true
    user_systemctl start llm-proxy-allocator.service llm-proxy-docker-forward.service >/dev/null 2>&1 || true
    docker start "$selected_node_container" >/dev/null 2>&1 || true
    if wait_for_legacy_proxy_plane && docker start "$app_container" >/dev/null 2>&1; then
      for _ in $(seq 1 120); do
        curl --noproxy '*' --silent --fail --max-time 3 \
          "http://127.0.0.1:$app_port/health" >/dev/null 2>&1 && break
        sleep 1
      done
      if curl --noproxy '*' --silent --show-error --fail --max-time 5 \
        "http://127.0.0.1:$app_port/health" >/dev/null; then
        echo 'Rollback restored the old production data plane: PASS' >&2
      else
        echo 'Rollback started the old Docker App but health did not recover.' >&2
      fi
    else
      echo 'Rollback could not restore the legacy proxy plane or Docker App.' >&2
    fi
  elif [[ $mode == --execute && $cutover_started == true ]]; then
    systemctl stop vsp-sub2api-app@production.service >/dev/null 2>&1 || true
    echo "Cutover failed after native App start in phase $phase." >&2
    echo 'Automatic Docker rollback is disabled because native writes may exist.' >&2
    echo 'Keep the Docker App stopped and perform a reviewed data-forward recovery.' >&2
  fi
  exit "$status"
}

rollback_pre_commit() {
  rollback_with_status "$?"
}

abort_on_signal() {
  echo "Cutover interrupted by $1 in phase $phase." >&2
  rollback_with_status 130
}

trap cleanup EXIT
trap rollback_pre_commit ERR
trap 'abort_on_signal INT' INT
trap 'abort_on_signal TERM' TERM
trap 'abort_on_signal HUP' HUP

require_command() {
  command -v "$1" >/dev/null || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

for command in cmp curl docker find flock git grep install pg_isready pg_restore psql python3 \
  redis-check-rdb redis-cli runuser sed seq ss stat systemctl tar tr; do
  require_command "$command"
done

lock_file=/run/vsp-sub2api-production-cutover.lock
if [[ $mode == --execute ]]; then
  if [[ ${EUID} -ne 0 ]]; then
    echo 'Execute mode requires root.' >&2
    exit 1
  fi
  exec 9>"$lock_file"
  flock -n 9 || { echo 'Another production cutover is active.' >&2; exit 1; }
elif [[ -e $lock_file ]]; then
  exec 8<"$lock_file"
  flock -n 8 || { echo 'A production cutover is active; dry-run refused.' >&2; exit 1; }
fi

if [[ -z $release ]]; then
  echo 'VSP_NATIVE_RELEASE is required.' >&2
  exit 1
fi
if [[ $(git -C "$repo_root" rev-parse --short=9 HEAD) != "$release" ]]; then
  echo "Repository HEAD does not match reviewed release $release." >&2
  exit 1
fi
if [[ -n $(git -C "$repo_root" status --porcelain) ]]; then
  echo 'Product worktree must be clean.' >&2
  exit 1
fi

for file in \
  "$repo_root/dist/native/sub2api" \
  "$repo_root/backend/resources/model-pricing/model_prices_and_context_window.json" \
  "$repo_root/deploy/native/sql/production-proxy-cutover.sql" \
  "$repo_root/deploy/native/sql/production-proxy-rollback.sql" \
  "$repo_root/deploy/native/config/redis.production.conf" \
  "$repo_root/deploy/native/config/redis.production-bootstrap.conf"; do
  [[ -s $file ]] || { echo "Missing candidate artifact: $file" >&2; exit 1; }
done

for container in "$app_container" "$pg_container" "$redis_container" "$selected_node_container"; do
  [[ $(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null) == true ]] || {
    echo "Required production container is not running: $container" >&2
    exit 1
  }
done
curl --noproxy '*' --silent --show-error --fail --max-time 5 \
  "http://127.0.0.1:$app_port/health" >/dev/null

if systemctl is-active --quiet vsp-sub2api-production.target; then
  echo 'Native production target is already active.' >&2
  exit 1
fi
if systemctl is-active --quiet postgresql || systemctl is-active --quiet redis-server; then
  echo 'Default PostgreSQL/Redis services must remain inactive.' >&2
  exit 1
fi
if ss -ltnH "sport = :$selected_node_port" | grep -q .; then
  echo "Native Selected Node port is occupied: $selected_node_port" >&2
  exit 1
fi

for unit in vsp-sub2api-production.target vsp-sub2api-app@.service vsp-postgresql@.service \
  vsp-redis@.service vsp-mihomo-production@.service vsp-proxy-allocator@.service \
  vsp-selected-node@.service; do
  cmp -s "/etc/systemd/system/$unit" "$repo_root/ops/systemd/$unit" || {
    echo "Installed systemd unit differs from candidate: $unit" >&2
    exit 1
  }
done

docker inspect "$app_container" --format '{{range .Config.Env}}{{println .}}{{end}}' >"$temp_dir/container.env"
python3 "$repo_root/deploy/native/render_app_env.py" \
  --profile production --source "$temp_dir/container.env" --output "$temp_dir/app.env" >/dev/null
python3 "$repo_root/ops/mihomo/render_profile.py" \
  --profile production \
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
expected = {
    "SERVER_HOST": "127.0.0.1",
    "SERVER_PORT": "19821",
    "DATABASE_HOST": "127.0.0.1",
    "DATABASE_PORT": "5432",
    "REDIS_HOST": "127.0.0.1",
    "REDIS_PORT": "6379",
    "SELECTED_NODE_ENDPOINT": "http://127.0.0.1:19290/v1/selected-nodes",
    "SUB2API_DISABLE_AUTONOMOUS_WORKERS": "0",
}
for key, value in expected.items():
    if app.get(key) != value:
        raise SystemExit(f"invalid production app setting: {key}")
if app.get("REDIS_PASSWORD"):
    raise SystemExit("native Redis config does not support the current non-empty password")
if selected.get("bind_host") != "127.0.0.1" or selected.get("bind_port") != 19290:
    raise SystemExit("production Selected Node must bind loopback:19290")
if not app.get("SELECTED_NODE_TOKEN") or app["SELECTED_NODE_TOKEN"] != selected.get("api_token"):
    raise SystemExit("Selected Node token contract mismatch")
PY

for slot in slot-a slot-b slot-c slot-d slot-e; do
  /home/heyx/.local/bin/mihomo -t \
    -d "$temp_dir/runtime/mihomo/$slot" \
    -f "$temp_dir/runtime/mihomo/$slot/config.yaml" >/dev/null
done

docker exec -i "$pg_container" sh -lc \
  'exec psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -qAt' <<'SQL' | grep -qx ok
SELECT CASE WHEN
  (SELECT jsonb_agg(jsonb_build_array(id, proxy_id) ORDER BY id)
     FROM accounts WHERE deleted_at IS NULL AND proxy_id IS NOT NULL)
    = '[[22, 4], [36, 5], [40, 7], [41, 8]]'::jsonb
  AND NOT EXISTS (SELECT 1 FROM accounts WHERE deleted_at IS NULL AND proxy_id BETWEEN 1 AND 3)
  AND (SELECT count(*) FROM proxies WHERE id BETWEEN 1 AND 8 AND deleted_at IS NULL) = 8
THEN 'ok' ELSE 'changed' END;
SQL

for unit in mihomo-llm@slot-a.service mihomo-llm@slot-b.service mihomo-llm@slot-c.service \
  mihomo-llm@slot-d.service mihomo-llm@slot-e.service llm-proxy-allocator.service \
  llm-proxy-docker-forward.service; do
  [[ $(user_systemctl is-active "$unit") == active ]] || {
    echo "Expected active legacy user unit: $unit" >&2
    exit 1
  }
done

app_data_source=$(docker inspect "$app_container" --format \
  '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{.Source}}{{end}}{{end}}')
[[ -d $app_data_source ]] || { echo 'Docker App data mount source is missing.' >&2; exit 1; }

if find "$config_root" -mindepth 1 -print -quit 2>/dev/null | grep -q . \
  || find "$data_root" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
  echo 'Production native config/data roots are not empty; explicit reset or resume is required.' >&2
  exit 1
fi

if [[ $mode == --dry-run ]]; then
  cat <<EOF
Production cutover dry-run: PASS
candidate=$release
selected_node=127.0.0.1:$selected_node_port
live_account_mapping=22->4,36->5,40->7,41->8
phases=PREFLIGHT,PREPARED,QUIESCED,SNAPSHOTTED,DATA_READY,PROXY_READY,COMMITTING,LIVE
automatic_rollback=enabled before COMMITTING; disabled after native App starts
production side effects=none
EOF
  exit 0
fi

if [[ $(basename "$(readlink -f "$prefix/current")") != "$release" ]]; then
  echo "Installed release does not match candidate $release." >&2
  exit 1
fi

timestamp=$(date +%Y%m%dT%H%M%S)
snapshot_dir="$backup_root/$timestamp"
state_file="$snapshot_dir/state"
install -d -o root -g postgres -m 0750 "$snapshot_dir"
cutover_started=true
printf '%s\n' "$phase" >"$state_file"
install -m 0600 "$temp_dir/container.env" "$snapshot_dir/container.env"

install -d -m 0755 "$config_root" "$data_root"
install -d -o root -g vsp-admin -m 0750 "$config_root/mihomo"
install -o root -g vsp-admin -m 0640 "$temp_dir/app.env" "$config_root/app.env"
install -o root -g vsp-admin -m 0640 "$temp_dir/runtime/allocator.json" "$config_root/allocator.json"
install -o root -g vsp-admin -m 0640 "$temp_dir/runtime/selected-node.json" "$config_root/selected-node.json"
install -o root -g postgres -m 0640 \
  "$repo_root/deploy/native/config/postgresql.production.env.example" "$config_root/postgresql.env"
install -o root -g redis -m 0640 \
  "$repo_root/deploy/native/config/redis.production-bootstrap.conf" "$config_root/redis.conf"
for slot in slot-a slot-b slot-c slot-d slot-e; do
  install -d -o root -g vsp-admin -m 0750 "$config_root/mihomo/$slot"
  install -o root -g vsp-admin -m 0640 \
    "$temp_dir/runtime/mihomo/$slot/config.yaml" "$config_root/mihomo/$slot/config.yaml"
  install -d -o "$operator_user" -g vsp-admin -m 0750 "$data_root/mihomo/$slot"
done
install -d -o "$operator_user" -g vsp-admin -m 0750 \
  "$data_root/app" "$data_root/app/data" "$data_root/allocator"
install -d -o redis -g redis -m 0750 "$data_root/redis"
install -d -o postgres -g postgres -m 0700 "$data_root/postgresql"
if find "$data_root/postgresql" -mindepth 1 -print -quit | grep -q .; then
  echo 'Production PostgreSQL directory is not empty.' >&2
  exit 1
fi
runuser -u postgres -- /usr/lib/postgresql/16/bin/initdb -D "$data_root/postgresql" --auth-local=peer --auth-host=scram-sha-256 >/dev/null

phase=PREPARED
printf '%s\n' "$phase" >"$state_file"
systemctl stop vsp-sub2api-rehearsal.target

docker stop --time 90 "$app_container" >/dev/null
for _ in $(seq 1 30); do
  ss -ltnH "sport = :$app_port" | grep -q . || break
  sleep 1
done
if ss -ltnH "sport = :$app_port" | grep -q .; then
  echo 'Port 19821 did not close after Docker App stop.' >&2
  exit 1
fi

phase=QUIESCED
printf '%s\n' "$phase" >"$state_file"

docker exec "$pg_container" sh -lc \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl' \
  >"$snapshot_dir/postgresql.dump"
chown root:postgres "$snapshot_dir/postgresql.dump"
chmod 0640 "$snapshot_dir/postgresql.dump"
pg_restore --list "$snapshot_dir/postgresql.dump" >/dev/null
redis_reply=$(docker exec "$redis_container" env -u REDISCLI_AUTH redis-cli --raw SAVE | tr -d '\r')
[[ $redis_reply == OK ]] || { echo "Redis SAVE failed: $redis_reply" >&2; exit 1; }
docker cp "$redis_container:/data/dump.rdb" "$snapshot_dir/dump.rdb" >/dev/null
redis-check-rdb "$snapshot_dir/dump.rdb" >/dev/null
tar -C "$app_data_source" -czf "$snapshot_dir/app-data.tar.gz" .
chmod 0600 "$snapshot_dir/dump.rdb" "$snapshot_dir/app-data.tar.gz"

phase=SNAPSHOTTED
printf '%s\n' "$phase" >"$state_file"

database_user=$(sed -n 's/^DATABASE_USER=//p' "$config_root/app.env")
database_name=$(sed -n 's/^DATABASE_DBNAME=//p' "$config_root/app.env")
if [[ ! $database_user =~ ^[A-Za-z_][A-Za-z0-9_]*$ || ! $database_name =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo 'Production database user/name must be simple PostgreSQL identifiers.' >&2
  exit 1
fi

systemctl start vsp-postgresql@production.service
for _ in $(seq 1 60); do
  pg_isready -q -h 127.0.0.1 -p "$pg_port" && break
  sleep 1
done
pg_isready -q -h 127.0.0.1 -p "$pg_port"

python3 - "$config_root/app.env" "$temp_dir/create-database.sql" "$temp_dir/pgpass" <<'PY'
import sys
from pathlib import Path

def ident(value: str) -> str:
    if not value or "\x00" in value or "\n" in value:
        raise ValueError("invalid PostgreSQL identifier")
    return '"' + value.replace('"', '""') + '"'

def literal(value: str) -> str:
    if "\x00" in value or "\n" in value:
        raise ValueError("invalid PostgreSQL literal")
    return "'" + value.replace("'", "''") + "'"

def pgpass(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")

env = dict(
    line.split("=", 1)
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    if line and not line.startswith("#") and "=" in line
)
user = env["DATABASE_USER"]
password = env["DATABASE_PASSWORD"]
database = env["DATABASE_DBNAME"]
Path(sys.argv[2]).write_text(
    "\\set ON_ERROR_STOP on\n"
    f"CREATE ROLE {ident(user)} LOGIN PASSWORD {literal(password)};\n"
    f"CREATE DATABASE {ident(database)} OWNER {ident(user)};\n",
    encoding="utf-8",
)
Path(sys.argv[3]).write_text(
    f"127.0.0.1:5432:{pgpass(database)}:{pgpass(user)}:{pgpass(password)}\n",
    encoding="utf-8",
)
PY
chmod 0600 "$temp_dir/create-database.sql" "$temp_dir/pgpass"
runuser -u postgres -- psql -X -q -h 127.0.0.1 -p "$pg_port" -d postgres <"$temp_dir/create-database.sql"
runuser -u postgres -- pg_restore --exit-on-error --no-owner --no-acl \
  --role "$database_user" -h 127.0.0.1 -p "$pg_port" -d "$database_name" \
  "$snapshot_dir/postgresql.dump"
PGPASSFILE="$temp_dir/pgpass" psql -X -q -h 127.0.0.1 -p "$pg_port" \
  -U "$database_user" -d "$database_name" \
  -f "$repo_root/deploy/native/sql/production-proxy-cutover.sql"

tar -C "$data_root/app" -xzf "$snapshot_dir/app-data.tar.gz"
install -d -o "$operator_user" -g vsp-admin -m 0750 "$data_root/app/data"
if [[ ! -s $data_root/app/data/model_pricing.json ]]; then
  if [[ -s $data_root/app/model_pricing.json ]]; then
    install -o "$operator_user" -g vsp-admin -m 0644 \
      "$data_root/app/model_pricing.json" "$data_root/app/data/model_pricing.json"
  else
    install -o "$operator_user" -g vsp-admin -m 0644 \
      "$prefix/current/resources/model-pricing/model_prices_and_context_window.json" \
      "$data_root/app/data/model_pricing.json"
  fi
fi
chown -R "$operator_user":vsp-admin "$data_root/app"
install -o redis -g redis -m 0600 "$snapshot_dir/dump.rdb" "$data_root/redis/dump.rdb"
expected_redis_keys=$(docker exec "$redis_container" env -u REDISCLI_AUTH redis-cli --raw DBSIZE)
systemctl start vsp-redis@production.service
for _ in $(seq 1 50); do
  env -u REDISCLI_AUTH redis-cli -h 127.0.0.1 -p "$redis_port" ping 2>/dev/null | grep -qx PONG && break
  sleep 0.2
done
actual_redis_keys=$(env -u REDISCLI_AUTH redis-cli -h 127.0.0.1 -p "$redis_port" --raw DBSIZE)
[[ $actual_redis_keys == "$expected_redis_keys" ]] || {
  echo "Redis bootstrap key count mismatch: expected $expected_redis_keys got $actual_redis_keys" >&2
  exit 1
}
env -u REDISCLI_AUTH redis-cli -h 127.0.0.1 -p "$redis_port" CONFIG SET appendonly yes >/dev/null
for _ in $(seq 1 300); do
  redis_info=$(env -u REDISCLI_AUTH redis-cli -h 127.0.0.1 -p "$redis_port" INFO persistence)
  grep -q '^aof_enabled:1' <<<"$redis_info" \
    && grep -q '^aof_rewrite_in_progress:0' <<<"$redis_info" \
    && grep -q '^aof_rewrite_scheduled:0' <<<"$redis_info" \
    && grep -q '^aof_last_bgrewrite_status:ok' <<<"$redis_info" && break
  sleep 0.2
done
grep -q '^aof_enabled:1' <<<"$redis_info" \
  && grep -q '^aof_rewrite_in_progress:0' <<<"$redis_info" \
  && grep -q '^aof_rewrite_scheduled:0' <<<"$redis_info" \
  && grep -q '^aof_last_bgrewrite_status:ok' <<<"$redis_info" \
  && test -s "$data_root/redis/appendonlydir/appendonly.aof.manifest" \
  && find "$data_root/redis/appendonlydir" -type f -name '*.base.rdb' -size +0c -print -quit | grep -q . || {
    echo 'Redis AOF rewrite did not complete successfully.' >&2
    exit 1
  }
systemctl stop vsp-redis@production.service
install -o root -g redis -m 0640 \
  "$repo_root/deploy/native/config/redis.production.conf" "$config_root/redis.conf"
systemctl start vsp-redis@production.service
for _ in $(seq 1 50); do
  env -u REDISCLI_AUTH redis-cli -h 127.0.0.1 -p "$redis_port" ping 2>/dev/null | grep -qx PONG && break
  sleep 0.2
done
actual_redis_keys=$(env -u REDISCLI_AUTH redis-cli -h 127.0.0.1 -p "$redis_port" --raw DBSIZE)
[[ $actual_redis_keys == "$expected_redis_keys" ]] || {
  echo "Redis AOF restart key count mismatch: expected $expected_redis_keys got $actual_redis_keys" >&2
  exit 1
}
redis_info=$(env -u REDISCLI_AUTH redis-cli -h 127.0.0.1 -p "$redis_port" INFO persistence)
grep -q '^loading:0' <<<"$redis_info" \
  && grep -q '^aof_enabled:1' <<<"$redis_info" \
  && grep -q '^aof_rewrite_in_progress:0' <<<"$redis_info" \
  && grep -q '^aof_last_bgrewrite_status:ok' <<<"$redis_info" \
  && test -s "$data_root/redis/appendonlydir/appendonly.aof.manifest" \
  && find "$data_root/redis/appendonlydir" -type f -name '*.base.rdb' -size +0c -print -quit | grep -q . || {
    echo 'Redis final AOF persistence contract failed.' >&2
    exit 1
  }

phase=DATA_READY
printf '%s\n' "$phase" >"$state_file"

user_systemctl stop llm-proxy-allocator.service llm-proxy-docker-forward.service
user_systemctl stop mihomo-llm@slot-a.service mihomo-llm@slot-b.service \
  mihomo-llm@slot-c.service mihomo-llm@slot-d.service mihomo-llm@slot-e.service
docker stop "$selected_node_container" >/dev/null

systemctl start vsp-mihomo-production@slot-a.service vsp-mihomo-production@slot-b.service \
  vsp-mihomo-production@slot-c.service vsp-mihomo-production@slot-d.service \
  vsp-mihomo-production@slot-e.service
for port in 17901 17902 17903 17904 17905 29091 29092 29093 29094 29095; do
  for _ in $(seq 1 50); do
    ss -ltnH "sport = :$port" | grep -q . && break
    sleep 0.2
  done
  ss -ltnH "sport = :$port" | grep -q .
done

rm -f "$data_root/allocator/state.json"
allocator_started_at=$(date +%s)
systemctl start vsp-proxy-allocator@production.service
python3 - "$data_root/allocator/state.json" "$allocator_started_at" <<'PY'
import json
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
started = int(sys.argv[2])
for _ in range(180):
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        assignments = state.get("assignments", {})
        names = [assignments.get(f"slot-{letter}", {}).get("LLM-PRIMARY") for letter in "abcde"]
        health = state.get("health", {})
        if state.get("updated_at", 0) >= started and all(names) and len(set(names)) == 5 \
                and all(health.get(name, {}).get("healthy") for name in names):
            break
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    time.sleep(1)
else:
    raise SystemExit("allocator did not produce five healthy distinct production assignments")
PY

systemctl start vsp-selected-node@production.service
for _ in $(seq 1 50); do
  ss -ltnH "sport = :$selected_node_port" | grep -q . && break
  sleep 0.2
done
python3 - "$config_root/selected-node.json" <<'PY'
import json
import sys
import time
import urllib.request
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = {f"Slot {letter}" for letter in "ABCDE"}
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for _ in range(90):
    try:
        request = urllib.request.Request("http://127.0.0.1:19290/v1/selected-nodes")
        request.add_header("Authorization", f"Bearer {config['api_token']}")
        with opener.open(request, timeout=5) as response:
            slots = json.load(response).get("slots", {})
        names = [slot.get("selected_node_name") for slot in slots.values()]
        if set(slots) == expected and all(slot.get("status") == "fresh" for slot in slots.values()) \
                and all(names) and len(set(names)) == 5:
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit("Selected Node did not return five fresh distinct production slots")
PY
for port in 17901 17902 17903 17904 17905; do
  curl --silent --show-error --fail --max-time 20 \
    --proxy "http://127.0.0.1:$port" https://chatgpt.com/cdn-cgi/trace --output /dev/null
done

phase=PROXY_READY
printf '%s\n' "$phase" >"$state_file"

phase=COMMITTING
printf '%s\n' "$phase" >"$state_file"
commit_boundary=true
systemctl start vsp-sub2api-app@production.service
for _ in $(seq 1 180); do
  curl --noproxy '*' --silent --fail --max-time 3 \
    "http://127.0.0.1:$app_port/health" >/dev/null 2>&1 && break
  sleep 1
done
curl --noproxy '*' --silent --show-error --fail --max-time 5 \
  "http://127.0.0.1:$app_port/health" | grep -q '"status":"ok"'

systemctl start vsp-sub2api-production.target
systemctl enable vsp-sub2api-production.target >/dev/null
user_systemctl disable llm-proxy-allocator.service llm-proxy-docker-forward.service \
  mihomo-llm@slot-a.service mihomo-llm@slot-b.service mihomo-llm@slot-c.service \
  mihomo-llm@slot-d.service mihomo-llm@slot-e.service >/dev/null

phase=LIVE
printf '%s\n' "$phase" >"$state_file"
cat <<EOF
Native production is live at http://127.0.0.1:$app_port
Snapshot: $snapshot_dir
State: $phase
Docker PostgreSQL/Redis remain running and frozen for observation.
Do not restart the old Docker App without a reviewed data-forward rollback.
EOF
