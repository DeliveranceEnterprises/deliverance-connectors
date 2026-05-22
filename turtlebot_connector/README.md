# TurtleBot Demo Connector

Demo InOrbit Edge connector for a simulated TurtleBot-style robot.

This is the main README for the connector itself. It explains what the
connector does, how it is configured, which CAC objects it uses, and how the
fake and ROS 2 backends fit into the same connector boundary.

The repo also includes a second README under `docker/ros2_gazebo/README.md`.
That document is narrower in scope: it exists specifically for the
containerized ROS 2 / Gazebo / Nav2 demo workflow used to reproduce and debug
the simulated TurtleBot environment. Both README files coexist on purpose:

- this root README explains the connector as a project
- the `docker/ros2_gazebo` README explains the validated demo environment step
  by step

This connector starts in fake mode by default. It can also be configured to use
a ROS 2 / Gazebo / Nav2 backend for a simulated TurtleBot, while keeping the
same InOrbit Edge connector boundary.

## Why Edge SDK

The InOrbit Edge SDK path is designed for applications that act as an edge-side
proxy between robot or fleet-manager data and InOrbit. The Python
`inorbit-connector` package builds on that model with `FleetConnector`, command
handlers, configuration loading, and telemetry publishing helpers.

This connector follows the same internal pattern as the repo's cloud connectors:

- YAML fleet configuration.
- `FleetConnector` subclass.
- Periodic `_execution_loop`.
- `publish_robot_pose`, `publish_robot_odometry`, and `publish_robot_key_values`.
- InOrbit `RunScript` actions handled through custom command parsing.

## What It Simulates

For each configured robot, the connector publishes:

- `online_status`
- `operational_state`: `idle`, `moving`, `charging`, or `error`
- pose: `x`, `y`, `yaw`
- odometry linear speed
- `battery` and `battery_percent`
- `current_task`
- `current_waypoint`
- `mission_status`
- `mission_tracking`

Each robot must define these waypoints:

- `home`
- `station_1`
- `station_2`
- `charger`

When a waypoint action is received, the fake robot moves progressively toward
the target. It switches from `idle` to `moving`, publishes progress, and returns
to `idle` when it arrives. If the target is `charger`, the simulator switches to
`charging` until the fake battery is nearly full.

## Install

From this connector directory:

```bash
uv sync --extra=dev
```

## Configure Fleet YAML

Copy the example fleet file:

```bash
cp config/fleet.example.yaml config/my_fleet.yaml
```

Edit `config/my_fleet.yaml` and set:

- `account_id`, if required by your InOrbit setup.
- `robot_id`, matching the robot you want to create/use in InOrbit.
- `name`, for display/debugging.
- `initial_pose`.
- `initial_battery`.
- `update_freq`.
- `connector_config.movement_speed_mps`.
- `connector_config.backend`: `fake` or `ros2_gazebo`.
- `connector_config.ros2.*` when using ROS 2 / Gazebo.
- waypoint poses for `home`, `station_1`, `station_2`, and `charger`.

## Configure Environment

Copy the example environment file:

```bash
cp config/example.env config/.env
```

Set the real InOrbit connector API key in `config/.env` or export it in the
shell that starts the connector:

```bash
export INORBIT_API_KEY="your-inorbit-api-key"
```

Do not commit `config/.env`, local YAML files, logs, or generated robot data.

The connector loads `config/.env` and `config/.env.local` from the same
directory as the YAML file passed to `--config`. Shell-exported variables take
precedence over values in those files.

## Run The Connector

```bash
uv run turtlebot-connector --config config/my_fleet.yaml
```

With `backend=fake`, the connector publishes fake pose, odometry, battery,
operational state, and task state for each configured robot.

## Configuration With InOrbit CLI

Use the InOrbit CLI for Configuration as Code: applying, listing, describing,
and deleting configuration objects. Treat it as a configuration tool, not as the
runtime mechanism for sending tasks to the fake robot.

Install or run the CLI according to the official InOrbit docs, then configure:

```bash
export INORBIT_CLI_API_KEY="your-inorbit-cli-api-key"
```

Before applying the files in `cac/`, replace every placeholder scope:

```yaml
scope: "tag/<ACCOUNT_ID>/<TAG_ID>"
```

with the real account/tag or robot scope for your test robots.

Apply configuration:

```bash
inorbit apply -f cac/data_sources.yaml
inorbit apply -f cac/status_definition.yaml
inorbit apply -f cac/actions.yaml
inorbit apply -f cac/robot_camera.yaml
```

Optional placeholder files:

```bash
inorbit apply -f cac/footprint.yaml
```

The repo's current connector CAC pattern does not include ready-made dashboard
or MissionDefinition files. Start by exporting/tuning those from InOrbit Control
if you need them:

```bash
inorbit get config --scope "<scope>" --kind "DashboardDefinition" --yaml > my_dashboards.yaml
```

List or dump applied configuration:

```bash
inorbit get config --scope "<scope>" --kind "ActionDefinition"
inorbit get config --scope "<scope>" --kind "ActionDefinition" --dump
inorbit get config --scope "<scope>" --kind "StatusDefinition" --dump
```

Describe robots/tags while validating scope and visibility:

```bash
inorbit get robots
inorbit describe robots
inorbit get tags
inorbit describe tags
```

Delete configuration only when you are sure you are targeting the right scope:

```bash
inorbit delete config --scope "<scope>" --kind "ActionDefinition" "turtlebot-go-home"
```

The CAC files are coherent with the existing repo style, but they still need to
be validated against the target InOrbit account because scopes, edition support,
and available widgets are account-specific.

For the validated TurtleBot demo setup, camera validation ended up using a
robot-scoped `RobotCamera` with `metadata.id: "0"` so it matched the existing
InOrbit camera wiring for the demo robot. A dedicated
`cac/dashboard_camera_test.yaml` was also used to isolate the problem with a
plain `cameraWidget`.

At the time of writing, the connector can open the ROS camera adapter and
receive frames from `/camera/image_raw`, but neither the `navigation` widget nor
the standalone `cameraWidget` renders the image in InOrbit for this robot. That
points to a remaining issue in InOrbit-side camera consumption or UI/config
rather than in the ROS topic itself.

## Actions From InOrbit Control

After applying `cac/actions.yaml`, operators should use InOrbit Control to run:

- `Go Home`
- `Go Station 1`
- `Go Station 2`
- `Cancel Task`

These are `RunScript` actions. The connector receives them as custom commands
and maps them to the selected backend:

- `go_to` with `waypoint=home`
- `go_to` with `waypoint=station_1`
- `go_to` with `waypoint=station_2`
- `cancel_task`

With `backend=ros2_gazebo`, the `go_to` actions become Nav2
`NavigateToPose` goals and `cancel_task` cancels the active Nav2 goal.

## ROS 2 / Gazebo Phase

The connector now has a backend boundary:

- `fake`: default backend, no ROS dependency, keeps the current deterministic
  simulator behavior.
- `ros2_gazebo`: optional backend that imports ROS 2 packages only when
  selected.

To keep fake mode:

```yaml
connector_config:
  backend: fake
```

To use ROS 2 / Gazebo / Nav2:

```yaml
connector_config:
  backend: ros2_gazebo
  ros2:
    enabled: true
    pose_source: odom
    odom_topic: /odom
    amcl_pose_topic: /amcl_pose
    nav2_action_name: /navigate_to_pose
    cmd_vel_topic: /cmd_vel
    map_frame: map
    odom_frame: odom
    base_frame: base_link
    use_sim_time: true
    camera_enabled: true
    camera_id: "0"
    camera_topic: /camera/image_raw
```

Expected ROS interfaces:

- `/odom`: fallback pose and speed source.
- `/amcl_pose`: optional localization pose source when `pose_source: amcl`.
- `/navigate_to_pose`: Nav2 `NavigateToPose` action server.
- `/cmd_vel`: future teleop output, not implemented yet.
- `/camera/image_raw`: ROS image source bridged to InOrbit camera streaming.

Manual ROS 2 / Gazebo validation flow:

1. Launch Gazebo with TurtleBot.
2. Launch Nav2 and confirm `/navigate_to_pose` is available.
3. Set `backend: ros2_gazebo` in a local fleet YAML.
4. Run `uv run turtlebot-connector --config config/my_fleet.yaml`.
5. Run `Go Station 1` from InOrbit Control.
6. Confirm the TurtleBot moves in Gazebo.
7. Confirm pose and KVs update in InOrbit.
8. Try `Cancel Task` while moving.

If ROS 2 Python packages are not installed, `backend=ros2_gazebo` fails with a
clear message. `backend=fake` does not import or require `rclpy`.

### Single-Container Gazebo Demo

A reproducible first validation environment lives in `docker/ros2_gazebo/`.
It runs Gazebo, TurtleBot3, Nav2, and this connector in one ROS 2 Humble
container to avoid DDS networking issues between host and containers.

Build and start:

```bash
docker compose -f docker/ros2_gazebo/docker-compose.yml build
docker compose -f docker/ros2_gazebo/docker-compose.yml up -d
docker compose -f docker/ros2_gazebo/docker-compose.yml exec turtlebot-ros2-gazebo bash
```

Open the VNC desktop at:

```text
http://localhost:6080
```

Prepare a local ROS config:

```bash
cp config/fleet.ros2.example.yaml config/fleet.ros2.local.yaml
```

Inside the container, use separate terminals:

```bash
# Terminal 1
cd /workspace/turtlebot_connector
docker/ros2_gazebo/scripts/launch_sim.sh

# Terminal 2
cd /workspace/turtlebot_connector
docker/ros2_gazebo/scripts/launch_nav2.sh

# Terminal 3
cd /workspace/turtlebot_connector
docker/ros2_gazebo/scripts/check_ros_graph.sh

# Terminal 4
cd /workspace/turtlebot_connector
docker/ros2_gazebo/scripts/setup_connector_env.sh
docker/ros2_gazebo/scripts/run_connector_ros2.sh config/fleet.ros2.local.yaml
```

The default Nav2 map is:

```text
/opt/ros/humble/share/turtlebot3_navigation2/map/map.yaml
```

The connector uses `frame_id=map`. For a visually correct InOrbit map, register
the same or equivalent map in InOrbit. Until then, the Nav2 action flow can be
valid while the InOrbit map visualization remains approximate.

### Camera Streaming

The installed Edge SDK exposes `RobotSession.register_camera()` and
`publish_camera_frame()`. The ROS 2 backend registers a camera when
`camera_enabled: true`, subscribes to `camera_topic`, converts raw ROS image
frames to JPEG, and streams frames when InOrbit requests the camera module.
Apply [robot_camera.yaml](/home/carlos-fernandez/INORBIT/deliverance-connectors/turtlebot_connector/cac/robot_camera.yaml)
so InOrbit has a `RobotCamera` with `metadata.id: camera` aligned with the
connector's `camera_id`.

The Docker demo uses TurtleBot3 `waffle_pi` by default because it publishes
`/camera/image_raw` in Gazebo. The lighter `burger` model does not publish a
camera image.

### Teleop / Joystick Investigation

The installed Edge SDK exposes command callbacks for custom commands, initial
pose, and navigation goals. I did not find a clear joystick/cmd_vel callback in
`inorbit-connector-python` or the installed Edge SDK. The InOrbit docs mention
teleoperation features, but this connector currently keeps the validated control
flow to actions: `Go Home`, `Go Station 1`, `Go Station 2`, and `Cancel Task`.

Mapping the joystick panel to `/cmd_vel` is therefore pending confirmation of
the supported Edge SDK mechanism for teleop commands.

## API Or Mission Dispatch

The connector currently implements direct action handling, not a full
MissionDefinition catalog.

If your InOrbit account supports MissionDefinitions or action execution through
the REST API, the intended flow is:

1. Configure `ActionDefinition` objects with the CLI.
2. Optionally configure MissionDefinitions that dispatch those actions.
3. Dispatch through InOrbit Control, MissionDefinition support, or the REST API.
4. Let this connector receive the action/custom command and update the fake task.

Do not treat the CLI as the runtime task dispatcher unless the official CLI
documentation for your installed version explicitly supports that operation.

## Development

Run tests and linting:

```bash
uv run pytest
uv run ruff check
```

## Next Phase

Validate teleop/RCP support and, if the Edge SDK exposes a supported runtime
callback for joystick commands, map it to ROS `/cmd_vel`.

## References

- InOrbit Developer Docs: https://developer.inorbit.ai/docs
- InOrbit Template Connector: https://github.com/inorbit-ai/template-connector
- InOrbit Connector Cookiecutter: https://github.com/inorbit-ai/inorbit-connector-cookiecutter
- InOrbit Connector Python: https://github.com/inorbit-ai/inorbit-connector-python
- InOrbit Robot Connectors: https://github.com/inorbit-ai/inorbit-robot-connectors
