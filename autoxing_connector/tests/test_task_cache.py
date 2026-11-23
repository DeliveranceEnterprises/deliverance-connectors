# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""The task start-time cache: bounded, persisted, shared by all robots."""

from __future__ import annotations

import json
import time

from autoxing_cloud_connector.src.api.task_cache import CACHE_FILE_NAME, TaskStartCache
from tests.test_task_lifecycle import FakeClient, Harness, robot

DAY_MS = 86400 * 1000


def now_ms() -> int:
    return int(time.time() * 1000)


def test_start_ts_is_recorded_once_and_survives_a_reload(tmp_path) -> None:
    path = tmp_path / "data" / CACHE_FILE_NAME
    cache = TaskStartCache(path)
    first = cache.start_ts("T1", 1_000 + now_ms())
    assert cache.start_ts("T1", 5) == first
    assert TaskStartCache(path).start_ts("T1") == first


def test_closing_a_task_is_persisted(tmp_path) -> None:
    path = tmp_path / CACHE_FILE_NAME
    cache = TaskStartCache(path)
    cache.start_ts("T1")
    cache.close("T1")
    assert TaskStartCache(path).is_closed("T1")


def test_old_entries_are_dropped_and_the_drop_is_persisted(tmp_path) -> None:
    path = tmp_path / CACHE_FILE_NAME
    path.write_text(json.dumps({"OLD": now_ms() - 8 * DAY_MS, "NEW": {"start_ts": now_ms(), "closed": True}}))
    cache = TaskStartCache(path)
    assert "OLD" not in cache and cache.is_closed("NEW")
    assert set(json.loads(path.read_text())) == {"NEW"}


def test_the_cache_keeps_only_the_newest_entries(tmp_path) -> None:
    cache = TaskStartCache(tmp_path / CACHE_FILE_NAME, max_entries=3)
    base = now_ms()
    for i in range(5):
        cache.start_ts(f"T{i}", base + i)
    assert len(cache) == 3
    assert "T0" not in cache and "T1" not in cache and "T4" in cache


def test_an_unreadable_file_starts_an_empty_cache(tmp_path) -> None:
    path = tmp_path / CACHE_FILE_NAME
    path.write_text("{not json")
    assert len(TaskStartCache(path)) == 0


def test_without_a_path_nothing_is_written(tmp_path) -> None:
    cache = TaskStartCache(None)
    cache.start_ts("T1")
    cache.close("T1")
    assert cache.is_closed("T1")
    assert list(tmp_path.iterdir()) == []


async def test_a_restart_keeps_the_start_ts_and_does_not_reopen_a_closed_task(tmp_path) -> None:
    h = Harness(FakeClient([robot("T1"), robot("T1"), robot("T1", finish=True), robot("T2")]), data_dir=tmp_path)
    await h.run()
    start_t1 = h.published[0]["mission_tracking"]["startTs"]
    start_t2 = h.published[-1]["mission_tracking"]["startTs"]
    saved = json.loads((tmp_path / CACHE_FILE_NAME).read_text())
    assert saved["T1"] == {"start_ts": start_t1, "closed": True}

    # After a restart, AutoXing still shows the finished T1, then T2 again.
    h2 = Harness(FakeClient([robot("T1", finish=True), robot("T1", finish=True), robot("T2")]), data_dir=tmp_path)
    await h2.run()
    assert [m[0] for m in h2.missions] == ["T2"]
    assert h2.published[-1]["mission_tracking"]["startTs"] == start_t2


async def test_all_robots_share_one_cache(tmp_path) -> None:
    h = Harness(FakeClient([robot("T1")]), data_dir=tmp_path)
    assert not hasattr(h.state, "_task_start_ts_cache")
    await h.run()
    assert "T1" in h.poller._task_cache
