# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for AllybotConnector data publishing and WebSocket message handling."""

from __future__ import annotations

import json
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


# ---------------------------------------------------------------------------
# Language-independent work_status / mode (seen live: "Charging" <-> "Cargando")
# ---------------------------------------------------------------------------


def _device_status_body(work_status: str, have_task: bool = False) -> dict:
    return {"data": {"id": SERIAL, "battery": 100, "work_status": work_status,
                     "haveTaskRunning": have_task}}


def test_spanish_work_status_is_normalised_and_keeps_mode_charging() -> None:
    connector = _make_connector()
    ws = AllybotAppWebSocket.__new__(AllybotAppWebSocket)
    ws._robot_states = connector._robot_states
    ws._fleet_serial_to_robot_id = connector._fleet_serial_to_robot_id
    ws._unseen_work_status_logged = set()
    state = connector._robot_states[ROBOT_ID]

    for raw in ("Charging", "Cargando", "CARGANDO", "Charging"):
        ws._on_device_status(_device_status_body(raw))
        assert state.work_status == "Charging"
        assert connector._compute_mission_status(state) == "Charging"


def test_normalize_work_status_maps_known_pairs_and_passes_unknown() -> None:
    from allybot_connector.src.api.models import normalize_work_status

    assert normalize_work_status("En funcionamiento") == "Operating"
    assert normalize_work_status("Volviendo") == "Returning"
    assert normalize_work_status("Algo nuevo") == "Algo nuevo"
    assert normalize_work_status(None) is None


# ---------------------------------------------------------------------------
# Each run gets its own startTs / missionId and a fixed end time
# ---------------------------------------------------------------------------


def _ws_for(connector: AllybotConnector) -> AllybotAppWebSocket:
    ws = AllybotAppWebSocket.__new__(AllybotAppWebSocket)
    ws._robot_states = connector._robot_states
    ws._fleet_serial_to_robot_id = connector._fleet_serial_to_robot_id
    ws._unseen_work_status_logged = set()
    return ws


def _task_status_body(start_ms: int) -> dict:
    return {"robotid": SERIAL, "taskId": "task-A", "name": "Hotel_Hospital",
            "taskStatus": 5, "percent": 10, "msg": json.dumps({"startTime": start_ms})}


def test_second_run_gets_its_own_start_and_mission_id() -> None:
    connector = _make_connector()
    ws = _ws_for(connector)
    state = connector._robot_states[ROBOT_ID]

    ws._on_device_status(_device_status_body("Operating", have_task=True))
    ws._on_task_status(_task_status_body(1_000_000))
    first = connector._build_mission_report(state)
    assert first["startTs"] == 1_000_000
    assert first["missionId"] == "task-A_1000000"

    ws._on_device_status(_device_status_body("Charging", have_task=False))  # run 1 ends
    ws._on_device_status(_device_status_body("Operating", have_task=True))  # run 2 begins
    assert state.task_start_ts is None  # reset, not inherited from run 1
    ws._on_task_status(_task_status_body(2_000_000))
    second = connector._build_mission_report(state)
    assert second["startTs"] == 2_000_000
    assert second["missionId"] == "task-A_2000000"


def test_finished_mission_keeps_a_fixed_end_and_stops_being_republished() -> None:
    connector = _make_connector()
    ws = _ws_for(connector)
    state = connector._robot_states[ROBOT_ID]
    ws._on_device_status(_device_status_body("Operating", have_task=True))
    ws._on_task_status(_task_status_body(1_000_000))
    ws._on_device_status(_device_status_body("Charging", have_task=False))

    r1 = connector._build_mission_report(state)
    end_1 = r1["endTs"]
    assert r1["state"] == "Completed" and r1["inProgress"] is False
    time.sleep(0.01)
    assert connector._build_mission_report(state)["endTs"] == end_1  # does not creep

    state.task_end_ts -= 61_000  # a minute later
    assert connector._build_mission_report(state) is None  # no longer republished


def test_new_run_waits_for_robot_start_time_then_falls_back() -> None:
    connector = _make_connector()
    ws = _ws_for(connector)
    state = connector._robot_states[ROBOT_ID]
    state.task_id = "task-A"
    ws._on_device_status(_device_status_body("Operating", have_task=True))
    assert connector._build_mission_report(state) is None  # inside the grace window

    state.run_seen_at -= 10.0  # grace elapsed without a robot startTime
    report = connector._build_mission_report(state)
    assert report is not None and report["startTs"] == state.task_start_ts
    assert connector._build_mission_report(state)["startTs"] == report["startTs"]  # stable


def test_dispatched_task_is_not_published_until_robot_reports_running() -> None:
    connector = _make_connector()
    ws = _ws_for(connector)
    state = connector._robot_states[ROBOT_ID]

    # start_task just returned OK: task_id set, robot not yet running
    state.task_id, state.task_status_code = "task-A", 3
    assert connector._build_mission_report(state) is None

    ws._on_device_status(_device_status_body("Operating", have_task=True))
    ws._on_task_status(_task_status_body(1_000_000))
    report = connector._build_mission_report(state)
    assert report is not None and report["missionId"] == "task-A_1000000"


# ---------------------------------------------------------------------------
# The robot's own time estimate (whole minutes) is published, and its first value is kept
# ---------------------------------------------------------------------------


def _task_status_with_estimate(start_ms: int, total: object, **inner_extra: object) -> dict:
    inner: dict = {"startTime": start_ms, **inner_extra}
    if total is not None:
        inner["totalTime"] = total
    return {"robotid": SERIAL, "taskId": "task-A", "name": "Test Site",
            "taskStatus": 5, "percent": 10, "msg": json.dumps(inner)}


def test_time_estimate_is_published_with_its_first_value_kept() -> None:
    """The sequence the robot really sent (a 5 min 3 s run): 3 at the start, 10 at 11 %, a dip to 3, settling at 5."""
    connector = _make_connector()
    ws = _ws_for(connector)
    state = connector._robot_states[ROBOT_ID]
    ws._on_device_status(_device_status_body("Operating", have_task=True))
    for total in [3, 10, 3, 6, 5]:
        ws._on_task_status(_task_status_with_estimate(1_000_000, total))
    data = connector._build_mission_report(state)["data"]
    assert data["estimated_total_time_start_min"] == 3   # fixed for the run
    assert data["estimated_total_time_min"] == 5         # the latest
    assert "working_time_min" not in data                # the report already carries the real duration


def test_time_estimate_starts_over_with_each_run() -> None:
    connector = _make_connector()
    ws = _ws_for(connector)
    state = connector._robot_states[ROBOT_ID]
    ws._on_device_status(_device_status_body("Operating", have_task=True))
    ws._on_task_status(_task_status_with_estimate(1_000_000, 3))
    ws._on_task_status(_task_status_with_estimate(1_000_000, 5))

    ws._on_device_status(_device_status_body("Charging", have_task=False))  # run 1 ends
    ws._on_device_status(_device_status_body("Operating", have_task=True))  # run 2 begins
    assert (state.task_estimate_start_min, state.task_estimate_min) == (None, None)
    ws._on_task_status(_task_status_with_estimate(2_000_000, 4))
    data = connector._build_mission_report(state)["data"]
    assert data["estimated_total_time_start_min"] == 4   # not run 1's 3
    assert data["estimated_total_time_min"] == 4


@pytest.mark.parametrize("bad", ["abc", True, -1, [3], {"a": 1}])
def test_unreadable_time_estimate_is_left_out_and_does_not_cost_the_area(bad: object) -> None:
    connector = _make_connector()
    ws = _ws_for(connector)
    state = connector._robot_states[ROBOT_ID]
    ws._on_device_status(_device_status_body("Operating", have_task=True))
    ws._on_task_status(_task_status_with_estimate(1_000_000, bad, workingScope=16.0))
    data = connector._build_mission_report(state)["data"]
    assert "estimated_total_time_start_min" not in data and "estimated_total_time_min" not in data
    assert data["plan_area"] == 16.0   # the area in the same message is still read


def test_time_estimate_accepts_numbers_sent_as_text_or_floats() -> None:
    connector = _make_connector()
    ws = _ws_for(connector)
    state = connector._robot_states[ROBOT_ID]
    ws._on_device_status(_device_status_body("Operating", have_task=True))
    ws._on_task_status(_task_status_with_estimate(1_000_000, "5"))
    ws._on_task_status(_task_status_with_estimate(1_000_000, 4.0))
    data = connector._build_mission_report(state)["data"]
    assert (data["estimated_total_time_start_min"], data["estimated_total_time_min"]) == (5, 4)


# ---------------------------------------------------------------------------
# Emergency stop (not verified on a real robot: see AllybotRobotState.emergency_stop)
# ---------------------------------------------------------------------------


def _ws_and_state(connector):
    ws = AllybotAppWebSocket.__new__(AllybotAppWebSocket)
    ws._robot_states = connector._robot_states
    ws._fleet_serial_to_robot_id = connector._fleet_serial_to_robot_id
    ws._unseen_work_status_logged = set()
    return ws, connector._robot_states[ROBOT_ID]


def test_emergency_stop_flag_or_work_status_gives_the_emergency_mode_and_clears() -> None:
    connector = _make_connector()
    ws, state = _ws_and_state(connector)

    body = _device_status_body("Operating", have_task=True)
    body["data"]["emergencyStop"] = True
    ws._on_device_status(body)
    assert state.emergency_stop is True
    assert connector._compute_mission_status(state) == "Emergency"   # wins over the running task

    ws._on_device_status(_device_status_body("Operating", have_task=True))       # released
    assert state.emergency_stop is False
    assert connector._compute_mission_status(state) == "Mission"

    ws._on_device_status(_device_status_body("Emergency Stop"))                   # a work_status that says it
    assert connector._compute_mission_status(state) == "Emergency"
    ws._on_device_status(_device_status_body("Idle"))
    assert connector._compute_mission_status(state) == "Idle"


def test_a_dead_websocket_is_still_an_error_before_an_emergency() -> None:
    connector = _make_connector()
    state = connector._robot_states[ROBOT_ID]
    state.emergency_stop = True
    state.ws_connected = False
    assert connector._compute_mission_status(state) == "Error"


def test_ordinary_work_status_never_reads_as_an_emergency() -> None:
    connector = _make_connector()
    ws, state = _ws_and_state(connector)
    for raw, mode in (("Charging", "Charging"), ("Cargando", "Charging"), ("Idle", "Idle"),
                      ("Operating", "Idle"), ("Returning", "Idle")):
        ws._on_device_status(_device_status_body(raw))
        assert state.emergency_stop is False
        assert connector._compute_mission_status(state) == mode


def test_an_unseen_work_status_is_logged_once(caplog) -> None:
    connector = _make_connector()
    ws, _ = _ws_and_state(connector)
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            ws._on_device_status(_device_status_body("Something New"))
        ws._on_device_status(_device_status_body("Charging"))
    assert sum("never seen before" in r.message for r in caplog.records) == 1


def test_unseen_work_status_log_is_kept_per_websocket_instance(caplog) -> None:
    connector = _make_connector()
    first, _ = _ws_and_state(connector)
    second, _ = _ws_and_state(connector)
    with caplog.at_level(logging.WARNING):
        first._on_device_status(_device_status_body("Something New"))
        second._on_device_status(_device_status_body("Something New"))
    assert sum("never seen before" in r.message for r in caplog.records) == 2
    assert first._unseen_work_status_logged is not second._unseen_work_status_logged
