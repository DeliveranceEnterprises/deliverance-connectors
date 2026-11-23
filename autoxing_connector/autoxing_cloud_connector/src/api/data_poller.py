# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Background polling loop for AutoXing robot state."""

import asyncio
import logging
import time
from pathlib import Path

from .client import AutoxingAPIClient
from .models import RobotState
from .task_cache import CACHE_FILE_NAME, TaskStartCache

logger = logging.getLogger(__name__)

# Task detail (GET /task/v1.1/{id}) is tried at most this many times per task,
# the n-th retry waiting n * _TASK_DETAIL_RETRY_DELAY_S after the previous
# failure. After that the mission goes out without it.
_TASK_DETAIL_MAX_ATTEMPTS = 3
_TASK_DETAIL_RETRY_DELAY_S = 5.0

class DataPoller:
    """Polls the AutoXing API for robot state and updates shared RobotState objects.

    Runs as a background asyncio task. Each poll cycle fetches the online robot list
    (for online/task flags) and per-robot state (for pose, battery, flags).
    """

    def __init__(
        self,
        client: AutoxingAPIClient,
        robot_states: dict[str, RobotState],
        robot_id_to_fleet_id: dict[str, str],
        fleet_id_to_robot_id: dict[str, str],
        update_freq: float = 1.0,
        data_dir: str | Path | None = None,
    ) -> None:
        self._client = client
        self._robot_states = robot_states
        self._robot_id_to_fleet_id = robot_id_to_fleet_id
        self._fleet_id_to_robot_id = fleet_id_to_robot_id
        self._poll_interval = 1.0 / update_freq if update_freq > 0 else 1.0
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._clock = time.monotonic
        # In-flight task detail fetches, one per robot at most.
        self._detail_jobs: dict[str, asyncio.Task] = {}
        # Start time and closed flag of each task, shared by all robots and
        # kept on disk under data_dir so a restart keeps each mission's
        # startTs and does not reopen tasks already closed. None: memory only.
        cache_path = Path(data_dir) / CACHE_FILE_NAME if data_dir is not None else None
        self._task_cache = TaskStartCache(cache_path)

    async def poll_once(self) -> None:
        """Run a single poll cycle synchronously. Call before start() to
        pre-populate robot state so no (0, 0) pose artefact is published
        when the InOrbit session first connects."""
        await self._poll_once()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="autoxing-poller")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for job in self._detail_jobs.values():
            job.cancel()
        self._detail_jobs.clear()

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            start = time.monotonic()
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Poll cycle error: %s", exc)
            elapsed = time.monotonic() - start
            wait = max(0.0, self._poll_interval - elapsed)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait)
            except TimeoutError:
                pass

    async def _poll_once(self) -> None:
        # Fetch list for online/isTask flags.  This endpoint (/robot/v1.1/list)
        # 500s intermittently on AutoXing's side, so isolate it: a list failure
        # never blocks the per-robot state poll below (which carries taskObj and
        # is what drives mission detection).
        fleet_online: dict[str, dict] = {}
        try:
            robot_list = await self._client.get_robot_list()
            fleet_online = {r["robotId"]: r for r in robot_list if "robotId" in r}
        except Exception as exc:
            logger.warning("Robot list fetch failed (continuing with per-robot state): %s", exc)

        for robot_id, fleet_id in self._robot_id_to_fleet_id.items():
            state = self._robot_states[robot_id]
            list_entry = fleet_online.get(fleet_id)

            if list_entry:
                state.online = bool(list_entry.get("isOnLine", False))
                state.is_task = bool(list_entry.get("isTask", False))

            # Per-robot detailed state, the authoritative source for pose,
            # battery and taskObj.  get_robot_state already swallows errors and
            # returns None, so one robot failing does not abort the cycle.
            raw = await self._client.get_robot_state(fleet_id)
            if raw:
                self._apply_state(state, raw)
                state.api_connected = True
                state.has_data = True
                # Per-robot state proves the robot is reachable; trust it for
                # online even when the fleet list call failed.
                if not list_entry:
                    state.online = True
                self._maybe_fetch_task_detail(state)
            else:
                state.api_connected = False
                if not list_entry:
                    state.online = False

            state.last_update = time.time()

    def _maybe_fetch_task_detail(self, state: RobotState) -> None:
        """Start a background fetch of the task detail if one is due.

        The detail holds the real destination (taskPts), return point (backPt)
        and origin (curPt); taskObj.target is the RETURN point. The fetch runs
        as its own task so a slow or failing call never holds up the poll of
        the other robots, and it is capped and spaced so a task without
        detail does not cost one request per robot per poll.
        """
        task_id = state.task_id
        if not task_id or state._task_ready or state.task_detail_fetched == task_id:
            return
        job = self._detail_jobs.get(task_id)
        if job and not job.done():
            return
        if state._task_detail_attempts >= _TASK_DETAIL_MAX_ATTEMPTS:
            state._task_ready = True
            return
        if self._clock() < state._task_detail_next_at:
            return
        state._task_detail_attempts += 1
        self._detail_jobs[task_id] = asyncio.create_task(
            self._fetch_task_detail(state, task_id), name=f"autoxing-task-detail-{task_id}"
        )

    async def _fetch_task_detail(self, state: RobotState, task_id: str) -> None:
        try:
            detail = await self._client.get_task(task_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Task detail fetch failed task=%s: %s", task_id, exc)
            detail = None
        finally:
            self._detail_jobs.pop(task_id, None)
        if state.task_id != task_id:
            return  # the robot has moved on to another task
        if detail:
            self._apply_task_detail(state, detail)
            state.task_detail_fetched = task_id
            state._task_ready = True
        elif state._task_detail_attempts >= _TASK_DETAIL_MAX_ATTEMPTS:
            logger.info("No task detail for task=%s after %d attempts", task_id, state._task_detail_attempts)
            state._task_ready = True
        else:
            state._task_detail_next_at = self._clock() + _TASK_DETAIL_RETRY_DELAY_S * state._task_detail_attempts

    def _apply_state(self, state: RobotState, raw: dict) -> None:
        x = raw.get("x")
        y = raw.get("y")
        yaw_deg = raw.get("yaw")

        if x is not None:
            state.x = float(x)
        if y is not None:
            state.y = float(y)
        if yaw_deg is not None:
            # API docs say degrees but real values are radians — use directly.
            state.yaw = float(yaw_deg)

        speed = raw.get("speed")
        if speed is not None:
            state.speed = float(speed)

        area_id = raw.get("areaId")
        if area_id:
            state.area_id = area_id

        battery = raw.get("battery")
        if battery is not None:
            state.battery = int(battery)

        state.is_charging = raw.get("isCharging")
        state.is_go_home = raw.get("isGoHome")
        state.is_emergency_stop = raw.get("isEmergencyStop")
        state.is_manual_mode = raw.get("isManualMode")
        state.is_remote_mode = raw.get("isRemoteMode")
        state.has_obstruction = raw.get("hasObstruction")

        loc_quality = raw.get("locQuality")
        if loc_quality is not None:
            state.loc_quality = int(loc_quality)

        errors = raw.get("errors")
        if isinstance(errors, list):
            state.errors = errors

        task_obj = raw.get("taskObj") or {}
        task_id = task_obj.get("taskId")

        # Grace period: Autoxing API drops taskObj for 1-2 cycles mid-task.
        # Wait 3 consecutive absent polls before declaring the task finished to
        # avoid creating duplicate missions in InOrbit.
        _TASK_ABSENT_GRACE = 3

        # The connector closes a task once its terminal mission is published;
        # persist that, so a restart does not reopen it either.
        if state._closed_task_id and state._closed_task_id != state._closed_task_saved:
            self._task_cache.close(state._closed_task_id)
            state._closed_task_saved = state._closed_task_id

        if task_id and (task_id == state._closed_task_id or self._task_cache.is_closed(task_id)):
            # The terminal mission of this task is already published; AutoXing
            # just has not dropped it from taskObj yet. Ignore it.
            task_id = None
            task_obj = {}

        if task_id and task_id != state.task_id:
            # New task_id. Reuse the cached start_ts so the mission's startTs
            # is stable across connector restarts.
            state.begin_task(task_id, self._task_cache.start_ts(task_id))
            # The first sighting may already be terminal (a short task, or a
            # task that finished while the connector was down).
            state.task_is_finish = bool(task_obj.get("isFinish"))
            state.task_is_cancel = bool(task_obj.get("isCancel"))
        elif task_id:
            state._task_absent_polls = 0
            if task_id not in self._task_cache and state.task_start_ts:
                # Started by a connector command: record its start time too.
                self._task_cache.start_ts(task_id, state.task_start_ts)
            # Once terminal, stay terminal: a flapping flag must not reopen the
            # mission, and a cancel sent by the connector is kept even if the
            # API has not reflected it yet.
            state.task_is_finish = bool(state.task_is_finish or task_obj.get("isFinish"))
            state.task_is_cancel = bool(state.task_is_cancel or task_obj.get("isCancel"))
        elif not task_id and state.task_id:
            state._task_absent_polls += 1
            if state._task_absent_polls >= _TASK_ABSENT_GRACE:
                # Task cleared by robot after grace period. task_is_cancel keeps
                # its last known value, so a cancelled task whose taskObj
                # vanished is still reported as Canceled, not Completed.
                state.task_is_finish = True
                state._task_absent_polls = 0
                # Keep task_id so connector can publish final mission_tracking

        # Capture execution metrics while the task is active.  taskObj vanishes
        # once the task ends, so these are the only source for the report.
        if task_id:
            mileage = task_obj.get("mileage")
            if mileage is not None:
                state.task_mileage = float(mileage)
            total_dis = task_obj.get("totalDis")
            if total_dis is not None:
                state.task_total_dis = float(total_dis)
            duration = task_obj.get("duration")
            if duration is not None:
                state.task_duration = int(duration)
            # taskObj.target is the RETURN point, not the destination.
            # task_target_name is populated by _apply_task_detail instead.
            if task_obj.get("taskType") is not None:
                state.task_type = task_obj.get("taskType")

    def _apply_task_detail(self, state: RobotState, detail: dict) -> None:
        """Populate route fields from GET /task/v1.1/{taskId} response.

        taskPts[0] = real destination; backPt = return point; curPt = origin.
        """
        def _f(val):
            try:
                return float(val) if val is not None else None
            except (TypeError, ValueError):
                return None

        pts = detail.get("taskPts") or []
        for pt in pts:
            name = (pt.get("ext") or {}).get("name")
            if name:
                state.task_target_name = name
                state.task_target_x = _f(pt.get("x"))
                state.task_target_y = _f(pt.get("y"))
                state.task_area_id = pt.get("areaId")
                break

        back = detail.get("backPt") or {}
        back_name = (back.get("ext") or {}).get("name")
        if back_name:
            state.task_back_name = back_name
            state.task_back_x = _f(back.get("x"))
            state.task_back_y = _f(back.get("y"))

        cur = detail.get("curPt") or {}
        ox = _f(cur.get("x"))
        oy = _f(cur.get("y"))
        if ox is not None:
            state.task_origin_x = ox
        if oy is not None:
            state.task_origin_y = oy

        if detail.get("buildingId"):
            state.task_building_id = detail["buildingId"]
