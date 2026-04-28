# AutoXing Cloud Platform API Reference

> **Version:** v1.1.0  
> **API Base URL:** `https://apiglobal.autoxing.com`  
> **Web App URL:** `https://serviceglobal.autoxing.com`  
> **Auth:** All API endpoints require both `Authorization: APPCODE <code>` and `X-Token: <JWT>` headers.

---

## Domains & APPCODEs

| Purpose | APPCODE | Used For |
|---------|---------|----------|
| Login | `APPCODE 8184850f6ebe4edea8ba3e37ae46a35b` | `POST /user/v1.1/login` only |
| API calls | `APPCODE dd7afee0a068431abb2425ac622e70d2` | All other endpoints |

---

## Authentication (Web Login Flow)

Authentication is a two-step process. The login returns an initial JWT, then the ticket exchange returns a fresh 7-day JWT plus user profile data.

### Step 1 — Login

```
POST /user/v1.1/login
Authorization: APPCODE 8184850f6ebe4edea8ba3e37ae46a35b
Content-Type: application/json
Origin: https://serviceglobal.autoxing.com
Referer: https://serviceglobal.autoxing.com/
```

**Body Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| loginName | String | yes | Email address |
| password | String | yes | AES-encrypted password |

**Example Request:**

```bash
curl -X POST 'https://apiglobal.autoxing.com/user/v1.1/login' \
  -H 'Authorization: APPCODE 8184850f6ebe4edea8ba3e37ae46a35b' \
  -H 'Content-Type: application/json' \
  -H 'Origin: https://serviceglobal.autoxing.com' \
  -H 'Referer: https://serviceglobal.autoxing.com/' \
  -d '{"loginName":"user@example.com","password":"<encrypted_password>"}'
```

**Response:** Returns an initial token and key used in the next step.

### Step 2 — Get Ticket (User Info + Fresh Token)

```
GET /user/v1.0/ticket/{openId}
Authorization: APPCODE dd7afee0a068431abb2425ac622e70d2
X-Token: <token from Step 1>
Content-Type: application/json
Origin: https://serviceglobal.autoxing.com
Referer: https://serviceglobal.autoxing.com/
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| openId | String | yes | User's openId (from login or known) |

**Response:**

```json
{
  "status": 200,
  "message": "onGetUserInfo succ.",
  "data": {
    "openid": "521c59db24946f8991b5012c1e3f4055",
    "nickName": "DeliveranceEnterprises",
    "businessId": "672877e15796438e1f9f7c6c",
    "busIds": ["672877e15796438e1f9f7c6c"],
    "token": "eyJhbG...<fresh JWT>",
    "expireTime": 603800,
    "key": "e93284e7ba304d76",
    "role": 2,
    "userType": 3,
    "phoneNumber": "user@example.com",
    "code": "12000000448",
    "isAvail": true,
    "status": 1
  }
}
```

**Key response fields:**

| Field | Type | Description |
|-------|------|-------------|
| token | String | Fresh JWT (~7 day validity). Use as `X-Token` for all API calls |
| openid | String | User unique ID |
| businessId | String | Primary business ID |
| busIds | Array | All business IDs the user has access to |
| expireTime | Integer | Token validity in seconds |
| key | String | Token key ID |
| role | Integer | User role |
| userType | Integer | User type |

> After Step 2, use the returned `token` as `X-Token` header and `APPCODE dd7afee0a068431abb2425ac622e70d2` as `Authorization` header for all subsequent requests.

---

## Authentication (Programmatic API — Alternative)

For server-to-server integration, AutoXing also offers a programmatic token endpoint. This requires a dedicated `appId` and `appSecret` provisioned by AutoXing (separate from web login credentials).

```
POST /auth/v1.1/token
Authorization: <AppCode>
Content-Type: application/json
```

**Body Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| appId | String | yes | App ID (provisioned by AutoXing) |
| timestamp | Integer (int64) | yes | Current timestamp (ms) |
| sign | String | yes | Signature: `MD5(appId + timestamp + appSecret)` |

**Response:**

```json
{
  "status": 200,
  "message": "success",
  "data": {
    "key": "e2ac30ea7724442b",
    "token": "eyJh...ocDzA",
    "expireTime": 600
  }
}
```

> **Note:** This endpoint requires separately provisioned credentials. The web login APPCODEs and user credentials will NOT work here (tested — returns `"appId is invalid"`). Contact AutoXing to obtain `appId`/`appSecret` for programmatic access.

---

## Common Request Headers

All API endpoints (after authentication) require:

```
Authorization: APPCODE dd7afee0a068431abb2425ac622e70d2
X-Token: <JWT from login>
Content-Type: application/json
```

## Common Response Format

```json
{
  "status": 200,
  "message": "success",
  "data": { }
}
```

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 201 | Invalid parameter (e.g. invalid appId) |
| 400 | Parameter error |
| 500 | Internal error |

---

## Robot Endpoints

### Get Robot List

```
POST /robot/v1.1/list
```

**Body Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| keyWorld | String | no | Keyword filter (currently supports robot ID only) |
| pageSize | Integer | no | Page size (0 = no pagination) |
| pageNum | Integer | no | Page number |

**Example Request:**

```bash
curl -X POST 'https://apiglobal.autoxing.com/robot/v1.1/list' \
  -H 'Authorization: APPCODE dd7afee0a068431abb2425ac622e70d2' \
  -H 'X-Token: <JWT>' \
  -H 'Content-Type: application/json' \
  -d '{"pageSize": 20, "pageNum": 1}'
```

**Response Data:**

| Field | Type | Description |
|-------|------|-------------|
| count | Integer | Total matching robots |
| list[].robotId | String | Robot ID |
| list[].areaId | String | Current area ID |
| list[].isOnLine | Boolean | Whether robot is online |
| list[].isTask | Boolean | Whether robot is performing a task |
| list[].businessId | String | Business ID of the robot |
| list[].x | Number | X coordinate of current pose |
| list[].y | Number | Y coordinate of current pose |
| list[].yaw | Integer | Orientation angle (degrees) |
| list[].battery | Integer | Battery level (0–100) |

---

### Get Robot State

```
GET /robot/v1.1/{robotId}/state
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| robotId | String | yes | Robot ID |

**Response Data:**

| Field | Type | Description |
|-------|------|-------------|
| robotId | String | Robot ID |
| areaId | String | Current area ID |
| x | Number | X coordinate |
| y | Number | Y coordinate |
| yaw | Integer | Orientation angle (degrees) |
| speed | Number | Current driving speed |
| locQuality | Integer | Positioning accuracy (0–100) |
| battery | Integer | Battery level |
| hasObstruction | Boolean | Obstacles detected |
| isCharging | Boolean | Currently charging |
| isEmergencyStop | Boolean | Emergency stop pressed |
| isGoHome | Boolean | Returning to charging pile |
| isManualMode | Boolean | In manual mode |
| isRemoteMode | Boolean | In remote control mode |
| errors | Array of Integer | Fault codes |
| timestamp | Integer | Status timestamp |
| taskObj.taskId | String | Current task ID |
| taskObj.isFinish | Boolean | Task completed |
| taskObj.isCancel | Boolean | Task cancelled |

---

### Get Robot Deployment Info

```
GET /map/v1.1/robot/{robotId}/deploy
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| robotId | String | yes | Robot ID |

**Response Data:**

| Field | Type | Description |
|-------|------|-------------|
| activationTime | Integer | Activation time |
| businessId | String | Business ID |
| customerId | String | Customer ID |
| deployPlace | String | Building ID where deployed |
| deployState | String | Deployment status |

---

## Map Endpoints

### Get Area List

```
POST /map/v1.1/area/list
```

**Body Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| businessId | String | yes* | Business ID (*at least one of businessId or robotId required) |
| robotId | String | yes* | Robot ID |

**Response Data:**

| Field | Type | Description |
|-------|------|-------------|
| count | Integer | Total matching areas |
| list[].id | String | Area ID |
| list[].buildingId | String | Building ID |
| list[].businessId | String | Business ID |
| list[].createTime | Integer | Creation time |
| list[].floor | Integer | Floor number |
| list[].name | String | Area name |

---

### Get Map Image

```
GET /map/v1.1/area/{areaId}/base-map
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| areaId | String | yes | Area ID |

**Response:** Binary image data of the map.

---

### Get POI List

```
POST /map/v1.1/poi/list
```

**Body Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| businessId | String | yes* | Business ID (*at least one of businessId, robotId, areaId required; priority: businessId > robotId > areaId) |
| robotId | String | yes* | Robot ID |
| areaId | String | yes* | Area ID |
| type | Integer | no | POI type filter |
| pageSize | Integer | no | Page size |
| pageNum | Integer | no | Page number |

**Response Data:**

| Field | Type | Description |
|-------|------|-------------|
| count | Integer | Total matching POIs |
| list[].id | String | POI ID |
| list[].areaId | String | Area ID |
| list[].buildingId | String | Building ID |
| list[].businessId | String | Business ID |
| list[].coordinate | Array of Number | POI coordinates `[x, y]` |
| list[].floor | Integer | Floor |
| list[].name | String | POI name |
| list[].type | Integer | POI type |
| list[].yaw | Integer | Orientation angle (degrees) |
| list[].properties | Object | Attached properties |

---

### Get POI Detail

```
GET /map/v1.1/poi/{poiId}
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| poiId | String | yes | POI ID |

**Response Data:**

| Field | Type | Description |
|-------|------|-------------|
| id | String | POI ID |
| buildingId | String | Building ID |
| businessId | String | Business ID |
| areaId | String | Area ID |
| floor | Integer | Floor |
| name | String | POI name |
| type | Integer | POI type |
| coordinate | Array of Number | Coordinates `[x, y]` |
| properties | Object | Attached properties |
| yaw | Integer | Orientation angle (degrees) |

---

### Create POI

```
PUT /map/v1.1/poi/{areaId}
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| areaId | String | yes | Area ID |

**Body Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | String | no | Site name |
| coordinate | Array of Number | yes | Site coordinates `[x, y]` |
| yaw | Integer | no | Orientation angle (degrees) |

**Response Data:** `data` contains the ID of the new site (String).

---

### Delete POI

```
DELETE /map/v1.1/poi/{poiId}
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| poiId | String | yes | POI ID |

---

## Task Endpoints

### Create Task

```
POST /task/v1.1
```

**Body Parameters (NewTaskRequest):**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | String | yes | Task name |
| robotId | String | yes | Robot ID to execute the task |
| routeMode | Integer | no | 1: sequential routing (default), 2: shortest distance routing |
| runMode | Integer | no | 1: flexible obstacle avoidance (default), 2: trajectory-based travel |
| runNum | Integer | no | Execution count (default 1, 0 = infinite loop) |
| taskType | Integer | yes | Task type (see enum below) |
| runType | Integer | yes | Run type (see enum below) |
| sourceType | Integer | no | Task source (see enum below) |
| ignorePublicSite | Boolean | no | Whether to ignore public sites (default false) |
| speed | Number | no | Travel speed in m/s (recommended 0.4–1.0) |
| curPt | Point | no | Current point |
| taskPts | Array | yes | List of mission points (see below) |
| backPt | Point | no | Return point |

**taskType Enum:**

| Value | Description |
|-------|-------------|
| 0 | Disinfection |
| 1 | Return to charging station |
| 2 | Restaurant |
| 3 | Hotel |
| 4 | Delivery (five-in-one) |
| 5 | Factory |
| 6 | Chassis mini-program |

**runType Enum:**

| Value | Description |
|-------|-------------|
| 0 | Scheduled disinfection |
| 1 | Temporary disinfection |
| 20 | Quick meal delivery |
| 21 | Multi-point meal delivery |
| 22 | Direct delivery |
| 23 | Roaming |
| 24 | Return |
| 25 | Charging station |
| 26 | Summon |
| 27 | Birthday mode |
| 28 | Guiding |
| 29 | Lifting |
| 30 | Lifting cruise |
| 31 | Flexible carry |

**sourceType Enum:**

| Value | Description |
|-------|-------------|
| 0 | Unknown |
| 1 | Head shell App |
| 2 | Chassis mini program |
| 3 | Pager |
| 4 | Chassis |
| 5 | Dispatch |
| 6 | Secondary development |
| 7 | Pad App |

**Point Object:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| areaId | String | yes | Area ID |
| x | Number (float) | yes | X coordinate |
| y | Number (float) | yes | Y coordinate |
| yaw | Integer | no | Orientation angle (degrees) |
| type | Integer | no | POI type (-1 default, 9 = charging pile, 10 = standby point) |
| stopRadius | Number (float) | no | Stopping radius (default 1) |

**Task Point (taskPts item):** Extends Point with:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| ext | Object | yes | Extended data |
| ext.name | String | yes | Mission point name |
| ext.id | String | yes | Mission point ID |
| ext.idx | Array of Integer | no | Tray index list |
| stepActs | Array | no | Actions at this point (see StepActs below) |

**Response:**

```json
{
  "status": 200,
  "message": "success",
  "data": {
    "taskId": "<new_task_id>"
  }
}
```

---

### StepActs — Task Point Actions

Each task point can have a list of actions (`stepActs`). Each action has a `type` and `data` field.

#### PlayAction (Audio)

| Field | Type | Description |
|-------|------|-------------|
| type | Integer | 5 = play audio, 36 = close audio |
| data.mode | Integer | 1 = upper computer, 2 = chassis |
| data.audioId | String | Chassis audio resource ID |
| data.url | String | Audio URL |
| data.volume | Integer | Volume (0–100) |
| data.interval | Integer | Loop interval in seconds (-1 = play once) |
| data.num | Integer | Total play count |
| data.duration | Integer | Total playback duration (seconds) |

#### DoorAction (Cabin Door)

| Field | Type | Description |
|-------|------|-------------|
| type | Integer | 6 = open cabin door, 28 = close cabin door |
| data.mode | Integer | 1 = upper computer, 2 = chassis |
| data.doorIds | Array of Integer | Door numbers (range 1–4) |

#### PauseAction

| Field | Type | Description |
|-------|------|-------------|
| type | Integer | 18 = pause |
| data.pauseTime | Integer | Pause duration (seconds) |

#### GearAction (Spray)

| Field | Type | Description |
|-------|------|-------------|
| type | Integer | 32 = open/close spray |
| data.subType | Integer | Spray gear (0–5, 0 = close) |

#### LightAction (Light Strip)

| Field | Type | Description |
|-------|------|-------------|
| type | Integer | 37 = turn on, 38 = turn off |
| data.mode | Integer | 1 = upper computer, 2 = chassis |
| data.color | Integer | Light strip color |
| data.indexs | Array | Segment light strip list |

#### SpeedAction

| Field | Type | Description |
|-------|------|-------------|
| type | Integer | 41 = set speed |
| data.speed | Number | Speed in m/s (recommended 0.4–1.0) |

#### InteractAction

| Field | Type | Description |
|-------|------|-------------|
| type | Integer | 40 = wait for interaction |
| data | Object | Empty object `{}` |

---

### Get Task List

```
POST /task/v1.1/list
```

**Body Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| pageSize | Integer | no | Page size (0 = no pagination) |
| pageNum | Integer | no | Page number (default 1) |
| startTime | Integer (int64) | no | Start time (timestamp ms) |
| endTime | Integer (int64) | no | End time (timestamp ms) |

**Response Data:**

| Field | Type | Description |
|-------|------|-------------|
| count | Integer | Total matching tasks |
| list[].taskId | String | Task ID |
| list[].name | String | Task name |
| list[].robotId | String | Robot ID |
| list[].buildingId | String | Building ID |
| list[].businessId | String | Business ID |
| list[].busiType | String | Task type |
| list[].isExecute | Boolean | Whether executed |
| list[].isCancel | Boolean | Whether cancelled |
| list[].isDel | Boolean | Whether deleted |
| list[].createTime | Integer | Creation time |

---

### Get Task Details

```
GET /task/v1.1/{taskId}
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| taskId | String | yes | Task ID |

**Response Data:** Full Task object (same as task list fields plus taskPts, curPt, backPt).

---

### Update Task

```
POST /task/v1.1/{taskId}
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| taskId | String | yes | Task ID |

**Body Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| taskPts | Array | no | Updated mission points |
| taskPts[].index | Integer | no | Task point index (starting from 0) |
| taskPts[].isPass | Boolean | no | Whether the point has passed |
| taskPts[].stepActs | Array | no | Actions at this point |

---

### Execute Task

```
POST /task/v1.1/{taskId}/execute
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| taskId | String | yes | Task ID |

---

### Cancel Task

```
POST /task/v1.1/{taskId}/cancel
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| taskId | String | yes | Task ID |

---

### Delete Task

```
DELETE /task/v1.1/{taskId}
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| taskId | String | yes | Task ID |

---

## User Endpoints

### Get User List

```
POST /user/v1.1/list
```

**Response Data:**

| Field | Type | Description |
|-------|------|-------------|
| userItems | Array | User list |
| adminItems | Array | Administrator list |
| applyItems | Array | User application list |

**User Fields:**

| Field | Type | Description |
|-------|------|-------------|
| nickName | String | User nickname |
| avatarUrl | String | User avatar URL |
| role | Integer | User role type |
| phoneNumber | String | Phone number or email |
| delete | Boolean | Whether deleted |
| timestamp | Integer | Info update timestamp |

---

### Generate User Ticket

```
PUT /user/v1.1/ticket
```

**Body Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| openId | String | no | User ID (if not provided, extracted from token) |

**Response:**

```json
{
  "status": 200,
  "message": "success",
  "data": {
    "ticket": "463c69e17b9856b6594abd56adcc87cd"
  }
}
```

---

## Building Endpoints

### Get Building List

```
POST /building/v1.1/list
```

**Response Data:**

| Field | Type | Description |
|-------|------|-------------|
| list[].id | String | Building ID |
| list[].name | String | Building name |
| list[].type | String | Building type |
| list[].customerId | String | Customer ID |
| list[].businessId | String | Business ID |
| list[].floors | Array | Floor correspondence table |
| list[].floors[].serialNumber | Integer | Actual floor number |
| list[].floors[].name | String | Display floor name |
| list[].province | String | Province ID |
| list[].city | String | City ID |
| list[].area | String | District ID |
| list[].address | String | Specific address |
| list[].coordinates | Array of Number | Geographic coordinates |
| list[].editable | Boolean | Whether editable |
| list[].createTime | Integer | Creation time |

---

## Business Endpoints

### Get Business List

```
POST /business/v1.1/list
```

**Response Data:**

| Field | Type | Description |
|-------|------|-------------|
| list[].id | String | Business ID |
| list[].name | String | Business name |
| list[].type | Integer | Business type (see enum) |
| list[].address | String | Business address |
| list[].customerId | String | Owner ID |
| list[].buildingId | String | Building ID |
| list[].createTime | Integer | Creation time |
| groups[].id | String | Group ID |
| groups[].name | String | Group name |
| groups[].busList | Array | Businesses in group |

**Business Type Enum:**

| Value | Description |
|-------|-------------|
| 1 | Restaurant |
| 2 | Hotel |
| 3 | Disinfect |
| 4 | Office Building |
| 5 | Factory |

---

## API Endpoint Summary

| Method | Path | Description |
|--------|------|-------------|
| **Authentication (Web Login)** | | |
| POST | `/user/v1.1/login` | Login with email + encrypted password |
| GET | `/user/v1.0/ticket/{openId}` | Exchange token for user info + fresh JWT |
| **Authentication (Programmatic)** | | |
| POST | `/auth/v1.1/token` | Get token via appId/appSecret/sign (requires separate credentials) |
| **Robot** | | |
| POST | `/robot/v1.1/list` | Get robot list |
| GET | `/robot/v1.1/{robotId}/state` | Get robot state |
| GET | `/map/v1.1/robot/{robotId}/deploy` | Get robot deployment info |
| **Map** | | |
| POST | `/map/v1.1/area/list` | Get area list |
| GET | `/map/v1.1/area/{areaId}/base-map` | Get map image |
| POST | `/map/v1.1/poi/list` | Get POI list |
| GET | `/map/v1.1/poi/{poiId}` | Get POI detail |
| PUT | `/map/v1.1/poi/{areaId}` | Create POI |
| DELETE | `/map/v1.1/poi/{poiId}` | Delete POI |
| **Task** | | |
| POST | `/task/v1.1` | Create task |
| POST | `/task/v1.1/list` | Get task list |
| GET | `/task/v1.1/{taskId}` | Get task details |
| POST | `/task/v1.1/{taskId}` | Update task |
| POST | `/task/v1.1/{taskId}/execute` | Execute task |
| POST | `/task/v1.1/{taskId}/cancel` | Cancel task |
| DELETE | `/task/v1.1/{taskId}` | Delete task |
| **User** | | |
| POST | `/user/v1.1/list` | Get user list |
| PUT | `/user/v1.1/ticket` | Generate user ticket |
| **Building** | | |
| POST | `/building/v1.1/list` | Get building list |
| **Business** | | |
| POST | `/business/v1.1/list` | Get business list |
