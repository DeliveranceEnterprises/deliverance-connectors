#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
# SPDX-License-Identifier: MIT
#
# Generic connector supervisor with exponential backoff.
#
# Restarts a connector whenever it crashes (flaky upstream API, machine
# sleep, etc.) so it does not need manual relaunching.  Backoff grows on rapid
# repeated failures and resets after a run survives long enough.
#
# WARNING: every restart logs in to the vendor API again. Allybot and Keenon
# keep one session/token per account (or app), so a restart can invalidate
# the session of any other consumer of the same account (for example a
# Deliverance Platform integration). Give each consumer its own credentials.
#
# Usage:
#   tools/supervise.sh <connector_dir> <entrypoint> [extra uv args...]
#
# Example:
#   tools/supervise.sh autoxing_connector autoxing-cloud-connector \
#       --env-file config/.env
#
# The connector is launched from <connector_dir> as:
#   uv run [extra uv args] <entrypoint> --config "$SUPERVISE_CONFIG"
#
# Environment variables:
#   SUPERVISE_CONFIG               fleet config, relative to <connector_dir>
#                                  (default: config/my_fleet.yaml)
#   SUPERVISE_MIN_BACKOFF          first retry delay in seconds (default: 2)
#   SUPERVISE_MAX_BACKOFF          longest retry delay in seconds (default: 60)
#   SUPERVISE_HEALTHY_RUNTIME      a run at least this long (seconds) resets the
#                                  backoff and the failure count (default: 120)
#   SUPERVISE_MAX_RAPID_FAILURES   consecutive shorter runs before giving up with
#                                  a non-zero exit; 0 = never give up (default: 10)
#
# The supervisor does not restart the connector when it exits with code 0
# (clean stop) or 2 (configuration/usage error), or when it is stopped by a
# signal. SIGTERM/SIGINT sent to the supervisor are forwarded to the connector.

set -uo pipefail

CONNECTOR_DIR="${1:?need connector dir}"
ENTRYPOINT="${2:?need entrypoint}"
shift 2
EXTRA_ARGS=("$@")

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/$CONNECTOR_DIR" || exit 1

CONFIG="${SUPERVISE_CONFIG:-config/my_fleet.yaml}"
MIN_BACKOFF="${SUPERVISE_MIN_BACKOFF:-2}"
MAX_BACKOFF="${SUPERVISE_MAX_BACKOFF:-60}"
HEALTHY_RUNTIME="${SUPERVISE_HEALTHY_RUNTIME:-120}"
MAX_RAPID_FAILURES="${SUPERVISE_MAX_RAPID_FAILURES:-10}"

if [ ! -f "$CONFIG" ]; then
    echo "[supervise] config file $CONNECTOR_DIR/$CONFIG not found (set SUPERVISE_CONFIG)" >&2
    exit 2
fi

child=""
sleeper=""

# Forward the signal to the connector, wait for it and exit. The connector
# runs as a background job, where bash ignores SIGINT, so SIGTERM is sent in
# both cases.
on_signal() {
    local name="$1" code="$2"
    trap - TERM INT
    [ -n "$sleeper" ] && kill "$sleeper" 2>/dev/null
    if [ -n "$child" ] && kill -0 "$child" 2>/dev/null; then
        echo "[supervise] received SIG$name, stopping $ENTRYPOINT (pid $child)"
        kill -TERM "$child" 2>/dev/null
        wait "$child" 2>/dev/null
    fi
    echo "[supervise] $ENTRYPOINT stopped by SIG$name, exiting"
    exit "$code"
}
trap 'on_signal TERM 143' TERM
trap 'on_signal INT 130' INT

backoff=$MIN_BACKOFF
rapid_failures=0

echo "[supervise] $ENTRYPOINT starting (dir=$CONNECTOR_DIR, config=$CONFIG)"

while true; do
    start=$(date +%s)
    # ${EXTRA_ARGS[@]+...}: bash 3.2 (macOS) treats an empty array as unbound
    # under `set -u`.
    uv run ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} "$ENTRYPOINT" --config "$CONFIG" &
    child=$!
    wait "$child"
    code=$?
    child=""
    elapsed=$(( $(date +%s) - start ))

    # Stopped by a signal sent straight to the connector → stop supervising.
    if [ $code -eq 130 ] || [ $code -eq 143 ]; then
        echo "[supervise] $ENTRYPOINT stopped by signal (code $code), exiting"
        exit "$code"
    fi
    # 0 = clean stop; 2 = configuration or usage error. Restarting would not
    # change either.
    if [ $code -eq 0 ] || [ $code -eq 2 ]; then
        echo "[supervise] $ENTRYPOINT exited with code $code (clean stop or configuration error), not restarting"
        exit "$code"
    fi

    if [ $elapsed -ge "$HEALTHY_RUNTIME" ]; then
        backoff=$MIN_BACKOFF
        rapid_failures=0
    else
        rapid_failures=$(( rapid_failures + 1 ))
        if [ "$MAX_RAPID_FAILURES" -gt 0 ] && [ $rapid_failures -ge "$MAX_RAPID_FAILURES" ]; then
            echo "[supervise] $ENTRYPOINT failed $rapid_failures times in a row (last code $code), giving up" >&2
            exit 1
        fi
    fi

    echo "[supervise] $ENTRYPOINT exited (code $code, ran ${elapsed}s), restarting in ${backoff}s"
    sleep "$backoff" &
    sleeper=$!
    wait "$sleeper"
    sleeper=""

    backoff=$(( backoff * 2 ))
    [ $backoff -gt "$MAX_BACKOFF" ] && backoff=$MAX_BACKOFF
done
