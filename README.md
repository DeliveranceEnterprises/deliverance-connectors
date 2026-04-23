<!--
SPDX-FileCopyrightText: 2026 Deliverance Enterprises

SPDX-License-Identifier: MIT
-->

# Deliverance Connectors

This repository hosts InOrbit Connectors built and maintained by [Deliverance Enterprises](https://deliverance.enterprises). Each Connector bridges a specific robot fleet API with the [InOrbit Platform](https://inorbit.ai/) using the [InOrbit Connector Python framework](https://github.com/inorbit-ai/inorbit-connector-python), enabling unified fleet visibility and control across heterogeneous robot vendors.

## Connectors

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

## Repository Structure

```
deliverance-connectors/
├── keenon_connector/       # Keenon Cloud API connector
│   ├── keenon_connector/   # Python package
│   ├── cac/                # InOrbit Configuration-as-Code definitions
│   ├── config/             # Configuration examples
│   ├── docker/             # Docker packaging
│   └── tests/
└── allybot_connector/      # Ally Fleet Robot API connector
    ├── allybot_connector/  # Python package
    ├── cac/                # InOrbit Configuration-as-Code definitions
    ├── config/             # Configuration examples
    ├── docker/             # Docker packaging
    └── tests/
```

## Getting Started

Each connector is a standalone Python package managed with [uv](https://github.com/astral-sh/uv). To run a connector:

```bash
cd keenon_connector          # or allybot_connector
cp config/fleet.example.yaml config/my_fleet.yaml
cp config/example.env config/.env
# Edit both files with your credentials and robot IDs
source config/.env
uv run keenon-connector -c config/my_fleet.yaml
```

Refer to each connector's README for full configuration details.

## Development

Both connectors follow the same development workflow:

```bash
cd keenon_connector
uv sync --extra=dev
uv run pytest
uv run ruff check
```

Each connector ships with unit tests (pytest + pytest-httpx for HTTP mocking) and a ruff linting configuration. See the individual `CONTRIBUTING.md` files for contributor guidelines.

These connectors were generated from the [InOrbit Connector Cookiecutter](https://github.com/inorbit-ai/inorbit-connector-cookiecutter) and built on the [`inorbit-connector-python`](https://github.com/inorbit-ai/inorbit-connector-python) framework.

---

**Powered by [InOrbit](https://inorbit.ai)**
