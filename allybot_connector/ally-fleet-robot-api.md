# Ally-Fleet Robot API Reference

> **Version:** v2023-02-09  
> **Base URL:** `http://127.0.0.1`  
> **Auth:** All authenticated endpoints require the header `x-token: <JWT>`

---

## Authentication

All endpoints (except register/login) require a JWT token passed via the `x-token` request header. Obtain this token by calling the login endpoint.

---

## Map Endpoints

### List User Maps (Paginated)

```
GET /map/mapPage
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| page | int | yes | Page index |
| pageSize | int | yes | Page size |
| projectId | string | yes | Project ID |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/map/mapPage?page=1&pageSize=20&projectId=001'
```

**Response:**

```json
{
  "code": 619,
  "message": "success",
  "generalMessage": "success",
  "data": [
    {
      "mapCount": 1,
      "maps": [
        {
          "createdTime": 1626157972000,
          "creator": "cbc5968cb602fb10e446ecc7c6f0c249",
          "deleted": 0,
          "floorNum": 30,
          "freeThresh": 0.05,
          "image": "map.png",
          "imagePath": null,
          "lastUpdated": 1626157972000,
          "mapDesc": "",
          "mapId": "01093115f5d29fd5913cef81392fce6e",
          "mapName": "cloud30_0713_01",
          "mapPath": "/home/zhihui/AutoRS_v2/data/20210713143138/",
          "mapUrl": "/resource/map/20210713143309/map.png",
          "negate": 0,
          "occupiedThresh": 0.1,
          "origin": null,
          "originStr": "[-119.42, -133.83, 0.0]",
          "project": null,
          "projectId": "001",
          "resolution": 0.05,
          "robot": { "robotId": "9b46471e179341b745bcc3625eb15ea7" },
          "robotId": "9b46471e179341b745bcc3625eb15ea7",
          "version": 0
        }
      ]
    }
  ]
}
```

**Key Map Fields:**

| Field | Type | Description |
|-------|------|-------------|
| mapId | string | Map ID |
| mapName | string | Map name |
| projectId | string | Project this map belongs to |
| floorNum | int | Floor number |
| resolution | float | Map resolution — 1 pixel = this many meters |
| originStr | string | Navigation origin offset vector from bottom-left corner `[x, y, z]` |
| mapUrl | string | Static resource URL for the map image |
| robotId | string | Robot that recorded this map |
| deleted | int | 0 = active, 1 = deleted |
| createdTime | long | Created timestamp (ms) |
| lastUpdated | long | Last updated timestamp (ms) |

---

### Find All Robots Using a Map

```
GET /map/robot
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| mapId | string | yes | Map ID |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/map/robot?mapId=048290a54abc8684b36e5bcf0dfc6f3d'
```

**Response:**

```json
{
  "code": 619,
  "message": "success",
  "generalMessage": "success",
  "data": [
    {
      "robotId": "c9b79ae24d8cfa93e9b94f4d046897c4",
      "robotType": 3
    }
  ]
}
```

---

### Get All Semantic Shapes on a Map

```
GET /map/baseShape
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| mapId | string | yes | Map ID |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/map/baseShape?mapId=048290a54abc8684b36e5bcf0dfc6f3d'
```

**Response:**

```json
{
  "code": 772,
  "message": "success",
  "generalMessage": "success",
  "data": [
    {
      "shapeId": "0d064e503d4af4177c18fe247e390610",
      "mapId": "048290a54abc8684b36e5bcf0dfc6f3d",
      "shapeName": "区域1",
      "createdBy": "cbc5968cb602fb10e446ecc7c6f0c249",
      "pointSeq": "-7.106466,-6.106466,0,-2.889677,-1.889677,0,1.258731,2.258731,0,-3.030342,-2.030342,0",
      "shapeDesc": "",
      "shapeType": 1,
      "lastUpdated": 1644581861000,
      "points": [
        { "x": -7.106466, "y": -6.106466 },
        { "x": -2.889677, "y": -1.889677 },
        { "x": 1.258731, "y": 2.258731 },
        { "x": -3.030342, "y": -2.030342 }
      ],
      "baseHeight": 0,
      "height": 2,
      "colorIndex": "#1E90FF"
    }
  ]
}
```

**Key Shape Fields:**

| Field | Type | Description |
|-------|------|-------------|
| shapeId | string | Region/shape ID |
| shapeName | string | Region name |
| shapeType | int | Region type |
| points | array | Polygon vertices `[{x, y}, ...]` |
| pointSeq | string | Comma-separated point sequence |
| baseHeight | float | Base height |
| height | float | Height |
| colorIndex | string | Display color (hex) |

---

### Get Map Details by Map ID

```
GET /map/mapInfo
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| mapId | string | no | Map ID |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/map/mapInfo?mapId=048290a54abc8684b36e5bcf0dfc6f3d'
```

**Response:**

```json
{
  "code": 604,
  "message": "success",
  "generalMessage": "success",
  "data": {
    "mapId": "048290a54abc8684b36e5bcf0dfc6f3d",
    "projectId": "001",
    "floorNum": 0,
    "creator": "75cf99df044366f99db8afbb9bd50bf4",
    "robotId": "c38860b9096f90e79e766e737786d94b",
    "mapName": "Test",
    "mapPath": "/home/zhihui/AutoRS_v2/data/Test/",
    "mapUrl": "/resource/map/20210605195136/map.png",
    "image": "map.png",
    "resolution": 0.05,
    "originStr": "[-19.0, -35.0, 0.0]",
    "occupiedThresh": 0.1,
    "negate": 0,
    "freeThresh": 0.05,
    "createdTime": 1622893890000,
    "lastUpdated": 1622893890000,
    "version": 0,
    "mapDesc": "",
    "deleted": 0,
    "imagePath": "/resource/map/20210605195136/map.png",
    "origin": [-19, -35, 0],
    "project": null,
    "robot": null
  }
}
```

---

### Get Plans by Map ID

```
GET /map/mapPlan
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| mapId | string | no | Map ID |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/map/mapPlan?mapId=103'
```

**Response:**

```json
{
  "code": 552,
  "message": "success",
  "generalMessage": "success",
  "data": [
    {
      "planId": "a51ca8bc12a9fb327dd5a731402aa6e5",
      "mapId": "01093115f5d29fd5913cef81392fce6e",
      "planName": "lishun",
      "planType": 2,
      "planDesc": null,
      "lastUpdated": 1645002782000,
      "createdBy": null,
      "deleted": null,
      "points": [],
      "baseMap": { "mapId": "...", "mapName": "...", "..." : "..." },
      "virtualWalls": []
    }
  ]
}
```

---

### Get Plan Details by Plan ID

```
GET /map/plan
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| planId | string | yes | Plan ID |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/map/plan?planId=103'
```

---

### Get Virtual Walls

```
GET /map/virtualWall
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| planId | string | no | Plan ID |
| wallId | string | no | Virtual wall ID |

At least one of `planId` or `wallId` should be specified.

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/map/virtualWall?planId=103&wallId=103'
```

**Response:**

```json
{
  "code": 334,
  "message": "success",
  "generalMessage": "success",
  "data": [
    {
      "wallId": "7045c63924fc52a9449378d06c4bde7a",
      "planId": "a96e8f744bb6096a95bc572ec1e03ae9",
      "wallName": null,
      "lastUpdated": 1644889067000,
      "createdBy": "4a0bcdc02d7a53e69249a342a4fe70d6",
      "pointSeq": "7.9188747,1.2462845,0,5.205101,-9.258129,0",
      "expansion": 1.5,
      "wallDesc": null,
      "deleted": 0,
      "points": [
        { "x": 7.918875, "y": 1.246285 },
        { "x": 5.205101, "y": -9.258129 }
      ],
      "mapPlan": null
    }
  ]
}
```

**Key Virtual Wall Fields:**

| Field | Type | Description |
|-------|------|-------------|
| wallId | string | Virtual wall ID |
| planId | string | Parent plan ID |
| wallName | string | Wall name |
| expansion | float | Wall width |
| points | array | Wall endpoint coordinates |
| deleted | int | 0 = active, 1 = deleted |

---

### Bind/Subscribe to Map Realtime Messages

```
GET /map/binding
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| userId | string | no | User ID (extracted from `x-token` header) |
| mapId | string | no | Map ID |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/map/binding?mapId=103&userId=103'
```

**Response:**

```json
{
  "code": 593,
  "message": "success",
  "generalMessage": "success",
  "data": null
}
```

---

## Robot Endpoints

### Get All Available Robots on a Map

```
GET /robot/available
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| mapId | string | yes | Map ID |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/robot/available?mapId=103'
```

**Response:**

```json
{
  "code": 930,
  "message": "success",
  "generalMessage": "success",
  "data": [
    {
      "robotId": "c38860b9096f90e79e766e737786d94b",
      "robotName": "10112"
    }
  ]
}
```

---

### Get Single Robot Info

```
GET /robot/singleRobotInfo
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| robotId | string | yes | Robot ID |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/robot/singleRobotInfo?robotId=103'
```

**Response:** Returns full robot object including nested `project`, `baseMap`, and `organization` objects.

**Key Robot Fields:**

| Field | Type | Description |
|-------|------|-------------|
| robotId | string | Robot ID |
| robotName | string | Robot name |
| robotAlias | string | Robot alias |
| robotType | int | Robot type |
| robotBatch | string | Robot batch number |
| aliveStatus | int | Online status |
| sizeLength | float | Robot length |
| sizeWidth | float | Robot width |
| sizeHeight | float | Robot height |
| lastOnline | long | Last online timestamp (ms) |
| orgId | string | Organization ID |
| projectId | string | Project ID |
| mapId | string | Current map ID |
| deleted | int | 0 = active, 1 = deleted |

---

### Get All Robots on a Map

```
GET /robot/mapRobots
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| mapId | string | no | Map ID |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/robot/mapRobots?mapId=103'
```

**Response:** Returns array of robot objects (same schema as single robot info, without nested details).

---

### List All Robots in Organization (Paginated)

```
GET /robot/robotPage
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| organizationId | string | no | Organization ID |
| page | int | no | Page index |
| pageSize | int | no | Page size |
| projectName | string | no | Filter by project name |
| robotId | string | no | Filter by robot ID |
| robotType | int | no | Filter by robot type |
| aliveStatus | int | no | Filter by alive status |
| orgName | string | no | Filter by org name |
| robotAlias | string | no | Filter by robot alias |
| robotBatch | string | no | Filter by batch number |
| orgId | string | no | Filter by org ID |
| projectId | string | no | Filter by project ID |
| mapId | string | no | Filter by map ID |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/robot/robotPage?page=1&pageSize=10&orgId=001'
```

**Response:**

```json
{
  "code": 823,
  "message": "success",
  "generalMessage": "success",
  "data": {
    "count": 41,
    "robots": [
      {
        "robotId": "...",
        "robotName": "...",
        "robotAlias": "...",
        "robotType": 3,
        "aliveStatus": 1,
        "orgId": "001",
        "projectId": "001",
        "mapId": "...",
        "project": { "..." },
        "baseMap": { "..." },
        "organization": { "..." }
      }
    ]
  }
}
```

---

### Bind/Subscribe to Robot Realtime Messages

```
GET /robot/binding
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| userId | string | no | User ID (from `x-token`) |
| robotId | string | yes | Robot ID |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/robot/binding?userId=103&robotId=103'
```

**Response:**

```json
{
  "code": 700,
  "message": "success",
  "generalMessage": "success",
  "data": null
}
```

---

## Task Endpoints

### Get Task Information

```
GET /task/task
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| taskId | string | yes | Task ID |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/task/task?taskId=103'
```

**Response:**

```json
{
  "code": 665,
  "message": "success",
  "generalMessage": "success",
  "data": {
    "taskId": "023c008fc1905283a43c0936781a5dd4",
    "taskCode": "test2",
    "execCron": "00 00 00 28 01 ? 2022",
    "taskMode": 2,
    "autoContinue": 1,
    "autoReturn": 1,
    "createdTime": "2022-01-27 04:45:53",
    "createdBy": "75cf99df044366f99db8afbb9bd50bf4",
    "startTime": "00:00:00",
    "endTime": "23:59:59",
    "repetition": 1000,
    "scheduleStatus": 0,
    "taskDesc": null,
    "deleted": 0,
    "projectId": "001",
    "activated": 1,
    "arrangeCode": 0,
    "arrangeTime": null,
    "defaultTask": true,
    "cleanIntensity": 0,
    "robotId": "cd7147988c011cda9680b2d395dd1336",
    "jobList": [
      {
        "jobId": "d3a8164f118caf0aa061940cc6720321",
        "jobCode": "taskJob_1643229953013",
        "taskId": "023c008fc1905283a43c0936781a5dd4",
        "serialNum": 0,
        "planId": "93544477f4d0ca076640b068eace174c",
        "planName": "ha",
        "mapId": "7dfb204381eed3b2129b01aafc333ca6",
        "mapName": "T001",
        "jobType": 2,
        "issuedBy": "75cf99df044366f99db8afbb9bd50bf4",
        "repetition": 1,
        "jobPoints": "-3.453,16.955,0.01,0.0,0.0,0.0,1.0,...",
        "status": 0,
        "deleted": 0,
        "listJobPoint": [
          {
            "pointId": null,
            "mapId": null,
            "pointName": null,
            "pointType": null,
            "position": { "x": -3.453, "y": 16.955, "z": 0.01 },
            "orientation": { "x": 0, "y": 0, "z": 0, "w": 1 }
          }
        ],
        "jobArea": 0,
        "coverArea": 0,
        "uncoveredArea": 0,
        "percentCoverArea": 0,
        "percentComplete": 0,
        "patrolJob": false,
        "regionalJob": true,
        "routeJob": false
      }
    ]
  }
}
```

**Key Task Fields:**

| Field | Type | Description |
|-------|------|-------------|
| taskId | string | Task ID |
| taskCode | string | Task code/name |
| execCron | string | Cron schedule expression |
| taskMode | int | Task mode |
| autoContinue | int | 1 = auto continue |
| autoReturn | int | 1 = auto return after completion |
| startTime | string | Daily start time |
| endTime | string | Daily end time |
| repetition | int | Number of repetitions |
| scheduleStatus | int | Schedule status |
| activated | int | 1 = activated |
| cleanIntensity | int | Cleaning intensity level |
| robotId | string | Assigned robot ID |
| jobList | array | List of jobs in this task |

**Key Job Fields:**

| Field | Type | Description |
|-------|------|-------------|
| jobId | string | Job ID |
| jobCode | string | Job code |
| jobType | int | Job type |
| planId | string | Plan ID |
| planName | string | Plan name |
| mapId | string | Map ID |
| mapName | string | Map name |
| repetition | int | Repetition count |
| status | int | Job status |
| jobArea | float | Total job area |
| coverArea | float | Covered area |
| uncoveredArea | float | Uncovered area |
| percentCoverArea | float | Coverage percentage |
| percentComplete | float | Completion percentage |
| routeJob | bool | Is route-type job |
| regionalJob | bool | Is region-type job |
| patrolJob | bool | Is patrol-type job |
| listJobPoint | array | Job waypoints with position `{x,y,z}` and orientation `{x,y,z,w}` |

---

## Task Control Endpoints (verified 2026-04-27)

These endpoints drive the full lifecycle of a cleaning task on a robot:
list available tasks → optional reachability check → start → pause / resume / cancel.
All requests use the standard `/fleetapi` headers documented under
[Device Endpoints](#device-endpoints) (`Token`, `Mobile-User-Id`, `X-Api-Version: 184`,
`Language`, `Robot-Id: <null>`).

### Standard Task-Control Headers

```
Token: <token>
Mobile-User-Id: <openid>
X-Api-Version: 184
Language: en_US
Content-Type: application/x-www-form-urlencoded
Robot-Id: <null>
```

> Authentication for these endpoints is duplicated in **both** the `Token` /
> `Mobile-User-Id` headers **and** the `openid` / `token` body or query parameters.
> Both sets are sent in the captured traffic — include both for compatibility.

---

### List Cleaning Tasks for a Robot

Returns the saved cleaning schedules / tasks for a robot. Use the returned `id`
as `taskId` when starting a task.

```
POST /fleetapi/clean/list
Content-Type: application/x-www-form-urlencoded
```

**Body Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| id | string | yes | Robot device ID |
| page | int | yes | Page index (1-based) |
| pageSize | int | yes | Page size |
| type | int | yes | Task type filter (`0` = all) |
| openid | string | yes | Mobile user ID |
| token | string | yes | Auth token |

**Example Request:**

```bash
curl -X POST \
  -H "Token: <token>" \
  -H "Mobile-User-Id: 72426fd7de4cb929dc2645378fc4e7dd" \
  -H "X-Api-Version: 184" \
  -H "Language: en_US" \
  -H "Robot-Id: <null>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "id=6d70603da0cb3d00ba104a191770170b&page=1&pageSize=20&type=0&openid=72426fd7de4cb929dc2645378fc4e7dd&token=672f4106d95d4b88946f2c8c21f167f9" \
  "http://116.205.178.152:28080/fleetapi/clean/list"
```

**Response:**

```json
{
  "code": 200,
  "message": "SUCCESS",
  "generalMessage": null,
  "data": [
    {
      "id": "ae3178a170b0f97b40e783e7f9dad747",
      "name": "Espaitec",
      "time": "09:30:58-15:43:58",
      "start": "09:30:58",
      "end": "15:43:58",
      "status": 1,
      "mode": "3",
      "modeType": "1",
      "scheType": "4",
      "scheDate": "2,3,4,5,6",
      "isDefault": 0,
      "repeat": 1,
      "mapName": "DELIVERANCE",
      "daySpan": null,
      "carpetType": null
    }
  ]
}
```

**Key Task Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Task ID — pass as `taskId` to start the task |
| `name` | string | Task name |
| `status` | int | `1` = active schedule, `0` = inactive |
| `mode` / `modeType` | string | Cleaning mode |
| `scheType` | string | Schedule type (`1` = once, `4` = weekly recurring) |
| `scheDate` | string | Days of week, comma-separated (`2,3,4,5,6` = Mon–Fri) |
| `start` / `end` | string | Daily start / end time |
| `mapName` | string | Map this task runs on |
| `isDefault` | int | `1` = default task |

---

### Check Task Plan Reachability (pre-flight)

Optional pre-flight check before starting a task — confirms that the robot can
reach the task's start point on its current map. Always called by the mobile
app immediately before `clean/default/start`.

```
GET /fleetapi/task/plan/reachable
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| robotId | string | yes | Robot device ID |
| taskId | string | yes | Task ID (from `clean/list`) |
| planId | string | no | Plan ID (leave empty for default) |

**Example Request:**

```bash
curl -X GET \
  -H "Token: <token>" \
  -H "Mobile-User-Id: 72426fd7de4cb929dc2645378fc4e7dd" \
  -H "X-Api-Version: 184" \
  -H "Language: en_US" \
  -H "Robot-Id: <null>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  "http://116.205.178.152:28080/fleetapi/task/plan/reachable?planId=&robotId=6d70603da0cb3d00ba104a191770170b&taskId=ae3178a170b0f97b40e783e7f9dad747"
```

**Response (map mismatch warning):**

```json
{
  "code": 200,
  "message": "The current map is \"DELIVERANCE\", please confirm whether it is consistent with the location of the robot",
  "generalMessage": null,
  "data": null
}
```

> The `code: 200` is returned even when the server is asking the user to confirm
> the active map — `message` carries the human-readable warning. Surface the
> `message` to the operator before sending `clean/default/start`.

---

### Start a Task

Dispatches the named task to the robot. The robot transitions out of `Charging`
and begins navigating to the task's first waypoint.

```
POST /fleetapi/clean/default/start
Content-Type: application/x-www-form-urlencoded
```

**Body Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| id | string | yes | Robot device ID |
| taskId | string | yes | Task ID to run (from `clean/list`) |
| reachChargePoint | bool | yes | `true` = robot returns to dock after task; `false` = stay where it finished |
| openid | string | yes | Mobile user ID |
| token | string | yes | Auth token |

**Example Request:**

```bash
curl -X POST \
  -H "Token: <token>" \
  -H "Mobile-User-Id: 72426fd7de4cb929dc2645378fc4e7dd" \
  -H "X-Api-Version: 184" \
  -H "Language: en_US" \
  -H "Robot-Id: <null>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "id=6d70603da0cb3d00ba104a191770170b&taskId=ae3178a170b0f97b40e783e7f9dad747&reachChargePoint=false&openid=72426fd7de4cb929dc2645378fc4e7dd&token=672f4106d95d4b88946f2c8c21f167f9" \
  "http://116.205.178.152:28080/fleetapi/clean/default/start"
```

**Response (success):**

```json
{
  "code": 200,
  "message": "SUCCESS",
  "generalMessage": null,
  "data": true
}
```

`data: true` confirms the task was accepted and dispatched. After ~5–10 seconds,
`device/usestatus` will reflect `haveTaskRunning: true` and `work_status` will
change from `"Charging"` to the task's working state.

---

### Get Running Task Path

Returns the live planned path of the currently running task. Returns `data: null`
when no task is running or the path has not yet been computed.

```
GET /fleetapi/task/plan/path/running
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| robotId | string | yes | Robot device ID |

**Example Request:**

```bash
curl -X GET \
  -H "Token: <token>" \
  -H "Mobile-User-Id: 72426fd7de4cb929dc2645378fc4e7dd" \
  -H "X-Api-Version: 184" \
  -H "Language: en_US" \
  -H "Robot-Id: <null>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  "http://116.205.178.152:28080/fleetapi/task/plan/path/running?robotId=6d70603da0cb3d00ba104a191770170b"
```

**Response:**

```json
{
  "code": 200,
  "message": "SUCCESS",
  "generalMessage": null,
  "data": null
}
```

> The mobile app polls this endpoint shortly after `clean/default/start` to
> render the live route on the map. Live position updates come from the App
> WebSocket (`device_position`), not this endpoint.

---

### Pause / Resume / Cancel a Running Task

A single endpoint controls every state transition on a running task. The action
is selected by the `type` query parameter.

```
POST /fleetapi/device/taskaction
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| openid | string | yes | Mobile user ID |
| token | string | yes | Auth token |
| id | string | yes | Robot device ID |
| type | int | yes | Action — see table below |

**`type` action mapping:**

| `type` | Action | When to use |
|--------|--------|-------------|
| `0` | **Resume / Continue** | Resume a paused task |
| `1` | **Pause** | Suspend the running task; robot stops in place |
| `2` | **Stop / Cancel** | Cancel the running task; robot exits the working state |

**Body:** empty (`Content-Length: 0`). All parameters travel in the query string.

**Example — Pause (`type=1`):**

```bash
curl -X POST \
  -H "Token: <token>" \
  -H "Mobile-User-Id: 72426fd7de4cb929dc2645378fc4e7dd" \
  -H "X-Api-Version: 184" \
  -H "Language: en_US" \
  -H "Robot-Id: <null>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "Content-Length: 0" \
  "http://116.205.178.152:28080/fleetapi/device/taskaction?openid=72426fd7de4cb929dc2645378fc4e7dd&id=6d70603da0cb3d00ba104a191770170b&token=672f4106d95d4b88946f2c8c21f167f9&type=1"
```

**Example — Resume (`type=0`):**

```bash
curl -X POST \
  -H "Token: <token>" \
  -H "Mobile-User-Id: 72426fd7de4cb929dc2645378fc4e7dd" \
  -H "X-Api-Version: 184" \
  -H "Language: en_US" \
  -H "Robot-Id: <null>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "Content-Length: 0" \
  "http://116.205.178.152:28080/fleetapi/device/taskaction?openid=72426fd7de4cb929dc2645378fc4e7dd&id=6d70603da0cb3d00ba104a191770170b&token=672f4106d95d4b88946f2c8c21f167f9&type=0"
```

**Example — Cancel / Stop (`type=2`):**

```bash
curl -X POST \
  -H "Token: <token>" \
  -H "Mobile-User-Id: 72426fd7de4cb929dc2645378fc4e7dd" \
  -H "X-Api-Version: 184" \
  -H "Language: en_US" \
  -H "Robot-Id: <null>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "Content-Length: 0" \
  "http://116.205.178.152:28080/fleetapi/device/taskaction?openid=72426fd7de4cb929dc2645378fc4e7dd&id=6d70603da0cb3d00ba104a191770170b&token=672f4106d95d4b88946f2c8c21f167f9&type=2"
```

**Response (all three actions):**

```json
{
  "code": 200,
  "message": "SUCCESS",
  "generalMessage": null,
  "data": null
}
```

Confirm the new state by polling `POST /fleetapi/device/usestatus` (look at
`work_status` and `haveTaskRunning`) or by listening to `TASK_STATUS` /
`ROBOT` messages on the WebSocket.

---

### Task Lifecycle — Captured Sequence

The following request sequence was captured end-to-end on 2026-04-27 against
robot `6d70603da0cb3d00ba104a191770170b` (task `Espaitec`,
id `ae3178a170b0f97b40e783e7f9dad747`):

| Δt | Method | Endpoint | Effect |
|----|--------|----------|--------|
| 0 s | `POST` | `/fleetapi/device/usestatus` | Snapshot — robot was `Charging`, `haveTaskRunning: false` |
| +0 s | `POST` | `/fleetapi/clean/list` | Discover available tasks (returned `Espaitec`) |
| +2 s | `GET`  | `/fleetapi/task/plan/reachable` | Pre-flight reachability check |
| +4 s | `POST` | `/fleetapi/clean/default/start` | **Start** — `data: true` |
| +13 s | `GET` | `/fleetapi/task/plan/path/running` | Poll planned path |
| +24 s | `POST` | `/fleetapi/device/taskaction?type=1` | **Pause** |
| +31 s | `POST` | `/fleetapi/device/taskaction?type=0` | **Resume** |
| +40 s | `POST` | `/fleetapi/device/taskaction?type=2` | **Cancel / Stop** |

---

## User Endpoints

### Register

```
POST /user/register
Content-Type: application/json; charset=utf-8
```

**Body Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| account | string | no | Account name |
| username | string | no | Display username |
| password | string | no | Password |

**Example Request:**

```bash
curl -X POST -H 'Content-Type: application/json; charset=utf-8' \
  http://127.0.0.1/user/register \
  --data '{
    "account": "myaccount",
    "username": "My Name",
    "password": "mypassword"
  }'
```

**Response:**

```json
{
  "code": 856,
  "message": "success",
  "generalMessage": "success",
  "data": null
}
```

---

### Login

```
POST /user/login
Content-Type: application/json; charset=utf-8
```

**Body Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| account | string | no | Account name |
| password | string | no | Password |

**Example Request:**

```bash
curl -X POST -H 'Content-Type: application/json; charset=utf-8' \
  http://127.0.0.1/user/login \
  --data '{
    "account": "myaccount",
    "password": "mypassword"
  }'
```

**Response:**

```json
{
  "code": 890,
  "message": "success",
  "generalMessage": "success",
  "data": {
    "userId": "c652c00ce411f9e7ab19e0d0b655ff13",
    "orgId": null,
    "account": "neloangelo",
    "username": "NeloAngelo",
    "password": null,
    "avatar": null,
    "roleId": "001",
    "email": null,
    "telNum": null,
    "organization": null,
    "permissions": null,
    "userPermission": null,
    "role": null
  }
}
```

> **Note:** Use the returned token (from response headers or login flow) as the `x-token` header for subsequent requests.

---

### Get User Info

```
GET /user/info
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| userId | string | no | User ID (auto-extracted from `x-token`) |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/user/info'
```

**Response includes** `userPermission` with role info, menu list, and permission list:

```json
{
  "code": 111,
  "message": "success",
  "generalMessage": "success",
  "data": {
    "userId": "c652c00ce411f9e7ab19e0d0b655ff13",
    "orgId": "001",
    "account": "neloangelo",
    "username": "NeloAngelo",
    "roleId": "001",
    "effectTime": 1638844050000,
    "failureTime": 1646620050000,
    "userPermission": {
      "userId": "c652c00ce411f9e7ab19e0d0b655ff13",
      "username": "NeloAngelo",
      "roleId": "001",
      "roleName": "admin",
      "menuList": ["role", "version", "user"],
      "permissionList": [
        "version:update", "user:list", "role:update",
        "user:add", "user:delete", "version:list",
        "role:list", "version:add", "role:delete",
        "user:update", "version:delete", "role:add"
      ]
    }
  }
}
```

---

### Get User Projects (Paginated)

```
GET /project/allProject
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| orgId | string | no | Organization ID |
| page | int | yes | Page index |
| pageSize | int | yes | Page size |

**Example Request:**

```bash
curl -X GET -H 'x-token: <JWT>' \
  'http://127.0.0.1/project/allProject?orgId=&page=1&pageSize=20'
```

**Response:**

```json
{
  "code": 111,
  "message": "success",
  "generalMessage": "success",
  "data": {
    "projectCount": 1,
    "projectExhibitionList": [
      {
        "latitude": 22.573986,
        "longitude": 113.944091,
        "mapNum": 610,
        "orgId": "001",
        "orgName": null,
        "projectAddr": "西丽万科云城6期",
        "projectDesc": null,
        "projectId": "001",
        "projectName": "万科云城6期2栋",
        "robotNum": 45,
        "taskNum": 19,
        "taskNumOfTheDay": 7
      }
    ]
  }
}
```

---

### Logout

```
POST /user/logout
Content-Type: application/json; charset=utf-8
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| userId | string | no | User ID (from `x-token`) |

**Example Request:**

```bash
curl -X POST -H 'Content-Type: application/json; charset=utf-8' \
  -H 'x-token: <JWT>' \
  http://127.0.0.1/user/logout
```

**Response:**

```json
{
  "code": 646,
  "message": "success",
  "generalMessage": "success",
  "data": null
}
```

---

## WebSocket — Realtime Messages

Three WebSocket sources exist, in priority order:

| Priority | URL | Accessible from | Position message |
|----------|-----|-----------------|------------------|
| **1 — App WS** | `ws://host:28080/fleetapi/websocketapp/{openid}/{token}` | Internet | `device_position` |
| **2 — Direct WS** | `ws://192.168.x.x:29997/robot` | Local network / hotspot only | `ROBOT_GESTURE` |
| **3 — Fleet WS** | `ws://host:28081/robot` | Internet | none (robot not connected) |

### 1. App WebSocket (primary — internet accessible)

**URL:** `ws://<host>:<port>/fleetapi/websocketapp/<openid>/<token>`

- Same host and port as the REST API (28080). No extra firewall rules needed.
- `openid` is the value returned from the login response (`data.openid`). For this deployment it equals `MOBILE_USER_ID`.
- `token` is the session token from login.
- Uses a **standard HTTP 101** WebSocket handshake — works with any WS library.
- Password must be **base64-encoded** in the login `POST` body.
- Requires application-level **JSON ping every 20 seconds**: `{"type": "ping", "language": "en_US"}`.
- Server responds with `{"type": "pong"}`.
- Delivers three message types at ~1 Hz each:
  - `device_position` — live x/y coordinates whenever the robot is localized
  - `devicestasktatus` — running task progress (`percent`, `taskStatus`, area, cycles) — see [Task Status Message](#task-status-message)
  - `devicestatus` — full device snapshot including `data.clean` task summary — see [Alternate Progress Source](#alternate-progress-source--devicestatus-message)

**Login (base64 password):**

```bash
curl -X POST http://116.205.178.152:28080/fleetapi/account/login \
  -H "X-Api-Version: 184" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=DeliveranceENT&password=QWRtaW4xMjM="
# QWRtaW4xMjM= = base64("Admin123")
```

Response includes `data.token` and `data.openid`.

**`device_position` message format:**

```json
{
  "type": "device_position",
  "uuid": "1776714412813",
  "msg": "{\"serial\":\"6d70603da0cb3d00ba104a191770170b\",\"position\":{\"x\":1.11,\"y\":0.22,\"z\":0.0},\"orientation\":{\"x\":-0.0052,\"y\":0.0044,\"z\":0.0717,\"w\":-0.9974},\"speed\":0.0}"
}
```

> The `msg` field is a **JSON-encoded string** — parse it with a second `json.loads()` call.

| Field | Description |
|-------|-------------|
| `msg.serial` | Robot device ID (matches `deviceId` from `/robot/deviceList`) |
| `msg.position.x` / `.y` | Live position in map-frame meters |
| `msg.position.z` | Always 0.0 (2D map) |
| `msg.orientation` | Quaternion (x, y, z, w) — robot heading |
| `msg.speed` | Current speed m/s |

---

### 2. Direct Robot WebSocket (local network only)

**URL:** `ws://<robot-local-ip>:29997/robot`

- Robot's onboard WS server. On the hotspot: `ws://192.168.8.188:29997/robot`.
  On the building LAN: `ws://192.168.3.63:29997/robot`.
- Standard HTTP 101 handshake. **No authentication required.**
- Delivers `ROBOT_GESTURE`, `ROBOT` (full chassis state), and `TASK_STATUS` messages.
- Configure via `ALLYBOT_DIRECT_HOST` or `ALLYBOT_DIRECT_WS_URL` env vars.
- Port 29997 is **not** forwarded through the fleet server — only accessible on the local network.

**`ROBOT_GESTURE` message format (direct WS):**

```json
{
  "type": "ROBOT_GESTURE",
  "content": {
    "serial": "6d70603da0cb3d00ba104a191770170b",
    "position": {"x": 1.11, "y": 0.22, "z": 0.0},
    "orientation": {"x": -0.0052, "y": 0.0044, "z": 0.0717, "w": -0.9974},
    "speed": 0.0
  }
}
```

---

### 3. Fleet WebSocket (fallback)

**URL:** `ws://host:28081/robot`

- **Non-standard handshake:** responds with `Establish connection successfully…` instead of HTTP 101.
- Currently delivers **no messages** because `aliveStatus: 2` — the robot is not connected to the fleet positioning server.
- Kept as last-resort fallback in case the robot's fleet connection is restored.

---

### Robot Status Message

**Type:** `ROBOT`

Provides full device status including battery, chassis hardware, cleaning mechanisms, and navigation state.

```json
{
  "type": "ROBOT",
  "content": {
    "serial": "ba17e07275ac9bb21cf964ecbe2bd5c8",
    "bluetoothStatus": false,
    "chassisStatus": {
      "battery": 48.0,
      "charging": false,
      "emergencyStop": false,
      "current": -2.3,
      "voltage": 26.09,
      "freshWater": 25.0,
      "sewageWater": 38.0,
      "hasWater": false,
      "ratedBatteryCapacity": 42.5,
      "remainingBatteryCapacity": 20.8,
      "lowPower": false,
      "machineId": "030220210817CN5180000005",
      "enableBrush": false,
      "enableSuction": false,
      "enableWater": false,
      "enableAbsorb": false,
      "enableManualPush": false,
      "enableMotorLiftingOpen": false,
      "enableFilterOpen": false,
      "chassisHardwareStatus": 0,
      "canErrorLeft": 0,
      "canErrorRight": 0,
      "liftingPressureLevel": 0,
      "lightBelt": 0,
      "waterLevel": 7
    },
    "cleanDeviceOpened": false,
    "currentApplyCleanIntensity": 2,
    "currentApplyMode": 0,
    "encounterObstruction": false,
    "gpsFixed": false,
    "haveTaskRunning": false,
    "highBatteryThreshold": 80.0,
    "lowBatteryThreshold": 20.0,
    "inElevator": false,
    "localization": false,
    "mapRecording": false,
    "navStatus": 2,
    "networkStatus": true,
    "recordingMapName": "",
    "robotConnected": true,
    "robotState": 1,
    "sweepStatus": [
      { "sweepingData": 0, "sweepingType": 1 },
      { "sweepingData": 0, "sweepingType": 2 },
      { "sweepingData": 0, "sweepingType": 16 },
      { "sweepingData": 0, "sweepingType": 16384 },
      { "sweepingData": 0, "sweepingType": 32768 }
    ]
  }
}
```

**Key Chassis Fields:**

| Field | Type | Description |
|-------|------|-------------|
| battery | float | Battery percentage |
| charging | bool | Currently charging |
| emergencyStop | bool | Emergency stop engaged |
| current | float | Current (amps) |
| voltage | float | Voltage |
| freshWater | float | Fresh water level |
| sewageWater | float | Sewage water level |
| ratedBatteryCapacity | float | Rated battery capacity |
| remainingBatteryCapacity | float | Remaining battery capacity |

**Key Status Fields:**

| Field | Type | Description |
|-------|------|-------------|
| robotState | int | Device state |
| navStatus | int | Navigation status |
| localization | bool | Position initialized |
| haveTaskRunning | bool | Task currently executing |
| encounterObstruction | bool | Obstacle detected |
| mapRecording | bool | Recording a map |
| inElevator | bool | In an elevator |
| robotConnected | bool | Navigation connection OK |
| networkStatus | bool | Network status |
| gpsFixed | bool | GPS fix reliable |
| cleanDeviceOpened | bool | Cleaning mechanism active |
| currentApplyCleanIntensity | int | Cleaning intensity level |
| currentApplyMode | int | Current working mode |

---

### Robot Pose Message

**Type:** `ROBOT_GESTURE`

```json
{
  "type": "ROBOT_GESTURE",
  "content": {
    "serial": "ba17e07275ac9bb21cf964ecbe2bd5c8",
    "position": {
      "x": -0.447401,
      "y": 0.902284,
      "z": -0.009134
    },
    "orientation": {
      "x": -0.013239,
      "y": 0.006611,
      "z": 0.823563,
      "w": 0.567032
    },
    "speed": 0.6
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| serial | string | Device ID |
| position | object | `{x, y, z}` coordinates |
| orientation | object | Quaternion `{x, y, z, w}` |
| speed | float | Movement speed |

---

### Task Queue Message

**Type:** `TASK_QUEUE`

Provides the full task queue for a robot, including task details and individual job statuses with coverage/completion data.

```json
{
  "type": "TASK_QUEUE",
  "serial": "ba17e07275ac9bb21cf964ecbe2bd5c8",
  "content": [
    {
      "task": {
        "taskId": "...",
        "taskCode": "front",
        "execCron": "...",
        "taskMode": 2,
        "robotId": "...",
        "jobList": [ "..." ]
      },
      "taskJob": {
        "jobId": "...",
        "status": 4,
        "percentComplete": 0,
        "coverArea": 0,
        "remainingRegion": "POLYGON((...,...))",
        "remainingRegionPoints": [ { "points": [ { "x": 0, "y": 0, "z": 0 } ] } ]
      },
      "serialNum": 1,
      "status": null
    }
  ]
}
```

---

### Task Status Message

**Type on App WS:** `devicestasktatus` *(yes — that spelling is what the wire format
uses; the Direct WS reports it as `TASK_STATUS`)*

Real-time progress of the currently running task. Pushed once per second
on the App WebSocket while a task is active.

**Observed wire format (App WS, captured 2026-04-27):**

```json
{
  "type": "devicestasktatus",
  "uuid": "1777296013173",
  "robotid": "6d70603da0cb3d00ba104a191770170b",
  "taskId": "ae3178a170b0f97b40e783e7f9dad747",
  "name": "Espaitec",
  "time": "21:20:05",
  "area": "0.0",
  "hour": 0,
  "percent": 0,
  "taskStatus": 3,
  "msg": "{\"taskName\":\"Espaitec\",\"robotId\":\"6d70603da0cb3d00ba104a191770170b\",\"taskId\":\"ae3178a170b0f97b40e783e7f9dad747\",\"startTime\":1777296005000,\"percentage\":0,\"workingScope\":0.0,\"currCircle\":1,\"totalCircle\":2,\"workingTime\":0,\"totalTime\":3,\"planId\":\"ac8c95b30ca2942e345f721f184107c2\",\"trace\":null,\"globalPlanRoute\":null,\"taskStatus\":3}"
}
```

> Like `device_position`, the inner `msg` field is a **JSON-encoded string** —
> parse it with a second `json.loads()` call.

**Outer fields (top-level JSON):**

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Always `devicestasktatus` on the App WS |
| `robotid` | string | Robot device ID (note lowercase `i`) |
| `taskId` | string | ID of the currently running task |
| `name` | string | Task name |
| `time` | string | Task start clock time (`HH:MM:SS`, local) |
| `area` | string | Cleaned area so far in m² (string, e.g. `"0.0"`) |
| `hour` | int | Working time so far (hours) |
| `percent` | float | **Completion percentage 0–100** — mirrors `msg.percentage` |
| `taskStatus` | int | **Task state code — see table below** — mirrors `msg.taskStatus` |
| `uuid` | string | Server-assigned message ID (epoch ms) |
| `msg` | string | JSON-encoded inner payload (parse separately) |

**Inner `msg` fields (after JSON-decoding):**

| Field | Type | Description |
|-------|------|-------------|
| `taskName` | string | Task name |
| `robotId` | string | Robot device ID |
| `taskId` | string | Task ID |
| `planId` | string | Active plan ID for this task |
| `startTime` | long | Start timestamp (epoch ms) |
| `percentage` | float | **Completion percentage 0–100** |
| `workingScope` | float | Total working area (m²) |
| `workingTime` | int | Elapsed working time |
| `totalTime` | int | Estimated total time |
| `currCircle` | int | Current cycle / pass number |
| `totalCircle` | int | Total cycles in this task |
| `taskStatus` | int | Task state code |
| `trace` | object | Movement trace (null until robot has moved) |
| `globalPlanRoute` | array | Planned route `[{x, y, z}, ...]` (may be null early in task) |

**Captured `taskStatus` codes (full lifecycle):**

| Code | Meaning | Observed transition |
|------|---------|---------------------|
| `3` | **Starting / dispatching** | Sent immediately after `clean/default/start` |
| `5` | **Running** (executing) | ~1.3 s after `taskStatus: 3` |
| `9` | **Paused** | Sent immediately after `taskaction?type=1` |
| `5` | **Running** (resumed) | Sent immediately after `taskaction?type=0` |
| *(message stream stops)* | **Cancelled / stopped** | Last `devicestasktatus` arrives just before `taskaction?type=2`; no more messages after cancel |

> The `percent` / `percentage` field is the **primary source** for task progress.
> In the captured run the task was paused and cancelled before any real area was
> covered, so percentage stayed at `0` throughout — but the field is updated
> live as the robot works.

**Observed update rate:** ~1 Hz on the App WebSocket while a task is active.

---

### Alternate Progress Source — `devicestatus` Message

The same App WebSocket also pushes `devicestatus` messages (~1 Hz). When a task
is running, the `data.clean` object carries a parallel summary of progress:

```json
{
  "type": "devicestatus",
  "uuid": 1777296023105,
  "code": 200,
  "data": {
    "id": "6d70603da0cb3d00ba104a191770170b",
    "name": "202352CNW002D0156",
    "battery": 67,
    "freshWater": 42,
    "sewageWater": 0,
    "online": "Online",
    "work_status": "Operating",
    "haveTaskRunning": true,
    "navStatus": 2,
    "location": true,
    "clean": {
      "title": "Espaitec",
      "task_mode": "Scrubbing.Standard",
      "start": "21:20:05",
      "end": "",
      "area": 0,
      "use_hour": 0,
      "left_hour": 3,
      "percent": 0,
      "repeat": 12,
      "date": "",
      "date_type": "",
      "mode_type": null
    }
  }
}
```

**Key `clean` fields for progress tracking:**

| Field | Type | Description |
|-------|------|-------------|
| `clean.title` | string | Running task name |
| `clean.percent` | float | Completion percentage 0–100 |
| `clean.area` | float | Cleaned area so far (m²) |
| `clean.use_hour` | float | Elapsed working time (hours) |
| `clean.left_hour` | float | Estimated remaining time (hours) |
| `clean.start` | string | Start clock time (`HH:MM:SS`) |
| `clean.task_mode` | string | Cleaning mode (e.g. `"Scrubbing.Standard"`) |

When no task is running, `clean` is `null`. `data.haveTaskRunning` and
`data.work_status` (`"Charging"` / `"Idle"` / `"Operating"`) are simpler boolean /
enum signals on the same message.

> **For progress tracking:** prefer `devicestasktatus` (richer fields,
> includes `taskStatus` state machine). Fall back to `devicestatus.data.clean`
> when only the high-level percent/area/time is needed.

---

## Common Response Format

All REST endpoints return:

```json
{
  "code": <int>,
  "message": "<string>",
  "generalMessage": "<string>",
  "data": <object|array|null>
}
```

---

## Device Endpoints

### Get Active Map for a Robot

```
POST /fleetapi/device/usemap
Content-Type: application/x-www-form-urlencoded
```

**Headers:** `Token`, `Mobile-User-Id`, `X-Api-Version: 184`, `Language`, `Robot-Id: <null>`

**Body Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| openid | string | yes | Mobile user ID |
| token | string | yes | Auth token |
| id | string | yes | Robot device ID |

**Example Request:**

```bash
curl -X POST \
  -H "Token: <token>" \
  -H "Mobile-User-Id: 72426fd7de4cb929dc2645378fc4e7dd" \
  -H "X-Api-Version: 184" \
  -H "Language: en_US" \
  -H "Robot-Id: <null>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "openid=72426fd7de4cb929dc2645378fc4e7dd&token=<token>&id=<robot_id>" \
  "http://116.205.178.152:28080/fleetapi/device/usemap"
```

**Response:**

```json
{
  "code": 200,
  "message": "SUCCESS",
  "generalMessage": null,
  "data": {
    "mapinfo": {
      "id": "9e1121fff00d8462f10a876aaf125a3b",
      "name": "DELIVERANCE",
      "avatar": "http://116.205.178.152:28080/resource/map/20250704185952/map.png",
      "floor": "1",
      "is_use": true,
      "is_add": true,
      "is_navback": false,
      "original": {
        "x": -6.55,
        "y": -3.24,
        "z": 0
      },
      "resolution": 0.05
    },
    "organ_name": "DeliveranceENT",
    "image_url": "http://116.205.178.152:28080/resource/map/20250704185952/map.png",
    "robot_name": "202352CNW002D0156",
    "usestatus": "1"
  }
}
```

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `mapinfo.id` | string | Active map ID — use for `map/mapPoint`, `map/shape`, etc. |
| `mapinfo.name` | string | Map name |
| `mapinfo.original` | object | Real-world offset `{x, y, z}` of the map's bottom-left corner (meters) |
| `mapinfo.resolution` | float | Meters per pixel — use to convert pixel coords to meters |
| `mapinfo.is_use` | bool | `true` = robot is actively navigating on this map |
| `image_url` | string | Full URL to the map PNG image |
| `robot_name` | string | Robot serial number / name |
| `usestatus` | string | `"1"` = robot is active on this map |

> **Note:** This is the primary endpoint to resolve the active `mapId` for a robot at runtime.
> The `mapinfo.original` and `mapinfo.resolution` fields are required to interpret
> `ROBOT_GESTURE` WebSocket coordinates in real-world meters.

---

## Map Endpoints (additional — verified 2026-04-20)

### Get Map Points (Waypoints)

```
GET /fleetapi/map/mapPoint
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| mapId | string | yes | Map ID |
| robotId | string | yes | Robot ID |

**Example Request:**

```bash
curl -X GET \
  -H "Token: <token>" \
  -H "Mobile-User-Id: 72426fd7de4cb929dc2645378fc4e7dd" \
  -H "X-Api-Version: 184" \
  -H "Robot-Id: <null>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  "http://116.205.178.152:28080/fleetapi/map/mapPoint?mapId=<mapId>&robotId=<robotId>"
```

**Response:**

```json
{
  "code": 200,
  "message": "SUCCESS",
  "generalMessage": null,
  "data": [
    {
      "mapId": "9e1121fff00d8462f10a876aaf125a3b",
      "pointId": "4649ec10f0760af97a20a888077688f9",
      "pointName": "",
      "pointType": 16,
      "position": { "x": 0.91, "y": 0.43, "z": 0.01 },
      "orientation": { "x": 0, "y": 0, "z": -0.0451, "w": 0.999 },
      "robotId": "6d70603da0cb3d00ba104a191770170b",
      "deleted": false,
      "elevatorIds": null
    }
  ]
}
```

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `pointId` | string | Waypoint ID |
| `pointName` | string | Waypoint name (`"自由点"` = free navigation point) |
| `pointType` | int | `0` = free nav point, `16` = charging dock |
| `position` | object | `{x, y, z}` coordinates in map frame (meters) |
| `orientation` | object | Quaternion `{x, y, z, w}` |

> **Note:** These are static predefined waypoints, not the robot's live position.
> `pointType: 16` is the charging dock — its position is the robot's known location when charging.

---

### Get Map Zones / Shapes

```
GET /fleetapi/map/shape
Content-Type: application/x-www-form-urlencoded
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| mapId | string | yes | Map ID |

**Example Request:**

```bash
curl -X GET \
  -H "Token: <token>" \
  -H "Mobile-User-Id: 72426fd7de4cb929dc2645378fc4e7dd" \
  -H "X-Api-Version: 184" \
  -H "Robot-Id: <null>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  "http://116.205.178.152:28080/fleetapi/map/shape?mapId=<mapId>"
```

**Response:**

```json
{
  "code": 200,
  "message": "SUCCESS",
  "generalMessage": null,
  "data": [
    {
      "shapeId": "3febd0ff257fa33afc6ccc95d229a162",
      "shapeName": "不可通行区域",
      "shapeType": 1,
      "shapeDesc": null,
      "points": "1.21,-1.7,0.01,-4.67,-1.14,0.01,-4.73,-2.72,0.01,1.09,-3.1,0.01",
      "colorIndex": "#FF9191",
      "baseHeight": 0.1,
      "height": 0.3,
      "mapId": "9e1121fff00d8462f10a876aaf125a3b",
      "del": false,
      "maps": {
        "id": "9e1121fff00d8462f10a876aaf125a3b",
        "name": "DELIVERANCE",
        "original": { "x": -6.55, "y": -3.24, "z": 0 },
        "resolution": 0.05,
        "avatar": "http://116.205.178.152:28080/resource/map/20250704185952/map.png"
      }
    }
  ]
}
```

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `shapeId` | string | Zone ID |
| `shapeName` | string | Zone name (Chinese labels common: `不可通行区域` = no-go zone, `地毯区` = carpet zone) |
| `shapeType` | int | `1` = no-go/blocked zone, `3` = special surface zone (carpet etc.) |
| `colorIndex` | string | Display color hex (`#FF9191` = red no-go, `#ffffff` = white carpet) |
| `points` | string | Comma-separated polygon vertices: `x,y,z,x,y,z,...` in map-frame meters |
| `maps.original` | object | Map origin offset — same as `device/usemap` response |
| `maps.resolution` | float | Map resolution (m/pixel) — same as `device/usemap` response |

> **Note:** `points` is a flat comma-separated string, not a JSON array. Parse by splitting on commas
> and grouping into triples: `[(x0,y0,z0), (x1,y1,z1), ...]`.

---

## Deployment Notes (verified 2026-04-20)

### Position Data Availability

| Source | Live x/y? | Accessible from | Notes |
|--------|-----------|-----------------|-------|
| App WS `device_position` | **Yes** | Internet | Primary source — use this |
| Direct WS `ROBOT_GESTURE` | **Yes** | Local network only | Fallback when on LAN/hotspot |
| `device/usestatus` | No | Internet | `location: false`, `navStatus` is an int |
| `device/status` | No | Internet | Has `localization` bool but no x/y |
| `map/mapPoint` | No | Internet | Static waypoints only |
| `device/usemap` | No | Internet | Map metadata/origin only |
| Fleet WS `ROBOT_GESTURE` | No | Internet | Robot not connected to fleet WS server |

### Task Progress Data Availability

| Source | % complete? | State machine? | Update rate | Notes |
|--------|-------------|----------------|-------------|-------|
| App WS `devicestasktatus` | **Yes** (`percent` / `msg.percentage`) | **Yes** (`taskStatus` codes 3 / 5 / 9) | ~1 Hz | **Primary source.** Also exposes area, working time, current cycle, total cycles |
| App WS `devicestatus.data.clean` | **Yes** (`clean.percent`) | No (only `haveTaskRunning` bool + `work_status` enum) | ~1 Hz | Has area, elapsed/remaining hours; `clean` is `null` when idle |
| Direct WS `TASK_STATUS` | Yes | Yes | n/a | Local-network only; same payload schema as `devicestasktatus.msg` |
| REST `device/usestatus` | No | No | On request | Only `haveTaskRunning` bool and `work_status` string |
| REST `task/plan/path/running` | No | No | On request | Returns the planned route, not progress |

### robot/binding Returns 513

`GET /robot/binding` returns `code: 513` (`"OPERACIÓN FALLIDA"`) when `aliveStatus: 2`
in `robot/singleRobotInfo`. This means the robot is connected to the consumer mobile API
(`/fleetapi`) but not to the fleet positioning server (port 28081). The App WS
(`/websocketapp/`) is unaffected — it works regardless of `aliveStatus`.

---

## API Endpoint Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/map/mapPage` | List user maps (paginated) |
| GET | `/map/robot` | Find robots using a map |
| GET | `/map/baseShape` | Get semantic shapes on a map (legacy) |
| GET | `/map/shape` | Get map zones/shapes with full map metadata |
| GET | `/map/mapPoint` | Get waypoints/navigation points on a map |
| GET | `/map/mapInfo` | Get map details |
| GET | `/map/mapPlan` | Get plans by map ID |
| GET | `/map/plan` | Get plan details by plan ID |
| GET | `/map/virtualWall` | Get virtual walls |
| GET | `/map/binding` | Subscribe to map realtime messages |
| GET | `/robot/available` | Get available robots on a map |
| GET | `/robot/singleRobotInfo` | Get single robot info (includes `aliveStatus`, `mapId`) |
| GET | `/robot/mapRobots` | Get all robots on a map |
| GET | `/robot/robotPage` | List org robots (paginated) |
| GET | `/robot/binding` | Subscribe to robot realtime messages (returns 513 if `aliveStatus: 2`) |
| GET | `/task/task` | Get task information |
| POST | `/fleetapi/clean/list` | List cleaning tasks/schedules for a robot |
| GET | `/fleetapi/task/plan/reachable` | Pre-flight: confirm task plan is reachable on current map |
| POST | `/fleetapi/clean/default/start` | **Start** a task on a robot (returns `data: true`) |
| GET | `/fleetapi/task/plan/path/running` | Get the live planned path of the running task |
| POST | `/fleetapi/device/taskaction?type=0` | **Resume** a paused task |
| POST | `/fleetapi/device/taskaction?type=1` | **Pause** the running task |
| POST | `/fleetapi/device/taskaction?type=2` | **Stop / Cancel** the running task |
| POST | `/user/register` | Register new user |
| POST | `/user/login` | User login |
| GET | `/user/info` | Get user info |
| GET | `/project/allProject` | Get user projects (paginated) |
| POST | `/user/logout` | User logout |
| POST | `/fleetapi/device/usemap` | Get active map for a robot (mapId, origin, resolution, image URL) |
| WS | `ws://host:28080/fleetapi/websocketapp/{openid}/{token}` | App WS: live position (`device_position`), task progress (`devicestasktatus`, `devicestatus.data.clean`), internet-accessible |
| WS | `ws://robot-ip:29997/robot` | Direct WS: position + chassis state, local network only |
| WS | `ws://host:28081/robot` | Fleet WS: fallback, non-standard handshake, currently no data |
