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

## DataSource scale decisions
- `autoxing-battery`: no scale (publishes 0–1)
- `autoxing-loc-quality`: `scale: 0.01` + `unit: '%'` (publishes 0–100)

## Known issues
- Robot was offline for 5+ days during CAC setup — gauges showed `--`. Normal when robot is off.
- `task_is_cancel`, `task_is_finish`, `is_remote_mode`, `is_go_home` show `0`/`1` instead of `false`/`true` for old historical data — InOrbit stored them before `fieldType: boolean` was applied. Fresh data shows correctly.
- `errors` publishes as a JSON array string e.g. `"[501]"` — shown as text in Status.

## CAC files
All files in `cac/` are Autoxing-specific except `dashboard_navigation.yaml`
which also contains Allybot and Keenon sections (full spec of `d-Navigation-Z8YZAb`).
The global Robot dashboard `d-Robot-lLybVa` is maintained in
`allybot_connector/cac/dashboard_robot.yaml`.
