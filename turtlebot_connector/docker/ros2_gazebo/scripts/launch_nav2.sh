#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

set -eo pipefail

source "/opt/ros/${ROS_DISTRO:-humble}/setup.bash"
export TURTLEBOT3_MODEL="${TURTLEBOT3_MODEL:-burger}"

MAP_FILE="${1:-/opt/ros/${ROS_DISTRO:-humble}/share/turtlebot3_navigation2/map/map.yaml}"

if [ ! -f "${MAP_FILE}" ]; then
  echo "Map file not found: ${MAP_FILE}" >&2
  exit 1
fi

ros2 launch turtlebot3_navigation2 navigation2.launch.py \
  use_sim_time:=True \
  map:="${MAP_FILE}"
