# InOrbit Ezviz Connector

InOrbit Edge connector for [Ezviz](https://www.ezviz.com/) cloud cameras.

Each Ezviz camera under your account is reported to InOrbit as a robot, with
key-values for online status, battery (where applicable), Wi-Fi signal,
firmware version, and last motion timestamp.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- An Ezviz account with at least one camera registered
- An InOrbit API key

## Setup

```bash
# Install
uv sync --extra=dev

# Configure
cp config/example.env config/.env
# Edit config/.env: Ezviz account/password/region + INORBIT_API_KEY

cp config/fleet.example.yaml config/my_fleet.yaml
# Edit config/my_fleet.yaml: add one entry per camera (robot_id + serial)
```

## Run

```bash
./run.sh
# or
uv run ezviz-connector -c config/my_fleet.yaml
```

## Verify the camera before launching

```bash
uv run scripts/test_camera.py
```

Lists every camera on the account, fetches its status, downloads a snapshot
to `snapshots/`, and prints what fields your specific model reports. Use this
to fill in `config/my_fleet.yaml` and to confirm credentials work.

## What gets published

| Key | Source | Notes |
|---|---|---|
| `online_status` | `device.status` | Drives the "online" indicator in InOrbit. |
| `api_connected` | derived | False when the last poll raised. |
| `battery` | `device.battery_level / 100` | Battery cameras only. InOrbit expects 0–1. |
| `signal_strength` | `device.signal / 100` | Wi-Fi RSSI %. |
| `firmware_version` | `device.version` | |
| `device_name` | `device.name` | User-set name in the Ezviz app. |
| `last_motion_ts` | `device.last_alarm_time` | Epoch ms. |
| `motion_triggered` | `device.Motion_Trigger` | True while an alarm is firing. |
| `connector_version` | local | |

PTZ + snapshot + alarm forwarding are tracked in `.prd/PRD.md` and will land
in v0.2.

## Troubleshooting

**`code 2003 — device not online`** — common for battery cameras that sleep
between events. The cloud lists them as online but cloud-issued commands
fail. Trigger motion or open the camera in the Ezviz app to wake it, then
retry.
