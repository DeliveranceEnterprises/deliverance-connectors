# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Task lifecycle: the real DataPoller and _publish_robot_data against a fake AutoXing API."""

from __future__ import annotations

import asyncio

import pytest

from autoxing_cloud_connector.src.api import data_poller as dp
from autoxing_cloud_connector.src.api.models import RobotState
from autoxing_cloud_connector.src.connector import AutoxingCloudConnector

DETAIL = {"taskPts": [{"ext": {"name": "Point A"}, "x": 1, "y": 2}]}


def robot(task_id: str | None = None, finish: bool = False, cancel: bool = False) -> dict:
    """One /robot/v1.1/{id}/state body."""
    raw = {"x": 1.0, "y": 1.0, "yaw": 0.0}
    if task_id:
        raw["taskObj"] = {"taskId": task_id, "isFinish": finish, "isCancel": cancel}
    return raw


class FakeClient:
    def __init__(self, states: list[dict], detail: dict | None = DETAIL) -> None:
        self.states = list(states)
        self.detail = detail
        self.get_task_calls = 0

    async def get_robot_list(self) -> list[dict]:
        return [{"robotId": "F1", "isOnLine": True}]

    async def get_robot_state(self, fleet_id: str) -> dict | None:
        return self.states.pop(0)

    async def get_task(self, task_id: str) -> dict | None:
        self.get_task_calls += 1
        return self.detail


class Harness:
    """Runs poll -> publish cycles and records what reached InOrbit."""

    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.state = RobotState()
        self.poller = dp.DataPoller(
            client=client,
            robot_states={"r1": self.state},
            robot_id_to_fleet_id={"r1": "F1"},
            fleet_id_to_robot_id={"F1": "r1"},
        )
        self.connector = AutoxingCloudConnector.__new__(AutoxingCloudConnector)
        self.connector._area_names = {}
        self.connector.publish_robot_pose = lambda *a, **k: None
        self.connector.publish_robot_odometry = lambda *a, **k: None
        self.published: list[dict] = []
        self.connector.publish_robot_key_values = lambda rid, **kv: self.published.append(kv)

    async def poll(self, publish: bool = True) -> None:
        await self.poller._poll_once()
        await asyncio.sleep(0)  # let a background detail fetch run
        if publish:
            self.connector._publish_robot_data("r1", self.state)

    async def run(self) -> None:
        while self.client.states:
            await self.poll()

    @property
    def missions(self) -> list[tuple[str, str]]:
        return [
            (kv["mission_tracking"]["missionId"], kv["mission_tracking"]["state"])
            for kv in self.published
            if "mission_tracking" in kv
        ]


@pytest.fixture(autouse=True)
def _cache_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "_CACHE_FILE", str(tmp_path / "task_start_ts_cache.json"))


async def test_a_finished_task_lingering_in_taskobj_is_not_reopened() -> None:
    h = Harness(FakeClient([robot("T1"), robot("T1"), *[robot("T1", finish=True)] * 4, robot(), robot()]))
    await h.run()
    assert h.missions == [("T1", "Executing"), ("T1", "Executing"), ("T1", "Completed")]
    assert h.published[-1]["mission_status"] == "Idle"
    assert h.client.get_task_calls == 1


async def test_a_new_task_after_a_closed_one_is_tracked() -> None:
    h = Harness(FakeClient([robot("T1"), robot("T1", finish=True), robot("T1", finish=True), robot("T2")]))
    await h.run()
    assert h.missions == [("T1", "Executing"), ("T1", "Completed"), ("T2", "Executing")]


async def test_a_short_task_without_detail_still_publishes_its_terminal_mission() -> None:
    h = Harness(FakeClient([robot("T1"), robot("T1", finish=True), robot(), robot()], detail=None))
    await h.run()
    assert h.missions == [("T1", "Completed")]


async def test_a_task_first_seen_already_finished_is_published_once_as_completed() -> None:
    h = Harness(FakeClient([robot("T1", finish=True)] * 3))
    await h.run()
    assert h.missions == [("T1", "Completed")]


async def test_a_cancelled_task_whose_taskobj_vanishes_is_reported_canceled() -> None:
    h = Harness(FakeClient([robot("T1"), robot("T1"), robot(), robot(), robot()]))
    await h.poll()
    # The cancel command marks the task cancelled; the API still shows it
    # running on the next poll, then drops taskObj.
    h.state.task_is_cancel = True
    await h.poll(publish=False)
    for _ in range(3):
        await h.poll(publish=False)
    h.connector._publish_robot_data("r1", h.state)
    assert h.missions[-1] == ("T1", "Canceled")


async def test_a_task_whose_taskobj_vanishes_is_completed_after_the_grace_period() -> None:
    h = Harness(FakeClient([robot("T1"), robot(), robot(), robot(), robot()]))
    await h.run()
    assert h.missions == [("T1", "Executing")] * 3 + [("T1", "Completed")]
