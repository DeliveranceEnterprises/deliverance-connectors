# Autoxing Connector — Context for Claude

See `../CLAUDE.md` for account-level context, tag IDs, global dashboard IDs,
CAC patterns and CLI reference.

## Robot
- Tag: `Autoxing`, tag ID: `8gMbOLofiZYK0uKx`
- Robots: `autoxing-chassis-1`
- SDK: `2.0.1.edgesdk_py`
- Location: RS EU (`hSTlpyR8qtgjSfcT`), Espaitec

## Key-values published
| Key | Type | Notes |
|---|---|---|
| `battery` | float 0–1 | Main battery |
| `battery_percent` | int 0–100 | Redundant with battery |
| `loc_quality` | int 0–100 | Localization quality % |
| `api_connected` | bool | API reachability |
| `is_charging` | bool | Currently charging |
| `is_emergency_stop` | bool | E-stop active |
| `has_obstruction` | bool | Obstacle detected |
| `is_manual_mode` | bool | Manual control active |
| `is_remote_mode` | bool | Remote mode active |
| `is_go_home` | bool | Returning to charger |
| `current_area_name` | string | Current zone/area |
| `errors` | string | Error codes e.g. `"[501]"` |
| `task_id` | string | Active task UUID |
| `task_is_cancel` | bool | Task was cancelled |
| `task_is_finish` | bool | Task finished |
| `mission_tracking` | JSON | Standard mission tracking shape |

## Display name + mission group
- `config/my_fleet.local.yaml` sets a per-robot `name` (optional field added to
  `AutoxingRobotConfig`); the connector overrides the framework's
  `robot_name=robot_id` via `_instrument_robot_session_if_needed`.
- `mission_tracking.data.group` is set to `"Delivery"` so tasks group under that
  type in InOrbit and in `tasks.type`.

## Task report (from taskObj)
AutoXing has NO task-report endpoint — `GET /task/v1.1/{id}` returns the task
DEFINITION, not execution metrics. The only metrics live in the robot state
`taskObj` (`mileage`, `totalDis`, `duration`, `target.name`, `taskType`) and
VANISH when the task finishes. `data_poller._apply_state` captures them into the
`RobotState` while the task runs; the connector publishes `mileage`,
`total_distance`, `duration_s`, `target_name` in `mission_tracking.data`.
`missionId` is suffixed with `startTs` so each run is a distinct mission.

Dealer-screen tasks DO appear in `taskObj`, so they are captured the same way;
their labels are the robot's UUIDs (nothing we can do — not InOrbit-dispatched).

## data_poller resilience (BUG fixed 2026-06-23)
`_poll_once` called `get_robot_list()` first; that endpoint
(`POST /robot/v1.1/list`) 500s intermittently and the exception aborted the whole
cycle — so the per-robot state poll (carrying `taskObj`) never ran and tasks went
undetected (`mission_status: Idle` with an active task). The list call is now
isolated in its own try/except so per-robot state always polls. Run under
`tools/supervise.sh` for the cases where the whole process dies.

## DataSource scale decisions
- `autoxing-battery`: no scale (publishes 0–1)
- `autoxing-loc-quality`: `scale: 0.01` + `unit: '%'` (publishes 0–100)

## Startup pose artefact fix (2026-06-24)
InOrbit's SDK publishes the robot pose immediately when the MQTT session opens,
before the DataPoller has fetched real coordinates — resulting in a spurious
(0, 0) point at the start of every Time Capsule recording.

Fix: two-part guard:
1. `RobotState.has_data` — starts `False`; set `True` after the first successful
   `get_robot_state` response. `_publish_robot_data` returns immediately if
   `has_data` is `False`.
2. `DataPoller.poll_once()` called synchronously in `_connect()` before
   `self._data_poller.start()`. This pre-populates real state (pose, area_id)
   before the InOrbit session connects, so the SDK's first publish already has
   real coordinates.

## Map overlay in Time Capsule
The connector publishes pose with `frame_id=state.area_id` (the Autoxing area ID
returned by the API). InOrbit calls `fetch_robot_map(robot_id, frame_id)` asking
the connector to serve the map image and origin/resolution for that frame.

Configure `area_map_config` in `my_fleet.local.yaml` keyed by the Autoxing area
ID. Use the origin values from InOrbit's Location Editor (origin_x/origin_y in
metres, resolution in m/px). Two IDs are listed in case the robot's `areaId`
changes between sessions:
```yaml
area_map_config:
  "6a3108ffca05c3a002825204":   # current area (robot's active areaId)
    origin_x: -31.82881017600105
    origin_y: -8.485818887977175
    resolution: 0.05000000074505806
  "68557cba05b448a565140d9a":   # alternate/fallback area
    origin_x: -31.82881017600105
    origin_y: -8.485818887977175
    resolution: 0.05000000074505806
```
In InOrbit Location Editor, associate the robot with the "DAG" map and enter the
same origin/resolution. The two IDs that appear as raw UUIDs in the dropdown
(`6a3108ffca05c3a002825204`, `6a315bb8e9846b52a637c478`) are Autoxing-derived
frame IDs — not human-created InOrbit maps. The connector log line
`"Map X not in configuration"` tells you which area_id InOrbit is requesting.

## Known issues
- Robot was offline for 5+ days during CAC setup — gauges showed `--`. Normal when robot is off.
- `task_is_cancel`, `task_is_finish`, `is_remote_mode`, `is_go_home` show `0`/`1` instead of `false`/`true` for old historical data — InOrbit stored them before `fieldType: boolean` was applied. Fresh data shows correctly.
- `errors` publishes as a JSON array string e.g. `"[501]"` — shown as text in Status.

## CAC files
All files in `cac/` are Autoxing-specific except `dashboard_navigation.yaml`
which also contains Allybot and Keenon sections (full spec of `d-Navigation-Z8YZAb`).
The global Robot dashboard `d-Robot-lLybVa` is maintained in
`allybot_connector/cac/dashboard_robot.yaml`.
