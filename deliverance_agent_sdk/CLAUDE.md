# Deliverance Agent SDK (prototype) — Context for Claude

## Status: prototype validated live end-to-end against the REAL production platform DB (2026-08-26)

This is Eduardo's **second** objective, distinct from [`../wdc_robot_sdk/`](../wdc_robot_sdk/)
(see workspace memory `project_robot_sdk_task`, message quoted verbatim there):

> "Ten en cuenta que aquí el objetivo es doble: por un lado utilizar el Agent SDK de
> InOrbit para conectarlo a su plataforma, y por otro, diseñar nuestro propio Agent SDK
> que sea especifico para actualizar la información en el formato de nuestra plataforma."

Objective 1 (use InOrbit's Agent SDK) is `wdc_robot_sdk/` — done. **This directory is
objective 2**: Deliverance's own equivalent, that updates OUR platform's own DB format
directly, with no InOrbit involved anywhere in the path. Why this matters: Deliverance is
about to collaborate with a company that manufactures onboard computers for robots —
this prototype is what that collaboration would eventually run, in Deliverance's own
format, instead of depending on InOrbit as a middleman.

## Architecture — literally one box swapped in a pipeline already built today

```
wdc_robot_sdk/ (unchanged):  WDC → wdc_bridge_node.py → standard ROS1 topics/tf
THIS repo, objective 1:                                        ↓
                                                    [Agent Core de InOrbit] → InOrbit Cloud
THIS repo, objective 2 (here):                                 ↓
                                          [deliverance_agent_node.py] → Deliverance platform DB
```

`wdc_bridge_node.py` needed **one small addition**, nothing else: a plain
`sensor_msgs/BatteryState` publish on `/battery_state` (topic already existed for
`/inorbit/custom_data/0`, but that key-value channel is InOrbit's own convention —
using it here would make this "our own SDK" secretly depend on InOrbit's format again).

`deliverance_agent_node.py` (this directory) is new. It knows **nothing** about Siruiy,
WDC, or InOrbit — it only subscribes to standard ROS1 things:
- `/scan` (`sensor_msgs/LaserScan`) — used only for a liveness heartbeat (see
  `_compute_status` below), not re-published anywhere.
- `/battery_state` (`sensor_msgs/BatteryState`) — `percentage` (0–1).
- `map` → `base_link` tf — position.

...and writes directly into `devices`/`device_status`, reusing the exact upsert shape
`integrations/deliverance-integrations-siruiy/service/unified_sync_platform.py` already
uses (the freshest reference in the workspace as of today) — same `ON CONFLICT` pattern,
same `_ensure_org` lookup-only rule, same `category="robot"` lowercase /
`enabled=False`-on-insert conventions every connector in this workspace follows.

**That "knows nothing about the specific robot" property is the whole point of calling
this an SDK.** In principle this exact script works unmodified against any ROS1 robot
publishing those three standard things — WDC is only today's test bench, not a
dependency.

## Confirmed live, 2026-08-26

Ran inside the same `wdc-robot-sdk` container as `wdc_bridge_node.py` (same roscore),
against `wdc-agent-sdk-test` (a NEW device row, deliberately named differently from the
real `WDC Panda` row the Siruiy Edge SDK connector already owns — this prototype must
never collide with or overwrite that one):

```
[INFO] deliverance_agent_node started -- robot=wdc-agent-sdk-test
       device_uid=caede5f9-1ca3-52bd-b29c-826a7a3db03a -> 172.17.0.1:5435/unified_api_real
[INFO] synced status=idle battery=100% pose=(-1.1708111763000488,5.153971195220948)
```

Verified directly in the platform DB (`deliverance-db`, port 5435 — the REAL sealed
platform, confirmed via `docker exec deliverance-db psql`, not a dev/staging copy):

```
name            | wdc-agent-sdk-test
category        | robot
enabled         | f
status          | idle
battery_level   | 100
scene           | {"coordinates_x": -1.1708, "coordinates_y": 5.154, ...}
last_connection | 2026-08-26 13:27:13   -- confirmed advancing on its own, real sync loop
```

Position and battery match exactly what the rest of today's investigation independently
confirmed live for the same robot — not a coincidence, proof the standard-ROS-topics
path carries the same real data as the InOrbit path did.

## Deliberate scope decisions for this prototype phase — not oversights

- **Writes DIRECTLY to the platform DB** (`psycopg`, real credentials in-process), the
  same simple pattern every existing connector already uses. Explicitly did **not**
  build against the richer `device_provider_mappings`/`device_status_events` adapter
  design that exists in `backend_introduction`'s
  `unified_api/app/integrations/inorbit/` (TTL cache, status-transition history —
  exactly the "estado anterior de cuándo quedó en off" Carlos asked about). Confirmed
  live 2026-08-26: **that richer schema was never ported to the real platform DB** —
  `deliverance-db` has neither table, and `deliverance-platform-api`'s own source has
  zero references to either. Porting it is a real, separate, bigger conversation
  (schema migration on the sealed platform) that Carlos deliberately parked — Eduardo
  saw the work in `backend_introduction` and didn't ask for it to move to production.
  Don't quietly re-open that scope here.
- **Direct DB credentials are only acceptable because Deliverance is the one running
  this right now**, on our own machine, same trust boundary every existing connector
  already has. **This must change before this is ever handed to the hardware-manufacturer
  partner** to embed on hardware Deliverance doesn't control — a compromised or buggy
  partner device with direct DB credentials could write (or corrupt) the whole platform
  DB, not just its own robot's row. That's a real architectural decision (direct DB vs.
  a scoped REST API) for whenever this moves from prototype to something handed to a
  third party — flagged here so it isn't quietly forgotten, deliberately not solved by
  this file.
- **`_compute_status` only distinguishes `offline`/`idle`**, not `running`/`error`/etc.
  With only generic ROS signals (tf/scan freshness, battery) available across ANY
  robot, there's no honest way to know "is it currently executing a mission" without a
  robot-specific concept layered on top (e.g. WDC's own `mode` register, confirmed
  today in `integrations/deliverance-integrations-siruiy/CLAUDE.md` — but that's
  WDC-specific, a generic node can't assume it exists). Same discipline this workspace
  already applies elsewhere (e.g. Siruiy's own `unified_sync_platform.py` not guessing
  a `running` bucket from an unconfirmed register) — don't invent a status bucket from
  data that isn't confirmed to mean that, generically, for any robot.
- **No map/scene name.** There is no standard ROS concept of a named floor/scene the
  way `map_name` exists in Siruiy's own vendor API — `scene.name` is left `null` on
  purpose rather than guessing or hardcoding one.

## Confirmed with a SECOND, genuinely different robot (2026-08-26, same day)

`deliverance_agent_node_ros2.py` — a straight rclpy port, same
`_upsert_device`/`_upsert_device_status` logic byte-for-byte, only the ROS API
differs — validated live against `turtlebot_robot_sdk`'s real Gazebo+Nav2
simulation (`turtlebot-robot-sdk-vnc` container). This is the strongest
evidence so far that this is genuinely robot-agnostic, not secretly
WDC-shaped: different ROS major version (ROS2 Humble vs. WDC's ROS1 Noetic),
different robot entirely, same unmodified business logic.

One real bug hit and fixed on the way: TurtleBot's `/scan` (Gazebo's own
lidar plugin) publishes `BEST_EFFORT`/`VOLATILE` QoS; `rclpy`'s default
subscription QoS is `RELIABLE`, which is incompatible and silently receives
nothing -- no error, just a permanently empty topic, the same family of
"quiet gap" this workspace already hit once with `turtlebot_robot_sdk`'s own
map-QoS bug. Fixed by matching the publisher's QoS explicitly in
`create_subscription`.

Verified in the platform DB, a separate device row from `wdc-agent-sdk-test`:

```
name            | turtlebot-agent-sdk-test
category        | robot
enabled         | f
status          | idle
scene           | {"coordinates_x": -2.0184, "coordinates_y": -0.4542, ...}
last_connection | 2026-08-26 14:55:12   -- real Nav2/AMCL pose, matches the
                                           seeded start pose documented in
                                           turtlebot_robot_sdk/CLAUDE.md
```

Battery is reported honestly as `0` here, not faked -- TurtleBot's Gazebo
simulation has no battery topic either (same known gap `turtlebot_connector`'s
Edge SDK backend works around by faking one; this generic node has no
robot-specific channel to read a fake value from, so it doesn't invent one).

## Open questions / next steps

- [ ] Decide DB-direct vs. REST-API-in-front before this is ever given to the hardware
      partner (see above) — this is the single biggest remaining design decision, and
      it's Eduardo's/Carlos's call, not something to default silently.
- [x] Validate against a SECOND robot — done, see above (TurtleBot, ROS2, real
      Gazebo+Nav2, same day).
- [ ] `enabled=False` on insert (workspace convention) means `wdc-agent-sdk-test` won't
      show up on the dashboard until enabled by hand from "Enable Devices for
      Deliverance" — same as every other connector's first-sync device.
- [ ] Currently only reads `/scan`+`/battery_state`+tf. A real deployment would also
      want mission/task data — but Siruiy's own API has no task history at all (see
      the Edge SDK repo's CLAUDE.md), so WDC alone can't validate that half either;
      would need a different test robot with real mission tracking (e.g. TurtleBot's
      `mission_data_node.py` pattern) to prototype that side.

## Hard constraints (same as the rest of this workspace)

- Never merge to main — stay on feature branches (`feature/deliverance-agent-sdk`).
- Never push without explicit user approval.
- Never `git push --force`.
- Never commit `.env` files or secrets — this prototype's DB credentials were passed as
  plain env vars at `docker exec` time, never written to a file in this repo.
