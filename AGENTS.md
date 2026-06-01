# AGENTS.md - Deliverance InOrbit Connectors

## 1. Project Context

This repository contains Deliverance-maintained connectors for publishing robot telemetry into InOrbit.

Main connectors:

- `allybot_connector/`
- `keenon_connector/`
- `autoxing_connector/`
- `turtlebot_connector/`

The shared read-only diagnostics and inventory tool lives in:

```text
tools/robot_diagnostics/
```

The goal of the diagnostics work is to compare:

- local connector configuration,
- manufacturer API data,
- InOrbit-visible robot state.

The initial validation target is data flow only:

```text
manufacturer API -> connector/diagnostics -> InOrbit
```

Do not treat this work as permission to control robots.

The repo also contains a simulated TurtleBot demo connector used for ROS 2 /
Gazebo / Nav2 validation against InOrbit. That workflow is different from the
read-only diagnostics tool and should be treated as a contained simulation
environment, not as permission to affect real robots.

## 2. Current Branch / Workflow

Current diagnostics work should happen on:

```bash
feature/inorbit-robot-diagnostics
```

Rules:

- Do not work directly on `main`.
- Do not commit without explicit user confirmation.
- Do not push without explicit user confirmation.
- Before commit/push-related work, run `git branch --show-current` and `git status --short`.

## 3. Safety Rules

Robots may be real or production-adjacent. Prioritize read-only inspection.

Never execute control actions unless the user explicitly authorizes the exact action and confirms a safe test window:

```text
start_task
pause_task
resume_task
stop_task
navigation commands
robot movement commands
mission start/cancel commands
```

Also forbidden without explicit authorization:

```text
inorbit apply
inorbit delete
map edits
location edits
zone edits
route edits
waypoint edits
```

Special case: the TurtleBot ROS 2 / Gazebo demo under `turtlebot_connector/`
operates in a local simulation environment. For that demo only:

- launching Gazebo/Nav2/connector processes is allowed when the user is
  explicitly working on the demo
- `inorbit apply` may be used only for clearly scoped demo CAC validation with
  explicit user approval
- the same command remains sensitive for real robots, shared maps, production
  dashboards, or non-demo accounts

Allowed by default:

```text
read local YAML/env files
inspect source code and docs
run unit tests
run static checks
query read-only manufacturer status endpoints
sample WebSocket telemetry without sending commands
read InOrbit with get/describe commands
export sanitized inventories under outputs/
```

## 4. Secrets And Public Repo

This repo is public or may become public.

Do not commit or paste:

```text
.env files
local YAML files with real IDs/secrets
outputs/
real generated inventories
connector logs
raw API responses containing tokens
API keys
passwords
tokens
full fleet_robot_id values
WebSocket URLs containing session tokens
real robot data dumps
```

Mask or sanitize:

```text
fleet IDs
tokens
API keys
passwords
WebSocket URLs
exception messages that may include URLs or headers
```

Expected ignored patterns include:

```text
outputs/
*.log
*.log.*
config/.env
config/.env.local
config/my_fleet.yaml
config/my_fleet.local.yaml
```

## 5. Environment Model

`~/INORBIT` is the general workspace. It is not the repo.

The repo root is:

```text
~/INORBIT/deliverance-connectors
```

The InOrbit CLI environment is separate:

```text
~/INORBIT/.venv-inorbit
~/INORBIT/.env-inorbit
```

Use it only for read-only CLI commands such as:

```bash
inorbit get robots
inorbit describe robots
```

The InOrbit CLI commonly uses `INORBIT_CLI_API_KEY`.

Connectors use their own `uv` environments inside each package:

```text
allybot_connector/.venv
keenon_connector/.venv
autoxing_connector/.venv
```

The shared diagnostics tool has its own `pyproject.toml` and `uv` environment:

```text
tools/robot_diagnostics/
```

Do not mix the CLI environment with connector or diagnostics environments.

For the TurtleBot demo specifically:

- connector runtime is usually inside the ROS 2 / Gazebo container
- the InOrbit CLI still runs from `~/INORBIT/.venv-inorbit`
- do not confuse local demo config with production-like connector configs

## 6. Diagnostics Tool

Location:

```text
tools/robot_diagnostics/
```

The tool is read-only. It must not send robot commands.

Responsibilities:

- load local connector YAML/env configuration,
- query safe read-only manufacturer data where implemented,
- query InOrbit with read-only CLI commands,
- generate Markdown/CSV/JSON inventory under `outputs/`,
- support providers through adapters under `robot_diagnostics/providers/`.

Common validation states:

```text
yaml_only
pending_credentials
source_partial
source_ok
inorbit_ok
full_flow_ok
failed
```

Meanings:

```text
yaml_only            configured locally, no live source/InOrbit signal confirmed
pending_credentials  required credentials or IDs are missing/placeholders
source_partial       at least one read-only manufacturer signal was found
source_ok            manufacturer status and map checks succeeded
inorbit_ok           InOrbit sees the robot online
full_flow_ok         source checks succeeded and InOrbit sees the robot online
failed               a required read-only step failed
```

Useful safe commands from `tools/robot_diagnostics/`:

```bash
uv sync
uv run robot-diagnostics --provider allybot --all --ws-seconds 10
uv run robot-diagnostics --provider all --all --include-inorbit-related
uv run robot-diagnostics --provider all --all --markdown ../../outputs/robot_inventory.md
uv run python -m unittest discover -s tests
```

Use `--all` when inventorying every robot configured in local YAML files.

## 7. Known Current Robot Status

Do not add full fleet IDs, tokens, IP addresses, or real inventory dumps here.

### Allybot

`allybot-cleaner-1` has been validated in read-only mode against both Allybot and InOrbit:

```text
Manufacturer status: OK
InOrbit visibility: OK while the connector is running
Observed published data: online/last_seen, pose, map DELIVERANCE, battery, water levels, work_status, key-values
```

`allybot-cleaner-2` has partial manufacturer-side validation:

```text
Manufacturer status/battery: seen
InOrbit visibility as allybot-cleaner-2: not seen
Active map check: provider returned OPERATION FAILURE 513
Full flow: not validated
```

### Keenon / AutoXing

Keenon and AutoXing diagnostics are not yet implemented against real provider APIs. Keep them inventory/skeleton-only until credentials, mappings, and read-only endpoints are confirmed.

### TurtleBot Demo Connector

`turtlebot_connector/` is a local demo/simulation connector, not a production
robot integration. It has two documentation entry points that intentionally
coexist:

- `turtlebot_connector/README.md`: connector-level overview, config, CAC, fake
  backend vs `ros2_gazebo`
- `turtlebot_connector/docker/ros2_gazebo/README.md`: validated step-by-step
  simulation flow for the ROS 2 / Gazebo / Nav2 demo

Validated demo learnings so far:

- Gazebo/Nav2/container flow is working in the VNC desktop environment
- validated display settings:
  - `DISPLAY=:1`
  - `XAUTHORITY=/home/ubuntu/.Xauthority`
  - `LIBGL_ALWAYS_SOFTWARE=1`
- `gzclient` should be launched as user `ubuntu`, not `root`
- `launch_sim.sh` spawns TurtleBot3 `waffle_pi` at:
  - `TB3_X_POSE=-2.0`
  - `TB3_Y_POSE=-0.5`
- `/camera/image_raw` is validated in RViz and shows live simulated images
- the connector camera path uses `RobotSession.register_camera()`
- for the validated InOrbit demo account, camera wiring ended up aligned to:
  - `camera_id: "0"`
  - `RobotCamera.metadata.id: "0"`
  - robot-scoped `RobotCamera` config for the demo robot
- camera is fully working in InOrbit Navigation widget
- map is fully working — scanned with slam_toolbox, uploaded via fetch_robot_map()
- actions scoped correctly to robot/rnLasGAxn5CP7bj32/turtlebot-demo-01
- teleoperation remains unvalidated / open work

Key lessons learned (see also turtlebot_connector/CLAUDE.md):

- CRITICAL: for Edge SDK connectors, `RobotCamera.spec.rosTopic` must be the
  camera_id (e.g. `"0"`), NOT the ROS topic name. For native ROS2 agents
  (4.x.x.ros2) it should be the actual ROS topic.
- map fetch requires Nav2 running and publishing /map before connector starts;
  use launch_nav2.sh with office_scanned.yaml, not launch_slam.sh
- scanned map saved at office_demo/maps/office_scanned.yaml — do not use
  office_map.yaml which is a pixel-converted PDF without real scan data
- camera settings matching other robots in account: width 380, height 240,
  rate 1, quality 30, outputEncoding rgb8

## 8. Provider Expansion Rules

Before implementing real read-only checks for Keenon, AutoXing, or another provider, inspect without executing connectors:

```text
README.md
pyproject.toml
config/example.env
config/fleet.example.yaml
connector entrypoint
src/connector.py
src/api/client.py
src/commands.py
```

For each provider, identify:

- required environment variables,
- minimum YAML fields,
- InOrbit `robot_id`,
- manufacturer robot ID field,
- authentication mechanism,
- read-only status/map/telemetry endpoints,
- command/control endpoints that must not be called.

If credentials, robot IDs, fleet IDs, store IDs, business IDs, or mappings are missing, stop and ask. Do not invent values.

## 9. Testing

For `tools/robot_diagnostics`, run:

```bash
uv run python -m unittest discover -s tests
```

Tests should cover:

- InOrbit CLI parsing,
- sanitization of secrets and WebSocket URLs,
- validation-state classification,
- Markdown/CSV/JSON exports,
- provider failures that should not abort the full inventory.

## 10. Response Style For Agents

Before acting, briefly explain what will be inspected or changed.

Keep phases separate:

```text
inspection
changes
validation
summary
```

For final summaries, include:

- files modified,
- commands executed,
- tests run,
- risks or limitations,
- recommended next steps.

If unsure, stop and ask before:

```text
writing to InOrbit
running a connector against real robots
adding credentials
committing generated outputs
changing maps/locations
executing any action command
```
