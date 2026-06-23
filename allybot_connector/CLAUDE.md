# Allybot Connector — Context for Claude

See `../CLAUDE.md` for account-level context, tag IDs, global dashboard IDs,
CAC patterns and CLI reference.

## Robot
- Tag: `Allybot`, tag ID: `StdZGa32GmBLReFr`
- Robots: `allybot-cleaner-1`, `allybot-cleaner-2`
- SDK: `2.0.1.edgesdk_py`
- Location: RS EU (`hSTlpyR8qtgjSfcT`), Espaitec

## Key-values published
| Key | Type | Notes |
|---|---|---|
| `battery` | float 0–1 | Main battery |
| `fresh_water` | float 0–100 | Clean water tank % |
| `sewage_water` | float 0–100 | Waste water tank % |
| `task_percentage` | float 0–100 | Task progress % |
| `speed` | float m/s | Linear speed |
| `ws_connected` | bool | WebSocket to robot API |
| `work_status` | string | "Idle", "Charging", etc. |
| `task_name` | string | Name of active task |
| `have_task_running` | bool | Reliable task indicator (task_status is NOT reliable — stays stale) |
| `map_name` | string | Active map name |
| `api_connected` | bool | API reachability |
| `mission_tracking` | JSON | Standard mission tracking shape |

## Task report (partial cleaningStats)
No task-report endpoint is reachable with the fleet credentials. The connector
builds a PARTIAL report from the App WS and publishes it in
`mission_tracking.data`: `plan_area` (`workingScope`), `cleaned_area` (`area`),
`progress_percent` (`percentage`), `fresh_water`, `sewage_water`, `task_mode`
(from `data.clean`). The backend mapper rebuilds these into a nested
`cleaningStats` object matching the production shape.

Production's full report (electricConsumption, waterConsumption, effect, overArea,
leftArea, coverage `imageBinary`) needs the robot's cleaning-report endpoint,
which current credentials cannot reach — left as TODO (ask for the Gausium/robot
REST creds or the endpoint spec).

`missionId` is suffixed with `startTs` (`task_id_startTs`); without it InOrbit
deduped on the constant `task_id` and overwrote the same 2 entries instead of
adding a new mission per cleaning run.

## DataSource scale decisions
- `allybot-battery`: no scale (publishes 0–1)
- `allybot-fresh-water`, `allybot-sewage-water`, `allybot-task-percentage`: `scale: 0.01` (publishes 0–100)

## Known issues
- `task_status` goes stale — not shown in Status widget, use `have_task_running` instead.
- Teleop not implemented — connector does not handle `ros/teleop/step` or `ros/nav/goal_path`.
- Action execution fails with "LOGGED IN SOMEWHERE ELSE" when another session (e.g. Raspberry Pi connector) holds the WebSocket. Not a CAC issue — it's the robot API rejecting a second connection.

## Charging station
`allybot-cs` SpatialAnnotation in RS EU location: `x: 4.049, y: 0.035, theta: -1.614`
Coordinates captured while robot was physically docked.

## CAC files
- `dashboard_robot.yaml` — owns the global `d-Robot-lLybVa` dashboard for ALL robots (Allybot, Autoxing, Keenon, TurtleBot). Edit here when adding new robot sections.
- `dashboard_navigation.yaml` — global `d-Navigation-Z8YZAb` with Allybot + Autoxing + Keenon sections.
- All other files are Allybot-specific.
