# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for the task-status poll and the per-task report fetch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from keenon_connector.src.api import data_poller as dp
from keenon_connector.src.api.data_poller import DataPoller
from keenon_connector.src.api.models import TERMINAL_TASK_STATUSES, RobotState


def _poller(task_status: int, info: dict | None) -> DataPoller:
    client = MagicMock()
    client.get_task_status = AsyncMock(return_value={"taskStatus": task_status})
    client.get_task_info = AsyncMock(return_value=info)
    return DataPoller(client, {}, {}, {}, update_freq=1.0)


def _state() -> RobotState:
    return RobotState(robot_type="food", task_no="task-1", task_start_ts=1_000)


def _info(distance) -> dict:
    return {
        "taskType": 1,
        "taskState": 4,
        "subTaskInfoList": [{"pointName": "Table 1", "taskDistance": distance}],
    }


def test_terminal_statuses_are_failed_completed_cancelled() -> None:
    assert TERMINAL_TASK_STATUSES == {0, 4, 5}
    assert 6 not in TERMINAL_TASK_STATUSES  # target reached: still active


async def test_target_reached_does_not_fetch_the_report() -> None:
    poller = _poller(6, _info(12.5))
    state = _state()
    await poller._update_task_status(state, "S1", "SN1")
    poller._client.get_task_info.assert_not_called()
    assert state.task_report is None


async def test_failed_task_fetches_the_report() -> None:
    poller = _poller(0, _info(0))
    state = _state()
    await poller._update_task_status(state, "S1", "SN1")
    assert state.task_report is not None and state.task_report["task_mileage"] == 0.0


async def test_completed_task_with_zero_distance_is_retried(monkeypatch) -> None:
    monkeypatch.setattr(dp, "REPORT_RETRY_INTERVAL_S", 0.0)
    poller = _poller(4, _info(0))
    state = _state()

    await poller._update_task_status(state, "S1", "SN1")
    assert state.task_report is None and state.task_report_attempts == 1

    poller._client.get_task_info.return_value = _info("12.5")
    await poller._update_task_status(state, "S1", "SN1")
    assert state.task_report["task_mileage"] == 12.5
    assert state.task_report["point_name"] == "Table 1"


async def test_incomplete_report_is_kept_on_the_last_attempt(monkeypatch) -> None:
    monkeypatch.setattr(dp, "REPORT_RETRY_INTERVAL_S", 0.0)
    poller = _poller(4, _info(0))
    state = _state()
    for _ in range(dp.MAX_REPORT_ATTEMPTS):
        await poller._update_task_status(state, "S1", "SN1")
    assert state.task_report is not None and state.task_report["task_mileage"] == 0.0
    assert poller._client.get_task_info.await_count == dp.MAX_REPORT_ATTEMPTS
