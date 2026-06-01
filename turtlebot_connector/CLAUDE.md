# TurtleBot Connector — Context for Claude

## Project overview
Edge connector for InOrbit that integrates a TurtleBot3 waffle_pi simulated in Gazebo with the InOrbit platform. Uses the InOrbit Edge SDK (`inorbit-edge 2.1.0`) and `inorbit-connector` base framework.

## Repo structure
- `turtlebot_connector/src/connector.py` — main FleetConnector implementation
- `turtlebot_connector/src/backends/ros2_gazebo.py` — ROS2/Nav2 backend (pose, navigation, map subscription)
- `turtlebot_connector/src/backends/ros2_camera.py` — ROS2 camera adapter (subscribes to `/camera/image_raw`, converts to JPEG)
- `turtlebot_connector/src/backends/base.py` — base backend interface
- `turtlebot_connector/src/backends/simulator.py` — fake backend for testing without ROS
- `config/fleet.ros2.office.local.yaml` — fleet config for the office demo (ROS2/Gazebo backend)
- `cac/robot_camera.yaml` — InOrbit CAC for the TurtleBot camera
- `cac/actions.yaml` — InOrbit CAC for navigation actions
- `office_demo/maps/office_scanned.pgm` + `office_scanned.yaml` — SLAM-scanned map of the Gazebo office world
- `office_demo/worlds/office_world.world` — Gazebo world file
- `docker/ros2_gazebo/` — Dockerfile and scripts for the ROS2/Gazebo container

## Stack
- Python 3.10, ROS2 Humble, Gazebo Classic
- TurtleBot3 waffle_pi model (has camera + LiDAR)
- Nav2 for navigation, slam_toolbox for map scanning
- InOrbit Edge SDK for MQTT publishing
- Virtual env: `.venv-ros2/` (always use this, not system Python)

## How to run (inside the Docker container VNC at http://localhost:6080)
1. Terminal 1: `WORLD_FILE=/workspace/turtlebot_connector/office_demo/worlds/office_world.world /workspace/turtlebot_connector/docker/ros2_gazebo/scripts/launch_sim.sh`
2. Terminal 2: `/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/launch_nav2.sh /workspace/turtlebot_connector/office_demo/maps/office_scanned.yaml`
3. Terminal 3: `/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/set_initial_pose.sh`
4. Terminal 4: `/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/run_connector_ros2.sh`

To rescan the map (only needed once): use `launch_slam.sh` instead of `launch_nav2.sh`, teleop the robot, then save with `ros2 run nav2_map_server map_saver_cli -f /tmp/scanned_map/office_scanned`.

## InOrbit account
- Account ID: `config/.env` → `INORBIT_ACCOUNT_ID` — not committed
- Robot ID: `config/.env` → `INORBIT_ROBOT_ID` (default: `turtlebot-demo-01`) — not committed
- Connector API key: `config/.env` → `INORBIT_API_KEY` — not committed
- CLI API key: `~/INORBIT/.env-inorbit` → `INORBIT_CLI_API_KEY` — not committed
- MQTT broker: configured automatically by the Edge SDK from the API key

## Key decisions and lessons learned

### Camera — rosTopic must be the camera_id, not the ROS topic
For Edge SDK connectors (`2.1.0.edgesdk_py`), the `rosTopic` field in the `RobotCamera` CAC must be set to the `camera_id` (e.g. `"0"`), NOT the actual ROS topic name. The connector handles the ROS subscription internally and publishes frames via MQTT (`ros/camera2`). InOrbit uses `rosTopic` to identify which channel to read from — for Edge SDK it expects the camera_id.

For native ROS2 agents (`4.x.x.ros2`), `rosTopic` should be the actual ROS topic (e.g. `raspicam_node/image/compressed`).

### Camera settings (production reference)
From other robots in the account: `width: 380`, `height: 240`, `rate: 1`, `quality: 30`, `outputEncoding: rgb8`. For Gazebo demo the same values apply. For real cameras with good network: `quality: 75`, `rate: 2`.

### Map
The connector implements `fetch_robot_map()` which subscribes to `/map` (OccupancyGrid with transient-local QoS), converts to PNG and uploads to InOrbit. Nav2 must be running and publishing `/map` before the connector starts, otherwise the map fetch fails silently (only retries on restart). The scanned map is `office_scanned.yaml` — do NOT use `office_map.yaml` which is a pixel-converted PDF floorplan without real scan data.

### Action scopes
`ActionDefinition` CAC must use `scope: tag/<ACCOUNT_ID>/<TURTLEBOT_TAG_ID>` — NOT `robot/...`. The `withControlWidget: true` on the navigation section filters actions by the robot's tags, not by robot ID. Using `robot/` scope causes the control widget to ignore those actions and show all account-level ones as broken icons instead. To delete and reapply: `inorbit delete config --kind ActionDefinition --scope robot/<ACCOUNT_ID>/<ROBOT_ID> <id>`.

### CAC apply
Use `yes | inorbit apply -f <file>` to auto-confirm. Source `/home/carlos-fernandez/INORBIT/.env-inorbit` first.

CAC files in the repo use placeholders (`<ACCOUNT_ID>`, `<TURTLEBOT_TAG_ID>`). Substitute them before applying:
```bash
sed -e "s/<ACCOUNT_ID>/${INORBIT_ACCOUNT_ID}/g" \
    -e "s/<TURTLEBOT_TAG_ID>/QJoR03aXlEhZkD6N/g" \
    cac/foo.yaml > /tmp/foo_applied.yaml
yes | inorbit apply -f /tmp/foo_applied.yaml
```
`inorbit apply -f -` does not accept stdin; always pipe via a real file.

### Preferences — navigationWidget action whitelist
The control widget on the Navigation tab (LOCK + dropdown) by default shows every account-level action with `widgets: ["navigation"]`. To restrict it to TurtleBot's own actions, apply a `Preferences` CAC with `navigationWidget.actions: [...]` at tag scope. Without this, broken icons from other robots' actions appear.

```yaml
kind: Preferences
metadata: {id: all, scope: tag/<ACCOUNT_ID>/<TURTLEBOT_TAG_ID>}
spec:
  navigationWidget:
    actions: [turtlebot-go-home, turtlebot-go-station-1, ...]
    panels: {teleop: false, ...}   # optional, hides built-in panels
```

### Gauge widget rule for `unit: '%'`
InOrbit's gauge widget expects a value in **0..1** when `unit: '%'` is set. It then multiplies by 100 internally. So:

| Connector publishes | DataSource spec | Result on gauge |
|---|---|---|
| `0.20` | `unit: '%'`, no scale | ✅ 20% |
| `20` | `unit: '%'`, `scale: 0.01` | ✅ 20% |
| `20` | `unit: '%'`, `scale: 1` (or none) | ❌ 2000% |
| `0.20` | `unit: '%'`, `scale: 100` | ❌ 2000% |

The cleaning demo tanks publish `72`/`35`/`58` (0–100) and use `scale: 0.01`. The custom `turtlebot-battery-display` data source (only used by the cleaning dashboard's Vitals) publishes `battery` raw (0–1) and uses no scale. Both produce correct gauges.

The catch: `StatusDefinition.rules` evaluate the **post-scale** value, so:
- `unit: '%'` + raw 0–1, no scale → thresholds in 0–1 (e.g. `0.15`, `0.30`)
- `unit: '%'` + raw 0–100, `scale: 0.01` → thresholds in 0–1 too (post-scale)
- raw 0–1, `scale: 100`, `unit: '%'` (the bugged combo) → thresholds in 0–100 (broken gauge but working status — that's how the `turtlebot-battery` + low-battery status pair survived; the gauge was the only thing broken)

### Two DataSources for the same key when display and status disagree
If a data source already exists for a key and is wired to a `StatusDefinition` (so its thresholds are tied to a particular scale), and you also want a clean gauge, create a **second** data source with a different id and the right scale for display. The cleaning dashboard does this: `turtlebot-battery` keeps `scale: 100` + thresholds in 0–100 for the incident pipeline; `turtlebot-battery-display` uses raw `battery` + no scale for the Vitals gauge.

### DataSourceDefinition — battery and the `xlXPmDo3Z3GMwSTM` system id
InOrbit's default Vitals widget looks up battery via the system-level id `xlXPmDo3Z3GMwSTM`. Defining a DataSource with that id at a tag scope **breaks the gauge** — it ends up multiplied by 100 a second time and shows 2000% for a 20% battery. The right pattern (validated against Keenon/Allybot/Autoxing) is:
- Custom id like `turtlebot-battery` (not the system id).
- `key: battery` (the connector publishes 0.0–1.0), `scale: 100`, `unit: '%'`.
- Reference that custom id from the custom dashboard's Vitals widget via `dataSources[].id: turtlebot-battery`.
- The default `Robot` dashboard resolves battery automatically without any extra config.

### StatusDefinition / IncidentDefinition link by id
Both kinds link to a DataSource implicitly by id matching, not by an explicit `source` or `statusId` field. So a `StatusDefinition` with `id: turtlebot-battery` evaluates the data source named `turtlebot-battery`. An `IncidentDefinition` with `id: turtlebot-battery` reacts to the status of that name. Keep all three ids aligned.

Threshold scale matters: `StatusDefinition.rules.params` evaluate the **post-scale** data source value. With `battery` × `scale: 100`, thresholds must be in 0–100 (e.g. WARNING < 30, ERROR < 15), not 0.30 / 0.15.

### Dashboard widget gotchas
- `actionsWidget` uses `actionIds: [...]` to whitelist actions; it does not auto-discover them from the tag scope.
- `actions[].widgets: ["robot"]` is **not valid** — only `["navigation"]` is. Don't try to scope an action to the Robot tab via a `widgets` field.
- `fleetStatus.config.statuses` items must be objects (`- id: foo`), not bare strings.
- `withControlWidget: true` enables the LOCK+ACTIONS toolbar on a `navigation`-scope section. Combined with the action group's name, the toolbar shows the group as a sub-menu — that's expected, also true on Keenon.

### MissionDefinition + InOrbit Expression Language
- Missions live at `account` scope; the `selector.robot.tagIds: [...]` is how a mission targets robots.
- Steps support `runAction`, `waypoint` (requires a real SpatialAnnotation in the map), `waitUntil` with an `expression`, and `waitEvent`.
- `waypoint:` cannot be used with this connector's `home`/`station_1`/`station_2` names because they live only in the local fleet YAML, not as SpatialAnnotations in InOrbit. Use `runAction` chaining instead.
- **Race-condition trap:** the expression engine does **not** see transient key-values (`current_waypoint`, `task_label`) reliably — they come back as `None` if not "fresh", even when the Key Values UI panel still shows the last value. The persistent JSON key-value `mission_tracking` **is** visible. The reliable pattern to chain `runAction` steps:
  ```yaml
  - label: Wait for arrival at station_1
    timeoutSecs: 180
    waitUntil:
      expression: (t = getValue('mission_tracking')); t.data.waypoint == 'station_1' and t.state == 'Completed'
  ```
- Validate expressions live against the robot before applying:
  ```bash
  inorbit expr eval turtlebot-demo-01 "(t = getValue('mission_tracking')); t.state"
  ```
- `not getValue('key')` returns True even when the value exists. Always use explicit `== ''` / `!= ''` (and remember `None != ''` is True).

### InOrbit CLI cheatsheet
```bash
# discovery
inorbit list kinds                              # all valid --kind values
inorbit get robots                              # robot id ↔ name table
inorbit get tags                                # tag id ↔ name table

# read configuration
inorbit get config --kind <Kind> --summary
inorbit get config --kind <Kind> --scope <scope> --yaml
inorbit get config --kind <Kind> <id> --scope <scope> --yaml
inorbit get config --kind <Kind> --yaml --all   # includes hidden/system defaults

# write / delete
yes | inorbit apply -f /tmp/foo.yaml
inorbit delete config --kind <Kind> --scope <scope> <id>

# validate expressions against a real robot
inorbit expr eval <robot_id> "<expression>"
```

### Mission verification — useful key-values
The connector publishes:
- `mission_status`: `"Idle"` / `"Mission"` / `"Charging"` / `"Error"` (visible to the engine; reliable for high-level state).
- `mission_tracking`: full JSON with `state`, `data.waypoint`, `completedPercent`, `endTs` (the right hook for chaining mission steps).
- `current_task`, `current_waypoint`, `task_label`, `task_state`: transient, **not reliably visible** to the expression engine — useful for the Key Values panel only.

### KpiDefinition — built-ins cover TurtleBot, no custom needed
The KPIs visible in the Missions tab (Mission success rate, Mission frequency, Avg/Max mission duration, Avg incidents per mission, Missions count, Robots count) **are not hardcoded** — they are real `KpiDefinition` CACs at `account/<ACCOUNT_ID>` scope that ship with the account. List them with `inorbit get config --kind KpiDefinition --summary`.

Shape:
```yaml
kind: KpiDefinition
metadata: {id: <id>, scope: account/<ACCOUNT_ID>}
spec:
  label: <human label>
  objectType: mission | incident | robot
  field: <path>         # id, data.isSuccessNum, data.duration, data.incidentsCount
  aggregation: AVG | COUNT | COUNT_DISTINCT | SUM
  secondAggregation: AVG          # optional, used by "frequency"-style KPIs
  intervalMinutes: 1440           # optional
  unit: '%' | 'ms' | '/day/robot' | ''
```

Useful `field` values populated by the `MissionTracking` pipeline:
- `data.isSuccessNum` — 1 if `defaultStatus: OK`, 0 if `error`. Drives `mission-success-rate`.
- `data.duration` — endTs − startTs in ms.
- `data.incidentsCount` — number of incidents during the mission.
- `id` — used with `COUNT` / `COUNT_DISTINCT` for mission counters.

**No filter expressivity in the spec.** A KPI computes over **all** objects in its scope. The per-robot view in the Missions tab is filtered by the URL (`robotId=...`), not by the KPI definition. There's no way to write a KPI like "success rate of mission-id `turtlebot-demo-route` only" — the spec doesn't have a `filter` / `where` field in the examples observed.

**Why TurtleBot does not need custom KPIs:**
- The 5 built-in KPIs already cover everything the Missions tab shows.
- They filter by robot automatically via the UI, so they're already TurtleBot-specific when you pick the robot.
- Any new account-scope KPI we add would pollute the account view for every robot.
- Mission-tracking-derived fields (isSuccessNum, duration, incidentsCount) are populated correctly by the explicit `MissionTracking` we applied, so the built-in KPIs are accurate without further config.

Custom KPIs would only be worth adding when:
- A field that's not in the standard mission shape needs surfacing (then it requires data-source plumbing).
- The team accepts the KPI as account-wide (e.g. "Low Battery Incidents" counting all robots, not just TurtleBot).

For now, recorded in this CLAUDE.md but not applied.

### Action types observed on this account
- `RunScript` (filename → connector custom command, e.g. `go_to`, `cancel_task`).
- `DispatchMission` (`arguments.missionDefinitionId` → launches a MissionDefinition).
- `Url` (opens a URL in a new tab; can use `{{robotName}}`, `{{dataSourceId}}` tokens).
- `PublishToTopic` (publishes a key-value).
No `InOrbitPage` was found — use `Url` to open a specific InOrbit dashboard.
