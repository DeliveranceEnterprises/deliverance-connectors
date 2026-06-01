<!--
SPDX-FileCopyrightText: 2026 Deliverance Enterprises

SPDX-License-Identifier: MIT
-->

# Deliverance Connectors

This repository hosts InOrbit Connectors built and maintained by [Deliverance Enterprises](https://deliverance.enterprises). Each Connector bridges a specific robot fleet API with the [InOrbit Platform](https://inorbit.ai/) using the [InOrbit Connector Python framework](https://github.com/inorbit-ai/inorbit-connector-python), enabling unified fleet visibility and control across heterogeneous robot vendors.

## Connectors

### Allybot

The [InOrbit](https://inorbit.ai/) Fleet Connector for [Allybot](https://www.allybot.com/) autonomous cleaning robots.

Using the Ally Fleet Robot API, the Connector establishes a single App WebSocket connection (internet-accessible) that delivers real-time position updates for all robots in the fleet. Robot metadata and active map information are fetched periodically via the REST API.

> **Note:** The Ally Fleet Robot API does not expose robot control endpoints. This Connector is monitoring-only — it publishes telemetry to InOrbit but does not send commands to the robots.

**Capabilities:**
- Live pose (position + heading from quaternion) and speed from the App WebSocket (`device_position` stream)
- Automatic reconnection with exponential backoff on WebSocket disconnect
- Map image fetching from the Ally Fleet server with correct origin and resolution metadata
- Robot online status, name, and active map name via REST polling
- Dual authentication: mobile fleet auth (required, for WebSocket and map endpoints) with graceful fallback to REST JWT auth (for robot metadata)

See the [allybot\_connector README](allybot_connector/README.md) for setup instructions.

---

### Keenon

The [InOrbit](https://inorbit.ai/) Fleet Connector for [Keenon](https://www.keenonrobot.com/) robots.

Using the Keenon Cloud API v2.2.0, a single Connector instance manages an entire fleet of Keenon robots across multiple robot series:

- **T-series** — food and restaurant delivery robots
- **W-series** — hotel and hospitality delivery robots
- **C-series** — autonomous cleaning robots

Robot type is detected automatically from the robot model returned by the API. The Connector polls the Keenon REST API for real-time state and optionally runs a built-in webhook receiver to accept Keenon push callbacks for lower-latency updates.

**Capabilities:**
- Live pose, battery level, online status, task status, and scene information for each robot
- Map fetching from the Keenon cloud (base64-encoded PNG with origin and resolution metadata)
- Remote delivery commands: send to point, return to origin, cancel task
- Cleaning commands: return to charger, finish task, pause task, start temporary cleaning
- Hotel robot cabin door control (open/close)

See the [keenon\_connector README](keenon_connector/README.md) for setup instructions.

---

### AutoXing

The [InOrbit](https://inorbit.ai/) Fleet Connector for [AutoXing](https://www.autoxing.com/) robots.

Using the AutoXing Cloud API v1.1.0, the Connector manages a fleet of AutoXing robots through a single instance. Authentication uses a dual APPCODE mechanism with a ticket exchange flow.

**Capabilities:**
- Multi-robot fleet management through a single connector instance
- Real-time robot monitoring: pose, battery, state, velocity
- Automatic retry logic with exponential backoff for API calls
- Background polling architecture for efficient data fetching
- Annotation synchronization for waypoint positions between AutoXing Cloud and InOrbit

See the [autoxing\_connector README](autoxing_connector/README.md) for setup instructions.

---

### Ezviz

The [InOrbit](https://inorbit.ai/) Connector for [Ezviz](https://www.ezviz.com/) cloud cameras.

Each Ezviz camera under a configured account is reported to InOrbit as a robot, enabling unified fleet visibility alongside mobile robots.

**Capabilities:**
- Online status, battery level (where applicable), Wi-Fi signal strength
- Firmware version and device name
- Last motion timestamp and motion trigger state
- Per-camera snapshot via `scripts/test_camera.py` for pre-launch credential validation

See the [ezviz\_connector README](ezviz_connector/README.md) for setup instructions.

---

### TurtleBot Demo

Demo InOrbit Edge connector for a simulated TurtleBot3 waffle\_pi robot running in Gazebo.

This connector serves as a reference implementation and validation environment for the InOrbit Edge SDK. It uses a containerized ROS 2 Humble / Gazebo Classic / Nav2 stack and connects to InOrbit through the `inorbit-edge` Python SDK.

**Capabilities:**
- Pose from `/odom` or `/amcl_pose`, published to InOrbit in real time
- Camera streaming from `/camera/image_raw` over MQTT (validated in InOrbit Navigation widget)
- Automatic map upload to InOrbit on startup via `/map` OccupancyGrid subscription
- Navigation actions: Go Home, Go Station 1, Go Station 2, Cancel Task (via Nav2 `NavigateToPose`)
- Fake simulator backend for testing without ROS (`backend: fake`)
- Office world: custom Gazebo environment with SLAM-scanned map (`office_scanned.yaml`)

See the [turtlebot\_connector README](turtlebot_connector/README.md) for connector details and [docker/ros2\_gazebo README](turtlebot_connector/docker/ros2_gazebo/README.md) for the step-by-step demo workflow.

---

## Shared Tools

### Robot Diagnostics

Read-only diagnostics and inventory tool for all connectors.

Reads local connector YAML/env configuration, queries manufacturer APIs using read-only endpoints, and queries InOrbit to compare what each source reports. Generates Markdown/CSV/JSON inventories under `outputs/` (Git-ignored).

See the [robot\_diagnostics README](tools/robot_diagnostics/README.md) for usage.

---

## Repository Structure

```
deliverance-connectors/
├── allybot_connector/      # Ally Fleet Robot API connector
│   ├── allybot_connector/  # Python package
│   ├── cac/                # InOrbit Configuration-as-Code definitions
│   ├── config/             # Configuration examples
│   ├── docker/             # Docker packaging
│   └── tests/
├── keenon_connector/       # Keenon Cloud API connector
│   ├── keenon_connector/   # Python package
│   ├── cac/
│   ├── config/
│   ├── docker/
│   └── tests/
├── autoxing_connector/     # AutoXing Cloud API connector
│   ├── autoxing_connector/ # Python package
│   ├── cac/
│   ├── config/
│   ├── docker/
│   └── tests/
├── ezviz_connector/        # Ezviz cloud camera connector
│   ├── ezviz_connector/    # Python package
│   ├── cac/
│   ├── config/
│   └── scripts/
├── turtlebot_connector/    # TurtleBot3 demo connector (Edge SDK + ROS 2 / Gazebo)
│   ├── turtlebot_connector/ # Python package
│   ├── cac/
│   ├── config/
│   ├── docker/
│   │   └── ros2_gazebo/    # Containerized ROS 2 / Gazebo / Nav2 demo environment
│   ├── office_demo/        # Gazebo office world, SLAM-scanned map, waypoints
│   └── tests/
├── tools/
│   └── robot_diagnostics/  # Read-only diagnostics and inventory tool
└── outputs/                # Generated inventories — Git-ignored
```

## Getting Started

Each connector is a standalone Python package managed with [uv](https://github.com/astral-sh/uv). To run a connector:

```bash
cd allybot_connector          # or keenon_connector, autoxing_connector, ezviz_connector
cp config/fleet.example.yaml config/my_fleet.yaml
cp config/example.env config/.env
# Edit both files with your credentials and robot IDs
uv run allybot-connector -c config/my_fleet.yaml
```

Refer to each connector's README for full configuration details.

## Development

All connectors follow the same development workflow:

```bash
cd allybot_connector          # or any connector
uv sync --extra=dev
uv run pytest
uv run ruff check
```

Each connector ships with unit tests (pytest) and a ruff linting configuration. See the individual `CONTRIBUTING.md` files for contributor guidelines.

The cloud connectors (Allybot, Keenon, AutoXing) were generated from the [InOrbit Connector Cookiecutter](https://github.com/inorbit-ai/inorbit-connector-cookiecutter) and built on the [`inorbit-connector-python`](https://github.com/inorbit-ai/inorbit-connector-python) framework.

---

**Powered by [InOrbit](https://inorbit.ai)**
