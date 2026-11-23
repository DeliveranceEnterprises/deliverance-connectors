# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""The mode (mission_status) the Autoxing connector publishes to InOrbit."""

from __future__ import annotations

import pytest

from autoxing_cloud_connector.src.api.models import RobotState
from autoxing_cloud_connector.src.connector import AutoxingCloudConnector


def _mode(**state) -> str:
    connector = AutoxingCloudConnector.__new__(AutoxingCloudConnector)
    return connector._compute_mission_status(RobotState(**{"api_connected": True, **state}))


def test_an_emergency_stop_is_its_own_mode_and_not_an_error() -> None:
    assert _mode(is_emergency_stop=True) == "Emergency"
    # it wins over everything the robot may be doing, but not over a dead API
    assert _mode(is_emergency_stop=True, is_manual_mode=True, task_id="t1", is_charging=True) == "Emergency"
    assert _mode(is_emergency_stop=True, api_connected=False) == "Error"


@pytest.mark.parametrize("state, expected", [
    (dict(api_connected=False), "Error"),
    (dict(is_manual_mode=True), "Manual"),
    (dict(task_id="t1"), "Mission"),
    (dict(task_id="t1", task_is_finish=True), "Idle"),
    (dict(task_id="t1", task_is_cancel=True, is_charging=True), "Charging"),
    (dict(is_charging=True), "Charging"),
    (dict(is_go_home=True), "Charging"),
    (dict(), "Idle"),
])
def test_every_other_mode_is_as_it_was(state, expected) -> None:
    """The emergency mode is the only change: nothing else about the mode of a robot in the field moves."""
    assert _mode(**state) == expected
