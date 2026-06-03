# Deliverance Connectors — Context for Claude

## Repo overview
Monorepo of InOrbit Edge SDK connectors for multiple robot types. Each connector
is a Python package under its own directory. All connectors share the same
InOrbit account and follow the same CAC patterns.

## InOrbit account
- Account ID: `rnLasGAxn5CP7bj32` (Deliverance Enterprises)
- CLI API key: `~/INORBIT/.env-inorbit` → `INORBIT_CLI_API_KEY`
- Always `source /home/carlos-fernandez/INORBIT/.env-inorbit` before CLI commands

## Connectors in this repo

| Directory | Robot | Tag | Tag ID | SDK version |
|---|---|---|---|---|
| `turtlebot_connector/` | TurtleBot3 waffle_pi (Gazebo sim) | TurtleBot | `QJoR03aXlEhZkD6N` | `2.1.0.edgesdk_py` |
| `allybot_connector/` | Allybot cleaning robot | Allybot | `StdZGa32GmBLReFr` | `2.0.1.edgesdk_py` |
| `autoxing_connector/` | Autoxing delivery chassis | Autoxing | `8gMbOLofiZYK0uKx` | `2.0.1.edgesdk_py` |
| `keenon_connector/` | Keenon T10 service robot | Keenon | `DJbJhivzeMvXDj8z` | `2.0.1.edgesdk_py` |
| `ezviz_connector/` | Ezviz cameras | — | — | — |

Other relevant tags:
- `TurtleBot Cleaning` → `kR4yZ9SrGPBnWiwi` (collection: Other — cleaning demo overlay)
- `RS EU` → `hSTlpyR8qtgjSfcT` (collection: location — physical location in Espaitec)

## CAC apply pattern
`inorbit apply -f -` does NOT read stdin. Always write to a temp file first:
```bash
source ~/INORBIT/.env-inorbit
sed -e "s/<ACCOUNT_ID>/rnLasGAxn5CP7bj32/g" \
    -e "s/<TAG_ID>/<real_tag_id>/g" \
    cac/foo.yaml > /tmp/foo.yaml
yes | inorbit apply -f /tmp/foo.yaml
```
Files that use hardcoded tag IDs (no placeholders) can be applied directly:
```bash
yes | inorbit apply -f cac/foo.yaml
```

## Global dashboards — IDs and rules

| Dashboard | ID | Order | Rule |
|---|---|---|---|
| Robot | `d-Robot-lLybVa` | 2 | **Single file** manages all robots. File lives at `allybot_connector/cac/dashboard_robot.yaml`. |
| Navigation | `d-Navigation-Z8YZAb` | 3 | **Single file** manages all robots. File lives at `allybot_connector/cac/dashboard_navigation.yaml`. |
| Fleet | `d-Fleet-FWDce3` | — | **Never touch.** |

### How to add a new robot's section
1. Edit `allybot_connector/cac/dashboard_robot.yaml` — add a new `conditional: {tags: [<NEW_TAG_ID>]}` section after the last robot section and before the pre-existing Kira/InStock/MIR100 sections.
2. Edit `allybot_connector/cac/dashboard_navigation.yaml` — add the new section there too.
3. Apply both files.

### Current sections in d-Robot-lLybVa (2026-06-01)
Pre-existing (not ours — do NOT remove or modify):
- Summary (all robots, internal conditional widgets by tag)
- Kira (`unxlDBfILnQ348gh`), InStock (`dT_B2luhESDW1al9`), MIR100 (`RSMiR100`), RSPeer, Details, MQTT (various tags), ROS, Debug

Ours (added by this repo):
- Allybot (`StdZGa32GmBLReFr`): Vitals + Status + Actions + Mission + Water/Battery/Task chart + Speed chart
- Allybot MQTT: pingAvg chart + history
- Autoxing (`8gMbOLofiZYK0uKx`): Vitals + Status + Actions + Mission + Battery/LocQuality chart
- Autoxing MQTT: pingAvg chart + history
- Keenon (`DJbJhivzeMvXDj8z`): Vitals (uses `xlXPmDo3Z3GMwSTM`) + Status + Actions + Mission + Battery chart
- Keenon MQTT: pingAvg chart + history

### Current sections in d-Navigation-Z8YZAb (2026-06-01)
Pre-existing (never touch):
- Robot Navigation (navigation widget, `withControlWidget: true`)
- Details (Vitals with `xlXPmDo3Z3GMwSTM`, Audit Log, Modes and Tags)

Ours:
- Allybot (`StdZGa32GmBLReFr`): Actions + Mission
- Autoxing (`8gMbOLofiZYK0uKx`): Actions + Mission
- Keenon (`DJbJhivzeMvXDj8z`): Actions + Mission

## gauge unit:'%' rule — the 2000% bug
InOrbit gauges with `unit: '%'` expect a value in **0–1**. They multiply by 100
internally before rendering. So:

| Connector publishes | DataSource spec | Gauge shows |
|---|---|---|
| `0.20` | `unit: '%'`, no scale | ✅ 20% |
| `20` | `unit: '%'`, `scale: 0.01` | ✅ 20% |
| `20` | `unit: '%'`, no scale | ❌ 2000% |
| `0.20` | `unit: '%'`, `scale: 100` | ❌ 2000% |

`StatusDefinition` thresholds evaluate the **post-scale** value:
- `battery` (0–1), no scale → thresholds `0.15`, `0.30`
- `battery_percent` (0–100), `scale: 0.01` → same thresholds `0.15`, `0.30`

## xlXPmDo3Z3GMwSTM — system battery id
InOrbit's built-in Vitals (Summary section) uses this id. Behavior:
- Defining it at tag scope with `unit: '%'` — InOrbit ignores `unit` and `label`, only saves `source.keyValue.key`. The gauge still works via internal logic.
- **Keenon**: `keenon-battery` has `scale: 100` + `unit: '%'` but shows correctly. Reason unknown. Use `xlXPmDo3Z3GMwSTM` in Keenon's custom Vitals widget to match Summary. Do NOT change `keenon-battery` scale.
- **TurtleBot**: `xlXPmDo3Z3GMwSTM` at tag scope causes 2000% because it overrides the account-level with `scale` ignored. Removed from TurtleBot tag — account-level `xlXPmDo3Z3GMwSTM` uses `key: "battery percent"` (with space). TurtleBot publishes `battery percent: <0-1 float>` to feed it.
- **Allybot / Autoxing**: use custom DataSources (`allybot-battery`, `autoxing-battery`) without `scale:100`.

## Preferences — navigationWidget.actions whitelist
Without this, the Navigation control widget LOCK dropdown shows ALL
account-level actions with `widgets: ["navigation"]` → broken icons from other
robots. Each connector needs its own `Preferences` at tag scope:
```yaml
kind: Preferences
metadata: {id: all, scope: tag/<ACCOUNT_ID>/<TAG_ID>}
spec:
  navigationWidget:
    actions: [<action-id-1>, <action-id-2>, ...]
```
**Keenon already had this working** before our changes — do not overwrite it.

## SpatialAnnotation — requires location tag
`SpatialAnnotation` only accepts tags with `type: location`. Hardware tags
(Allybot, Keenon, Autoxing, TurtleBot) are rejected:
`"Annotations can only be defined for tags with type location"`

Current annotations:
- `allybot-cs` — Allybot Charging Station at `RS EU` (`hSTlpyR8qtgjSfcT`)
  coords: `x: 4.049, y: 0.035, theta: -1.614`

To add more: apply to `RS EU` scope. Names prefixed with robot name to avoid
collisions (e.g. `allybot-cs`, `keenon-home`).

## StatusDefinition + IncidentDefinition linking
Both kinds link by id matching — a `StatusDefinition` with `id: foo` evaluates
the DataSource named `foo`. An `IncidentDefinition` with `id: foo` fires on
status transitions of `foo`. No explicit `source` or `statusId` field needed.

## InOrbit CLI quick reference
```bash
inorbit get tags                                      # tag id ↔ name
inorbit get robots                                    # robot id ↔ name
inorbit get config --kind <Kind> --summary            # list all of a kind
inorbit get config --kind <Kind> <id> --scope <scope> --yaml   # read one
inorbit list kinds                                    # all valid kinds
inorbit expr eval <robot_id> "<expression>"           # test expression live
yes | inorbit apply -f /tmp/file.yaml
inorbit delete config --kind <Kind> --scope <scope> <id>
```

## Per-connector CAC summary

### Allybot (`allybot_connector/cac/`)
- `data_sources.yaml` — battery (no scale), fresh/sewage-water (scale:0.01), task-percentage (scale:0.01), speed, ws-connected, work/task-status, have-task-running, map-name, api-connected
- `status_definition.yaml` — ws-connected (EQUALS false ERROR), battery (BELOW 0.30/0.15)
- `incident_definition.yaml` — ws-connected, battery
- `preferences.yaml` — 4 actions whitelisted
- `spatial_annotations.yaml` — allybot-cs at RS EU
- `dashboard_navigation.yaml` — global Navigation + Allybot + Autoxing + Keenon sections
- `dashboard_robot.yaml` — global Robot dashboard (ALL robots)
- `mission_tracking.yaml` — processingType: api

### Autoxing (`autoxing_connector/cac/`)
- `data_sources.yaml` — battery (no scale), loc-quality (scale:0.01), api-connected, errors, is-go-home, is-remote-mode, task-is-cancel, task-is-finish, plus booleans (charging, emergency-stop, obstruction, manual-mode)
- `status_definition.yaml` — battery, loc-quality, emergency-stop, obstruction, api-connected
- `incident_definition.yaml` — all 5 above
- `preferences.yaml` — 5 actions whitelisted
- `dashboard_navigation.yaml` — global Navigation + all sections
- `mission_tracking.yaml` — processingType: api

### Keenon (`keenon_connector/cac/`)
- `data_sources.yaml` — battery (scale:100, DO NOT CHANGE), api-connected, charge-status, can-be-called, current-scene, task-no/status, robot-model, app-version, online-type, elevator, clean-* fields (may not publish if no cleaning module), keenon-keenon-battery (key: keenon_battery, secondary battery)
- `status_definition.yaml` — battery, api-connected, clean-faulting, clean-emergency-stop
- `incident_definition.yaml` — all 4 above
- `preferences.yaml` — PRE-EXISTING, working, do NOT overwrite
- `dashboard_navigation.yaml` — global Navigation + all sections
- `mission_tracking.yaml` — processingType: api

### TurtleBot (`turtlebot_connector/`)
See `turtlebot_connector/CLAUDE.md` for full detail. Summary:
- Full CAC stack: DataSources, StatusDefinition, IncidentDefinition, Preferences, MissionDefinition, MissionTracking, DashboardDefinition (custom), RobotCamera
- Cleaning demo overlay on tag `TurtleBot Cleaning` (`kR4yZ9SrGPBnWiwi`)
- Mission `turtlebot-demo-route` chains 3 waypoints via `runAction` + `waitUntil` on `mission_tracking` JSON
