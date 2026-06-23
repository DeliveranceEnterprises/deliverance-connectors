#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
# SPDX-License-Identifier: MIT
#
# Generic connector supervisor with exponential backoff.
#
# Restarts a connector whenever it exits (crash, flaky upstream API, machine
# sleep, etc.) so it does not need manual relaunching.  Backoff grows on rapid
# repeated failures and resets after a run survives long enough.
#
# Usage:
#   tools/supervise.sh <connector_dir> <entrypoint> [extra uv args...]
#
# Example:
#   tools/supervise.sh autoxing_connector autoxing-cloud-connector \
#       --env-file config/.env.local
#
# The connector is always launched as:
#   uv run [extra uv args] <entrypoint> --config config/my_fleet.local.yaml

set -uo pipefail

CONNECTOR_DIR="${1:?need connector dir}"
ENTRYPOINT="${2:?need entrypoint}"
shift 2
EXTRA_ARGS=("$@")

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/$CONNECTOR_DIR" || exit 1

CONFIG="config/my_fleet.local.yaml"

MIN_BACKOFF=2
MAX_BACKOFF=60
# A run that lasts at least this long is considered "healthy" → reset backoff.
HEALTHY_RUNTIME=120

backoff=$MIN_BACKOFF

echo "[supervise] $ENTRYPOINT starting (dir=$CONNECTOR_DIR)"

while true; do
    start=$(date +%s)
    uv run "${EXTRA_ARGS[@]}" "$ENTRYPOINT" --config "$CONFIG"
    code=$?
    elapsed=$(( $(date +%s) - start ))

    # Clean shutdown via SIGINT/SIGTERM → stop supervising.
    if [ $code -eq 130 ] || [ $code -eq 143 ]; then
        echo "[supervise] $ENTRYPOINT stopped by signal (code $code) — exiting"
        break
    fi

    if [ $elapsed -ge $HEALTHY_RUNTIME ]; then
        backoff=$MIN_BACKOFF
    fi

    echo "[supervise] $ENTRYPOINT exited (code $code, ran ${elapsed}s) — restarting in ${backoff}s"
    sleep "$backoff"

    backoff=$(( backoff * 2 ))
    [ $backoff -gt $MAX_BACKOFF ] && backoff=$MAX_BACKOFF
done
