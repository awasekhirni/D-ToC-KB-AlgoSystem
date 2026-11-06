#!/usr/bin/env bash
# Tiny wait-for-tcp utility for healthcheck-first orchestration when the
# compose "depends_on.condition" feature isn't sufficient (e.g. CI scripts).
set -euo pipefail

HOST="${1:?host required}"; PORT="${2:?port required}"
TIMEOUT="${3:-30}"

start=$(date +%s)
while ! nc -z "$HOST" "$PORT" >/dev/null 2>&1; do
    if (( $(date +%s) - start >= TIMEOUT )); then
        echo "Timeout waiting for $HOST:$PORT after ${TIMEOUT}s" >&2
        exit 1
    fi
    sleep 1
done
