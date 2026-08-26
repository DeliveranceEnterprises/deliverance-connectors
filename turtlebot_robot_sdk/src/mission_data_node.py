#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT
"""Plain ROS2 node that feeds the Robot SDK agent's CustomDataAgentlet with
real mission/navigation state, mirroring turtlebot_connector's Edge SDK
key-value shape (mission_status, mission_tracking).

No InOrbit SDK involved — publishes std_msgs/String messages shaped
"key=value" (value may be a JSON blob) to /inorbit/custom_data, which the
already-running Robot SDK agent picks up and forwards to InOrbit. Validated
manually via `ros2 topic pub` on 2026-07-28 before writing this node (see
turtlebot_robot_sdk/CLAUDE.md).

Tracks real Nav2 state instead of the placeholder used in the first version:
- InOrbit's Waypoint Teleop feature makes the agent publish a goal directly to
  /goal_pose (geometry_msgs/PoseStamped) -- that's the trigger for "a new task
  started", same as turtlebot_connector/src/backends/ros2_gazebo.py's
  dispatch_to_pose(), just from the other direction (agent -> Nav2 instead of
  connector -> Nav2).
- Nav2's navigate_to_pose action server publishes its status on the plain
  topic /navigate_to_pose/_action/status (action_msgs/msg/GoalStatusArray) --
  observable without owning an ActionClient, since we're not the one sending
  the goal.

Mission JSON shape mirrors turtlebot_connector/src/connector.py's
_compute_mission_status()/_build_mission_report() so the two approaches stay
comparable field-for-field.
"""

import json
import time

import rclpy
from action_msgs.msg import GoalStatusArray
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from std_msgs.msg import String

CUSTOM_DATA_TOPIC = "/inorbit/custom_data"
GOAL_POSE_TOPIC = "/goal_pose"
NAV2_STATUS_TOPIC = "/navigate_to_pose/_action/status"
PUBLISH_PERIOD_SEC = 2.0

# Gazebo doesn't simulate a battery topic (same constraint turtlebot_connector's
# Edge SDK backend works around) -- fixed value matching that connector's own
# fleet.ros2.office.local.yaml initial_battery (0.30), which is itself static
# and never actually decremented, so this is at parity, not a simplification.
# Two keys, two different consumers, both already defined and in use:
#   battery_percent (0-100) -> tag-scoped DataSource `turtlebot-battery`
#     (scale 0.01), which is what the Deliverance platform reads via
#     INORBIT_ROBOTS_JSON[].battery_attr_id.
#   "battery percent" (0-1, with a space) -> account-level DataSource
#     xlXPmDo3Z3GMwSTM, which drives InOrbit's own built-in Vitals gauge.
BATTERY_FRACTION = 0.30

# action_msgs/msg/GoalStatus status codes
STATUS_EXECUTING = 2
STATUS_SUCCEEDED = 4
STATUS_CANCELED = 5
STATUS_ABORTED = 6

_STATE_TO_MISSION_STATE = {
    STATUS_EXECUTING: "Executing",
    STATUS_SUCCEEDED: "Completed",
    STATUS_CANCELED: "Canceled",
    STATUS_ABORTED: "Aborted",
}


class MissionDataNode(Node):
    def __init__(self) -> None:
        super().__init__("mission_data_node")

        self._task_id: str | None = None
        self._label = ""
        self._start_ts = 0
        self._end_ts: int | None = None
        self._nav2_status: int | None = None
        self._current_goal_uuid: bytes | None = None
        self._pending_label = ""
        # uuid -> wall-clock ms of the first status message that ever mentioned
        # that goal. See _on_nav2_status for why this can't be sampled lazily.
        self._first_seen: dict[bytes, int] = {}

        self.create_subscription(PoseStamped, GOAL_POSE_TOPIC, self._on_goal_pose, 10)
        self.create_subscription(
            GoalStatusArray, NAV2_STATUS_TOPIC, self._on_nav2_status, 10
        )

        self._pub = self.create_publisher(String, CUSTOM_DATA_TOPIC, 10)
        self.create_timer(PUBLISH_PERIOD_SEC, self._publish)

    def _on_goal_pose(self, msg: PoseStamped) -> None:
        # Only a label hint for whichever goal Nav2 picks up next -- NOT proof
        # a task actually started. Receiving this message doesn't guarantee
        # Nav2 accepted/executed it (confirmed 2026-07-28: a second /goal_pose
        # was silently ignored while a prior goal was still wrapping up).
        # _on_nav2_status, driven by Nav2's own authoritative status topic, is
        # what actually declares a task started.
        self._pending_label = f"Go to ({msg.pose.position.x:.2f}, {msg.pose.position.y:.2f})"

    def _on_nav2_status(self, msg: GoalStatusArray) -> None:
        if not msg.status_list:
            return

        # Stamp EVERY goal the array mentions the first time we ever see it,
        # before any filtering. A goal appears here at ACCEPTED (status 1),
        # i.e. at dispatch -- so this is the closest thing to its real start
        # time we can observe without trusting Nav2's own header stamp (which
        # is sim time under Gazebo and therefore not a wall clock).
        #
        # This must happen up here, for all entries, not lazily for the one we
        # end up tracking: the old code sampled time.time() only once the goal
        # reached a state it recognised, and skipped ACCEPTED entirely via the
        # `status not in _STATE_TO_MISSION_STATE` early return below. Any goal
        # whose EXECUTING phase we didn't happen to observe was therefore first
        # stamped when it was already SUCCEEDED -- collapsing startTs and endTs
        # into the same instant (~60 ms apart), which is exactly what InOrbit
        # recorded for 6 of 12 missions on 2026-07-29. A mission with a
        # zero-length window has no trajectory to integrate, so InOrbit's
        # estimatedDistance came back 0 -- the "Distance: 0" seen on the
        # platform. Not a pose/telemetry problem: the robot really moved.
        now_ms = int(time.time() * 1000)
        for entry in msg.status_list:
            uuid = bytes(entry.goal_info.goal_id.uuid)
            if uuid not in self._first_seen:
                self._first_seen[uuid] = now_ms
        # status_list accumulates for the node's lifetime; keep the dict bounded.
        if len(self._first_seen) > 200:
            for uuid in list(self._first_seen)[:-100]:
                del self._first_seen[uuid]

        # Nav2 appends new goals; the latest entry reflects the current one.
        latest = msg.status_list[-1]
        status = latest.status
        if status not in _STATE_TO_MISSION_STATE:
            return

        goal_uuid = bytes(latest.goal_info.goal_id.uuid)
        if goal_uuid != self._current_goal_uuid:
            # A genuinely new goal, confirmed by Nav2 itself -- not by us
            # merely having sent/seen a /goal_pose message.
            self._current_goal_uuid = goal_uuid
            self._task_id = f"nav2-goal-{self._first_seen[goal_uuid]}"
            self._label = self._pending_label or "Go to goal"
            self._start_ts = self._first_seen[goal_uuid]
            self._end_ts = None

        if status != STATUS_EXECUTING and self._end_ts is None:
            self._end_ts = int(time.time() * 1000)
        self._nav2_status = status

    def _mission_status(self) -> str:
        if self._task_id is None:
            return "Idle"
        if self._nav2_status == STATUS_EXECUTING:
            return "Mission"
        return "Idle"

    def _mission_tracking(self) -> dict | None:
        if self._task_id is None:
            return None
        in_progress = self._nav2_status == STATUS_EXECUTING
        mission_state = _STATE_TO_MISSION_STATE.get(self._nav2_status, "Executing")
        report = {
            "missionId": self._task_id,
            "inProgress": in_progress,
            "state": mission_state,
            "label": self._label,
            "startTs": self._start_ts,
            "data": {"waypoint": ""},
            "status": "OK",
            "tasks": [{"taskId": "0", "label": self._label}],
            "completedPercent": 1.0 if mission_state == "Completed" else 0.0,
            # InOrbit's custom_data channel merges each publish into the previous
            # JSON value instead of replacing it outright (confirmed 2026-07-28) --
            # fields must be explicitly nulled out, not omitted, or stale values
            # from an earlier "Executing" publish stick around after completion.
            "currentTaskId": "0" if in_progress else None,
            "endTs": self._end_ts if not in_progress else None,
        }
        return report

    def _publish(self) -> None:
        self._publish_kv("mission_status", self._mission_status())
        tracking = self._mission_tracking()
        if tracking is not None:
            self._publish_kv("mission_tracking", json.dumps(tracking))
        self._publish_kv("battery_percent", str(int(BATTERY_FRACTION * 100)))
        self._publish_kv("battery percent", str(BATTERY_FRACTION))

    def _publish_kv(self, key: str, value: str) -> None:
        msg = String()
        msg.data = f"{key}={value}"
        self._pub.publish(msg)


def main() -> None:
    rclpy.init()
    node = MissionDataNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
