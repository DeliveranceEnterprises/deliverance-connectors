# InOrbit Ezviz Connector — PRD

## 1. Overview

**Target system**: Ezviz Cloud (consumer/prosumer IP cameras: C-series, BC-series battery
cameras, CS-series, etc.).
**Integration type**: Fleet connector. Each Ezviz camera (identified by its 9-character
device serial, e.g. `BB1234567`) is reported to InOrbit as a robot. Multiple cameras under
the same Ezviz account form the fleet.
**Library**: [`pyezvizapi`](https://github.com/RenierM26/pyEzvizApi) — successor to the
deprecated `pyezviz` package. Synchronous, requires Python ≥3.12, depends on
`requests`, `paho-mqtt`, `pycryptodome`.
**Bridge strategy**: pyezvizapi is **synchronous**. The connector wraps blocking calls in
`asyncio.to_thread()` so the async framework remains non-blocking.

## 2. Authentication & Connection

The `EzvizClient` constructor signature is:

```python
EzvizClient(
    account: str | None = None,
    password: str | None = None,
    url: str = "apiieu.ezvizlife.com",
    timeout: int = DEFAULT_TIMEOUT,
    token: dict | None = None,
) -> None
```

- **Account** — Ezviz account email (the same one used in the Ezviz mobile app).
- **Password** — Ezviz account password. pyezvizapi hashes it before posting.
- **Region URL** — defaults to `apiieu.ezvizlife.com` (EU). Other known regions:
  - `apiieu.ezvizlife.com` — EU (default)
  - `apiius.ezvizlife.com` — US
  - `apirus.ezvizru.com` — Russia
  - `apisgp.ezvizlife.com` — Singapore / SEA
- **MFA** — `_login(smscode=...)` supports SMS 2FA. The connector keeps it optional;
  most personal accounts don't require it.
- **Token reuse** — `EzvizClient` accepts a previously saved `token` dict. The connector
  caches the token in-memory and re-authenticates only on expiry.

### Connection lifecycle

1. `_connect()` — instantiate `EzvizClient`, call `login()`, store the returned token.
2. `_disconnect()` — best-effort `close_session()` (if exposed) and release the executor.
3. On 401 / token-expired during polling, transparently re-login.

## 3. Data Publishing

Every value below is published per-camera under the key shown. Battery is the only field
expected as a 0–1 float by InOrbit; all percentages from pyezvizapi (`battery_level`,
`signal`) are divided by 100 at publish time.

| Key | Type | Source (pyezvizapi method / JSON path) | Notes |
|---|---|---|---|
| `connector_version` | str | local | Installed package version. |
| `online_status` | bool | `get_device_infos(serial)` → `status == 1` | Drives `_is_fleet_robot_online`. |
| `api_connected` | bool | derived | False if last poll raised. |
| `battery` | float 0–1 | `device.battery_level / 100.0` | Only present on battery cams. |
| `battery_percent` | float 0–1 | same | Duplicate for dashboards that expect this key. |
| `signal_strength` | float 0–1 | `device.signal / 100.0` | Wi-Fi RSSI percentage. |
| `firmware_version` | str | `device.version` | e.g. `V5.2.4 build 200812`. |
| `device_name` | str | `device.name` | User-set name in the Ezviz app. |
| `device_category` | str | `device.category` / `subcategory` | e.g. `IPC`, `BatteryCamera`. |
| `last_motion_ts` | int (ms) | `device.last_alarm_time` (epoch ms) | 0 if never triggered. |
| `seconds_since_last_motion` | float | `device.Seconds_Last_Trigger` | Useful for the dashboard. |
| `motion_triggered` | bool | `device.Motion_Trigger` | True while alarm is active. |
| `defence_mode` | str | `home_defence_mode()` getter | `HOME` / `AWAY` / `SLEEP`. |
| `privacy_enabled` | bool | device status | True if lens cover / sleep is on. |
| `recording_enabled` | bool | device status | True if continuous recording is active. |
| `storage_status` | str | device status | `OK` / `FULL` / `NONE` / `ERROR`. |
| `last_alarm_type` | str | `get_alarminfo(serial, limit=1)` → first item type | e.g. `motion_detection`, `human_detection`. |
| `last_alarm_message` | str | `get_alarminfo(...)` → first item description | Free-text. |
| `last_alarm_pic_url` | str | `get_alarminfo(...)` → first item pic_url | Thumbnail URL. |

### Pose / Odometry

Cameras don't move (in this connector's scope), so **no pose is published**. If a camera
ever needs to be located on a map, set its static location via the InOrbit UI
("Set robot pose"). PTZ cameras have orientation but it is not reliably reported by the
cloud API — we expose PTZ as commands, not as continuous pose.

### System stats

Not applicable — `inorbit-connector[system-stats]` would publish the **host** running the
connector. We don't publish per-camera system stats.

### Maps

Not applicable.

### Events (forwarded as InOrbit custom events)

Whenever the alarm poll surfaces a new alarm record (newer than the last seen timestamp),
publish a custom event via `publish_event(robot_id, event_type, event_data)`:

| Ezviz alarm | InOrbit event |
|---|---|
| motion_detection | `motion_detected` |
| human_detection | `person_detected` |
| pet_detection | `pet_detected` |
| call_button | `doorbell_press` |
| line_crossing | `line_crossing` |
| intrusion | `intrusion` |
| tampering | `tampering` |

Default mapping is permissive — unknown Ezviz alarm types pass through with the raw type
string.

## 4. Command Handling

Exposed as InOrbit **custom actions** (RunScript). Filenames match `CustomScripts` StrEnum.

| Script | EzvizClient method | Arguments | Notes |
|---|---|---|---|
| `ptz_up` | `ptz_control("UP", serial, action, speed)` | `action` (`START`/`STOP`), `speed` (1–10) | Two calls: START then STOP after `duration_ms`. |
| `ptz_down` | `ptz_control("DOWN", ...)` | same | |
| `ptz_left` | `ptz_control("LEFT", ...)` | same | |
| `ptz_right` | `ptz_control("RIGHT", ...)` | same | |
| `ptz_stop` | `ptz_control("STOP", serial, "STOP", speed)` | — | Emergency stop. |
| `ptz_step` | `ptz_control(direction, serial, ...)` | `direction`, `duration_ms` (default 500) | Convenience: nudge in a direction for N ms. |
| `ptz_goto` | `ptz_control_coordinates(serial, x_axis, y_axis)` | `x_axis` (0–1), `y_axis` (0–1) | Absolute aim. |
| `snapshot` | `capture_picture(serial, channel=1)` | — | Returns a URL/JSON; published as a key-value `last_snapshot_url`. |
| `sound_alarm` | `sound_alarm(serial, enable=1)` | — | Plays the camera's alarm tone. |
| `stop_alarm` | `sound_alarm(serial, enable=0)` | — | |
| `set_defence_mode` | `home_defence_mode(mode)` | `mode` (`HOME`/`AWAY`/`SLEEP`) | Account-wide. |
| `arm_camera` | `set_camera_defence(serial, enable=1)` | — | Per-camera motion detection on. |
| `disarm_camera` | `set_camera_defence(serial, enable=0)` | — | Off. |
| `reboot` | `reboot_camera(serial)` | — | Confirmation required. |

All commands run via `asyncio.to_thread()`. On exception, raise `CommandFailure` with the
exception message; on success, call `result_function(CommandResultCode.SUCCESS)`.

## 5. Configuration Schema

Environment prefix: `INORBIT_EZVIZ_`. Loaded from `config/.env` then overridden by YAML.

### Connector-level (`connector_config`)

| Field | Type | Default | Notes |
|---|---|---|---|
| `account` | str | — required | Ezviz account email. |
| `password` | str | — required | Ezviz account password. |
| `region_url` | str | `apiieu.ezvizlife.com` | EU/US/RU/SG host. |
| `request_timeout` | float | 30.0 | Seconds. |
| `alarm_poll_seconds` | float | 5.0 | How often to check for new alarms. |
| `metadata_poll_seconds` | float | 60.0 | Refresh firmware/category. |
| `default_ptz_speed` | int | 5 | 1–10. |
| `default_ptz_step_ms` | int | 500 | Used by `ptz_step`. |

### Per-robot (`fleet[]`)

| Field | Type | Notes |
|---|---|---|
| `robot_id` | str | InOrbit robot ID. |
| `fleet_robot_id` | str | Ezviz device serial (e.g. `BB1234567`). |
| `channel` | int = 1 | Camera channel for multi-lens devices. |
| `ptz_enabled` | bool = true | Surface PTZ commands for this camera. |

Validator: `fleet_robot_id` must be unique across the fleet.

## 6. Error Handling & Retry

- **Login failures**: log at ERROR with masked credentials; the connector keeps the session
  marked `api_connected=False` until a successful re-login. No restart required.
- **Per-camera errors**: each camera has its own polling task; a failure in one does not
  stop the others.
- **Retries**: `tenacity` with exponential backoff (3 attempts, 1–8s) wraps every
  pyezvizapi call.
- **Rate limits**: Ezviz cloud is undocumented. Defaults are conservative (alarm poll 5s,
  metadata 60s). The connector will back off and warn on HTTP 429.
- **MFA / SMS code**: not solved automatically — connector raises with a clear instruction
  to log in manually once via the Ezviz app to clear the challenge.

## 7. Testing Strategy

- `tests/test_config_models.py` — validates Pydantic config, env-var loading, unique
  serial check.
- `tests/test_api_client.py` — patches `EzvizClient` at the module level; verifies retry
  behaviour and exception → connected-state transitions.
- `tests/test_connector.py` — exercises `_execution_loop` with a synthetic `RobotState`,
  verifies key-values are published; exercises the command dispatcher for each script.
- `tests/test_alarms.py` — feeds synthetic alarm payloads, asserts events fire only on
  newer timestamps (no duplicates).

## 8. Open Questions

1. **MFA**: do any of your Ezviz accounts have SMS 2FA enabled? If yes, we should
   prompt for the code via an env var at startup rather than refusing to start.
2. **Multiple regions**: are all cameras under one regional cloud, or do you have
   accounts spanning EU + US? (Affects whether `region_url` lives at the connector level
   or per-camera.)
3. **PTZ scope**: do your cameras actually support PTZ, or are they fixed? If all fixed,
   we'll drop PTZ commands from the CaC actions.yaml and the ActionDefinitions.
4. **Snapshot delivery**: pyezvizapi's `capture_picture` returns a JSON dict with a URL.
   Confirm InOrbit dashboard usage: publish the URL as a key-value, or also upload the
   image bytes through the connector?
5. **Doorbell / battery cam alarm channel**: doorbell models stream alarms differently
   (push instead of poll). If you have a CS-DB1 or BC1, we may need an MQTT alarm
   subscriber instead of HTTP polling.

## 9. Out of Scope (for v0.1)

- Live RTSP/HLS video stream embed (dashboard config, not connector code).
- Two-way audio / talk-back.
- Local SDK / LAN-only access (ports 9010/9020).
- Cloud video clip retrieval / download.
- Per-camera sound/volume schedules.
- Light bulbs and other Ezviz IoT devices (`devices_light`).
