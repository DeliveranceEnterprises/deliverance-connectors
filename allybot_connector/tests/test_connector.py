# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for AllybotConnector data publishing and WebSocket message handling."""

from __future__ import annotations

import logging
import math
import time
from unittest.mock import MagicMock

import pytest

from allybot_connector.src.api.models import AllybotRobotState, quaternion_to_yaw
from allybot_connector.src.api.app_ws import AllybotAppWebSocket
from allybot_connector.src.connector import AllybotConnector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROBOT_ID = "inorbit-robot-1"
SERIAL = "6d70603da0cb3d00ba104a191770170b"


def _make_connector() -> AllybotConnector:
    connector = AllybotConnector.__new__(AllybotConnector)
    connector._robot_id_to_fleet_id = {ROBOT_ID: SERIAL}
    connector._robot_configs = {ROBOT_ID: MagicMock(fleet_robot_id=SERIAL)}
    connector._fleet_serial_to_robot_id = {SERIAL: ROBOT_ID}
    connector._robot_states = {ROBOT_ID: AllybotRobotState()}
    connector._logger = logging.getLogger("test")
    connector._api_client = None
    connector._app_ws = None
    connector._metadata_task = None
    return connector


# ---------------------------------------------------------------------------
# quaternion_to_yaw
# ---------------------------------------------------------------------------


def test_quaternion_to_yaw_identity() -> None:
    # Identity quaternion → yaw = 0
    assert quaternion_to_yaw(0, 0, 0, 1) == pytest.approx(0.0)


def test_quaternion_to_yaw_90_degrees() -> None:
    # 90° around z: qz = sin(45°), qw = cos(45°)
    s, c = math.sin(math.radians(45)), math.cos(math.radians(45))
    yaw = quaternion_to_yaw(0, 0, s, c)
    assert yaw == pytest.approx(math.radians(90), abs=1e-6)


def test_quaternion_to_yaw_negative() -> None:
    s, c = math.sin(math.radians(-45)), math.cos(math.radians(-45))
    yaw = quaternion_to_yaw(0, 0, s, c)
    assert yaw == pytest.approx(math.radians(-90), abs=1e-6)


# ---------------------------------------------------------------------------
# _publish_robot_data
# ---------------------------------------------------------------------------


def test_publish_pose_when_position_available() -> None:
    connector = _make_connector()
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_odometry = MagicMock()
    connector.publish_robot_key_values = MagicMock()

    state = connector._robot_states[ROBOT_ID]
    state.x = 1.5
    state.y = -2.3
    state.yaw = math.radians(45)
    state.speed = 0.5
    state.active_map_id = "map-abc"

    connector._publish_robot_data(ROBOT_ID, state)

    connector.publish_robot_pose.assert_called_once_with(
        ROBOT_ID, x=1.5, y=-2.3, yaw=pytest.approx(math.radians(45)), frame_id="map-abc"
    )
    connector.publish_robot_odometry.assert_called_once_with(ROBOT_ID, linear_speed=0.5)


def test_no_pose_when_position_missing() -> None:
    connector = _make_connector()
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_odometry = MagicMock()
    connector.publish_robot_key_values = MagicMock()

    connector._publish_robot_data(ROBOT_ID, connector._robot_states[ROBOT_ID])
    connector.publish_robot_pose.assert_not_called()
    connector.publish_robot_odometry.assert_not_called()


def test_key_values_include_ws_connected() -> None:
    connector = _make_connector()
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_odometry = MagicMock()
    connector.publish_robot_key_values = MagicMock()

    state = connector._robot_states[ROBOT_ID]
    state.ws_connected = True

    connector._publish_robot_data(ROBOT_ID, state)

    kv = connector.publish_robot_key_values.call_args.kwargs
    assert kv["ws_connected"] is True


def test_alive_status_1_maps_to_online_true() -> None:
    connector = _make_connector()
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_odometry = MagicMock()
    connector.publish_robot_key_values = MagicMock()

    state = connector._robot_states[ROBOT_ID]
    state.alive_status = 1

    connector._publish_robot_data(ROBOT_ID, state)

    kv = connector.publish_robot_key_values.call_args.kwargs
    assert kv["online_status"] is True
    assert kv["alive_status"] == "online"


def test_alive_status_2_maps_to_online_true() -> None:
    connector = _make_connector()
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_odometry = MagicMock()
    connector.publish_robot_key_values = MagicMock()

    state = connector._robot_states[ROBOT_ID]
    state.alive_status = 2

    connector._publish_robot_data(ROBOT_ID, state)

    kv = connector.publish_robot_key_values.call_args.kwargs
    assert kv["online_status"] is True
    assert kv["alive_status"] == "mobile_connected"


def test_alive_status_0_maps_to_online_false() -> None:
    connector = _make_connector()
    connector.publish_robot_pose = MagicMock()
    connector.publish_robot_odometry = MagicMock()
    connector.publish_robot_key_values = MagicMock()

    state = connector._robot_states[ROBOT_ID]
    state.alive_status = 0

    connector._publish_robot_data(ROBOT_ID, state)

    kv = connector.publish_robot_key_values.call_args.kwargs
    assert kv["online_status"] is False


# ---------------------------------------------------------------------------
# _is_fleet_robot_online
# ---------------------------------------------------------------------------


def test_is_fleet_robot_online_requires_ws_connected_and_recent_message() -> None:
    connector = _make_connector()
    state = connector._robot_states[ROBOT_ID]
    state.ws_connected = True
    state.last_ws_message = time.time()
    assert connector._is_fleet_robot_online(ROBOT_ID) is True


def test_is_fleet_robot_online_false_when_disconnected() -> None:
    connector = _make_connector()
    connector._robot_states[ROBOT_ID].ws_connected = False
    assert connector._is_fleet_robot_online(ROBOT_ID) is False


def test_is_fleet_robot_online_false_when_stale() -> None:
    connector = _make_connector()
    state = connector._robot_states[ROBOT_ID]
    state.ws_connected = True
    state.last_ws_message = time.time() - 120  # older than timeout
    assert connector._is_fleet_robot_online(ROBOT_ID) is False


# ---------------------------------------------------------------------------
# App WebSocket message dispatch
# ---------------------------------------------------------------------------


def test_app_ws_device_position_updates_state() -> None:
    import json

    robot_states = {ROBOT_ID: AllybotRobotState()}
    fleet_map = {SERIAL: ROBOT_ID}

    ws = AllybotAppWebSocket(
        base_url="http://host:28080",
        openid="oid",
        token="tok",
        robot_states=robot_states,
        fleet_serial_to_robot_id=fleet_map,
    )

    s, c = math.sin(math.radians(45)), math.cos(math.radians(45))
    inner_msg = json.dumps(
        {
            "serial": SERIAL,
            "position": {"x": 1.11, "y": 0.22, "z": 0.0},
            "orientation": {"x": 0.0, "y": 0.0, "z": s, "w": c},
            "speed": 0.5,
        }
    )
    ws._dispatch(json.dumps({"type": "device_position", "uuid": "123", "msg": inner_msg}))

    state = robot_states[ROBOT_ID]
    assert state.x == pytest.approx(1.11)
    assert state.y == pytest.approx(0.22)
    assert state.yaw == pytest.approx(math.radians(90), abs=1e-5)
    assert state.speed == pytest.approx(0.5)
    assert state.ws_connected is True


def test_app_ws_unknown_serial_ignored() -> None:
    import json

    robot_states = {ROBOT_ID: AllybotRobotState()}
    ws = AllybotAppWebSocket(
        base_url="http://host:28080",
        openid="oid",
        token="tok",
        robot_states=robot_states,
        fleet_serial_to_robot_id={},  # empty map
    )
    inner_msg = json.dumps(
        {
            "serial": "unknown-serial",
            "position": {"x": 9.9, "y": 9.9, "z": 0},
            "orientation": {"x": 0, "y": 0, "z": 0, "w": 1},
            "speed": 0,
        }
    )
    ws._dispatch(json.dumps({"type": "device_position", "msg": inner_msg}))
    # State must be untouched
    assert robot_states[ROBOT_ID].x is None


def test_app_ws_pong_does_not_update_state() -> None:
    import json

    robot_states = {ROBOT_ID: AllybotRobotState()}
    ws = AllybotAppWebSocket(
        base_url="http://host:28080",
        openid="oid",
        token="tok",
        robot_states=robot_states,
        fleet_serial_to_robot_id={SERIAL: ROBOT_ID},
    )
    ws._dispatch(json.dumps({"type": "pong"}))
    assert robot_states[ROBOT_ID].ws_connected is False  # unchanged
