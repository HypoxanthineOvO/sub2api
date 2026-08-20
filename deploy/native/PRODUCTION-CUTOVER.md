# Native Production Cutover

This runbook prepares the exact production migration path. It does not grant
permission to run it. `--execute` requires explicit S4 authorization because it
stops the Docker App and takes over `127.0.0.1:19821`.

## What Changes

- Docker `sub2api` stops; Docker PostgreSQL and Redis remain running and frozen.
- User-level Slot A-E, allocator, Docker forwarder, and Docker Selected Node stop.
- Native PostgreSQL, Redis, Slot A-E, allocator, Selected Node, and App start.
- Native Selected Node uses `127.0.0.1:19290`; unrelated `127.0.0.1:19090` remains untouched.
- The native database copy soft-retires proxy 1..3 and rewrites proxy 4..8 to loopback.
- Current account mappings and states are not changed.

The generic `mihomo.service`, every `lichf` process/service, unrelated Docker
workloads, and Nginx configuration are outside this cutover.

## Candidate Gate

Before S4, run the read-only dry-run from a clean candidate commit:

```bash
cd /home/heyx/Workspace/VSP/VSP-Sub2API
VSP_NATIVE_RELEASE=<candidate> \
  bash deploy/native/cutover-production.sh --dry-run
```

The dry-run validates Docker health, exact live account/proxy mappings, installed
systemd units, empty native production roots, five rendered Mihomo configs,
production loopback endpoints, the free `19290` port, and required artifacts. It
does not stop services, save Redis, dump PostgreSQL, or write production data.

## S4 Execute Command

Only after S4 acceptance:

```bash
cd /home/heyx/Workspace/VSP/VSP-Sub2API
sudo env VSP_NATIVE_RELEASE=<candidate> \
  bash deploy/native/cutover-production.sh \
  --execute --confirm-stop-production-and-switch-19821
```

The candidate must already be installed under `/opt/vsp-sub2api/releases` and
`/opt/vsp-sub2api/current` must resolve to it.

## State Machine

| Phase | Operation | Automatic rollback |
| --- | --- | --- |
| `PREFLIGHT` | Validate candidate, Docker, units, ports, configs, mappings | No side effects |
| `PREPARED` | Install native configs, initialize empty PG, stop rehearsal | Restart old production if later failure |
| `QUIESCED` | Stop Docker App and release `19821` | Start old Docker App |
| `SNAPSHOTTED` | Final PG dump, Redis SAVE/RDB, App data archive | Start old Docker App |
| `DATA_READY` | Restore native PG/Redis; apply native-copy proxy transaction | Discard native copy; start old Docker App |
| `PROXY_READY` | Replace old Slot control plane and verify five assignments | Restore old user units, forwarder, Selected Node, App |
| `COMMITTING` | Record irreversible boundary, then start native App | Disabled |
| `LIVE` | Health passes; target enabled; old user units disabled | Data-forward recovery only |

Nginx already targets `127.0.0.1:19821`. Between `QUIESCED` and `COMMITTING`,
requests receive an upstream error and cannot write. Starting the native App
immediately restores ingress and may create native-only writes, so the script
writes `COMMITTING` before starting it.

## Data Rules

- PostgreSQL snapshot: custom format, `--no-owner --no-acl`, validated with
  `pg_restore --list` after the Docker App is stopped.
- Redis snapshot: synchronous `SAVE`, then `redis-check-rdb`.
- Redis first boot: `appendonly no` loads the RDB; key count must match Docker.
  The script then enables AOF, waits for a successful rewrite, installs the final
  `appendonly yes` config, restarts Redis, and checks the key count again.
- App data: archived only after Docker App stop, restored under the native
  writable data directory, then owned by `heyx:vsp-admin`.
- Docker PostgreSQL/Redis and their bind mounts remain unchanged for M6 observation.

## Proxy Transaction

`production-proxy-cutover.sql` runs only on native `127.0.0.1:5432` after restore.
It asserts the complete live mapping is exactly:

```text
22 -> 4
36 -> 5
40 -> 7
41 -> 8
```

It asserts no undeleted account or live backup references proxy 1..3, soft-retires
proxy 1..3 to preserve historical foreign keys, and changes only proxy 4..8 host
to `127.0.0.1`. The rollback SQL restores those proxy fields. Neither file changes
account state, scheduling, or proxy assignment.

## Post-Start Acceptance

Before declaring M5 complete, verify:

- App `/health`, PostgreSQL, Redis, all 14 production loopback listeners;
- pricing initialization with a non-empty model catalog;
- five proxy data planes and five fresh, distinct Selected Node slots;
- administrator and user Dashboard views;
- existing Key `/v1/models`;
- one separately authorized minimal real request;
- usage written to native PG through the expected Slot;
- no fatal/panic/restart loop in the current invocations;
- Docker App remains stopped and Docker PG/Redis identities remain unchanged.

## Rollback Boundary

Before `COMMITTING`, the script automatically stops partial native services,
restarts the old user Slots/allocator/forwarder, Docker Selected Node, and Docker
App. Docker PG/Redis never changed, so this path is data-preserving.

At or after `COMMITTING`, do not directly restart the Docker App. Native workers
or requests may already have written newer data. Close ingress by stopping the
native App, snapshot native PG/Redis, and perform a separately reviewed
data-forward restore or fix the native stack forward.
