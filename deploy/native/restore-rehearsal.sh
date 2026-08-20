#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo 'restore-rehearsal.sh requires root; review and run only after explicit rehearsal authorization.' >&2
  exit 1
fi

echo 'This script is intentionally a guarded placeholder until the rehearsal restore command is authorized.' >&2
echo 'Required inputs: reviewed PostgreSQL logical dump, Redis 7.4.8 dump.rdb, app credentials, and target data paths.' >&2
exit 2
