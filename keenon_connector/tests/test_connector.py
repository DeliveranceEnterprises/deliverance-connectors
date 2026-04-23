# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for KeenonConnector command handling and data publishing."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inorbit_connector.commands import CommandResultCode

from keenon_connector.src.api.models import RobotState
from keenon_connector.src.commands import CustomScripts
from keenon_connector.src.connector import KeenonConnector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connector(robot_id: str = "robot-1", fleet_id: str = "AA:BB:CC:DD:EE:FF") -> KeenonConnector:
    """Build a KeenonConnector with all external dependencies stubbed out."""
    connector = KeenonConnector.__new__(KeenonConnector)
    connector._robot_id_to_fleet_id = {robot_id: fleet_id}
    connector._robot_configs = {
        robot_id: SimpleNamespace(store_id="S00000001", fleet_robot_id=fleet_id)
    }
    connector._fleet_sn_to_robot_id = {fleet_id: robot_id}
    connector._robot_states = {robot_id: RobotState(robot_type="food")}
    connector._logger = logging.getLogger("test")
    connector._api_client = MagicMock()
    connector._data_poller = None
    connector._webhook_receiver = None
    return connector


def _result_collector():
    calls: list = []

    def result_fn(code, **kwargs):
        calls.append((code, kwargs))

    return calls, result_fn


# ---------------------------------------------------------------------------
# Command: call_to_point
# ---------------------------------------------------------------------------


async def test_call_to_point_stores_task_no() -> None:
    connector = _make_connector()
    connector._api_client.call_to_point = AsyncMock(return_value="task-001")
    calls, result_fn = _result_collector()

    await connector._inorbit_robot_command_handler(
        robot_id="robot-1",
        command_name="customCommand",
        args=[CustomScripts.CALL_TO_POINT, ["point_uuid", "uuid-1", "point_id", "pt-1"]],
        options={"result_function": result_fn},
    )

    connector._api_client.call_to_point.assert_awaited_once()
    assert connector._robot_states["robot-1"].task_no == "task-001"
    assert calls[0][0] == CommandResultCode.SUCCESS


# ---------------------------------------------------------------------------
# Command: return_to_origin
# ---------------------------------------------------------------------------


async def test_return_to_origin_stores_task_no() -> None:
    connector = _make_connector()
    connector._api_client.return_to_origin = AsyncMock(return_value="task-002")
    calls, result_fn = _result_collector()

    await connector._inorbit_robot_command_handler(
        robot_id="robot-1",
        command_name="customCommand",
        args=[CustomScripts.RETURN_TO_ORIGIN, []],
        options={"result_function": result_fn},
    )

    connector._api_client.return_to_origin.assert_awaited_once_with(
        store_id="S00000001", robot_id="AA:BB:CC:DD:EE:FF"
    )
    assert connector._robot_states["robot-1"].task_no == "task-002"
    assert calls[0][0] == CommandResultCode.SUCCESS


# ---------------------------------------------------------------------------
# Command: cancel_task
# ---------------------------------------------------------------------------


async def test_cancel_task_marks_cancelled() -> None:
    connector = _make_connector()
    connector._api_client.cancel_task = AsyncMock()
    connector._robot_states["robot-1"].task_no = "task-abc"
    calls, result_fn = _result_collector()

    await connector._inorbit_robot_command_handler(
        robot_id="robot-1",
        command_name="customCommand",
        args=[CustomScripts.CANCEL_TASK, ["task_no", "task-abc"]],
        options={"result_function": result_fn},
    )

    connector._api_client.cancel_task.assert_awaited_once_with(task_no="task-abc")
    assert connector._robot_states["robot-1"].task_status == 5
    assert calls[0][0] == CommandResultCode.SUCCESS


# ---------------------------------------------------------------------------
# Command: cleaning commands
# ---------------------------------------------------------------------------


async def test_clean_recharge_dispatched() -> None:
    connector = _make_connector()
    connector._api_client.clean_recharge = AsyncMock()
    _, result_fn = _result_collector()

    await connector._inorbit_robot_command_handler(
        robot_id="robot-1",
        command_name="customCommand",
        args=[CustomScripts.CLEAN_RECHARGE, []],
        options={"result_function": result_fn},
    )

    connector._api_client.clean_recharge.assert_awaited_once_with(
        robot_sn="AA:BB:CC:DD:EE:FF"
    )


async def test_clean_pause_dispatched() -> None:
    connector = _make_connector()
    connector._api_client.clean_pause = AsyncMock()
    _, result_fn = _result_collector()

    await connector._inorbit_robot_command_handler(
        robot_id="robot-1",
        command_name="customCommand",
        args=[CustomScripts.CLEAN_PAUSE, []],
        options={"result_function": result_fn},
    )

    connector._api_client.clean_pause.assert_awaited_once_with(
        robot_sn="AA:BB:CC:DD:EE:FF"
    )


# ---------------------------------------------------------------------------
# Command: unknown
# ---------------------------------------------------------------------------


async def test_unknown_command_raises_command_failure() -> None:
    from inorbit_connector.commands import CommandFailure

    connector = _make_connector()
    _, result_fn = _result_collector()

    with pytest.raises(CommandFailure, match="Unknown command"):
        await connector._inorbit_robot_command_handler(
            robot_id="robot-1",
            command_name="customCommand",
            args=["does_not_exist", []],
            options={"result_function": result_fn},
        )


# ---------------------------------------------------------------------------
# _publish_robot_data
# ---------------------------------------------------------------------------


def test_publish_robot_data_battery_normalized() -> None:
    connector = _make_connector()
    connector.publish_robot_key_values = MagicMock()
    connector.publish_robot_pose = MagicMock()

    state = connector._robot_states["robot-1"]
    state.battery = 75
    state.online_status = True
    state.api_connected = True

    connector._publish_robot_data("robot-1", state)

    kv_call = connector.publish_robot_key_values.call_args
    assert kv_call.kwargs["battery"] == pytest.approx(0.75)


def test_publish_robot_data_pose_published_when_available() -> None:
    import math

    connector = _make_connector()
    connector.publish_robot_key_values = MagicMock()
    connector.publish_robot_pose = MagicMock()

    state = connector._robot_states["robot-1"]
    state.x = 1.5
    state.y = -2.3
    state.yaw = math.radians(45)
    state.scene_code = "testScene"

    connector._publish_robot_data("robot-1", state)

    connector.publish_robot_pose.assert_called_once_with(
        "robot-1", x=1.5, y=-2.3, yaw=pytest.approx(math.radians(45)), frame_id="testScene"
    )


def test_publish_robot_data_no_pose_when_missing() -> None:
    connector = _make_connector()
    connector.publish_robot_key_values = MagicMock()
    connector.publish_robot_pose = MagicMock()

    connector._publish_robot_data("robot-1", connector._robot_states["robot-1"])
    connector.publish_robot_pose.assert_not_called()


# ---------------------------------------------------------------------------
# _is_fleet_robot_online
# ---------------------------------------------------------------------------


def test_is_fleet_robot_online_reflects_api_connected() -> None:
    connector = _make_connector()
    connector._robot_states["robot-1"].api_connected = False
    assert connector._is_fleet_robot_online("robot-1") is False

    connector._robot_states["robot-1"].api_connected = True
    assert connector._is_fleet_robot_online("robot-1") is True
