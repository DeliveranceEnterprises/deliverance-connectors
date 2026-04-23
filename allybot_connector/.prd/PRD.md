# PRD: InOrbit Allybot Connector

## 1. Overview

| Field | Value |
|-------|-------|
| Target system | Ally Fleet Robot API v2023-02-09 |
| Integration type | Fleet (multi-robot) |
| Robot types | Autonomous cleaning/service robots |
| Primary transport | WebSocket (App WS, internet-accessible) |
| Secondary transport | WebSocket (Direct WS, local network — optional) |
| Control | **Read-only** — no command endpoints documented in the API |

The Ally Fleet server exposes REST endpoints for metadata and TWO separate WebSocket APIs for real-time data:
- **App WS** (`ws://host:28080/fleetapi/websocketapp/{openid}/{token}`): internet-accessible, delivers live robot position.
- **Direct WS** (`ws://robot-ip:29997/robot`): local network only, delivers full chassis status (battery, charging, obstacle, etc.) plus position and task status.

---

## 2. Authentication & Connection Strategy

### 2.1 Regular REST API
- **Endpoint:** `POST /user/login` with JSON `{account, password}`
- **Token location:** JWT is returned in the response header `x-token` (or response body; parse both).
- **Usage:** `x-token: <JWT>` header on all REST endpoints.
- **Refresh:** No explicit expiry documented; re-login on 401/403 responses.

### 2.2 Mobile Fleet API (App WS login)
- **Endpoint:** `POST /fleetapi/account/login` with `application/x-www-form-urlencoded`
- **Body:** `username=<user>&password=<base64(password)>`
- **Headers:** `X-Api-Version: 184`
- **Response:** `data.token` + `data.openid`
- **Usage:** WS URL `ws://host:28080/fleetapi/websocketapp/{openid}/{token}`
- **Ping/pong:** Send `{"type": "ping", "language": "en_US"}` every 20 seconds.

### 2.3 App WS — single connection per connector instance
One App WS connection serves all robots. Messages include `msg.serial` identifying the robot.

### 2.4 Direct WS — one connection per robot (optional)
Connects to `ws://<robot-ip>:29997/robot`. No auth. Delivers richer status data.

---

## 3. Data Publishing

### 3.1 Pose

| Source | Fields | Notes |
|--------|--------|-------|
| App WS `device_position` | `msg.position.{x,y}`, `msg.orientation.{x,y,z,w}` | Primary (internet) |
| Direct WS `ROBOT_GESTURE` | `content.position.{x,y}`, `content.orientation.{x,y,z,w}` | Fallback (LAN) |

Yaw from quaternion: `yaw = 2 * atan2(orientation.z, orientation.w)`.
`frame_id` = `active_map_id` from `POST /fleetapi/device/usemap`.

### 3.2 Odometry

| InOrbit Field | Source | Notes |
|---------------|--------|-------|
| linear_speed | `msg.speed` (App WS) or `content.speed` (Direct WS) | m/s |

### 3.3 Key-Values (universal)

| Key | Type | Source | Notes |
|-----|------|--------|-------|
| `online_status` | bool | `robot/singleRobotInfo` → `aliveStatus` | 1=online, 2=mobile-connected, 0=offline |
| `map_name` | str | `device/usemap` → `mapinfo.name` | Active map name |
| `robot_name` | str | `robot/singleRobotInfo` → `robotName` | |
| `speed` | float | WS `msg.speed` or `content.speed` | m/s |
| `connector_version` | str | Package `__version__` | |
| `ws_connected` | bool | App WS connection state | |

### 3.4 Key-Values (Direct WS only — chassis status)

Available only when `direct_ws_url` is configured:

| Key | Type | Source |
|-----|------|--------|
| `battery` | float 0–1 | `chassisStatus.battery / 100.0` |
| `charging` | bool | `chassisStatus.charging` |
| `emergency_stop` | bool | `chassisStatus.emergencyStop` |
| `nav_status` | int | `navStatus` (0=idle, 1=navigating, 2=lost) |
| `localization` | bool | `localization` |
| `have_task_running` | bool | `haveTaskRunning` |
| `encounter_obstruction` | bool | `encounterObstruction` |
| `in_elevator` | bool | `inElevator` |
| `robot_connected` | bool | `robotConnected` |
| `network_status` | bool | `networkStatus` |
| `clean_device_opened` | bool | `cleanDeviceOpened` |
| `clean_intensity` | int | `currentApplyCleanIntensity` |
| `fresh_water` | float | `chassisStatus.freshWater` (%) |
| `sewage_water` | float | `chassisStatus.sewageWater` (%) |
| `task_name` | str | TASK_STATUS `taskName` |
| `task_percentage` | float | TASK_STATUS `percentage` |
| `task_status` | int | TASK_STATUS `taskStatus` |

### 3.5 Maps

- **Source:** `POST /fleetapi/device/usemap` → `data.image_url` (full PNG URL) + `data.mapinfo.original` (origin) + `data.mapinfo.resolution`
- **Fetch:** HTTP GET `image_url` → PNG bytes
- **frame_id:** `mapinfo.id` (active map UUID)
- **Origin:** `mapinfo.original.{x,y}` (meters, bottom-left corner offset)
- **Resolution:** `mapinfo.resolution` (meters/pixel)

---

## 4. Commands

**None.** The API documents only GET endpoints for tasks (no create/update/delete task, no send-to-point, no navigate). The connector is **read-only/monitoring only**.

CaC `actions.yaml` will be left with placeholder comments.

---

## 5. Configuration Schema

### 5.1 Connector-Level (`AllybotConfig`)

| Field | Type | Env Var | Default | Description |
|-------|------|---------|---------|-------------|
| `base_url` | str | `INORBIT_ALLYBOT_BASE_URL` | — | `http://host:28080` |
| `username` | str | `INORBIT_ALLYBOT_USERNAME` | — | Login account |
| `password` | str | `INORBIT_ALLYBOT_PASSWORD` | — | Login password (plain; base64 applied internally for App WS) |
| `verify_ssl` | bool | `INORBIT_ALLYBOT_VERIFY_SSL` | `True` | |
| `request_timeout` | float | `INORBIT_ALLYBOT_REQUEST_TIMEOUT` | `30.0` | |
| `direct_ws_url` | str\|None | `INORBIT_ALLYBOT_DIRECT_WS_URL` | `None` | e.g. `ws://192.168.3.63:29997/robot` |

### 5.2 Per-Robot (`AllybotRobotConfig`)

| Field | Type | Description |
|-------|------|-------------|
| `robot_id` | str | InOrbit robot ID |
| `fleet_robot_id` | str | Allybot `robotId` / `serial` (UUID string) |

### 5.3 Example

```yaml
connector_type: allybot
update_freq: 1.0
location_tz: Europe/Madrid

connector_config:
  base_url: http://116.205.178.152:28080
  username: DeliveranceENT
  password: Admin123
  # Optional: direct WS for battery/chassis data (local network only)
  # direct_ws_url: ws://192.168.3.63:29997/robot

fleet:
  - robot_id: allybot-cleaner-1
    fleet_robot_id: "6d70603da0cb3d00ba104a191770170b"
```

---

## 6. Error Handling

- **WS disconnect:** Reconnect with exponential backoff (1s, 2s, 4s … max 60s).
- **REST 401/403:** Re-login and retry once.
- **`device/usemap` failure:** Keep last known map; log warning, skip map publishing.
- **Per-robot isolation:** Failure for one robot does not block others.
- **Direct WS unreachable:** Log warning, continue with App WS data only.

---

## 7. Testing Strategy

- `test_config_models.py`: Config validation (required fields, unique IDs, env fallback).
- `test_api_client.py`: REST login, re-login on 401, `singleRobotInfo`, `device/usemap` via pytest-httpx.
- `test_connector.py`: `_publish_robot_data` key-value correctness, battery normalization, quaternion→yaw, online status mapping.
- Run: `uv run pytest && uv run ruff check`

---

## 8. Open Questions

1. **App WS JWT field:** Does `/user/login` return the JWT in the response header `x-token`, the body, or both? The docs say "from response headers or login flow" but the example body doesn't include a token field. Need to inspect actual response.
2. **`aliveStatus` values:** Docs show `aliveStatus: 2` means connected to mobile app but not fleet server — treated as "online" for InOrbit purposes?
3. **Direct WS with fleet:** If `direct_ws_url` is `null`, we lose all chassis data (battery, charging, etc.). Is position-only acceptable for the initial version?
