#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

set -eo pipefail

source "/opt/ros/${ROS_DISTRO:-humble}/setup.bash"

python3 -c "import rclpy; print('rclpy OK')"

echo "Topics:"
TOPICS="$(ros2 topic list | sort)"
echo "${TOPICS}"

echo "Actions:"
ACTIONS="$(ros2 action list | sort)"
echo "${ACTIONS}"

for topic in /odom /cmd_vel /camera/image_raw; do
  if echo "${TOPICS}" | grep -qx "${topic}"; then
    echo "${topic} present"
  else
    echo "${topic} missing" >&2
  fi
done

if echo "${ACTIONS}" | grep -qx /navigate_to_pose; then
  echo "/navigate_to_pose present"
else
  echo "/navigate_to_pose missing" >&2
fi
