# WDC Robot SDK — Context for Claude

## Status: FULLY VALIDATED live against the real robot (2026-08-26) — pose + laser confirmed visually in InOrbit

This closes the question that blocked WDC's Agent SDK track for about a month (robot
offline, network isolation looked like a dead end — see "The problem this answers" below).
**Answer: yes, Agent SDK works for WDC**, via a small bridge script, no LAN access needed.

**Update 2026-08-28**: Agent Core now also confirmed running physically on the tablet
itself (not a dev machine/cloud bridge), satisfying the literal "runs on the
robot" requirement — see "Real Agent Core running physically on the tablet" section
below for the full writeup, including the real root cause of a "no data reaching
InOrbit" bug that briefly looked like a ROS networking issue but wasn't.

Sibling experiment to [`../turtlebot_robot_sdk/`](../turtlebot_robot_sdk/), same
task (Agent SDK vs Edge SDK), second real-world case study after TurtleBot. Does **not**
replace [`integrations/deliverance-integrations-siruiy/`](../../../integrations/deliverance-integrations-siruiy/),
which is the separate Edge SDK answer for the same robot — see that repo's own CLAUDE.md.

**Local-only, not yet committed to a Dockerfile**: lives in an ad-hoc container
(`wdc-robot-sdk`, `osrf/ros:noetic-desktop-full`, `docker run -d ... sleep infinity`),
same pattern `turtlebot_robot_sdk` started with before it got formalized. Resume with
`docker start wdc-robot-sdk`, don't recreate — would lose the Agent Core install and mint
a new robot identity.

## The problem this answers

WDC's ROS1 computer is genuinely network-isolated (confirmed on site, 2026-07-29/30):
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
telemetry/mission dashboard. **Not** viable for low-latency teleop — the same caveat given for any remote approach back in July, still true here regardless of transport.

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
- Robot identity: `wdc-robot-sdk-test`, id `728470394`. Tagged `RS EU` (location) via InOrbit Control directly (no CAC applied from here).
- **`RosMonitoringAgentlet` picked up our tf tree on load**, unprompted:
  `{'laser_link': 'base_link', 'base_link': 'map'}` — confirms the bridge's tf shape is
  exactly what a real robot's would look like.
- **Pose**: confirmed live via `inorbit expr eval 728470394 "getValue('pose')"` — real,
  advancing timestamps, matches the bridge's own SSE-sourced `x`/`y` to 3 decimal places.
  Also confirmed visually in InOrbit Control's Robot tab (X/Y/theta panel).
- **Laser**: default `laser_topic` was `robot1/scan_front` (agent's generic placeholder,
  same as TurtleBot's own defaults were) — it was reconfigured to `/scan` via InOrbit
  Control → Navigation tab → Map View, same UI/mechanism as TurtleBot. Agent log confirmed
  resubscription: `Registering subscriber to topic: /scan.`
  **Then went silent with zero errors** — root-caused by reading
  `agentlets/localization.py` directly (not guessed): `_ros_on_laser_all()` bails at its
  very first line whenever `RosMapAgentlet.map_published` is `False`
  (`_should_process_localization_data()`, same design as the gate behind the *different*
  TurtleBot map/QoS bug, but here it's working as designed — we genuinely weren't
  publishing `/map`). Fixed by having the bridge also publish a placeholder `/map`
  (20×20 cells, all "unknown", `latch=True`) purely to flip that flag — content is never
  validated by `_ros_on_map()`, only that *a* message arrives. **Confirmed visually in the Navigation tab, 2026-08-26**: real laser geometry (room walls/corners)
  rendering live around the robot icon, distinct blue lines matching the raw SSE data's
  shape. The small dark square near the robot in that view is the placeholder map itself,
  correctly identified as "invented," not a real scan of the room.
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

  Resolution was first guessed at `0.03` -- wrong, corrected same day, by pulling the
  real values from Keenon's and Allybot's own floorplan entries in InOrbit (same physical
  space, `RS EU`/Espaitec, their maps "provided by the robots" the same way this one is)
  -- both read exactly `0.05000000074505806`, the classic float32->float64 widening of
  `0.05`, confirming it's `map_server`'s own default resolution, not something either
  robot picked by hand. Matched that here too. Origin was NOT copied from either (Keenon:
  `origin ~= (-97.4, -101.8)`, Allybot: `~= (-0.91, -2.20)`) -- each robot's own SLAM
  origin is inherently arbitrary (tied to wherever that robot's own mapping session
  happened to start), there's no "correct" value to borrow; a human aligns
  position/rotation afterward regardless (see the pattern memory below).

  **Confirmed visually correct** in InOrbit Control's Locations Editor: WDC's
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

## Device identity: brand and model (2026-08-27, resolved with real caveats)

`devices.model` for both `WDC` and `WDC InOrbit` (platform DB) is set to **`ECS100-A3`** --
seen literally on the robot's own System page ("备注"/note field) during today's IDE
exploration. Deliberately NOT set to a commercial SKU name (`WDC-20` or `W50`, see
below) -- `ECS100-A3` is the only value that came directly off THIS robot, everything
else is inference from public listings that may not match our exact unit.

**Brand name, corrected**: earlier today this file's chat history assumed "WDC" stood
for 万德昌/"Wandechang" (Shenzhen Wandechang Innovation Intelligent Co., a marketplace
listing found via web search, `industry.aipage.com`). **Wrong source to trust** --
the real manufacturer site was found, `wdcrobot.com`, and its own logo reads
**"WDC / WONDERCHAMP"**, not Wandechang. Plausible (not confirmed) that Wandechang is
the Chinese legal-entity name and WonderChamp the English export brand for the same
company -- phonetically close, common pattern for Chinese manufacturers -- but this is
an inference, not verified. Prefer "WonderChamp" over "Wandechang" going forward as the
higher-confidence name, since it comes from the manufacturer's own primary site rather
than a third-party B2B listing.

**Two candidate commercial models found, neither confirmed to be our exact unit**:
- `WDC-20` -- from the same third-party marketplace listing above, "max navigation
  speed 0.8m/s". Matches the "Default speed 0.8" seen in our robot's own decompiled
  app -- but that field is a literal *software default*, not a hardware max-speed
  claim, so this match is weaker than it looks at first glance.
- `W50` (`wdcrobot.com/home/product_detail/id/5`) -- visually similar to our robot
  (multi-tray cargo cabinet design, matches the PDF's own physical description), but
  its stated max speed is 1.5 m/s, a different number from the 0.8 above. Since `1.5`
  is a hardware max-speed spec and `0.8` is a software default, these two numbers are
  not necessarily in conflict (a robot can default well below its hardware ceiling) --
  but it also means the speed comparison can't be used to confirm or rule out either
  model. `WDC-20` and `W50` may simply be two different SKUs in the same product line;
  no data found here pins down which one (if either) matches our physical unit.

**Bottom line**: don't put `WDC-20` or `W50` in `devices.model` without a stronger
confirmation (e.g. a spec sheet or serial-to-model lookup) -- `ECS100-A3` stays the
platform's model field until then, precisely because it's the only value with a direct
line back to this actual robot.

## Local-only path found, 2026-08-27 -- supersedes the cloud read for the "runs on the
## robot" requirement

The project requirement explicitly rules out any architecture where the code reading
robot data depends on an external server: an integration that connects to an
external server is a connector, not an agent, and does not have to run on the
robot at all. `wdc_bridge_node.py`'s original design (still
what it does, see above) reads Siruiy's cloud SSE API -- exactly the pattern ruled
out, even though the data itself is real and the validation above still holds.

Two real local findings since then, full detail in the `project_wdc_local_api_found`
memory:

1. **The tablet's own production app hosts a local WebSocket server**, port 9015, path
   `/robot` -- found by decompiling `wdc_fabricante.apk` (this directory's `android_app/`),
   reading `MainActivity.java` and `WdcRobotApi.java` directly, NOT from
   `WDC_Robot_Interaction_Capabilities.pdf` (which claims a different, unconfirmed port
   6060). Confirmed live 2026-08-27 from a dev machine via a Tailscale subnet
   router into the office LAN (`192.168.3.0/24`) -- tablet is `192.168.3.102`. Simple
   JSON request/response, no auth (`{"cmd":"getPoses"}`, `{"cmd":"obtainingPower"}`,
   `{"cmd":"scan"}`). `wdc_bridge_node.py` was rewired to read from here instead of the
   cloud SSE endpoint (`LocalApiClient` class, hand-rolled stdlib WebSocket client, no
   new pip dependency).

2. **`deliverance_wdc_agent_app/`** (sibling directory to this one): a real, separately
   buildable Android app based on the manufacturer's OWN official SDK sample project
   (`wdc_robot_demo.7z`, supplied as what was thought to be an old app version -- it's
   actually a clean example of `com.sirui.selfstudysdk.main.SelfChassisState`, package
   `com.sirui.ego`, confirmed genuine: real `.idea`/`.gradle` artifacts, a real
   developer's `local.properties` path, no jadx signatures, and confirmed by actually
   running `./gradlew assembleDebug` -- builds clean, produces a real APK). This one
   connects DIRECTLY to the embedded chassis computer (`192.168.31.7:9090`), no tablet
   app involved at all. This is the actual "runs on the robot" answer: a separate app,
   different package id than production `com.sirui.wdc_robot`, installs alongside it
   with zero risk (no signing-key conflict since it's not an update to anything).
   `MainActivity.java` currently polls pose/battery/charging every 2s and logs it
   (`sendTelemetry()` is a deliberate stub) -- see that file's own docstring for why the
   actual transport (InOrbit vs Deliverance's platform) isn't wired up yet, it's a real
   open decision, not an oversight.

   Modifying the production APK directly (patch+resign) was tested and works
   mechanically (apktool round-trip decompile/rebuild/sign succeeds clean) but is a dead
   end for updating the live app: Android requires matching signing keys to install as
   an update, and we don't have the manufacturer's real key -- would require uninstalling
   the production app first, too risky on a robot in daily use. `deliverance_wdc_agent_app/`
   avoids this entirely by being a new app, not a patch.

   `TelemetryService` (a proper foreground service, not just Activity code -- survives
   backgrounding/screen-off) + `BootReceiver` (auto-starts on every power-on) are already
   in place and building clean. Only `sendTelemetry()` is still a stub.

   **Investigated but NOT YET implemented** (2026-08-27, reading the rest of
   `SelfChassisState.java` and its raw message handler in full): the SDK offers more than
   what `TelemetryService` currently reads.
   - **Real map, precisely** -- `{"cmd":"getmap_source","map":<real map name>}` (constant
     `OpContent.OBTAINING_A_MAP`) returns the actual image (hex-encoded JPEG) PLUS exact
     `width`/`height`/`resolution`/`offx`/`offy` in `getMapData()`. Strictly better than
     `wdc_bridge_node.py`'s current approach (cached JPEG from Siruiy's cloud, resolution
     guessed by comparing against Keenon/Allybot's own entries) -- this path needs no
     guessing at all. NOTE: the SDK's own `getMap()` method hardcodes a wrong/placeholder
     map name (`"87326399.yaml"`) -- don't call it as-is, send the same request manually
     with `SelfChassisState.getInstance().getMapName()` instead.
   - **Real mission/route data exists** -- `getautonaveglobalpath()` /
     `getWalkingRoute()` (global path) and `getRoute()` / `analyticCircuit()` (all saved
     lines/routes) return real data. This is the first real "mission tracking" capability
     found for WDC at all -- Siruiy's cloud API has none (see `wdc_bridge_node.py`'s own
     docstring). Not explored deeply enough yet to design the actual mapping into
     `mission_tracking`-style fields.
   - **Stations** (`getStations()`, populated via `readConfiguration()`/`getSite()`) work,
     but the SDK's own message handler only keeps the FIRST station from the response
     (`points.get(0)`), discarding the rest -- a limitation of this reference code, not
     the robot. Getting the full list would need listening to the raw `readstations_result`
     message ourselves rather than relying on `SelfChassisState`'s built-in handling.
   - `getFrontLaser()` -- a single pre-filtered "closest obstacle roughly straight ahead"
     reading (±5 degrees), cheaper than consuming the full scan for basic proximity checks.

## Project direction 2026-08-27: InOrbit first, own platform on hold

Project direction 2026-08-27: test InOrbit only for now -- our own platform's
telemetry can come later via the EXISTING `inorbit_sync_platform` connector (already
syncing Autoxing/Keenon/Allybot/TurtleBot into the platform DB), once WDC feeds InOrbit,
instead of building a new direct-to-platform pipeline right away. So
`deliverance_wdc_agent_app` (Objective 2) is parked, not abandoned -- already built and
compiling, picked back up later. The "Deliverance's own Agent SDK as a product"
conversation is also deferred to a dedicated meeting once WDC itself is done.

Immediate priority: get InOrbit's real Agent Core running on the tablet via Termux
(Objective 1, "runs on the robot" literally, not via a VPN-reachable dev machine like the
earlier `wdc_bridge_node.py` cloud/local-API versions).

## Real Agent Core running physically on the tablet, live end-to-end 2026-08-28

Full stack (Termux → proot-distro Ubuntu 20.04 → ROS Noetic → `wdc_bridge_node.py` →
InOrbit Agent Core, unmodified installer) running natively on the real tablet, genuine
64-bit ARM (`aarch64`). Confirmed live via InOrbit's own REST API, not just `rosnode`/
`rostopic` checks: `GET /robots/223623373/attributes/xlXPmDo3Z3GMwSTM` →
`{"value":1,"ts":<fresh>}`, and `inorbit expr eval 223623373 "getValue('pose')"` →
real, advancing `x`/`y`/`theta` with a timestamp matching wall-clock at query time.
This satisfies the project's literal requirement: the agent runs "de
forma interna" on the robot itself, no external server in the loop.

**Real bug found and fixed, 2026-08-28: "no data reaching InOrbit" was NOT a ROS
networking bug.** Spent a while suspecting `ROS_HOSTNAME`/`ROS_IP` addressing under
PRoot (comparing against the old Docker container, which resolved its own hostname to
a real Docker-bridge IP rather than loopback) — that was a reasonable hypothesis but
turned out not to be the actual cause. The real cause, found by reading
`wdc_bridge_node.py`'s own log directly rather than guessing further: the bridge's
`WDC local API request(...) failed: [Errno 111] Connection refused` on every single
poll. The tablet's own manufacturer app (`com.sirui.wdc_robot`), which hosts the local
API on port 9015, closes or loses foreground on its own from time to time (same
symptom already found and fixed once earlier this same session by running
`am start -n com.sirui.wdc_robot/.MainActivity` over SSH) — confirmed by watching the
port flip open (right after `am start`) then closed again unprompted within under
70 seconds, repeatedly. Not yet root-caused at the Android level (couldn't confirm via
`dumpsys power`/`dumpsys activity` — Termux's `uid` lacks permission to dump those
system services on this device), but the *symptom* is fully confirmed and reproducible.

**Fix applied**: `~/wdc_watchdog.sh` on the tablet, a plain shell loop (no InOrbit/ROS
involved, nothing external) that checks `/dev/tcp/127.0.0.1/9015` every 10s and reissues
`am start -n com.sirui.wdc_robot/.MainActivity` whenever it's closed. Still fully local
to the tablet — doesn't compromise the "no external server" requirement. Wired into
`vpn_setup/start-deliverance.sh` (both the live tablet copy at
`~/.termux/boot/start-deliverance.sh` and this repo's copy) so it starts automatically
alongside roscore/bridge/agent on every boot. Confirmed live: after the watchdog
re-foregrounded the app once, `rostopic echo /inorbit/custom_data/0` showed a full,
real set of key-values (`battery percent`, `error_code`, `localization_confidence`,
`active_map`, `firmware_version`, `charge_step`, `charging_current`, `agv_stopped`) and
InOrbit's own REST API confirmed both battery and pose fresh moments later.

**Also changed while investigating (kept, even though it wasn't the actual root
cause)**: `ROS_HOSTNAME`/`ROS_IP` in the boot script now use the tablet's real WiFi IP
(`192.168.3.102`) instead of `localhost`/`127.0.0.1`, for roscore, the bridge, and the
agent alike. Not proven necessary on its own (the localhost config had already gotten
the ROS graph itself connecting fine — `rostopic info` showed a matched pub/sub pair
even before this change), but it matches the old working Docker container's own
addressing style and was the config in place when the pipeline was confirmed working
end-to-end, so kept as the known-good baseline rather than reverting to retest in
isolation.

Old comparison container `wdc-robot-sdk` (Docker, robot `728470394`) stopped again
after the networking comparison above -- no longer needed now that the tablet itself
has a confirmed working Objective-1 implementation. `docker start wdc-robot-sdk` to
bring it back if a side-by-side comparison is needed again.

## Live map wired in, vertical-flip bug found and fixed, same day (2026-08-28)

`_publish_real_map()` now fetches the map LIVE via `cmd:"map"`
(`WdcRobotApi.getAMap()` -> `SelfChassisState.getMapData()`, found by decompiling
`wdc_fabricante.apk` in full with `jadx` -- see "Full local API command set" below) --
a base64 JPEG data-URI plus REAL `resolution`/`width`/`height`/`offx`/`offy` straight
from the robot's own SLAM state, no more guessing (`_publish_static_fallback_map()`
kept as a fallback only, same static jpg as before).

**Real bug found and fixed**: this JPEG is already in `OccupancyGrid`'s own
row-0-is-bottom order -- unlike the old static jpg, which needed a vertical flip
(image row 0 is top). Copying that same flip onto the new live image was wrong and
made the robot render entirely outside/above its own published map in InOrbit's
Navigation tab. Found and fixed by ground-truth testing, not by eyeballing screenshots
(a screenshot comparison first raised the alarm, correctly) -- checked
live whether the robot's own pose and laser-scan endpoints land on the right pixels
in the map image under both row orderings:

| convention | robot's own pose lands on | scan endpoints landing on a wall pixel (859 samples) |
|---|---|---|
| flipped (wrong) | "unknown" grey (205) | 0% |
| as-is (correct) | free/white (255) | 20% wall, 80% free, 0% outside map bounds |

0% landing outside the map's bounds is the meaningful number -- confirms the
coordinate frame itself is right. The 80% landing on "free" instead of "wall" isn't a
bug: a live scan sees the room's current state (furniture, people) while the map is a
fixed snapshot from whenever it was last saved -- they were never going to match
pixel-for-pixel, same as every other robot's map here.

**Earlier same-day scare, resolved**: first compared cmd:"map"'s shape against Siruiy
cloud's own live map view (`.../pages/deploy/map`) and the shapes looked different
enough to revert to the static jpg out of caution. Turned out to be the wrong
comparison, not a real bug in cmd:"map" -- likely comparing against that view's LIVE
scan overlay (which draws real-time sensor data extending past whatever's baked into
the last saved map) rather than the saved map's own boundary. The real, decisive test
was the pose/scan-vs-own-map ground-truth check above, not a shape comparison against
a different, not-directly-comparable view.

## Full local API command set (found decompiling `wdc_fabricante.apk` with `jadx`, 2026-08-28)

Earlier sessions only found 4 commands (`getPoses`, `scan`, `obtainingPower`, `info`)
by testing what happened to be documented. A full `jadx` decompile of
`WdcRobotApi.java`'s `parseInstructions()` switch statement shows the REAL complete
set is 9 commands:

- **Read-only** (safe, this bridge only uses these): `getPoses`, `scan`,
  `obtainingPower`, `info`, `map` (see above).
- **Write/control** (deliberately NOT used -- this bridge is read-only against the
  real robot, see "Hard constraints"): `navigation`/`navigations` (drive the robot to
  a waypoint), `charging` (send it home to charge, `goHome()`), `stopAction` (stop
  motion), `speech` (play TTS on the robot's own speaker).

`info`'s real full field set (`getInfo()` in the decompiled source): `readycode`,
`result`, `stop`, `chargestep`, `chargingCurrent`, `agvStop`, `quantity`, `robtId`,
`version`, `mapName`, `floor`, `confidenceCoefficient`, `errorcode`, `agvlocaltime`,
`chargingPosition` ({x,y,z} of the charging dock -- z is very likely yaw in radians,
same unconfirmed-but-consistent inference as `location.position`'s own z field, not
independently verified). Currently published: `errorcode`, `confidenceCoefficient`,
`mapName`, `version`, `chargestep`, `chargingCurrent`, `agvStop`, `floor`. Not yet
published (available if wanted): `robtId` (real per-robot serial, e.g.
`WDC-0526822895`), `agvlocaltime` (robot's own internal clock, epoch millis --useful
to verify freshness independent of our own polling clock), `quantity` (raw 0-100
battery, redundant with `obtainingPower`), `result`/`readycode`/`stop` (status codes,
meaning not yet decoded), `chargingPosition` (dock location, could feed a
`SpatialAnnotation` like Allybot's `allybot-cs`, see `deliverance-connectors/CLAUDE.md`).

Also confirmed (`VideoActivity.java`, and a repo-wide search of the app's own
package for camera/video/rtsp/stream): **no live camera capability exists anywhere in
this app**, on this local API or otherwise. The only video-related code is a
`VideoView` playing a static demo file (`/sdcard/oem/1.mp4`), not a live feed. Closes
the "can we show a camera in InOrbit" question raised 2026-08-28 with a
definite no, for this tablet/app at least (a different, distinct "3D anti-collision"
proximity sensor DOES exist per the register table below, but it's a boolean alarm
flag, not a camera or a distance measurement, and it's on a different data channel
entirely).

## `3D防撞` (3D anti-collision) register found, 2026-08-28 -- different data channel, not wired in

the hand-copied register table (`wdc_table_registros.txt`, see
`integrations/deliverance-integrations-siruiy/CLAUDE.md`'s own register-table
section) has a real entry: `3D防撞` ("3D anti-collision"), address `0x23e`, type
`uint8`, range 0-1 -- confirmed it's a genuine hardware feature (a proximity/collision
sensor distinct from the 2D lidar this bridge already streams as `/scan`), but it's
just a **boolean alarm flag** (triggered / not triggered), not a distance
measurement in metres. Reachable only via the Siruiy Edge SDK integration's
`/table/reads` register API (`integrations/deliverance-integrations-siruiy/`), NOT
via this repo's local WebSocket API (port 9015) -- confirmed absent from all 9
commands in `WdcRobotApi.java` (see above). Not wired into anything yet -- would need
either adding it to the Siruiy Edge SDK integration, or finding it (unlikely, not
present in any of the 9 commands checked) somewhere in the local API.

## Termux:Boot survives a real physical reboot -- confirmed live 2026-08-29

The one previously-untested caveat (auto-start on boot, written 2026-08-28 but never
tested against an actual power cycle) is now confirmed working end-to-end. The
tablet was rebooted by hand (2026-08-29 00:16 local tablet time) to test this
deliberately. Confirmed via SSH immediately after: `uptime`
showed "up 1 min" (genuine fresh boot, not a stale session), and `ps aux` showed
`wdc_watchdog.sh`, `roscore`, `wdc_bridge_node.py`, and the InOrbit agent
(`python -u inorbit.py`) all freshly started (same start timestamp as the boot) with
zero manual intervention -- Termux:Boot's `~/.termux/boot/start-deliverance.sh`
executed the whole chain correctly on its own. Confirmed data reached InOrbit again
within 15s of the processes coming up (`GET /robots/223623373/attributes/...` battery
and `inorbit expr eval ... "getValue('pose')"` both returned fresh timestamps).

**Also found, useful for future incident response**: this tablet's `su` binary
(`/system/xbin/su`) grants root with no prompt/setup at all (`su -c id` ->
`uid=0(root)`) -- this is an "eng" build (`ro.build.type=eng`,
`ro.debuggable=1`), which explains it. Not used for anything so far (no `reboot`
binary is even present in Termux's own `$PATH`, and no need has come up to actually
issue one remotely -- that reboot was done by pressing the physical button),
but worth knowing this exists if a remote reboot/recovery is ever needed without anyone physically present.

## Real 38-hour disconnection, root-caused and fixed -- 2026-08-31

WDC was noticed showing disconnected in InOrbit (last real pose from 2026-08-29
19:37, found 2026-08-31 ~09:44 -- confirmed via the actual `ts` field on
`inorbit expr eval`, not just the dashboard's "recently"/"offline" label). The tablet
itself was fully healthy the whole time -- `uptime` showed 2 days 15h with no reboot,
`sshd`/`roscore`/`wdc_bridge_node.py`/`wdc_watchdog.sh` all still running fine. Only the
InOrbit agent process itself (`python -u inorbit.py`) was gone.

**Root cause, found in the agent's own log** (`/root/.inorbit/local/inorbit_agent.log`,
not guessed), last line before it stopped: `INFO __main__: Agent finishing to force
system restart.` -- the agent deliberately exits itself sometimes, expecting an
external supervisor to relaunch it (this is what `INORBIT_ENABLE_WATCHDOG` is for,
set to `"no"` in our `agent.env.sh`). Our launch mechanism was "start it once" (a plain
`nohup ... start.sh &`), so when it self-exited, nothing relaunched it -- and since the
tablet never rebooted, Termux:Boot never got a chance to either. Not an OOM kill, not a
crash, not a network issue -- a normal InOrbit-internal restart request that had nobody
to answer it.

**Fixed two ways**, both live-verified (`inorbit expr eval` showing fresh timestamps
again within seconds of each fix):
1. Wrapped roscore/bridge/agent launches in `vpn_setup/start-deliverance.sh` in
   `while true; do <launch>; sleep 3; done` loops (previously "launch once") -- applied
   both to the boot script (`~/.termux/boot/start-deliverance.sh` on the tablet) and
   live, by killing and relaunching the already-running agent under the same loop, so
   the fix took effect immediately rather than waiting for the next reboot.
2. Added `com.termux` and `com.sirui.wdc_robot` to Android's Doze/battery-optimization
   whitelist (`su -c 'dumpsys deviceidle whitelist +<package>'`, using the root access
   found 2026-08-29 -- see "Also found, useful for future incident response" below).
   Reduces (doesn't eliminate) the chance Android's own power management kills or
   throttles either app in the background. Expected to persist across reboots
   (Android normally persists this list to disk) but not yet verified against an
   actual reboot -- worth re-checking (`dumpsys deviceidle whitelist | grep -E
   'termux|sirui'`) next time the tablet restarts for any reason.

**Still not covered by either fix above -- now closed with a third**: if Android kills
the Termux **app process itself** (not just a script running inside it), the restart
loops die with it since they live inside Termux's own process tree; the Doze whitelist
only lowers the odds, doesn't make it impossible. Suggested approach: detect this
and force a real reboot. Closed via `vpn_setup/reboot_watchdog.sh` +
`termux-job-scheduler` (from the `termux-api` Debian package -- had to `pkg install`
it, wasn't there yet despite the Termux:API Android app being installed earlier;
these are two separate halves of the same feature, both needed). JobScheduler is an
Android system service, not a Termux child process -- it survives Termux being killed
entirely, and will start a fresh Termux process just to run the scheduled script even
if the app was fully dead a moment before. The script checks whether `roscore`,
`wdc_bridge_node.py`, and `inorbit.py` are all running; if any are missing, it's a
strong signal Termux itself died (our own restart loops would otherwise have kept them
alive), and it calls `su -c reboot` -- a real device reboot, recovering the same way
the 2026-08-29 manual reboot did via Termux:Boot. Scheduled every 900000ms (**15
minutes -- Android's own enforced minimum for periodic jobs since Android N**, not a
choice), `--persisted true` (survives reboots on its own), and also re-scheduled every
boot from `start-deliverance.sh` as a belt-and-braces second layer in case
`--persisted` doesn't hold on this particular Android build.

**Live-tested end-to-end, 2026-08-31** -- confirmed
the full real trigger path works, not just that the job is scheduled. Deliberately did
NOT use `am force-stop` to simulate the kill -- Android puts force-stopped apps into an
explicit "stopped" state that blocks JobScheduler/broadcasts/alarms from running at all
until a human manually reopens the app, which would have made this test pass or fail
for the wrong reason (proving/disproving force-stop's own special-cased behavior, not
our actual target scenario of an ordinary background low-memory kill). Used
`su -c 'kill -9 <termux_main_pid>'` instead (found via `su -c pidof com.termux`) --
a plain SIGKILL on the app's own process, which does NOT trigger that same "stopped"
state, faithfully matching what a real OOM kill does.

Result: killed at `ts=1788162922`; `reboot_watchdog.log` shows it fired and forced the
reboot at `ts=1788163690` -- **12.8 minutes later**, inside the expected 15-minute
window. `uptime` afterward confirmed a genuine fresh boot ("up 7 min" when checked),
every process (`wdc_watchdog.sh`, `roscore`, `wdc_bridge_node.py`, `inorbit.py`) came
back up on its own via the normal Termux:Boot chain, and InOrbit showed fresh
telemetry again within 10s of the processes restarting. Confirms the full recovery
chain -- Termux killed -> JobScheduler survives it -> watchdog detects the missing
processes -> real reboot -> Termux:Boot -> everything back -- genuinely works, not
just each piece in isolation.

**Real blocker found investigating this, 2026-08-27, not yet resolved**: InOrbit's own
installer (`curl https://space.inorbit.ai/liftoff/<key> | sh`, saved to
`vpn_setup/inorbit_installer.sh` for reference) assumes an Ubuntu-based host -- it
branches on Ubuntu codenames (`bionic`/`focal`/`jammy`/`noble`) for core logic (package
installs, autostart setup). Termux is its own environment, not Ubuntu, even though it
provides a real Linux userland -- this installer will very likely fail OS detection
before even reaching the question of 32-bit ARM (`armeabi-v7a`, confirmed the tablet's
real architecture from the SDK's own `abiFilters`) support. Not a hard "impossible", but
real adaptation work, not a drop-in install. Needs either patching the installer/running
its steps manually adapted for Termux's `pkg` instead of `apt`, or testing directly on
the tablet to see exactly how far it gets before giving up and guessing.

**Correction 2026-08-28, from reading the tablet's settings screen directly**:
Android is actually **7.1**, not 5.1 -- his first answer was wrong (not looked up
carefully). This matters a lot: 7.1 meets modern Termux's own minimum (Android 7+), so
the whole Linux-Deploy detour below was solving a problem that doesn't exist -- plain
Termux + proot-distro (the original, simpler plan) works fine here. Also: Developer
Options are already enabled on this tablet, which opens a real possibility -- USB
debugging + one-time USB connection to any computer + `adb tcpip 5555` would open ADB
over the network (reachable via the existing Tailscale route), letting Claude do the
rest of the setup remotely instead of walking someone through every step by hand. Not
yet tried as of this writing.

**Original (2026-08-27) entry, now superseded by the above but kept for the
PRoot/opencv findings which still apply**: Android confirmed 5.1 (Lollipop, released
2015). Tried to fingerprint it remotely first (full port scan 1-65535 on the tablet,
only 9015 open; no useful HTTP/WS banner) -- no reliable remote signal exists, had to be
asked directly. This is old enough to matter: modern Termux (F-Droid) requires Android
7+, and Termux dropped Android 5/6 package support in 2020 -- the surviving
`apt-android-5` fork is frozen with no ongoing updates, and `proot-distro` (needed for
the Ubuntu-userland fix below) is newer than that fork and very likely incompatible with
it.

**Better fix given Android 5.1, found 2026-08-27**: **Linux Deploy** instead of
Termux+proot-distro -- a different, actively-maintained app doing the same PRoot-based
"real Ubuntu inside Android, no root" trick, whose CURRENT release (2.6.0, not an
archived old version) officially requires only Android 5.0+. Has a no-root PRoot mode
(root mode also exists but rooting a production tablet isn't worth the risk here). This
avoids the frozen-Termux-fork problem entirely since it's live, current tooling that
happens to still support this old a device.

**Real worry raised, resolved positively**: does using Edge SDK instead of
Agent Core defeat the whole point? Yes it would -- Edge SDK means writing a WDC-specific
adapter again, exactly the `integrations/deliverance-integrations-*` pattern this was
supposed to avoid. Correctly rejected; stayed with Agent Core (ROS auto-discovery).

**Also resolved positively**: worried ROS1 itself might not run well on such an old ARM32
device. Confirmed via ROS's own official docs: both Melodic (Ubuntu Bionic 18.04) and
Noetic (Ubuntu Focal 20.04) ship OFFICIAL armhf/armv7 32-bit packages -- this isn't
community/experimental support, real robots run ROS1 on ARM boards like this all the
time. (Would have been a much harder "no" if this robot used ROS2 instead -- zero
official Android support for ROS2 at all, see [[project_robot_sdk_task]] history.)

**Net picture after all this**: ROS1-on-ARM32 is solid, Linux-Deploy-on-Android-5.1 is
solid. The one genuinely open unknown left is PRoot's own overhead/compatibility running
something as complete as roscore+Agent Core -- not a "does the ecosystem support this"
question anymore, purely a "how well does this specific virtualization layer perform"
question, answerable only by testing on the real tablet.

## Write path added: Actions, Current Mode, Missions -- 2026-08-28, real robot movement authorised

The project owner asked to enable the Robot Actions panel
(navigation buttons + Stop/Charge) and the "Current Mode"/Missions widgets for WDC,
overriding this file's own earlier read-only stance below -- Confirmed explicitly before proceeding. This is a real, deliberate policy change, not a drift -- see the corrected "Hard
constraints" section below.

### Current Mode / `mission_status`

InOrbit's account-wide "Modes and Tags" widget (Settings > Organization > Modes) reads
one specific key-value, `mission_status`, account-scoped `DataSourceDefinition` id
`mission_status` -> `key: mission_status` (confirmed by reading it directly with
`inorbit get config`, and by reading `allybot_connector/cac/data_sources.yaml`'s own
tag-scoped override, which documents the exact accepted values in a comment: "Idle",
"Mission", "Paused", "Charging", "Error"). Robots are bucketed **live/dynamically** by
whatever value they currently report -- NOT a static per-robot membership list (initial
assumption, corrected after actually reading the settings page: the "X ROBOTS"
counts shown per mode are just "however many robots currently report that value", so no
manual per-robot registration step exists at all).

No tag-scoped override was added for WDC (unlike Allybot's) -- WDC has no dedicated
hardware tag (only the generic "Robot"/"RS EU" tags), so the account-level default
already applies.

`wdc_bridge_node.py`'s `_compute_mission_status(info)` derives one of these 5 values
(never "Manual" -- no field in this local API distinguishes teleop) each tick from
fields already being read: `errorcode` truthy -> "Error"; `chargingCurrent > 0` ->
"Charging"; `agvStop` -> "Idle"; else -> "Mission". Confirmed live end-to-end via the
REST attributes API (`GET /robots/223623373/attributes/mission_status` -> fresh
timestamp) and visually in the "Modes and Tags" widget switching between Idle/Mission/
Charging in real time as real actions were fired.

### Robot Actions -- `ActionDefinition` type `PublishToTopic`, not `RunScript`

The Edge SDK connectors here (Keenon/Allybot/Autoxing) use `type: RunScript` --
InOrbit calls back into the connector's own process. Agent SDK is different: InOrbit's
shipped `CustomCommandsAgentlet` (read directly from
`/root/.inorbit/dist/inorbit/agentlets/custom_commands.py` on the tablet, not guessed)
subscribes to an MQTT topic and republishes onto a plain ROS topic,
`ROS_CUSTOM_COMMAND_TOPIC = "inorbit/custom_command"` (**singular** -- InOrbit's own
public docs, fetched via WebFetch, say `/inorbit/custom_commands` plural; the real
shipped agent source is the ground truth here, confirmed by the fact our bridge's
subscriber and the agent's own publisher matched up immediately with the singular
name, `rostopic info` showing both ends connected). The correct CAC type is
`ActionDefinition` `type: PublishToTopic`, `arguments: [{name: topic, value:
inorbit/custom_command}, {name: message, value: "<our own command string>"}]` -- the
message content is entirely our own convention (matches Keenon's own `filename`
argument being an arbitrary string that connector's code recognizes, not something
InOrbit prescribes).

`wdc_bridge_node.py._on_custom_command()` subscribes to that topic and recognizes:
`STOP` (-> `stopAction`, no params), `CHARGE` (-> `charging`, no params), and
`GOTO_<NAME>` (-> `navigation` with real `name`/`x`/`y`/`yaw`). Deliberately a small
explicit if/elif, not a lookup-table dispatch -- every branch moves a real robot, an
unrecognized string should do nothing rather than something unexpected from a coding
mistake in a generic table.

`cac/actions.yaml` defines 8 actions (`wdc-stop`, `wdc-charge`, `wdc-goto-a` through
`-e`, `wdc-goto-home`), scoped to `robot/rnLasGAxn5CP7bj32/223623373` directly (no
dedicated tag exists for WDC). Movement actions have `confirmation.required: true`;
Stop and Charge don't (Charge is never dangerous -- worst case it's already there and
nothing happens, confirmed live). Applying this CAC got blocked once by Claude Code's
own auto-mode classifier (expected and correct -- it's config that can move a real
robot) -- applied manually from a terminal after confirming intent.

### Named point coordinates -- found in the tablet app's own local storage, NOT recorded by hand

The A/B/C/D/E buttons on the manufacturer app's own "Delivery Mode" screen (seen on the tablet, 2026-08-28) need real x/y/yaw -- the local WebSocket API's `navigation`
command takes raw coordinates, no named-waypoint lookup exists anywhere in its 9
commands (confirmed against the full decompiled `WdcRobotApi.java`). Initially assumed
this would require physically parking the robot at each point via the tablet app and
recording `getPoses()` live (nobody was available on site to do this) -- turned out
unnecessary. Found instead, read-only, with the tablet's own root access (`su`, see
"Also found, useful for future incident response" below):

```
su -c 'sqlite3 /data/data/com.sirui.wdc_robot/databases/DCStorage \
  "SELECT value FROM DC_3928737_storage WHERE key=\"pointPosition\""'
```

The app is built with DCloud/uni-app (HTML/JS hybrid, not pure native Java --
`files/apps/__UNI__6504895/www/`, `weex` cache dirs), and its `DCStorage` sqlite db is
uni-app's own `localStorage` persistence -- the exact same data the "Delivery Mode"
screen itself reads to draw buttons A-E, real values, not inferred:

| Point | x | y | yaw |
|---|---|---|---|
| A | 0.276 | 0.612 | -0.046 |
| B | -0.712 | 0.617 | -1.260 |
| C | 3.623 | -2.191 | -1.024 |
| D | 4.266 | -1.959 | 1.969 |
| E | 4.646 | -2.560 | 2.103 |

Key `regular` (same db) also has named system points: Home (-0.334, -0.250, -0.000),
Return Point (-0.335, -0.250, -0.001), Recycling point (-0.333, -0.262, 0.001) -- Home
wired into `wdc-goto-home`, the other two not exposed as actions (no clear use case
yet). All in `wdc_bridge_node.py`'s `NAMED_POINTS` dict -- if these are ever redefined
in the app, this dict needs manual updating, same maintenance burden as Keenon's own
hardcoded `point_uuid`/x/y in `keenon_connector/cac/actions.yaml`.

### Mission tracking -- same shape as `turtlebot_robot_sdk`'s own Agent SDK sibling

Copied `turtlebot_robot_sdk/src/mission_data_node.py`'s `mission_tracking` JSON shape
field-for-field (that file's own docstring warns InOrbit **merges** each custom_data
publish into the previous JSON instead of replacing it -- fields that should disappear,
like `currentTaskId`/`endTs`, must be set to `None` explicitly, never omitted, or stale
values stick forever; respected here the same way). We have no Nav2 action-status topic
to observe, so `agvStop` (real-time, from "info") stands in as ground truth for
"actually moving right now": a moving-to-stopped transition while a task is tracked
means arrival/completion; `errorcode` becoming truthy means Aborted (no "Canceled" --
`stopAction` can't be told apart from "arrived" with the fields we have).
`cac/mission_tracking.yaml` (`MissionTracking`, scoped to the robot, `processingType:
api`, `stateDefinitions` for Executing/Completed/Aborted) applied cleanly (not blocked
by the classifier, unlike the Actions CAC -- this one only affects how InOrbit
interprets already-published data, doesn't itself act on the robot).

**Confirmed live** in InOrbit's own Missions widget: real entries appeared with correct
labels ("Go Charge", "Go to Home", "Go to B") and state transitions (Executing ->
Completed/Aborted) as real actions were fired against the physical robot.

**Known real limitation, not yet fixed**: only ONE task is tracked at a time (plain
instance variables, no queue). Firing a second action before the first finishes
silently overwrites the tracking state -- the first mission's entry freezes at
whatever state it last had (seen live: a "Go Charge" stuck at "Executing" forever after
a "Go to Home" was fired 9 seconds later). Not dangerous (the robot itself just accepts
the newest navigation command, per `WdcRobotApi.navigation()`'s own lack of queueing)
-- purely a reporting gap. Fix would mean either tracking a small stack of recent tasks
or explicitly marking the previous one "Aborted"/"Canceled" the instant a new command
interrupts it.

## The three pending items investigated/closed, 2026-08-31

The three follow-up items identified after the executive summary -- camera, mission
progress, task overlap. All three addressed the same session.

### Camera / teleoperation -- investigated, closed with a definite "not from here"

Went back to the decompiled `wdc_fabricante.apk` with real tooling this time (no
`jadx`/Java available in this sandbox -- installed `androguard`, a pure-Python APK
analysis library, in a local venv instead) to answer this properly rather than
re-asserting the earlier "no camera" claim, which turned out to be imprecise (conflated
"no live feed found in the two APIs explored" with "no camera hardware", not the same
claim -- caught during review, correctly).

Confirmed via the manifest's real permission list: **no `android.permission.CAMERA`
anywhere** -- only `RECORD_AUDIO` and `READ_MEDIA_VIDEO` (reads existing video FILES
from storage, e.g. the local demo mp4, not camera capture). Confirmed via the full
Activity/Service list too: no camera Activity at all, only
`com.dmcbig.mediapicker.PickerActivity`/`PreviewActivity` (a generic gallery file
picker, not a live camera). A port scan of the tablet's own IP for common
camera/streaming ports (554, 8080, 1935, RTSP/ONVIF/MJPEG range) came back empty --
only 8022 (sshd) and 9015 (the local API already known) are open.

**Conclusion**: the tablet has zero code path to any camera, live or otherwise. The
real camera confirmed via the chassis register table (`托盘识别参数`, see the
`3D防撞` section above) is almost certainly wired directly to the isolated chassis
computer for its own onboard pallet-recognition pipeline, physically separate from and
unreachable by the tablet. Live video for teleoperation would need either direct
access to the chassis computer (not currently possible, see "Restricción de red") or
genuinely new camera hardware mounted independently -- not a software gap that more
searching on the tablet side will close.

### Progreso de misión por distancia -- implemented

`_compute_progress()` (new method) replaces the old binary `completedPercent`
(0.0 while executing, 1.0 once Completed) with a real straight-line-distance ratio:
`1 - (distance from current position to destination) / (distance from task start to
destination)`, clamped to [0, 1]. Needs three things not previously tracked:

- `self._last_pose`, updated every tick by `_publish_pose_tf()` regardless of whether
  a task is active -- cheap (two floats), and means the command handler (an event
  callback, not the poll loop) always has a recent position on hand without an extra
  API round-trip.
- `self._task_start_pose`, snapshotted from `_last_pose` when `_start_task()` fires.
- `self._task_dest`, the real target coordinate -- `NAMED_POINTS[point]` for
  `GOTO_*`, or the live `chargingPosition` (one extra `info` request, only on the rare
  `CHARGE` command) for `CHARGE`. `STOP` never calls `_start_task()` at all, so it was
  never part of this problem.

No path-curvature accounting (unavailable from this local API either way) -- straight-
line is an approximation, reasonable given this robot's own indoor paths are short.
Verified with a standalone Python sanity check (not against the real robot) before
deploying: 0.0 at the start pose, 0.5 at the literal midpoint, 1.0 at the destination,
and clamped to 0.0 (not negative) if the robot moves away from the destination instead
of toward it -- all four cases behaved correctly.

### Solapamiento de tareas -- fixed

`_start_task()` now checks whether a previous task is still `in_progress`
(`self._task_id is not None and self._task_end_ts is None`) before overwriting its own
state. If so, it publishes one final `mission_tracking` update for the OLD task first
(`_publish_tracking_snapshot("Aborted", "interrupted by a new command")`), so that
task's InOrbit record closes out truthfully instead of freezing at "Executing" forever
-- the exact bug seen live 2026-08-28 (a "Go Charge" mission stuck at Executing after a
"Go to Home" interrupted it 9 seconds later, see "Robot Actions" section above). Does
not change the robot's own real behaviour at all (`WdcRobotApi.navigation()` already
had no queueing -- a new command always just replaced whatever it was doing), only
what gets reported about it.

**Deployed live, not yet re-tested against a real overlapping-command sequence** (the
original bug repro) -- the bridge restart during this deploy had an unrelated hiccup
(its own supervisor `while true` loop vanished entirely after a plain `kill -9` on the
inner Python process, for a reason not fully understood -- the other two supervisor
loops, roscore's and the agent's, were unaffected by the same kind of restart done
minutes apart; relaunched by hand immediately, no reboot involved, no data gap beyond
that). Confirmed the bridge is back up and publishing (`battery percent`, `error_code`
seen fresh via `rostopic echo`) and the new `_compute_progress()` math checks out in
isolation, but firing two real overlapping actions to confirm the InOrbit-visible fix
end-to-end is still an open next step, ideally with someone watching given it moves the
real robot.

## Missions finally reported correctly, and the robot's own `BUSY！` refusal -- 2026-08-31

Two separate problems that looked like one, untangled the same session. Both were found
by reading real data rather than the dashboard: the widget's own display was misleading
in the first case, and our code was throwing away the robot's answer in the second.

### Missions stuck at "Executing" forever -- fixed (`currentTaskId`)

Every WDC mission stayed "Executing" in InOrbit's Missions widget no matter what,
including a "Go Charge" still showing as running 65 hours later. Two independent reads
proved our own published data was already correct -- the raw ROS topic, and
`GET /robots/223623373/attributes/mission_tracking`, both showing
`state: "Completed", completedPercent: 1.0`. So the bug was in what InOrbit did with it,
not in what we sent.

`GET /missions?robotId=223623373` (the widget's real backing store, NOT the attribute)
showed what actually got stored:

```
"tasks":[{"taskId":"0","label":"Go to B","inProgress":true}]   <- never closed
"currentTaskId":"0"
"state":"Executing"
```

InOrbit's own internal task stayed open, and the mission never left Executing regardless
of the top-level `state` field we published. Comparing against Keenon's working payload
(`GET /robots/keenon-krtx24098y0005/attributes/mission_tracking`) showed the difference:
Keenon keeps `currentTaskId` populated even when Completed; ours set it to `None` on
completion (copied from `turtlebot_robot_sdk`'s own node, which does the same -- so that
file likely has this same latent bug, never noticed because it runs against a sim).
With no `currentTaskId`, InOrbit had no task to close.

Fixed by keeping `currentTaskId: "0"` throughout and giving each task its own
`inProgress` flag. **Confirmed live**: "Go Charge", "Go to A" and "Go to B" all reached
"Completed" in the widget afterwards.

A second, unrelated confirmation came out of the same investigation: every old mission's
`updatedTs` matched exactly the `createdTs` of the NEXT mission, proving those were
being closed by InOrbit's own `autoClosePreviousMission: true`, not by our "Completed"
ever landing.

### `BUSY！` -- the robot refusing navigation, silently

Separately, "Go to Point" actions started doing nothing at all: no movement, no error,
mission left Executing. The robot was in fact **actively refusing** every navigation
request, replying with the literal string `"BUSY！"` (Chinese full-width exclamation
mark), and `_on_custom_command()` discarded that reply without inspecting it -- so logs
and InOrbit both showed a clean, successful command.

Now handled by `_check_nav_response()`: a `BUSY` reply is logged as a warning naming the
cause and the fix. Accepted commands log the robot's real reply too (`开始任务`,
"start task"), which turned out to matter -- see below.

**What the state actually is**: `readycode` reads 0 when the robot is free and 300 when
it refuses. `stopAction` clears it reliably (confirmed live: 300 -> 0, stable across
repeated checks), which the existing STOP action already sends -- so "press STOP, then
retry" is a real workaround, and it did get the robot moving again once.

**Deliberately NOT auto-sending stopAction on a BUSY reply.** It would cancel whatever
the robot is waiting on -- plausibly an undelivered order -- as an invisible side effect
of pressing a different button. That is a product decision for the project owner, not
something to bury in the bridge.

### Unresolved: robot accepts a command, reports "start task", then does not move

Later the same session the failure changed shape and is **not explained yet**. From the
bridge log, C and D were both ACCEPTED (`开始任务`), only E onward were refused
(`BUSY！`) -- yet the robot never moved for any of them. Verified by measuring real
distance from its live pose to every named point: it sat 0.059 m from B (where it had
last legitimately arrived) and 5.6 m from D, i.e. it never left B.

Checked and ruled out from here:
- Not our command path -- commands arrive and the robot acknowledges them (logged).
- Not a confirmation dialog waiting on the tablet -- captured the tablet's framebuffer
  directly (`su -c screencap`, worth remembering as a diagnostic: it works and needs
  nobody physically present). It shows the animated idle "face" screen, no dialog. A
  `KEYCODE_WAKEUP` and a re-capture showed the same, and the eyes had moved, so the app
  was alive, not frozen.
- Not the app being backgrounded -- `am start` on MainActivity brought it forward
  (`Activity not started, its current task has been brought to the front`) and
  `readycode` stayed at 300.
- `readycode`/`isBusy` are NOT in the app's JavaScript (this is a DCloud/uni-app hybrid;
  its `www/` bundle was searched directly on the tablet). They live in the Java layer
  (`getReadycode`/`setReadycode`/`isBusy` confirmed present as DEX strings alongside
  `BUSY！` and `开始任务`), fed from the chassis computer.

**RESOLVED same session** -- root cause named by the app itself, and cleared remotely.

A tablet reboot (`su -c reboot`) did NOT clear it: `readycode` came back at 300 while the
whole Termux stack recovered cleanly on its own (a second real validation of the
auto-recovery chain, after the 2026-08-31 SIGKILL test). That confirmed the stuck state
lives in the chassis, not the tablet.

**The tablet's screen can be driven remotely** -- `su -c screencap` to see it and
`su -c 'input tap X Y'` to touch it (screen is 1280x800). This turns "someone has to
walk over to the robot" into a remote operation, and is the single most useful
diagnostic found this session. Waking the screen and tapping its centre (the idle face
screen's own config text is `请触摸屏幕`, "please touch the screen") opened the main menu,
which stated the problem outright:

```
Navigation Status: Line controller busy
Abnormal state: Normal
Current position: X:-0.69 Y:0.67 YAW:-1.26
```

So: the chassis's own line/navigation controller was busy, which is why it answered
`开始任务` ("start task") to a navigation request and then never moved -- the tablet app
accepted the command and the chassis silently declined to act on it.

**Fix: the menu's own "Return Point" button** (`input tap 776 558` on this layout), not
our STOP. Confirmed live: the robot drove from B to Home (ending 0.019 m from it) and
`readycode` went 300 -> 0. Our own `stopAction` only ever cleared `readycode`
temporarily without freeing the controller, which is why "STOP then retry" worked once
and then stopped working.

Recovery procedure worth keeping, in order of escalation:
1. `stopAction` (the STOP action in InOrbit) -- clears a plain `readycode` 300.
2. If navigation is accepted but the robot does not move: screencap the tablet, tap to
   the main menu, and press "Return Point". Fixes a busy line controller.
3. Only if both fail is anything physical needed (power-cycling the chassis itself --
   a tablet reboot is confirmed NOT to help).

## Points C/D/E are outside the navigable map -- not a bug, 2026-08-31

Hypothesis raised during testing, and it turned out to be right. A/B/Home always worked; C/D/E never did, from InOrbit AND
from the tablet's own Delivery Mode screen -- which already ruled out this repo's code.

Verified against the robot's own live map (`cmd:"map"`), two ways:

| Point | map pixel | free space within 25 cm | reachable by free space from robot |
|---|---|---|---|
| A / B / Home | 255 (free) | 100% | YES |
| C | 205 (unknown) | 0% | NO -- 0.45 m outside |
| D | 205 (unknown) | 0% | NO -- 1.05 m outside |
| E | 205 (unknown) | 0% | NO -- 1.85 m outside |

The second column is the decisive one: a flood fill over free cells starting from the
robot's real pose covers 51.3 m² (the room) and never reaches C/D/E. There is no free
path to them, so the planner has nothing to follow -- hence `开始任务` accepted, robot
never moves, "Line controller busy", task eventually timing out with the app's
"unhealthy" popup.

Almost certainly stale waypoints: they sit just past the edge of the scanned area (C by
only 45 cm), consistent with having been recorded when the map extended further, then
orphaned when ESPAITEC_1 was re-scanned. `NAMED_POINTS` in `wdc_bridge_node.py` holds
exactly what the tablet app's own storage holds, so both are equally stale -- this is
not a transcription error on our side.

**Fix is physical, not code**: drive the robot to each spot and re-record C/D/E against
the current map, from the manufacturer's app (it owns those definitions), then update
`NAMED_POINTS` to match. Until then A/B/Home/Charge are four working destinations.

Caveat on rigour: this proves they are unreachable *in the map the robot itself hands
us*. That its internal planner uses that same map is a reasonable inference, not
something tested. The clean causal test would be sending it to an arbitrary FREE point
far away -- if that works, distance is excluded and the map region is confirmed as the
only variable. Not done (needs the robot free and someone watching).

## Missions only appear in InOrbit when the command came FROM InOrbit

Noticed during testing and confirmed: a "Go to A" pressed on the tablet leaves no mission in
InOrbit, while the same action from InOrbit does. Expected given the design --
`_start_task()` is only ever called from `_on_custom_command()`, i.e. off the ROS
command topic. The local API reports the robot's *state*, never "a task was started",
so a tablet-initiated job is invisible to the bridge.

Could in principle be inferred (robot starts moving toward a known point unprompted),
but that would fabricate missions from ambiguous evidence -- deliberately not done.

## Operational notes added this session

- **ADB over TCP is enabled** on the tablet (`su -c 'setprop service.adb.tcp.port 5555'`
  + restart adbd; connects with no on-screen authorisation prompt because this is an
  `eng` build). Does NOT survive a reboot -- re-run to restore. Disable with
  `setprop service.adb.tcp.port -1` and restarting adbd.
- **scrcpy** (portable build, no root/sudo needed on the dev machine) is extracted at
  `~/scrcpy` on the dev machine: live screen + mouse control of the tablet. This plus
  `screencap`/`input tap` is how the "Line controller busy" diagnosis and the Return
  Point recovery were both done without anyone walking to the robot.
- **If the manufacturer app gets into a half-dead state** (task exists but window never
  paints, `am start` says "brought to the front" and nothing appears): force a clean
  restart, `am force-stop com.sirui.wdc_robot` then `am start -n
  com.sirui.wdc_robot/.MainActivity`. Bringing it to front alone does not fix it.
- **Battery 0% / Error in InOrbit is usually a lie** -- it is what gets published while
  the local API is down (app crashed/restarting). Check `obtainingPower` directly before
  believing it; the robot read 87% while InOrbit showed 0%.
- **Coming off the charger needs `stopAction` first.** Docked, the robot reports
  `readycode` 300 and ignores navigation; `stopAction` un-docks it (measured: moved
  0.112 m, `readycode` 300 -> 0) and it then accepts destinations normally.

## Hard constraints (same as the rest of this workspace)

- Never touch `integrations/deliverance-integrations-siruiy/` from here (separate Edge SDK
  answer for the same robot, different repo, different track).
- **No longer read-only, as of 2026-08-28** (see "Write path added" above) -- real
  robot movement via InOrbit's Actions panel was explicitly authorised. Every write
  command this bridge accepts must still trace back to something explicitly authorized
  this way, never added unprompted "while we're at it" -- and every new coordinate used
  for navigation must be a real recorded value (tablet app storage, or a live-recorded
  pose), never guessed, given the real risk of sending a 100kg+ delivery robot into a
  wall or a person.
- Do not commit secrets — this bridge needs none (`/events/service` requires no auth,
  neither does the local WebSocket API on port 9015).
- Do not push without explicit approval; stay on `feature/turtlebot-robot-sdk` (this
  experiment was added to that same branch, not a new one, since it's the same
  Agent SDK evaluation task, just a second robot).
