#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

set -eo pipefail

source "/opt/ros/${ROS_DISTRO:-humble}/setup.bash"

INITIAL_X="${INITIAL_X:--2.0}"
INITIAL_Y="${INITIAL_Y:--0.5}"
INITIAL_YAW_Z="${INITIAL_YAW_Z:-0.0}"
INITIAL_YAW_W="${INITIAL_YAW_W:-1.0}"

timeout 6 ros2 topic pub -r 2 --qos-reliability best_effort \
  /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  "{header: {frame_id: map}, pose: {pose: {position: {x: ${INITIAL_X}, y: ${INITIAL_Y}, z: 0.0}, orientation: {z: ${INITIAL_YAW_Z}, w: ${INITIAL_YAW_W}}}, covariance: [0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.068]}}"
