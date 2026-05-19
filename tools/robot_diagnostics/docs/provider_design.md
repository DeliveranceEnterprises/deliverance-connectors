# Provider Design

This document describes planned read-only diagnostics for Keenon and AutoXing. It is based on static inspection only. Do not call real APIs until credentials, mappings, and safe read-only scope are confirmed.

## Keenon

### Variables Necesarias

- `INORBIT_API_KEY` for connector publication, not needed for manufacturer-only diagnostics.
- `INORBIT_KEENON_API_DOMAIN`
- `INORBIT_KEENON_CLIENT_ID`
- `INORBIT_KEENON_CLIENT_SECRET`
- `INORBIT_KEENON_VERIFY_SSL`
- Optional: `INORBIT_KEENON_WEBHOOK_PORT` for connector webhooks, not needed for read-only diagnostics.

### YAML Minimo

- `connector_type: keenon`
- `update_freq`
- `connector_config.api_domain`
- `connector_config.client_id`
- `connector_config.client_secret`
- `fleet[].robot_id` as InOrbit robot ID.
- `fleet[].fleet_robot_id` as Keenon robot identifier.
- `fleet[].store_id` as Keenon store identifier.

### Read-Only Endpoints / Operaciones Identificadas

- OAuth token: `POST /api/open/oauth/token`
- Robot list: `GET /api/open/data/v1/store/robot/list`
- Robot status: `GET /api/open/scene/v1/robot/status`
- Robot location: `GET /api/open/custom/robot/location`
- Cleaning robot status: `GET /api/open/custom/clean/robot/status`
- Task status read: `GET /api/open/scene/v1/robot/call/task`
- Map image read: `GET /api/open/custom/robot/map`

### Acciones De Control Que NO Deben Ejecutarse

- Call to point: `POST /api/open/scene/v3/robot/call/task`
- Return to origin: `POST /api/open/scene/v2/robot/call/back/task`
- Cancel task: `DELETE /api/open/scene/v1/robot/call/task`
- Clean recharge: `POST /api/open/custom/clean/robot/recharge/task`
- Clean finish: `POST /api/open/custom/clean/robot/finish/task`
- Clean pause: `POST /api/open/custom/clean/robot/pause/task`
- Temporary cleaning task: `POST /api/open/custom/clean/robot/strategy/temporary/task`
- Cabin control: `POST /api/open/custom/robot/cabin/door`

### Datos Faltantes Para Probar

- Real Keenon client ID and client secret.
- Confirmed region/API domain.
- Confirmed `store_id`.
- Confirmed mapping between InOrbit `robot_id` and Keenon `fleet_robot_id`.
- Confirmation that map/status/location endpoints are allowed for the account.

### Propuesta De Implementacion Read-Only

1. Load local `keenon_connector/config/my_fleet.local.yaml` and `.env.local`.
2. Validate missing/placeholder credentials and IDs.
3. Authenticate with OAuth client credentials.
4. For each configured robot, query robot list/status/location.
5. Query cleaning status only when robot type/model indicates cleaning robot, or mark as not available.
6. Query map metadata/image only as read-only and never write maps/locations in InOrbit.
7. Return common inventory rows using `source_partial`, `source_ok`, or `failed`.
8. Sanitize all exception messages.

### Fixtures / Tests Antes De APIs Reales

- Token success fixture.
- Token failure fixture with sanitized error.
- Robot status fixture.
- Location fixture with pose.
- Cleaning status fixture.
- Map permission failure fixture.
- Control endpoint names listed as forbidden and never called by diagnostics.

## AutoXing

### Variables Necesarias

- `INORBIT_API_KEY` for connector publication, not needed for manufacturer-only diagnostics.
- `INORBIT_AUTOXING_PASSWORD`
- YAML `connector_config.base_url`
- YAML `connector_config.login_name`
- YAML `connector_config.business_id`
- Built-in app codes exist in code; do not print or rotate them from diagnostics.

### YAML Minimo

- `connector_type: autoxing`
- `account_id`
- `update_freq`
- `connector_config.base_url`
- `connector_config.login_name`
- `connector_config.business_id`
- `fleet[].robot_id` as InOrbit robot ID.
- `fleet[].fleet_robot_id` as AutoXing robot ID.
- Optional `fleet[].area_map_config` for map origin/resolution by area ID.

### Read-Only Endpoints / Operaciones Identificadas

- Login step 1: `POST /user/v1.1/login`
- Ticket exchange: `GET /user/v1.0/ticket/{ticket}`
- Robot list: `POST /robot/v1.1/list`
- Robot state: `GET /robot/v1.1/{robot_id}/state`
- Area list: `POST /map/v1.1/area/list`
- Map image read: `GET /map/v1.1/area/{area_id}/base-map`
- POI list: `POST /map/v1.1/poi/list`
- Task read: `GET /task/v1.1/{task_id}`

### Acciones De Control Que NO Deben Ejecutarse

- Create task: `POST /task/v1.1`
- Execute task: `POST /task/v1.1/{taskId}/execute`
- Cancel task: `POST /task/v1.1/{taskId}/cancel`
- Navigate to POI command.
- Go home command.
- Execute existing task command.

### Datos Faltantes Para Probar

- Confirmed login name.
- Confirmed encrypted/expected password value.
- Confirmed business ID.
- Confirmed `fleet_robot_id` for each AutoXing robot.
- Confirmed InOrbit `robot_id` mapping.
- Confirmation that robot state and map/area endpoints are safe and permitted.

### Propuesta De Implementacion Read-Only

1. Load local `autoxing_connector/config/my_fleet.local.yaml` and `.env.local`.
2. Validate placeholders for login name, password, business ID, and fleet robot IDs.
3. Perform login only after explicit approval to use real credentials.
4. Query robot list and per-robot state.
5. Query area list and map image only as read-only, never modify InOrbit maps/locations.
6. Never call task creation/execution/cancel endpoints.
7. Return common inventory rows using `source_partial`, `source_ok`, or `failed`.
8. Sanitize all token, ticket, app-code, and URL-bearing errors.

### Fixtures / Tests Antes De APIs Reales

- Login success fixture with fake ticket/token.
- Login failure fixture with sanitized error.
- Robot list fixture.
- Robot state fixture with pose/battery/status.
- Area list fixture.
- Map image failure fixture.
- Forbidden task endpoint guard test.
