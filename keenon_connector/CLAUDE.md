# Keenon Connector — Context for Claude

See `../CLAUDE.md` for account-level context, tag IDs, global dashboard IDs,
CAC patterns and CLI reference.

## Robot
- Tag: `Keenon`, tag ID: `DJbJhivzeMvXDj8z`
- Robots: `keenon-krtx24098y0005` (and others)
- SDK: `2.0.1.edgesdk_py`
- Location: RS EU (`hSTlpyR8qtgjSfcT`), Espaitec

## Key-values published
| Key | Type | Notes |
|---|---|---|
| `battery` | float 0–1 | Main robot battery |
| `battery_percent` | float | Redundant (same value as battery here) |
| `keenon_battery` | float 0–1 | Secondary/cleaning module battery (stale) |
| `api_connected` | bool | API reachability |
| `charge_status` | string | "charging", "discharging", etc. |
| `can_be_called` | bool | Robot available for tasks |
| `current_scene` | string | Active map/scene name |
| `task_no` | string | Active task UUID |
| `task_status` | string | "completed", "executing", etc. |
| `robot_model` | string | e.g. "T10" |
| `app_version` | string | Keenon firmware version |
| `online_type` | string | Network type |
| `elevator_status` | bool | In elevator |
| `clean_main_state` | string | Cleaning mode (only if cleaning module present) |
| `clean_sub_state` | string | Cleaning sub-state |
| `clean_faulting` | bool | Cleaning fault active |
| `clean_emergency_stop` | bool | Cleaning e-stop active |
| `clean_water_tank` | float | Clean water level (only if cleaning module) |
| `clean_bilge_tank` | float | Waste water level (only if cleaning module) |
| `mission_tracking` | JSON | Standard mission tracking shape |

## CRITICAL: Do NOT change keenon-battery DataSource
`keenon-battery` has `scale: 100` + `unit: '%'` + `key: battery` (0–1). This
combination should give 2000% but shows correctly. Reason unknown — possibly
internal InOrbit resolution. For custom Vitals widgets, use `xlXPmDo3Z3GMwSTM`
directly (same as the Summary section) instead of `keenon-battery`.

## CRITICAL: Do NOT overwrite Preferences
The Keenon `Preferences` CAC was already correctly configured before our work.
It controls the Navigation control widget LOCK dropdown. Do not apply a new
Preferences file unless you are certain of what it currently contains.

## Cleaning module fields
The `clean_*` keys are only published when the robot has the cleaning module
attached and active. They appear in the Status widget but may show `0`/`--`
when the module is not present. This is expected — leave the DataSources and
Status entries in place for when the module is used.

## Task report (from task/info)
The report comes from `GET /api/open/scene/v1/robot/task/info?taskNo=` (the API
doc says POST but the server only accepts GET). It returns `taskType` and
`subTaskInfoList[].taskDistance`; the connector publishes `task_mileage`
(Σ distances), `task_mode` (`taskType`), `point_name`, `task_state` in
`mission_tracking.data` for the backend to fold into `tasks.report`. Fetch is
retried with spacing (not 5 retries in 5 s).

Do NOT use `GET /api/open/data/v1/store/task/food/list` for InOrbit-dispatched
tasks — it returns `total=0` for remote "call to point" tasks (only logs
robot-initiated food deliveries). Keenon allows ONE session per `client_id`: do
not run a probe client while the connector is up (causes 401s + the connector's
500 "connection prematurely closed"). The client now resets the HTTP session
after repeated 500s to recover. `Available: false` while charging means the robot
rejects remote tasks (`614920 无可用机器人`) — not a connector bug.

## CAC files
`dashboard_navigation.yaml` is a full copy of `d-Navigation-Z8YZAb` including
Allybot and Autoxing sections. Keep it in sync with the other connectors'
`dashboard_navigation.yaml` files.
The global Robot dashboard `d-Robot-lLybVa` is maintained in
`allybot_connector/cac/dashboard_robot.yaml`.
