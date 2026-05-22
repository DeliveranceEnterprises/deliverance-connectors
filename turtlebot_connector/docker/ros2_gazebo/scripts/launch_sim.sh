#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

set -eo pipefail

source "/opt/ros/${ROS_DISTRO:-humble}/setup.bash"
source "/usr/share/gazebo/setup.sh"
export TURTLEBOT3_MODEL="${TURTLEBOT3_MODEL:-waffle_pi}"
export GAZEBO_PLUGIN_PATH="/opt/ros/${ROS_DISTRO:-humble}/lib:${GAZEBO_PLUGIN_PATH:-}"
export GAZEBO_MODEL_PATH="/opt/ros/${ROS_DISTRO:-humble}/share/turtlebot3_gazebo/models:${GAZEBO_MODEL_PATH:-}"
export DISPLAY="${DISPLAY:-:1}"
export XAUTHORITY="${XAUTHORITY:-/home/ubuntu/.Xauthority}"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"

WORLD_FILE="/opt/ros/${ROS_DISTRO:-humble}/share/turtlebot3_gazebo/worlds/turtlebot3_world.world"
TB3_X_POSE="${TB3_X_POSE:--2.0}"
TB3_Y_POSE="${TB3_Y_POSE:--0.5}"

cleanup() {
  jobs -pr | xargs --no-run-if-empty kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

gzserver \
  --verbose \
  -s libgazebo_ros_init.so \
  -s libgazebo_ros_factory.so \
  "${WORLD_FILE}" &

ros2 launch turtlebot3_gazebo robot_state_publisher.launch.py use_sim_time:=true &

for _ in $(seq 1 60); do
  if ros2 service list | grep -qx "/spawn_entity"; then
    break
  fi
  sleep 1
done

if ! ros2 service list | grep -qx "/spawn_entity"; then
  echo "ERROR: /spawn_entity is not available. Gazebo did not load GazeboRosFactory." >&2
  exit 1
fi

ros2 launch turtlebot3_gazebo spawn_turtlebot3.launch.py \
  x_pose:="${TB3_X_POSE}" \
  y_pose:="${TB3_Y_POSE}"

wait
