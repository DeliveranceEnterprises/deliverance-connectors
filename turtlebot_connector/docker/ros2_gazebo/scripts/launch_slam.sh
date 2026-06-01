#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

# Launch slam_toolbox (online async) + Nav2 without a pre-built map.
# The TurtleBot will scan the Gazebo office world and build the map live.
# Once the map looks good, save it with:
#   ros2 run nav2_map_server map_saver_cli -f /tmp/scanned_map/office_scanned

set -eo pipefail

source "/opt/ros/${ROS_DISTRO:-humble}/setup.bash"
export TURTLEBOT3_MODEL="${TURTLEBOT3_MODEL:-waffle_pi}"

SAVE_DIR="${1:-/tmp/scanned_map}"
mkdir -p "${SAVE_DIR}"

echo "Starting slam_toolbox (online async) with sim time..."
echo "Map will be built live. Drive the robot around to cover the office world."
echo "To save the map when done:"
echo "  ros2 run nav2_map_server map_saver_cli -f ${SAVE_DIR}/office_scanned"
echo ""

cleanup() {
  jobs -pr | xargs --no-run-if-empty kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# slam_toolbox first — publishes /map and the map→odom transform
ros2 launch slam_toolbox online_async_launch.py use_sim_time:=true &

# Wait until /map is being published before starting Nav2
echo "Waiting for slam_toolbox to publish /map..."
for _ in $(seq 1 30); do
  if ros2 topic info /map 2>/dev/null | grep -q "Publisher count: [^0]"; then
    echo "/map is available, starting Nav2..."
    break
  fi
  sleep 1
done

# Nav2 without slam (slam_toolbox already running)
ros2 launch nav2_bringup navigation_launch.py \
  use_sim_time:=True \
  slam:=False

wait
