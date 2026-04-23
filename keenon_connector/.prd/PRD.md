# PRD: InOrbit Keenon Connector

## 1. Overview

| Field | Value |
|-------|-------|
| Target system | Keenon Cloud API v2.2.0 |
| Integration type | Fleet (multi-robot) |
| Robot series | T-series (food delivery), W-series (hotel), C-series (cleaning), hospital |
| Transport | REST/HTTP polling — no WebSocket streaming |
| Auth | OAuth2 client credentials |
| Approach | Polling-based; webhooks deferred |

Keenon organizes robots into **stores** (physical locations). Robots belong to a store and are identified by their **MAC address** (e.g. `AA:BB:CC:DD:EE:FF`). The connector maps InOrbit robot IDs to Keenon `robotId` values.

---

## 2. Authentication & Connection Strategy

- **Endpoint:** `POST /api/open/oauth/token` with `client_id`, `client_secret`, `grant_type=client_credentials`
- **Token validity:** `expires_in` seconds (default 7200 s on first request; validity is extended by each successful request)
- **Strategy:** Obtain token on startup. Track `expires_in` and refresh proactively when < 5 minutes remain. On 610401 (token expired), refresh immediately and retry.
- **Base URL:** Configurable per region (China, EU, Japan — see domain table in API spec)
- **SSL:** HTTPS by default (all production domains are HTTPS). Optional `verify_ssl` flag for dev environments.

---

## 3. Data Publishing

All data is gathered by polling Keenon REST endpoints. Poll interval = `update_freq` (default 1 Hz).

### 3.1 Pose

| InOrbit Field | Source | Notes |
|---------------|--------|-------|
| x | `GET /api/open/custom/robot/location` → `data.coordinate` (split by `,`) | Meters |
| y | Same as above (second token) | Meters |
| yaw | Same as above (third token, degrees → radians) | Convert: `math.radians(angle)` |
| frame_id | `sceneCode` from robot status | Falls back to `"map"` |

Also consider: `GET /api/open/custom/robot/position` (hotel W-series specific, same coordinate format).

### 3.2 Odometry

Not available from the API. Skip — do not publish.

### 3.3 Key-Values

One row per key published via `publish_robot_key_values()`.

| Key | Type | Source | Notes |
|-----|------|--------|-------|
| `battery` | float 0–1 | `GET /api/open/data/v1/store/robot/list` → `power` | Divide by 100.0 |
| `online_status` | bool | `onlineStatus` from robot list | |
| `charge_status` | str | `GET /api/open/scene/v1/robot/status` → `chargeStatus` | `"charging"` (1) or `"discharging"` (-1) |
| `can_be_called` | bool | `canBeCalled` from robot status | |
| `robot_state` | str | `RobotWorkState` webhook / polled state | Map int → string: 1=`on_task`, 2=`idle`, 3=`operating`, 4=`scheduling`, 5=`charging`, 6=`powering_on` |
| `current_scene` | str | `sceneName` from robot status | |
| `task_no` | str | From active task query | Empty string if no task |
| `task_status` | str | `taskStatus` from `GET /api/open/scene/v1/robot/call/task` | `queued`, `calling`, `in_progress`, `completed`, `cancelled`, `target_reached`, `waiting`, `failed` |
| `robot_model` | str | `robotModel` from robot list | T2, W-series, etc. |
| `app_version` | str | `appVersion` from robot list | |
| `online_type` | str | `onlineType` from robot list | Map int → string: 2=`wifi`, 3=`3G`, 4=`4G`, 5=`unknown` |
| `elevator_status` | bool | `takeElevatorStatus` from location | True if in elevator |
| `connector_version` | str | Package `__version__` | Published from skeleton |

**Cleaning robots only** (detected by robot type):

| Key | Type | Source |
|-----|------|--------|
| `clean_main_state` | str | `GET /api/open/custom/clean/robot/status` → `mainState` (mapped to string) |
| `clean_sub_state` | str | `subState` (mapped to string) |
| `clean_is_faulting` | bool | `globalState.faulting` |
| `clean_emergency_stop` | bool | `globalState.scram` |
| `clean_is_navigating` | bool | `childState.navigating` |
| `clean_bilge_tank` | str | `hardwareState.bilgeTankState` mapped: -1=`no_hw`, 0=`empty`, 1=`medium`, 2=`full` |
| `clean_water_tank` | str | `hardwareState.cleanWaterTank` mapped: -1=`no_hw`, 0=`empty`, 1=`low`, 2=`medium`, 3=`full` |

### 3.4 Maps

Available via `GET /api/open/custom/robot/map` (requires `sceneCode` + `floorInfo`). Response is binary map data in `data.content`.

**Decision to make:** The binary format is not documented (byte array). We cannot reliably parse it as a PNG without knowing the format. **Deferred** — `fetch_robot_map` returns `None` until format is clarified.

Map point positions are available via `GET /api/open/custom/robot/map/position` and can be synchronized as InOrbit annotations. Deferred to a later phase.

### 3.5 System Stats

Not available from the Keenon Cloud API. The `publish_connector_system_stats=True` flag in the skeleton publishes host machine stats. Keep as-is.

---

## 4. Command Handling

All commands via `customCommand`. No edge mission execution needed.

| Script name (CustomScripts) | Label | Parameters | API endpoint | Notes |
|-----------------------------|-------|-----------|--------------|-------|
| `call_to_point` | Send to Point | `point_uuid` (str), `point_id` (str), `store_id` (str), `scene_code` (str, opt), `robot_type` (str, opt: `food`/`hotel`) | `POST /api/open/scene/v3/robot/call/task` | Schedules robot to go to a single point. Returns `taskNo`. |
| `call_multi_point` | Multi-Point Delivery | `store_id`, `scene_code`, `robot_type`, `points` (JSON string array with uuid/pointId/pointName) | `POST /api/open/scene/v4/robot/call/task` | Multi-point delivery. `robotId` from config. |
| `return_to_origin` | Return to Origin | `store_id` (str) | `POST /api/open/scene/v2/robot/call/back/task` | T-series only (food delivery v1.8.0+). |
| `cancel_task` | Cancel Task | `task_no` (str) | `DELETE /api/open/scene/v1/robot/call/task` | Cancels active call task. |
| `clean_recharge` | Return to Charger | _(none)_ | `POST /api/open/custom/clean/robot/recharge/task` | Cleaning robots only. |
| `clean_finish` | Finish Cleaning | _(none)_ | `POST /api/open/custom/clean/robot/finish/task` | Cleaning robots only. |
| `clean_pause` | Pause Cleaning | _(none)_ | `POST /api/open/custom/clean/robot/pause/task` | Cleaning robots only. |
| `clean_temporary_task` | Start Temporary Clean | `area_id_list` (JSON array), `clean_model_id` (str), `clean_times` (int), `back_point_id` (int) | `POST /api/open/custom/clean/robot/strategy/temporary/task` | Cleaning robots only. |
| `open_cabin` | Open Cabin | `cabin` (int) | `POST /api/open/custom/robot/cabin/door` with `ctrlType=1` | Hotel W-series only. Rate limited: 1 call/10 s per robot. |
| `close_cabin` | Close Cabin | `cabin` (int) | `POST /api/open/custom/robot/cabin/door` with `ctrlType=0` | Hotel W-series only. Rate limited: 1 call/10 s per robot. |

### 4.1 Task Tracking

After sending a command that creates a task (`call_to_point`, etc.), the connector stores the returned `taskNo` and polls `GET /api/open/scene/v1/robot/call/task` to track task status. Task status is published as `task_status` and `task_no` key-values.

---

## 5. Configuration Schema

### 5.1 Connector-Level (`KeenonConfig`)

| Field | Type | Env var | Default | Description |
|-------|------|---------|---------|-------------|
| `api_domain` | str | `INORBIT_KEENON_API_DOMAIN` | — | Base URL, e.g. `https://es.robotkeenon.com` |
| `client_id` | str | `INORBIT_KEENON_CLIENT_ID` | — | OAuth2 client ID |
| `client_secret` | str | `INORBIT_KEENON_CLIENT_SECRET` | — | OAuth2 client secret |
| `verify_ssl` | bool | `INORBIT_KEENON_VERIFY_SSL` | `True` | Set False for dev/test |
| `request_timeout` | float | `INORBIT_KEENON_REQUEST_TIMEOUT` | `30.0` | HTTP timeout in seconds |

### 5.2 Per-Robot (`KeenonRobotConfig`)

| Field | Type | Description |
|-------|------|-------------|
| `robot_id` | str | InOrbit robot ID |
| `fleet_robot_id` | str | Keenon `robotId` / `robotSn` (MAC address, e.g. `AA:BB:CC:DD:EE:FF`) |
| `store_id` | str | Keenon `storeId` the robot belongs to |
| `robot_type` | str \| None | `"food"`, `"hotel"`, `"hospital"`, `"clean"`, or `None` (auto-detect) |

> **Note:** `fleet_robot_id` type changes from `int` (skeleton default) to `str` to match Keenon's MAC address format.

### 5.3 Example `fleet.yaml`

```yaml
connector_type: keenon
update_freq: 1.0
location_tz: Europe/Madrid

connector_config:
  api_domain: https://es.robotkeenon.com
  client_id: your-client-id
  client_secret: your-client-secret

fleet:
  - robot_id: keenon-food-1
    fleet_robot_id: "AA:BB:CC:DD:EE:01"
    store_id: S00000001
    robot_type: food
  - robot_id: keenon-hotel-1
    fleet_robot_id: "AA:BB:CC:DD:EE:02"
    store_id: S00000001
    robot_type: hotel
  - robot_id: keenon-clean-1
    fleet_robot_id: "34:7D:E4:98:A1:BA"
    store_id: S00000001
    robot_type: clean
```

---

## 6. Error Handling & Retry Strategy

- **Network errors / timeouts:** Retry up to 3 times with exponential backoff (1 s initial, max 10 s) via `tenacity`.
- **610401 (token expired):** Refresh token and retry the original request once.
- **610000 success, but `data` is empty / None:** Log warning, skip publishing for that cycle.
- **614920 (no robot available):** Raise `CommandFailure` with descriptive message.
- **Per-robot errors:** Isolated — one robot failure does not stop polling for other robots.
- **API rate limits (610609, 5011):** Back off 10 s before retry for cleaning robot commands.

---

## 7. Testing Strategy

- `test_config_models.py`: Config validation (valid config, missing fields, duplicate IDs, type mismatch, env-var fallback).
- `test_api_client.py` (new): HTTP mocking with `pytest-httpx` — token acquisition, token refresh on 610401, robot list, location, status endpoints.
- `test_connector.py` (new): Command dispatch, key-value publishing from polled data, `_is_fleet_robot_online` behavior.
- Run: `uv run pytest && uv run ruff check`

---

## 8. Open Questions

1. **Map binary format:** What format is `data.content` in the map endpoint? (PNG, ROS map, custom binary?) Cannot implement map fetching without this.
2. **Robot type auto-detection:** Should `robot_type` be inferred from `robotModel` (T-series → food, W-series → hotel) or always require explicit config?
3. **Webhook support:** Should the connector optionally expose an HTTP endpoint to receive Keenon webhooks for real-time updates? (Would reduce polling overhead significantly for large fleets.)
4. **Scene/floor refresh:** Location includes `building` and `floor` fields for multi-floor robots. Should these be published as key-values?
5. **Task tracking polling frequency:** Should `task_status` be polled at a higher frequency than other data (e.g., 2 Hz while a task is active)?
6. **Hospital robot API:** Hospital endpoints require different request structures. Should this connector version support hospital robots, or target food/hotel/cleaning only?
