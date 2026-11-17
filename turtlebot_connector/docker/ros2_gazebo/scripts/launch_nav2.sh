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

# Default Nav2 params: a copy of waffle_pi.yaml with reverse driving enabled,
# so InOrbit "Open Teleop Backward" actually moves the robot backwards.
PARAMS_FILE="${PARAMS_FILE:-/workspace/turtlebot_connector/docker/ros2_gazebo/params/waffle_pi_reverse.yaml}"

if [ ! -f "${PARAMS_FILE}" ]; then
  echo "Nav2 params file not found: ${PARAMS_FILE}" >&2
  exit 1
fi

ros2 launch turtlebot3_navigation2 navigation2.launch.py \
  use_sim_time:=True \
  map:="${MAP_FILE}" \
  params_file:="${PARAMS_FILE}"
