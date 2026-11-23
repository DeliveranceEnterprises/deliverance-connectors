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
| `robot_model` | config | `robot_model` per camera, "Ezviz Camera" by default. "Ezviz " is prepended when the value does not start with "Ezviz" (case-insensitive), so `H6C` is published as `Ezviz H6C`; the platform uses that prefix to recognise the robot as a camera. |

PTZ + snapshot + alarm forwarding are tracked in `.prd/PRD.md` and will land
in v0.2.

## InOrbit data sources

`cac/data_sources.yaml` defines the data sources for `robot_model`,
`online_status` and `api_connected`. Its scopes are placeholders
(`tag/<ACCOUNT_ID>/<EZVIZ_TAG_ID>`): replace them with your InOrbit account ID
and the ID of the tag that groups your cameras before applying. `inorbit apply`
does not read from stdin, so write the substituted file to a temporary path:

```bash
sed -e "s/<ACCOUNT_ID>/<your-account-id>/g" \
    -e "s/<EZVIZ_TAG_ID>/<your-ezviz-tag-id>/g" \
    cac/data_sources.yaml > "${TMPDIR:-/tmp}/ezviz_data_sources.yaml"
inorbit apply -f "${TMPDIR:-/tmp}/ezviz_data_sources.yaml"
```

Do not commit the substituted file.

## Running alongside deliverance-integrations-ezviz

The Deliverance Platform integration (`deliverance-integrations-ezviz`) can
read the same Ezviz account. Logging in from this connector may end the
account's other sessions (not verified), so prefer separate credentials when
both run at the same time. Run each camera through only one path: a camera
imported both by this connector and through the platform integration appears
twice in the platform.

## Troubleshooting

**`code 2003 — device not online`** — common for battery cameras that sleep
between events. The cloud lists them as online but cloud-issued commands
fail. Trigger motion or open the camera in the Ezviz app to wake it, then
retry.
