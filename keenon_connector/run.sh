#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

# Build, start, stop and inspect the Keenon connector with Docker Compose.
#
# Usage: ./run.sh <command>
#
#   up        Build the image from this directory and start the connector in the background
#   down      Stop the connector and remove its container (named volumes are kept)
#   restart   Rebuild the image and recreate the container
#   build     Only build the image
#   logs      Follow the connector logs (Ctrl+C stops following, not the connector)
#   status    Show the state of the connector container
#
# It needs two files that are never committed, config/.env and config/my_fleet.yaml.
# Start from config/example.env and config/fleet.example.yaml.
#
# The container setup comes from docker/docker-compose.yaml when that file exists and from
# docker/docker-compose.example.yaml otherwise.

set -euo pipefail

NAME="Keenon"
PROJECT="keenon-connector"

cd "$(dirname "${BASH_SOURCE[0]}")"

COMPOSE_FILE="docker/docker-compose.example.yaml"
if [ -f docker/docker-compose.yaml ]; then
    COMPOSE_FILE="docker/docker-compose.yaml"
fi

usage() {
    cat <<EOF
Usage: ./run.sh <command>

Commands:
  up        Build the image and start the ${NAME} connector in the background
  down      Stop the connector and remove its container (named volumes are kept)
  restart   Rebuild the image and recreate the container
  build     Only build the image
  logs      Follow the connector logs
  status    Show the state of the connector container
EOF
}

compose() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "Docker is not installed or not in the PATH." >&2
        exit 1
    fi
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"
}

# The connector cannot start without its configuration.
require_config() {
    local ok=1
    if [ ! -f config/.env ]; then
        echo "Missing config/.env (start from config/example.env)." >&2
        ok=0
    fi
    if [ ! -f config/my_fleet.yaml ]; then
        echo "Missing config/my_fleet.yaml (start from config/fleet.example.yaml)." >&2
        ok=0
    fi
    if [ "$ok" -eq 0 ]; then
        exit 1
    fi
    # The compose file mounts this folder. Create it here so that Docker does not create it as root.
    mkdir -p config/user_scripts
}

# Docker Compose reads the env file even to stop or inspect a container. If the configuration
# has already been removed, empty placeholders are used so that a running container can still
# be stopped. They are deleted when the script ends.
placeholders=()

cleanup() {
    if [ "${#placeholders[@]}" -gt 0 ]; then
        rm -f "${placeholders[@]}"
    fi
}
trap cleanup EXIT

allow_missing_config() {
    local f
    for f in config/.env config/my_fleet.yaml; do
        if [ ! -f "$f" ]; then
            : > "$f"
            placeholders+=("$f")
        fi
    done
}

case "${1:-}" in
    up | start)
        require_config
        compose up -d --build
        ;;
    restart)
        require_config
        compose up -d --build --force-recreate
        ;;
    build)
        require_config
        compose build
        ;;
    down | stop)
        allow_missing_config
        compose down
        ;;
    logs)
        allow_missing_config
        compose logs -f --tail 100
        ;;
    status | ps)
        allow_missing_config
        compose ps
        ;;
    -h | --help | help)
        usage
        ;;
    *)
        usage >&2
        exit 1
        ;;
esac
