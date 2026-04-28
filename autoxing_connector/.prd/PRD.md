# PRD — AutoXing Cloud Connector

## 1. Overview

| Field | Value |
|-------|-------|
| Target system | AutoXing Cloud Platform |
| API version | v1.1.0 |
| Base URL | `https://apiglobal.autoxing.com` |
| Integration type | **Fleet** — one connector instance manages multiple robots |
| Transport | REST only (no WebSocket) |
| Data flow | Polling — periodic REST calls per robot |

AutoXing robots are deployed in restaurants, hotels, hospitals, offices, and factories. The fleet
platform exposes robot state (pose, battery, status flags), map/area management, and task
dispatch (navigation to POIs, return to charger, delivery, disinfection, etc.).

---

## 2. Authentication & Connection Strategy

### Web Login (Two-Step)

The only tested flow uses web login credentials:

**Step 1 — Login** (`POST /user/v1.1/login`)
- `Authorization: APPCODE 8184850f6ebe4edea8ba3e37ae46a35b` (login-only APPCODE)
- Body: `{ loginName, password }` — **password must be AES-encrypted** (scheme TBD — see Open Questions)
- Returns: initial token + openId

**Step 2 — Ticket exchange** (`GET /user/v1.0/ticket/{openId}`)
- `Authorization: APPCODE dd7afee0a068431abb2425ac622e70d2` (API APPCODE)
- `X-Token: <token from Step 1>`
- Returns: fresh 7-day JWT, businessId, busIds

All subsequent calls use:
```
Authorization: APPCODE dd7afee0a068431abb2425ac622e70d2
X-Token: <7-day JWT>
```

### Programmatic Auth (Alternative — not usable yet)
`POST /auth/v1.1/token` with appId/appSecret/MD5 signature. Requires separately provisioned
credentials from AutoXing. **Tested — returns "appId is invalid" with web credentials.** Flag
for future use when credentials are provisioned.

### Token Refresh Strategy
JWT expiry ≈ 7 days (603,800 s). Connector will track expiry and re-run the two-step login
at 90% of the expiry window (~6.3 days) to avoid expiry during operation.

---

## 3. Data Publishing

### 3.1 Pose
| InOrbit Field | Source | Notes |
|---------------|--------|-------|
| x | `state.x` | metres |
| y | `state.y` | metres |
| yaw | `state.yaw` | **degrees → radians** (multiply by π/180) |
| frame_id | `state.areaId` | Use area ID as map frame |

Source: `GET /robot/v1.1/{robotId}/state` (polled at `update_freq`)

### 3.2 Odometry
| InOrbit Field | Source | Notes |
|---------------|--------|-------|
| linear_speed | `state.speed` | m/s, from state endpoint |

### 3.3 Key-Values (one per key)

| Key | Source Field | Type | Notes |
|-----|-------------|------|-------|
| `battery` | `state.battery` | float 0–1 | divide by 100.0 |
| `battery_percent` | `state.battery` | int | raw 0–100 |
| `online_status` | `robot.isOnLine` | bool | from list endpoint |
| `is_charging` | `state.isCharging` | bool | |
| `is_task` | `robot.isTask` | bool | from list endpoint |
| `is_go_home` | `state.isGoHome` | bool | returning to charger |
| `is_emergency_stop` | `state.isEmergencyStop` | bool | |
| `is_manual_mode` | `state.isManualMode` | bool | |
| `is_remote_mode` | `state.isRemoteMode` | bool | |
| `loc_quality` | `state.locQuality` | int 0–100 | positioning accuracy |
| `has_obstruction` | `state.hasObstruction` | bool | obstacle detected |
| `errors` | `state.errors` | str | JSON-serialised error code array |
| `current_area_id` | `state.areaId` | str | |
| `current_area_name` | resolved from area list | str | cached at startup |
| `task_id` | `state.taskObj.taskId` | str | current task ID |
| `task_is_finish` | `state.taskObj.isFinish` | bool | |
| `task_is_cancel` | `state.taskObj.isCancel` | bool | |
| `mission_status` | derived | str | "Idle" / "Mission" / "Charging" / "Error" / "Manual" |
| `connector_version` | package version | str | |

### 3.4 Mission Tracking
Publish `mission_tracking` key-value (dict) when a task is active. Fields:

| Field | Source | Notes |
|-------|--------|-------|
| `missionId` | `taskObj.taskId` | |
| `inProgress` | `!taskObj.isFinish && !taskObj.isCancel` | |
| `state` | derived | "Executing" / "Completed" / "Canceled" |
| `label` | task name from task details | cached per task |
| `startTs` | first time task seen | epoch ms |
| `completedPercent` | 1.0 if isFinish else 0.0 | no progress % in API |

### 3.5 Maps
| InOrbit Concept | Source | Notes |
|-----------------|--------|-------|
| Image | `GET /map/v1.1/area/{areaId}/base-map` | Binary image (format TBD — see Open Questions) |
| frame_id | `areaId` | |
| origin_x / origin_y | **Unknown** | API returns no map metadata — see Open Questions |
| resolution | **Unknown** | API returns no resolution — see Open Questions |

---

## 4. Command Handling

| Command | Script Name | API Endpoint | Parameters | Notes |
|---------|-------------|-------------|------------|-------|
| Navigate to POI | `navigate_to_poi` | `POST /task/v1.1` then `POST /task/v1.1/{id}/execute` | `poi_id: str`, `task_type: int = 4`, `run_type: int = 22` | Creates + immediately executes a Direct Delivery task to the POI |
| Go home / charge | `go_home` | `POST /task/v1.1` then execute | No user params | taskType=1 (return to charging station), runType=25 |
| Cancel task | `cancel_task` | `POST /task/v1.1/{taskId}/cancel` | `task_id: str` (optional — defaults to current task) | |
| Execute task | `execute_task` | `POST /task/v1.1/{taskId}/execute` | `task_id: str` | Execute a previously created task by ID |

> **Note:** AutoXing's task model separates task creation from execution. `navigate_to_poi`
> and `go_home` create a task and immediately execute it in one command handler.

---

## 5. Configuration Schema

### Connector-level (`connector_config`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `login_appcode` | str | no | APPCODE for login endpoint (default: `8184850f6ebe4edea8ba3e37ae46a35b`) |
| `api_appcode` | str | no | APPCODE for all other endpoints (default: `dd7afee0a068431abb2425ac622e70d2`) |
| `login_name` | str | yes | Email address for login |
| `password` | str | yes (env) | Plain-text password (connector encrypts before sending) |
| `open_id` | str | yes | User openId (from first manual login; used for ticket exchange) |
| `business_id` | str | yes | Primary businessId (from ticket exchange) |
| `base_url` | str | no | API base URL (default: `https://apiglobal.autoxing.com`) |
| `verify_ssl` | bool | no | SSL verification (default: `true`) |
| `request_timeout` | float | no | HTTP timeout in seconds (default: `30.0`) |

### Per-robot config

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `robot_id` | str | yes | InOrbit robot ID |
| `fleet_robot_id` | str | yes | AutoXing robot ID |
| `area_id` | str | no | Default area ID override (if not set, resolved from robot state) |

---

## 6. Error Handling & Retry

- HTTP retries: 3 attempts, exponential backoff with jitter (1–10 s), on 408/429/500/502/503/504
- Auth errors (401/403): trigger re-login
- Token expiry: proactive refresh at 90% of `expireTime`
- Per-robot errors: logged as warnings, robot skipped for that poll cycle
- `errors` array: published as-is; no interpretation of error codes (not documented in API)

---

## 7. Testing Strategy

- `test_config_models.py` — config validation, env prefix, defaults
- `test_api_client.py` — login flow, state fetch, task create/execute/cancel; mock with pytest-httpx
- `test_connector.py` — `_publish_robot_data`, `_compute_mission_status`, command dispatch

---

## 8. Open Questions

1. **AES password encryption**: The login endpoint requires an AES-encrypted password. The API
   docs don't specify the key, IV, or mode. This must be clarified before authentication can be
   implemented. Options: (a) capture from browser traffic, (b) ask AutoXing.

2. **Map metadata**: `GET /map/v1.1/area/{areaId}/base-map` returns binary image data but the
   API provides no origin (x, y) or resolution (m/px) fields. Maps cannot be correctly
   positioned without this. Options: (a) hardcode resolution from known robots, (b) ask AutoXing
   for a metadata endpoint, (c) make origin/resolution per-area configuration fields.

3. **Map image format**: Is the base-map a PNG, JPEG, or PGM? The Content-Type header will tell
   us, but this needs verification.

4. **Edge mission execution**: Should `navigate_to_poi` use cloud-level task dispatch (create +
   execute via REST) or edge mission execution (behavior trees dispatched locally)? REST dispatch
   is simpler and consistent with Keenon/Allybot approach.

5. **Token openId**: The `openId` is required for the ticket exchange (Step 2). Should it be a
   mandatory config field, or should the connector extract it from the Step 1 login response?

6. **Programmatic auth**: Are AutoXing willing to provision `appId`/`appSecret` for this
   integration? That would be cleaner than web-login credential reuse.
