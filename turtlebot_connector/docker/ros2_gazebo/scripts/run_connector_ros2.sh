#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

set -eo pipefail

source "/opt/ros/${ROS_DISTRO:-humble}/setup.bash"

cd /workspace/turtlebot_connector
CONNECTOR_VENV="${CONNECTOR_VENV:-.venv-ros2}"

CONFIG_FILE="${1:-config/fleet.ros2.local.yaml}"

if [ ! -f "${CONFIG_FILE}" ]; then
  echo "Config file not found: ${CONFIG_FILE}" >&2
  echo "Create it with: cp config/fleet.ros2.example.yaml config/fleet.ros2.local.yaml" >&2
  exit 1
fi

if [ -f config/.env ]; then
  set -a
  # shellcheck disable=SC1091
  source config/.env
  set +a
fi

if [ -f config/.env.local ]; then
  set -a
  # shellcheck disable=SC1091
  source config/.env.local
  set +a
fi

if [ ! -x "${CONNECTOR_VENV}/bin/turtlebot-connector" ]; then
  docker/ros2_gazebo/scripts/setup_connector_env.sh
fi

test -n "${INORBIT_API_KEY:-}" || {
  echo "INORBIT_API_KEY is not set. Add it to config/.env or export it in this shell." >&2
  exit 1
}

"${CONNECTOR_VENV}/bin/turtlebot-connector" --config "${CONFIG_FILE}"
