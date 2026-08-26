# WDC Robot SDK — Context for Claude

## Status: FULLY VALIDATED live against the real robot (2026-08-26) — pose + laser confirmed visually in InOrbit

This closes the question that blocked WDC's Agent SDK track for about a month (robot
offline, network isolation looked like a dead end — see "The problem this answers" below).
**Answer: yes, Agent SDK works for WDC**, via a small bridge script, no LAN access needed.

Sibling experiment to [`../turtlebot_robot_sdk/`](../turtlebot_robot_sdk/), same boss-assigned
task (Agent SDK vs Edge SDK), second real-world case study after TurtleBot. Does **not**
replace [`integrations/deliverance-integrations-siruiy/`](../../../integrations/deliverance-integrations-siruiy/),
which is the separate Edge SDK answer for the same robot — see that repo's own CLAUDE.md.

**Local-only, not yet committed to a Dockerfile**: lives in an ad-hoc container
(`wdc-robot-sdk`, `osrf/ros:noetic-desktop-full`, `docker run -d ... sleep infinity`),
same pattern `turtlebot_robot_sdk` started with before it got formalized. Resume with
`docker start wdc-robot-sdk`, don't recreate — would lose the Agent Core install and mint
a new robot identity.

## The problem this answers

WDC's ROS1 computer is genuinely network-isolated (confirmed by Eduardo, 2026-07-29/30):
only reachable by cable from its own tablet, which does NOT speak ROS (confirmed: its
WebSocket to the embedded computer is a proprietary protocol, not rosbridge). Confirmed
live 2026-08-26 that Siruiy's own remote-access proxy doesn't help either — ROS1 ports
(11311 master, 9090 rosbridge, 11312) are closed on the robot's public proxy hostname;
only HTTP (the vendor's own API) gets through. **So Agent Core cannot run anywhere with
direct network access to the real ROS1 graph.** This blocked the whole investigation for
about a month (robot was also powered off most of that time).

**The insight that unblocks it**: Agent Core doesn't care where its ROS graph comes from.
It just subscribes to topics. And the vendor's own public HTTP/SSE API — reachable from
anywhere, no LAN access needed — turns out to echo back data shaped **exactly** like real
ROS messages, original field names intact (`frame_id: "laser_link"`, `angle_min`,
`angle_increment`, `range_min`/`range_max`). This is almost certainly the tablet's app
relaying real ROS1 topics from the embedded computer over its own protocol, which Siruiy's
cloud then wraps in this SSE feed for its own dashboard. We don't need to reach the
isolated LAN — we just need the data, and this public endpoint already hands it to us.

So: run a small ROS1 node **anywhere with internet** (this machine, an office server —
doesn't matter, see "why any machine works" below) that polls this public API and
re-publishes the SAME real data as genuine ROS1 topics on a local `roscore`. Agent Core,
running on that same machine against that same `roscore`, auto-detects them exactly like
it did for TurtleBot's real Gazebo topics — zero custom InOrbit code, same as before.

```
WDC (isolated) → tablet → Siruiy cloud (public HTTP/SSE, confirmed live) → src/wdc_bridge_node.py
                                                                                  ↓ publishes /scan, tf, custom_data
                                                                          local roscore + Agent Core
                                                                                  ↓ MQTT (outbound only)
                                                                             InOrbit Cloud
```

**Why any machine works, not just a "local computer"**: both hops out of our machine are
outbound-only — the bridge node polls Siruiy's cloud over plain HTTPS, and Agent Core talks
to InOrbit over outbound MQTT (`blue-label.brokers.inorbit.ai:8883`, same as TurtleBot).
Nothing needs an inbound connection, a static IP, or to be "near" the robot. "Local" here
only meant "not the isolated embedded computer" — any machine with outbound internet is
equally valid, dev laptop included.

**Trade-off, be upfront about it**: every hop adds latency (robot → tablet → Siruiy cloud →
our bridge → InOrbit). Confirmed the SSE feed updates every few seconds (live, not cached —
verified via `agvlocaltime` advancing in step with wall-clock polling gaps). Fine for a
telemetry/mission dashboard. **Not** viable for low-latency teleop — same caveat Eduardo
gave for any remote approach back in July, still true here regardless of transport.

## `src/wdc_bridge_node.py` — what it actually does

Plain `rospy` node, no InOrbit SDK, mirrors `turtlebot_robot_sdk/src/mission_data_node.py`'s
spirit (small script feeding real ROS topics/CustomDataAgentlet, not a vendored library).

- Polls `GET {ROBOT_URL}/events/service` (SSE) every 2s — **no auth needed**, confirmed
  live. This alone was a nice simplification: the register-table reads
  (`/table/reads`) and `login_robot()` that `SiruiyClient` needs for the Edge SDK path
  require login and hit the CAPTCHA-adjacent cloud auth eventually; the SSE feed doesn't,
  so this bridge sidesteps that whole concern entirely.
- Publishes:
  - `/scan` (`sensor_msgs/LaserScan`) from `location.scans[0]` — the **1043-point** array,
    not the coarser 138-point one under top-level `camera[]`. Both exist in the payload;
    `location.scans[0]` has real field names (`frame_id`, `angle_start`/`angle_max`,
    `increment`) and matches ROS's own `LaserScan` shape field-for-field. Confirmed live:
    real obstacle geometry (walls at 1.19m and 7.3m, clean gaps where the beam doesn't
    return), not noise.
  - `map` → `base_link` tf from `location.position` `[x, y, theta]` — **note: the third
    value is named `z` in the raw payload but is actually yaw in radians**, not a height.
    Unconfirmed against a spec sheet, inferred from context (a ground AGV has no reason to
    report a 3rd position axis; the values seen, ~0.006 rad, are far too small to be a real
    height and are exactly the right order of magnitude for "facing roughly forward").
  - a static `base_link` → `laser_link` tf from `location.laser.laserOffset` (translation
    only, no orientation given by the API — assumed identity/forward-facing, unconfirmed).
  - battery via `CustomDataAgentlet`, same two-key pattern as TurtleBot's
    `mission_data_node.py`: `"battery percent"` (0–1, feeds the account-level
    `xlXPmDo3Z3GMwSTM` Vitals gauge) from `stateInfo.powerquantity` (already 0–100 from the
    API, divided by 100 here). Only one key published (no tag-scoped `wdc-battery`
    DataSource exists yet, unlike TurtleBot's `turtlebot-battery` — would need a CAC applied
    if a dashboard-specific gauge is wanted later).
- **Not implemented**: `/map` (occupancy grid). Only have the map's *name*
  (`stateInfo.mapname`, e.g. `"ESPAITEC_1.yaml"`) from this API, not the actual grid data —
  no endpoint found for it. `RosMapAgentlet` will just have nothing to show until this gets
  filled in (manually uploaded, most likely — see "Open questions").
- **Not implemented**: camera. No image/video endpoint found in this API surface at all.
- **Not implemented**: mission/task tracking. Confirmed in the Edge SDK repo's CLAUDE.md —
  Siruiy's API has no task-history endpoint of any kind, so there's no WDC equivalent of
  TurtleBot's `mission_status`/`mission_tracking`.

## 🐛 Real bug found: this agent's ROS1 build needs the field-id suffix

`mission_data_node.py` (TurtleBot, ROS2 agent) publishes to the **plain** topic
`/inorbit/custom_data` and that's the default field ("0"), per the ROS2 agent's own
`CustomDataAgentlet` source (see `turtlebot_robot_sdk/CLAUDE.md`, "Custom data — validated
live"). Copied that same plain-topic pattern here first — **it silently did nothing**. No
error anywhere; the value just never appeared in InOrbit (confirmed via
`GET /robots/{id}/attributes/xlXPmDo3Z3GMwSTM` returning nothing before the fix, `{"value":
1, ...}` immediately after).

Root cause, found via `rostopic list -v` (not by reading agent source this time — quicker
to just look at who's actually connected): this agent's subscriber sits on
`/inorbit/custom_data/0` — **with the field-id suffix**, even for the default field.
Publishing to the plain topic reached a topic with **zero subscribers** — a real ROS1
topic, valid, just nobody listening. Fixed by publishing directly to
`/inorbit/custom_data/0`.

**Unconfirmed**: whether this is a ROS1-vs-ROS2 agent build difference (the two are
different binaries/packages even if functionally similar) or something else entirely
(different `custom_data_sources` config shape, different agent version — this one came in
at `4.26.0`). Don't assume the plain-topic pattern documented for TurtleBot transfers to a
ROS1 agent without checking `rostopic list -v` first.

## Validated live, 2026-08-26

- **Agent Core install**: same `liftoff` installer as TurtleBot, ROS1 auto-detected
  correctly from `ROS_DISTRO`/`ROS_MASTER_URI` env (`INORBIT_ROS="noetic"` in the generated
  `agent.env.sh`, no `?variant=` needed, matching the installer's documented
  `SUPPORTED_ROS1_DISTROS="kinetic melodic noetic"`). Same systemd-in-Docker failure at the
  end as TurtleBot (expected, harmless — no real init/PID1) — start manually:
  `source /root/.inorbit/local/agent.env.sh && /root/.inorbit/dist/scripts/start.sh`.
- Robot identity: `wdc-robot-sdk-test`, id `728470394`. Tagged `RS EU` (location) by Carlos
  via InOrbit Control directly (no CAC applied from here).
- **`RosMonitoringAgentlet` picked up our tf tree on load**, unprompted:
  `{'laser_link': 'base_link', 'base_link': 'map'}` — confirms the bridge's tf shape is
  exactly what a real robot's would look like.
- **Pose**: confirmed live via `inorbit expr eval 728470394 "getValue('pose')"` — real,
  advancing timestamps, matches the bridge's own SSE-sourced `x`/`y` to 3 decimal places.
  Also confirmed visually by Carlos in InOrbit Control's Robot tab (X/Y/theta panel).
- **Laser**: default `laser_topic` was `robot1/scan_front` (agent's generic placeholder,
  same as TurtleBot's own defaults were) — Carlos reconfigured it to `/scan` via InOrbit
  Control → Navigation tab → Map View, same UI/mechanism as TurtleBot. Agent log confirmed
  resubscription: `Registering subscriber to topic: /scan.`
  **Then went silent with zero errors** — root-caused by reading
  `agentlets/localization.py` directly (not guessed): `_ros_on_laser_all()` bails at its
  very first line whenever `RosMapAgentlet.map_published` is `False`
  (`_should_process_localization_data()`, same design as the gate behind the *different*
  TurtleBot map/QoS bug, but here it's working as designed — we genuinely weren't
  publishing `/map`). Fixed by having the bridge also publish a placeholder `/map`
  (20×20 cells, all "unknown", `latch=True`) purely to flip that flag — content is never
  validated by `_ros_on_map()`, only that *a* message arrives. **Confirmed visually by
  Carlos in the Navigation tab, 2026-08-26**: real laser geometry (room walls/corners)
  rendering live around the robot icon, distinct blue lines matching the raw SSE data's
  shape. The small dark square near the robot in that view is the placeholder map itself,
  correctly identified by Carlos as "invented," not a real scan of the room.
- **Battery**: confirmed via `GET /robots/728470394/attributes/xlXPmDo3Z3GMwSTM` (**not**
  `inorbit expr eval` — same transient-key-visibility quirk documented in
  `turtlebot_connector/CLAUDE.md` for `current_waypoint`/`task_label`; don't trust
  `expr eval` for a freshly-added custom-data key, verify via the REST attributes API
  instead) → `{"value": 1, ...}`. Also confirmed visually in Robot tab's Key Value pairs
  widget (`battery percent | 1.0 | recently`) once the topic-suffix bug above was fixed.

## Open questions

- **Map (occupancy grid) — found the real image, not yet a real `/map`.** Found via the
  robot's own web UI (`http://{ROBOT_URL}/#/pages/deploy/map`, Firefox devtools Network
  tab) that `POST /cache/getKey` with body `{"db":3,"keys":["centretalk:map"]}` (header
  `token: SUCCESS`, same convention as the rest of this API) returns the real live map:
  `{"format":"JPG","map":"<hex-encoded JPEG bytes>"}`. Confirmed live 2026-08-26: decodes
  to a real JPEG matching exactly what the deploy/map page renders (same L-shaped room,
  same notch). Saved as `espaitec1_real_map_reference.jpg` in this directory.
  **Not wired into the bridge** — this is a plain image, no resolution (m/px) or origin
  metadata came with it, and no sibling key was found for that either (tried
  `centretalk:map:info`, `centretalk:slam:map`, `centretalk:map:resolution`,
  `centretalk:map:origin`, `centretalk:slam:mapinfo`, `centretalk:map:yaml` — all `null`).
  Publishing it as `/map` without real calibration would mean guessing scale/offset by
  eyeballing the robot's known position against the image — that produces something that
  *looks* plausible but isn't verified, worse than the honest all-"unknown" placeholder
  currently in use. Left as a documented finding + reference image at first.
  The `/table/reads` register `330` (`map_name`) and this `cache/getKey` mechanism are
  two different vendor subsystems — worth remembering if picking this back up.

  **Applied and aligned, 2026-08-26.** `_publish_real_map()` in `wdc_bridge_node.py` now
  loads `espaitec1_map.jpg`, thresholds it (grey background -> unknown, white interior ->
  free, black outline -> occupied; JPEG-safe ranges, not exact-value matches), flips it
  vertically (image row 0 is top, `OccupancyGrid` row 0 is the bottom in world coords),
  and publishes it as the real `/map` (replacing the earlier blank placeholder, which is
  kept as `_publish_blank_placeholder_map()`, a fallback only if the JPEG fails to load).

  Resolution was first guessed at `0.03` -- wrong, corrected same day: Carlos pulled the
  real values from Keenon's and Allybot's own floorplan entries in InOrbit (same physical
  space, `RS EU`/Espaitec, their maps "provided by the robots" the same way this one is)
  -- both read exactly `0.05000000074505806`, the classic float32->float64 widening of
  `0.05`, confirming it's `map_server`'s own default resolution, not something either
  robot picked by hand. Matched that here too. Origin was NOT copied from either (Keenon:
  `origin ~= (-97.4, -101.8)`, Allybot: `~= (-0.91, -2.20)`) -- each robot's own SLAM
  origin is inherently arbitrary (tied to wherever that robot's own mapping session
  happened to start), there's no "correct" value to borrow; a human aligns
  position/rotation afterward regardless (see the pattern memory below).

  **Confirmed visually correct by Carlos** in InOrbit Control's Locations Editor: WDC's
  jagged real-scan outline now traces the same walls as Floorplan0's clean architectural
  lines (same L-shape, same notch), a dramatic improvement over the first alignment
  attempt (before the resolution fix), which was wildly oversized/offset. See workspace
  memory `reference_inorbit_floorplan_alignment_pattern` for the general pattern this
  follows (every office robot's own map gets manually aligned onto one shared
  Floorplan0 -- not WDC-specific).
- Camera: not found in this API surface. Possibly doesn't exist for this robot model, or
  exists at an endpoint not yet discovered.
- Teleop / custom commands: not attempted. `RosTeleopAgentlet` loaded with generic
  defaults (`cmd_vel` placeholder) same as TurtleBot's did before being pointed at a real
  topic — WDC has no equivalent of `/cmd_vel` reachable from outside the isolated LAN
  (confirmed: navigation goals go through the vendor's own `/agv/navigation` endpoint,
  fire-and-forget, not a raw velocity topic) — likely not worth pursuing given the latency
  trade-off already noted; telemetry-only was always the realistic target for this path.
- Formalize `wdc-robot-sdk` into a committed Dockerfile (currently ad hoc `docker run` +
  `docker cp`, same not-yet-reproducible state `turtlebot_robot_sdk` started in).
- Report the topic-suffix bug context back to whoever ends up productionizing this — not
  necessarily an InOrbit-side bug to file (unlike the TurtleBot map-QoS one), more of a
  "verify with `rostopic list -v` before assuming ROS2-agent docs transfer to ROS1."

## Hard constraints (same as the rest of this workspace)

- Never touch `integrations/deliverance-integrations-siruiy/` from here (separate Edge SDK
  answer for the same robot, different repo, different track).
- Read-only against the robot: this bridge only ever calls `GET /events/service`. No
  navigation commands, no writes of any kind to the real robot from this experiment.
- Do not commit secrets — this bridge needs none (`/events/service` requires no auth).
- Do not push without explicit approval; stay on `feature/turtlebot-robot-sdk` (this
  experiment was added to that same branch, not a new one, since it's the same
  boss-assigned Agent SDK evaluation task, just a second robot).
