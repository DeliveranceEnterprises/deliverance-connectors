# TurtleBot Robot SDK — Context for Claude

## Status: Agent Core successfully installed and validated (2026-07-27)

This directory is a **parallel experiment**, not a replacement for
[`../turtlebot_connector/`](../turtlebot_connector/), which stays untouched and is the
working Edge SDK reference.

We validated the install end-to-end in a separate container (`turtlebot-robot-sdk-test`,
built from the *same* `deliverance/turtlebot-connector-ros2-gazebo:humble` image, run
with a different container name so the real demo container was never touched) — **not**
yet wired into the actual Gazebo/Nav2 simulation. See "What we validated" below.

**Local-only, not yet committed to disk in a reproducible way**: the installed agent
currently lives only inside the running `turtlebot-robot-sdk-test` container /
`deliverance/turtlebot-robot-sdk-test:latest` local image (both created ad hoc via
`docker commit`/`docker run`, not from a Dockerfile in this repo yet). Resume with
`docker start turtlebot-robot-sdk-test` — don't recreate it from scratch, that would
lose the install and mint a *new* robot identity. Turning this into a proper
Dockerfile/compose file here is one of the next steps.

## Why this exists

Boss-assigned task: learn InOrbit's **Robot SDK / Agent Core** pattern (agent installed
directly on/near the robot) as an alternative to the **Edge SDK** pattern we use
everywhere else in this repo (intermediary Python process talking to InOrbit cloud on
the robot's behalf). TurtleBot is the reference robot because it's the only ROS-based
connector here — Autoxing/Keenon/Allybot talk to vendor cloud REST APIs with no local
robot access, so Robot SDK doesn't apply to them; Edge SDK stays correct there
regardless of this experiment.

## Edge SDK vs Robot SDK — quick recap

| | `turtlebot_connector/` (Edge SDK) | `turtlebot_robot_sdk/` (this dir) |
|---|---|---|
| Where it runs | Our Python process, anywhere with network access | Agent Core installed on/near the robot (here: inside the Gazebo container) |
| Who talks to InOrbit cloud | Our code, via `inorbit-edge` MQTT session | InOrbit's own Agent Core binary |
| How data gets in | We subscribe to ROS2 topics and call `publish_key_values`/`publish_pose` by hand | Agent Core auto-detects standard topics (pose, map, camera) via UI config; custom data goes through `CustomDataAgentlet`, fed by a **plain ROS2 node** publishing `std_msgs/String` `key=value` messages — validated live, see "Custom data" below |

## Key findings from the investigation

- **Agent Core install**: `curl "https://control.inorbit.ai/liftoff/${ACCOUNT_KEY}?variant=core" | sh`. Runs as a local service (`localhost:5000` by default, configurable in `~/.inorbit/local/agent.env.sh`).
- **Language**: two different things got conflated early on, worth being precise about:
  - Code written **against InOrbit's own Robot SDK bindings** (the `sdk.sendKeyValue()`
    C++ API from the public docs): use **C++**, not Python — InOrbit's docs reference a
    `robot-sdk-python` repo, but as of 2026-07-27 it 404s and doesn't exist in the
    `inorbit-ai` GitHub org's public repo listing; only `robot-sdk-cpp` is real. See
    workspace memory `reference_inorbit_robot_sdk_gap`.
  - But: **we ended up not needing that binding at all.** Feeding `CustomDataAgentlet`
    (see "Custom data" below) is just a **plain ROS2 node** publishing a standard
    `std_msgs/String` message — no InOrbit SDK/library involved, so this part has no
    language constraint at all. We wrote it in **Python** (`src/mission_data_node.py`),
    matching the team's existing comfort and the Edge SDK connector's own Python logic
    for the same data. The C++-only rule applies specifically to InOrbit-SDK-bound code,
    which this project hasn't needed so far.
- **ROS2 docs are thin**: InOrbit's ROS1 docs name a concrete package
  (`ros-noetic-inorbit-republisher`) and give full YAML examples. The ROS2 section is a
  single unelaborated sentence ("the agent includes support for ROS 2"). Expect to have
  to find the ROS2 republisher package by inspecting
  [`ros_inorbit_samples`](https://github.com/inorbit-ai/ros_inorbit_samples) directly
  (its default branch is `noetic-devel`, i.e. ROS1 — verify a ROS2 branch/package exists
  before assuming parity).
- **Republisher: superseded by a simpler, validated approach.** `republisher/mission_data.example.yaml`
  in this directory was our first guess at the mechanism (InOrbit's own ROS1-only
  example, adapted). We never needed it: `CustomDataAgentlet` reads plain
  `std_msgs/String` messages (`"key=value"`, value may be JSON) directly off
  `/inorbit/custom_data` — validated live with `ros2 topic pub` and then a real node
  (`src/mission_data_node.py`), see "Custom data" below. The republisher is InOrbit's own
  packaged way to produce those same messages *from config instead of code* — worth
  revisiting only if config-only ends up preferable to owning a small Python node, and
  only once its ROS2 support is actually confirmed (still unconfirmed, ROS1 Noetic is the
  only concretely-documented target). The example YAML file is kept for reference but is
  not the path we're building on right now.
- Pose/map/camera/laser (standard topics) are configured once via InOrbit Control's UI
  (see "Confirmed against our own InOrbit account" and the later full validation below) —
  no republisher or custom code needed for those either.

## Custom data — validated live (2026-07-27)

Read `~/.inorbit/dist/inorbit/agentlets/custom_data.py` from the installed agent (real
vendored source, not docs) to find the exact contract:

- Topic: `/inorbit/custom_data` (or `/inorbit/custom_data/<custom_field>` for a specific
  field id other than the default `"0"`).
- Message type: plain `std_msgs/msg/String`.
- Payload format: `"key=value"` (split on the *first* `=` only, so values may safely
  contain more of them). No key → stored under a `__default__` key.
- Values that look like JSON get parsed into structured data automatically — no special
  encoding needed on our end beyond `json.dumps(...)`.
- Published to InOrbit roughly every 10s by the agentlet's own publish loop (it batches
  whatever's been received since the last cycle), independent of how often we publish to
  the ROS topic.

Verified end-to-end against `turtlebot-demo-02`, first via raw CLI, then via a real node:

```bash
ros2 topic pub -1 /inorbit/custom_data std_msgs/msg/String "data: 'mission_status=Mission'"
# -> inorbit expr eval 295895248 "getValue('mission_status')"  =>  'Mission'

ros2 topic pub -1 /inorbit/custom_data std_msgs/msg/String \
  "data: 'mission_tracking={\"state\": \"Executing\", \"data\": {\"waypoint\": \"station_1\"}}'"
# -> getValue('mission_tracking')  =>  {'state': 'Executing', 'data': {'waypoint': 'station_1'}}
```

Then wrote `src/mission_data_node.py` — a plain `rclpy` node (no InOrbit SDK dependency)
publishing `mission_status`/`mission_tracking` on a timer, mirroring the key names and
JSON shape `turtlebot_connector/src/connector.py` already uses via Edge SDK
(`_compute_mission_status`/`_build_mission_report`).

### Wired to real Nav2 state (2026-07-29) — no longer a placeholder

The node doesn't dispatch goals itself — it *observes* whatever navigation is already
happening, the same way it would need to for goals dispatched by InOrbit's own Waypoint
Teleop feature (which makes the agent publish directly to `/goal_pose`,
`geometry_msgs/PoseStamped` — confirmed by reading `ROS_SET_POSE_TOPIC_DEFAULT`-style
constants in the agent's `localization.py`). Two subscriptions, no ActionClient needed:

- `/goal_pose` — just a label hint for whichever goal Nav2 picks up next. **Receiving
  this does NOT prove a task started** — confirmed empirically that Nav2 can silently
  ignore a `/goal_pose` message (e.g. if the previous goal is still settling). Don't
  treat this topic as authoritative.
- `/navigate_to_pose/_action/status` (`action_msgs/msg/GoalStatusArray`) — Nav2's *own*
  authoritative status feed for the `navigate_to_pose` action, published as a plain topic
  regardless of who owns the ActionClient. `status_list` accumulates one entry per goal
  for the node's lifetime (doesn't get replaced); the *last* entry is always the current
  one. A goal's UUID (`status_list[-1].goal_info.goal_id.uuid`) changing from what we
  last saw is what actually means "a new task started" — this is the correct way to
  detect it, not `/goal_pose` reception.

**Real bugs found and fixed while validating this, both worth remembering:**
1. `AttributeError: 'GoalStatus' object has no attribute 'goal_id'` — the UUID is nested
   under `.goal_info.goal_id.uuid`, not `.goal_id.uuid` directly. This crashed the node
   on the very first status message ever received, silently (background process, no one
   watching stdout) — is *exactly* what caused yesterday's evening confusion ("second
   goal doesn't update the mission"). Not a Nav2 quirk, not an InOrbit issue — just a
   typo in our own code that looked like something more mysterious because the process
   kept running with no further output after crashing its subscription callback once.
2. InOrbit's custom-data channel **merges each publish into the previous JSON value
   instead of replacing it** — a field that's merely *omitted* from a later publish
   keeps its old value forever. Fields that should disappear (`currentTaskId` once a
   task completes) must be explicitly set to `None`/`null`, not left out of the dict.

**Validated with four consecutive goals in a row**, each correctly reporting
`Executing` (right label, right target coords) → `Completed` (`completedPercent: 1`,
`endTs` populated, stale fields cleared). One thing to know if re-testing: checking
InOrbit immediately (0s) after sending a goal can show stale data — the node's own
publish timer runs every 2s, so a `sleep`/poll-until-changed is needed, same as the
InOrbit backend itself needs a moment; don't mistake that lag for a bug.

Not yet covered: cancellation (`CANCELED`/`ABORTED` states are handled in the state
machine but not exercised live), and the label being sourced from whichever `/goal_pose`
was last seen rather than being reliably correlated to the specific goal UUID it belongs
to (fine in practice — goals arrive faster than a human/InOrbit teleop click, so ordering
holds — but worth knowing if goals ever get dispatched by two sources at once).

## Confirmed against our own InOrbit account (2026-07-27)

The public docs are thin on ROS2, so instead of trusting them blindly we inspected our
own account (`rnLasGAxn5CP7bj32`) via `inorbit get robots`. It's a shared account that
also hosts a large pre-existing InOrbit demo/reference fleet (same pattern as the
pre-existing "Kira/InStock/MIR100/RSPeer" dashboard sections noted in the parent
`CLAUDE.md` — not ours, don't touch, but useful to read). Several dozen of those robots
report agent version `4.x.x.ros2` (e.g. `jackal-rs-1` → `4.18.0.ros2`,
`rs-magni-sim-1` → `4.18.0.ros2`, `jackal-outdoor-1` → `4.21.0.ros2`) — this **confirms
the native ROS2 agent is a real, first-class, currently-deployed agent variant**, not
just a docs promise.

Inspecting `jackal-rs-1`'s `RobotCamera` CAC (`inorbit get config --kind RobotCamera
--scope robot/rnLasGAxn5CP7bj32/jackal-rs-1 --yaml`) confirms what our own
`docker/ros2_gazebo/README.md` already noted from prior experience: for a native
ROS2 agent, `rosTopic` is the **real ROS topic name** (`image_raw`), not a channel
index like our Edge SDK connectors use (`rosTopic: "0"`). No custom
`DataSourceDefinition` exists for that robot — consistent with standard telemetry
(pose, battery, camera) being auto-detected with zero config.

These demo robots appear offline right now (`inorbit expr eval jackal-rs-1
"getValue('battery')"` → `None`), so we can read their static CAC but not watch live
behavior — still, this is a much stronger reference than the public docs alone.

## Battery — same node, two keys, two consumers (2026-08-03)

Gazebo publishes no battery topic, and unlike pose/map/camera there is **no agentlet
that auto-detects one** — so a Robot SDK robot reports `0%` everywhere until something
publishes it explicitly. Fixed by extending `mission_data_node.py` (no new process, no
new mechanism — same `CustomDataAgentlet` channel already used for mission data).

Value is a fixed `0.30`, deliberately: `turtlebot_connector`'s own
`fleet.ros2.office.local.yaml` sets `initial_battery: 0.30` and never decrements it
either (`battery_drain_per_second` exists in the config but nothing in
`ros2_gazebo.py` applies it — grep for `drain`, there's only the config key). So this
is at parity with the Edge SDK demo, not a shortcut.

**Two keys are published because there are two real, independent consumers** — this is
the part worth remembering, since publishing only one silently half-works:

| Key published | Consumed by | Range | Why |
|---|---|---|---|
| `battery_percent` | tag-scoped `DataSourceDefinition turtlebot-battery` (`scale: 0.01`) | 0–100 | What the **Deliverance platform** reads, via `INORBIT_ROBOTS_JSON[].battery_attr_id` → `GET /robots/{id}/attributes/turtlebot-battery` |
| `battery percent` (with a space) | account-level `DataSourceDefinition xlXPmDo3Z3GMwSTM` | 0–1 | What **InOrbit's own built-in Vitals gauge** reads |

Neither DataSource had to be created — both already existed (`turtlebot-battery` is
the Edge SDK connector's, shared via the TurtleBot tag `QJoR03aXlEhZkD6N`; the other is
account-level and ships with InOrbit). The robot just wasn't feeding them.

**Verify it end-to-end via the attribute API, not `inorbit expr eval`** — the
expression engine returns `None` for these raw keys (the same transient-key-visibility
quirk `turtlebot_connector/CLAUDE.md` documents for `current_waypoint`/`task_label`),
which makes a working setup look broken:

```bash
curl -s -H "X-Auth-InOrbit-App-Key: $KEY" \
  https://api.inorbit.ai/robots/660828878/attributes/turtlebot-battery
# {"attribute":"turtlebot-battery","value":0.3,"ts":...}   <- post-scale, 0-1
```

The platform's `normalise_battery()` then maps `0.3` → `30` (values ≤ 1.0 are treated
as a fraction and multiplied by 100). Confirmed live in `device_status.battery_level`.

## 🐛 Fifth bug — ours this time: `Distance: 0` on most missions (2026-08-03)

The platform's mission report showed `Distance: 0` and `Duration: 60` on 6 of the 12
missions synced from `660828878`. **First guess was wrong and worth recording as a
warning**: it looked like fallout from the map-QoS/pose-freeze bug (some early missions
do have real distances, later ones don't), which is a tempting but incorrect story. The
InOrbit API settles it — `duration` is in **milliseconds**, not seconds:

```
Go to (-1.80, -0.42)  start=09:09:41.194  end=09:09:41.254  dur=60      dist=0
Go to (0.19, -0.58)   start=09:17:24.906  end=09:17:24.966  dur=60      dist=0
Go to (1.09, -0.60)   start=08:09:35.667  end=08:09:44.428  dur=8761    dist=0.405
```

Those missions lasted 60 **ms**. The robot really moved; the *mission window we reported*
was zero-length, so InOrbit had no trajectory to integrate and returned
`estimatedDistance: 0`. Nothing wrong with pose, telemetry or InOrbit.

**Root cause, in our own `mission_data_node.py`:** `_on_nav2_status()` sampled
`time.time()` for `startTs` only at the moment it *first recognised* a goal — and its
early return (`if status not in _STATE_TO_MISSION_STATE: return`) skipped
`STATUS_ACCEPTED` (1) entirely, so a goal was only ever registered once it reached
`EXECUTING`. Any goal whose `EXECUTING` phase we didn't happen to observe was therefore
first stamped when it was already `SUCCEEDED`, collapsing `startTs` and `endTs` into the
same instant.

**Fix applied**: stamp *every* uuid in `status_list` the first time it is ever seen,
before any filtering — a goal appears there at `ACCEPTED`, i.e. at dispatch — and use
that stored timestamp as `startTs`. Dict is bounded (`status_list` accumulates for the
node's lifetime).

**Deliberately not used: Nav2's own `goal_info.stamp`.** It would be the obvious source
for a true start time, but under Gazebo it is **sim time**, not a wall clock — feeding it
to InOrbit as an absolute ms timestamp would put missions somewhere near 1970. Converting
via a ROS-time↔wall-time offset only works if this node and Nav2 agree on `use_sim_time`,
which is not currently configured. First-sighting wall time sidesteps the whole question.

**Not yet re-validated live** — needs one fresh Nav2 goal to confirm a real non-zero
`estimatedDistance` comes back. The historical missions stay wrong; they can't be
recomputed.

## Deliverance platform: scene and device image (2026-08-03)

Two cosmetic-but-visible platform fields that need per-robot config in the launcher's
`INORBIT_ROBOTS_JSON`, not code — both were wrong for the TurtleBots until fixed:

- **`map_name`** — without an override, robots fall back to the *global*
  `INORBIT_MAP_NAME` (`DATF`, which is **Autoxing's** scene), so the TurtleBots showed
  up as if they were in Autoxing's location. Set `"map_name":"Office"` on both
  TurtleBot entries (after the sim's own `office_world.world` / `office_scanned.yaml`).
  Note `deliverance-integrations-inorbit`'s `_find_scene_uid()` is **lookup-only** — it
  will not create a missing scene (unlike Keenon's/Siruiy's `_ensure_scene()`), so the
  `scenes` row had to be inserted directly into the platform DB, using the same
  `uuid5`-derived-UID convention the other integrations use.
- **`image`** — without it, `devices.image` is `NULL` and the device-list thumbnail
  renders a broken image (that view has no fallback, unlike most others which fall back
  to `viggo_sc50.png`). Set `"image":"waffle_pi.png"` on both. The PNG files live
  **baked into the sealed frontend image** at
  `/usr/share/nginx/html/assets/images/devices/` — no repo, no volume mount — so a new
  one has to be `docker cp`'d in and will be **lost on container recreate**. Adding a
  bind mount in the launcher's compose file is the durable fix if this matters later.

Both take effect only after `docker compose up -d --force-recreate --no-deps
inorbit_sync` (a plain `docker restart` does not re-read `.env`), and then only on the
sync's next full pass — which walks several hundred robots on this shared account, so
allow a few minutes before concluding it didn't work.

## What we validated (real install, real InOrbit account)

Ran the actual `liftoff` installer (`curl https://space.inorbit.ai/liftoff/<ACCOUNT_KEY> | sh`)
inside a throwaway container built from the same image as the real demo
(`deliverance/turtlebot-connector-ros2-gazebo:humble`), with `ROS_DOMAIN_ID=42` and
`ROS_DISTRO=humble` (sourced from `/opt/ros/humble/setup.bash`) already set in the
environment before running the installer. Findings:

- **The installer supports Humble explicitly.** Its `SUPPORTED_ROS2_DISTROS` list is
  `foxy humble iron jazzy kilted`. With `ROS_DISTRO` and `ROS_DOMAIN_ID` pre-set, it
  auto-detects ROS2 and needs **zero interactive input** beyond the one unavoidable
  "Press ENTER to continue" greeting (which only appears on a fresh install, not on
  `update`). It correctly resolved `INORBIT_AGENT_VARIANT=ros2` automatically — no
  `?variant=` query param needed, contradicting the older public docs example.
- **Install requires `apt-get update` to have been run first** in the target image —
  the installer needs `python3-virtualenv`, and our Dockerfile clears `/var/lib/apt/lists/*`
  after its own installs, so a fresh `apt-get update` is needed before running `liftoff`
  in this image. Should be baked into the Dockerfile instead of done ad hoc.
- **Autostart via systemd doesn't work in a container without a real init (PID 1).**
  The installer generates a systemd unit, but it's inert in Docker. The agent has to be
  started manually: `source ~/.inorbit/local/agent.env.sh && ~/.inorbit/dist/scripts/start.sh`
  (run in background/foreground, not as a service) — same constraint the existing
  `turtlebot_connector` container already works around with explicit terminal scripts.
- **Robot identity is auto-generated** (`INORBIT_ID="$(date +%N)"`, a 9-digit
  nanosecond-timestamp number) and written to `~/.inorbit/local/agent.env.sh` on first
  install — matches the numeric IDs seen on several pre-existing demo-fleet robots
  (`914792897`, `807080683`, etc.), confirming those were installed the same way.
- **It connected for real**: MQTT to `blue-label.brokers.inorbit.ai:8883`, published
  online status, and the robot **appeared live in `inorbit get robots`**, initially as
  `9aded8691d1a` (container hostname), then renamed to `turtlebot-demo-02` — see "Robot
  identity" below.

### Agentlet architecture (the actual mechanism — better than the public docs)

On startup, the agent loads a fixed set of **agentlets** (modules), each with its own
JSON config pushed from InOrbit's backend on connect (visible in
`~/.inorbit/local/inorbit_agent.log`):

| Agentlet | Purpose | Config fields seen |
|---|---|---|
| `RosMapAgentlet` | Map upload | `map_topic` (defaulted to `/global_map` — **wrong for us**, TurtleBot/Nav2 publish `/map`) |
| `RosLocalizationAgentlet` | Laser + costmap | `laser_topic`, `laser2_topic`, `costmap_topic`, `map_topic` (defaults are generic placeholders like `robot1/scan_front` — **not our topics**) |
| `RosPoseAgentlet` | Robot pose | reads `map`→`base_link` tf2 transform automatically, no config needed if that transform exists (it will, once Nav2/AMCL are running — the "LookupException" we saw is expected with no Gazebo/Nav2 running in this idle test container) |
| `RosOdometryAgentlet` | Odometry | reads `odom`→`base_link` tf2 transform automatically, same caveat |
| `RosImageAgentlet` | Camera | `cameras_config` dict keyed by channel id: `topic`, `output_encoding`, `quality`, `img_width`, `img_height`, `rate`, `is_on` (default topic was a generic RealSense example path — **not ours**, we'd set `/camera/image_raw`) |
| `RosTeleopAgentlet` | Teleop | `linear_vel`, `angular_vel`, `publish_zero_vel` |
| `CustomDataAgentlet` | Custom key-values | subscribes to `inorbit/custom_data` — **this is what the republisher publishes onto**, confirming the architecture end-to-end |
| `CustomCommandsAgentlet` | Commands | subscribes/publishes `inorbit/custom_command` — likely how `Go Station 1`/`Cancel Task`-style actions would be implemented instead of our Edge SDK custom-command callbacks |
| `RosDiagnosticsAgentlet`, `GPSAgentlet`, `SystemAgentlet`, `RobotEventsAgentlet`, `DatabagAgentlet` | misc | not yet investigated |

**Key implication: none of the "wrong" defaults above needed the republisher or any
C++ code to fix** — they're just agentlet config values that need to point at our real
topics (`/map`, `/scan`, `/camera/image_raw`, `/cmd_vel`, tf frames `map`/`odom`/`base_link`,
all of which TurtleBot3 + Nav2 already publish, per `docker/ros2_gazebo/README.md`'s
"Expected ROS graph" list). **We have not yet found where this config is edited** — no
CAC `kind` for it (`inorbit list kinds` only shows `RobotCamera`/`RobotFootprint` as
ROS-adjacent kinds); it's probably set from InOrbit Control's web UI directly on the
robot's page, not via our CLI. Needs checking in the UI next.

## Robot identity: `turtlebot-demo-02`

Decision (Carlos, 2026-07-27): keep using this identity for all Robot SDK testing,
named to mirror the existing Edge SDK demo (`turtlebot-demo-01`). Renamed via the
`INORBIT_ROBOT_NAME` env var — the agent falls back to the container hostname if this
isn't set (`inorbit/link.py`: `self.my_hostname = os.getenv("INORBIT_ROBOT_NAME")`,
falls back to `socket.gethostname()`). Applied by appending a line to
`~/.inorbit/local/agent.env.sh` and restarting the agent:

```bash
echo 'export INORBIT_ROBOT_NAME="turtlebot-demo-02"' >> ~/.inorbit/local/agent.env.sh
source ~/.inorbit/local/agent.env.sh && ~/.inorbit/dist/scripts/start.sh &
```

Robot id (immutable, auto-generated at install time): `295895248`.

## ✅ Full validation against live Gazebo/Nav2 (2026-07-27)

Found the agentlet config UI: **InOrbit Control → select `turtlebot-demo-02` → Navigation
tab → Map View / Cameras / Teleop** (screenshotted by Carlos). Not exposed via our CLI's
CAC `kind`s — it's web-UI-only. Carlos edited it there to match TurtleBot's real topics
(confirmed against `docker/ros2_gazebo/README.md`'s ROS graph and
`docker/ros2_gazebo/params/waffle_pi_reverse.yaml`, not guessed):

| Field | Default (wrong) | Set to (real TurtleBot topic) |
|---|---|---|
| Map | `/global_map` | `/map` |
| Primary laser | `robot1/scan_front` | `/scan` |
| Secondary laser | `robot1/scan_back` | *(should be cleared — waffle_pi has only one LiDAR; still showing set as of this writing, harmless but not accurate)* |
| Local costmap | DISABLED | left DISABLED (not needed yet) |
| Camera | `/rear_rs_camera/color/image_color/compressed` | `/camera/image_raw` |
| Teleop → Publish on | *(empty)* | `/cmd_vel` |

Then we ran the **full real simulation** (not the empty throwaway container from earlier)
to validate end-to-end:

1. New container `turtlebot-robot-sdk-vnc`, run directly from
   `deliverance/turtlebot-connector-ros2-gazebo:humble` (the *original* image, not our
   `--entrypoint sleep` variant — needed the base image's real entrypoint for the VNC/Xvfb
   display Gazebo's camera rendering depends on), with the same bind mount as the real
   compose service (`turtlebot_connector/:/workspace/turtlebot_connector:rw`) and
   `ROS_DOMAIN_ID=42`. Ports `6081`/`5901` (offset from the real container's `6080`/`5900`
   so both could coexist).
2. Copied `~/.inorbit` from the earlier validated container (`turtlebot-robot-sdk-test`)
   into it via `docker cp`, preserving the `295895248`/`turtlebot-demo-02` identity instead
   of registering yet another robot.
3. Ran the same validated flow as the Edge SDK README: `launch_sim.sh` (Gazebo +
   spawn) → `launch_nav2.sh office_scanned.yaml` → `set_initial_pose.sh` → confirmed
   `/map /scan /odom /cmd_vel /camera/image_raw` all present via `ros2 topic list`.
4. **Then** started the InOrbit agent (`source agent.env.sh && start.sh`).

Result — **it worked with zero custom code**:

- Agent log showed the edited config actually took effect:
  `"map_topic":"/map","laser_topic":"/scan"`,
  `"cameras_config":{"0":{"topic":"/camera/image_raw",...}}`,
  `"cmd_vel_topic":"/cmd_vel"`.
- `RosMapAgentlet: map upload finished: map -1356722701634789705` — the scanned map
  uploaded to InOrbit automatically.
- No tf2 `LookupException` this time (unlike the earlier idle-container test) — pose and
  odometry resolved cleanly because AMCL/Nav2 were actually running and already had an
  initial pose.
- **Live pose confirmed via CLI at startup**, matching the seeded initial pose almost
  exactly:
  ```
  inorbit expr eval 295895248 "getValue('pose')"
  → {'x': -2.018, 'y': -0.456, 'theta': -0.0024, 'frameId': 'map'}
  ```
  (seeded at `x=-2.0, y=-0.5` in `launch_sim.sh` — matches.) **This pose value never
  updated again after this first publish — see "🐛 Known bug" below, found once Carlos
  drove the robot via InOrbit's teleop panel.**

## 🐛 Known bug: pose freezes after the first publish, survives an agent restart

### ✅✅ ROOT CAUSE FOUND FOR REAL, 2026-07-29 — read this first, skip the history below

After two days of circumstantial evidence, found the exact bug by patching the installed
agent with debug `print()` statements (had to also flip `INORBIT_LOG_LEVEL=debug` in
`agent.env.sh` — `start.sh` redirects the agent's stdout to `/dev/null` otherwise, which
is why the prints were invisible at first and made it *look* like the code wasn't even
running). Full chain, in `~/.inorbit/dist/inorbit/agentlets/map.py`:

1. On agent startup, `MapAgentlet.load()` subscribes to a guessed default topic (`"map"`)
   with the correct QoS (`ROS_MAP_QOS_PROFILE_DEFAULT` — `TRANSIENT_LOCAL` durability,
   `RELIABLE`), because Nav2's `map_server` publishes `/map` **once**, latched, at
   startup — a subscriber needs `TRANSIENT_LOCAL` to receive it if it (re)subscribes
   after that one publish. This first subscription correctly includes the QoS as a 4th
   tuple element: `(topic, msg_type, callback, ROS_MAP_QOS_PROFILE_DEFAULT)`.
2. When we configure the *real* topic (`/map`) in InOrbit Control's Navigation tab — the
   exact step this whole doc tells you to do — `MapAgentlet.set_state()` detects the
   topic changed, sets `self._map_published = False`, and re-subscribes via
   `self._ros.update_subscriber_topic(...)`. **The replacement subscription tuple it
   builds only has 3 elements — no QoS**: `(new_topic, nav_msgs.msg.OccupancyGrid,
   lambda ...)`.
3. `RosAgentlet.update_subscriber_topic()` (`ros.py`) reads the QoS as `new_sub[3]`,
   catches the `IndexError`, and silently falls back to `qos = 10` — a plain integer,
   which rclpy treats as a default profile (`VOLATILE` durability, not
   `TRANSIENT_LOCAL`).
4. A `VOLATILE` subscriber to a topic whose only publish already happened will **never
   receive anything** — `map_server` doesn't republish. So `_ros_on_map()` (the callback
   that sets `_map_published = True`) never fires again, for the rest of the process's
   life.
5. `RosLocalizationAgentlet._should_process_localization_data()` returns
   `self._states["disable_map_published_flag"] or self._map_agentlet.map_published` —
   both `False` — so `_maybe_publish()` returns at its **very first line**, before any
   logging statement. That's why nothing ever appeared in the logs: not an exception
   being swallowed, a silent early return with zero instrumentation on that specific
   path. Confirmed directly: `DEBUG _maybe_publish called, map_published=False,
   disable_flag=False` / `DEBUG bailing` on every single cycle, forever.

**This is a real bug in InOrbit's shipped code, 100% reproducible, with an exact root
cause and file/line to point to** — not "something about teleop" or "something about
Gazebo" as earlier theories guessed (see history below; both were red herrings/noise
from an unrelated, already-fixed Gazebo issue). It explains every symptom observed
across two days: works once at startup (default topic, correct QoS) → breaks the moment
you do the one config step the docs tell you to do (retopic to the real map) → never
recovers, restart or not, because the bug is in *how the resubscription is built*, not
in any runtime state that a restart would clear (a fresh process hits the exact same
code path and loses the QoS the exact same way, every time).

### ✅✅✅ Local patch applied and CONFIRMED WORKING, 2026-07-29

Applied the one-line fix to `turtlebot-robot-sdk-test` (`660828878`): added
`ROS_MAP_QOS_PROFILE_DEFAULT` as the 4th element of the `sub` tuple in `map.py`'s
`set_state()`, mirroring exactly what `load()` already does correctly. Backup kept at
`map.py.bak` before patching.

```python
# Before (buggy — 3 elements, falls back to default qos=10 → VOLATILE):
sub = (
    new_topic,
    nav_msgs.msg.OccupancyGrid,
    lambda msg, map_topic=new_topic: self._ros_on_map(msg, map_topic),
)
# After (fixed — 4th element matches load()'s correct subscription):
sub = (
    new_topic,
    nav_msgs.msg.OccupancyGrid,
    lambda msg, map_topic=new_topic: self._ros_on_map(msg, map_topic),
    ROS_MAP_QOS_PROFILE_DEFAULT,
)
```

Restarted the agent, changed the Map field in InOrbit Control's Navigation tab (had to
first fix it to a topic that actually exists in our sim — `map` — since it had drifted to
`/global_map`, which doesn't exist here, during earlier testing). Log confirmed:
`Registering subscriber to topic: map.` → `RosMapAgentlet: map upload finished` —
the map arrived this time. **Pose then confirmed live and continuously updating, both
via CLI (`getValue('pose')` timestamps advancing every ~10-20s, not stuck) and visually
by Carlos in InOrbit Control's Navigation view.** This is airtight confirmation of both
the diagnosis and the fix.

**Caveat found along the way, unrelated to this bug**: most other robots on the shared
account show their Map field as `map` (no leading slash) rather than `/map`. Likely
explanation: people configure this field by picking from a dropdown of auto-detected
topics (which InOrbit displays without the leading slash) rather than typing a value by
hand. Since the bug triggers on the map-topic *string value changing* from whatever was
already stored — not specifically on the slash — most users probably never trigger the
buggy code path at all, simply because picking the same value from a dropdown doesn't
register as a "change." We hit it because we typed `/map` by hand, which differs from
the agent's own internal default string (`"map"`, no slash) even though both resolve to
the identical ROS2 topic. Also found a second, unrelated pre-existing issue on this test
### 🐛 Third bug found, 2026-07-29 (not yet fixed): teleop step-by-step never sends a final stop

Instrumented `teleop.py` (`_set_vel`/`_drive`) the same way as the map bug, with debug
prints (backup kept at `teleop.py.bak` before/during, reverted after). A single
"Step-by-Step" arrow click in InOrbit Control:

- Correctly triggers `_set_vel()` once (confirmed only one call, not a frontend
  double-fire).
- `_drive()`'s publish loop runs for only 2 cycles (`remaining_commands`: 20 → 19 → 18)
  instead of the expected ~20 (`MAX_PUBLICATIONS_PER_CMD = VEL_PUBLISH_RATE_HZ *
  TELEOP_CMD_TIMEOUT_MS / 1000 = 10 * 2000 / 1000 = 20`, i.e. should run for 2 full
  seconds at 10Hz) — then goes **completely silent**, no more debug prints, and no
  error/exception logged anywhere in either log file, no `"Halting current
  teleoperation"` message either (confirmed `_should_halt_movement()` isn't what's
  triggering this — that path logs explicitly and we saw nothing).
- **The robot keeps physically rotating in Gazebo indefinitely** after this — confirmed
  by Carlos live in InOrbit Control.

Root mechanism (confirmed, even without pinning the exact reason the loop stops early):
`_drive()`'s publish loop is the *only* thing that ever calls `_publish_vel(...)` with a
real command, and the *only* code path that sends a zero-velocity stop is gated deep
inside the same loop (`if self._states["publish_zero_vel"] is True: ... if local_counter
== 0 ...`). If the loop stops iterating for any reason before reaching that gate with
`local_counter` actually at `0`, **no stop command is ever published** — and Gazebo's
diff_drive plugin (like most real robot bases) has no command timeout of its own, so it
keeps executing the last received `Twist` forever. `publish_zero_vel` config was
confirmed `true` at the time (so it's not simply the safety feature being disabled) —
the loop is dying/stalling before it ever gets there.

**This is a safety-relevant bug**: a single low-intensity teleop click can leave a real
robot moving indefinitely with no automatic recovery, until an operator manually sends
another command. Not patched locally (didn't fully isolate why the loop dies after 2
cycles specifically, and ran out of time before the InOrbit meeting) — documented as-is
for InOrbit to investigate, with the exact reproduction steps above.

**Workaround for now**: manually send another movement command (or Cancel/Stop) to
publish a fresh command and override the stuck one — there's no automatic recovery.
Confirmed direction-agnostic: happens the same way for forward/backward, not just
rotation. Also confirmed a new command genuinely **replaces** a stuck one cleanly (e.g.
commanding forward while stuck turning right correctly stops the turn and goes straight)
— so the underlying `/cmd_vel` publishing itself works fine; it's specifically the
"stop automatically when the step/duration ends" mechanism that's missing.

### 🐛 Fourth issue found, 2026-07-29: "Rotation" gauge oscillates (real code bug found, patched, did NOT fix the visible symptom — root cause still open)

Separate from the above — the "Rotation" number displayed in InOrbit Control's Navigation
teleop panel jumps between unrelated values (e.g. `0` → `10.4` → `-10.4`) even while the
robot is genuinely stationary (confirmed earlier via `/odom`'s real `angular.z` sitting at
~0). Already ruled out the `RosTeleopAgentlet` crash-loop from the trailing-space bug as
the cause — Carlos confirmed the crash loop stopped after that fix, but the gauge still
oscillates.

**A real, separate bug was found and fixed in `odometry.py`'s `_compute_speed()`**, but
turned out not to explain this specific symptom:
- `linear_speed` is computed consistently: `(current_linear_distance -
  last_linear_distance) / delta_ts`, where both the distance values *and* `delta_ts` come
  from the same 5Hz (`ODOM_QUERY_RATE_HZ`) distance-accumulation loop.
- `angular_speed`, by contrast, mixes sources: the angle numerator comes from a **freshly
  fetched pose** (`self._get_robot_pose()`, called live inside `_compute_speed()`), but
  the denominator (`delta_ts`) still comes from that *same unrelated 5Hz loop's*
  timestamp — a different loop running at a different, not-necessarily-aligned cadence
  (the publish loop calling `_compute_speed()` itself runs at 0.5-1s per
  `PUBLISHER_PERIOD_*_RUNLEVEL`). Dividing an angle sampled at one instant by a time
  delta that belongs to a different, unsynchronized clock is a real correctness bug —
  confirmed by reading the code, not guessed.
- **Patched**: added a dedicated `self._last_pose_ts` sampled at the same instant as
  `current_pose` (via `self.get_ts()`), and used that for `angular_speed`'s `delta_ts`
  instead of the borrowed one. Backup was kept (`odometry.py.bak`) while testing.
- **Result: no visible change** — Carlos confirmed the gauge still oscillates the same
  way after this fix. **Reverted the patch** (not applied, since it didn't fix the
  observed problem — no reason to carry an unproven change).

**Conclusion**: the timestamp-mixing bug in `odometry.py` is real (verified by reading
the code) but isn't proven to be *this* symptom's cause. Searched the whole agent
codebase for anything else publishing speed/rotation-shaped data
(`grep -rl 'angular_speed\|linear_speed\|VelocityMessage'`) and `odometry.py` is the only
match — so either: the widget doesn't source from `OdometryDataMessage` at all (maybe a
frontend-only computation, or a completely different backend field not obviously named),
or `_compute_speed()` isn't even being reached in practice (e.g. `_should_compute_speed`
gated on `RUNLEVEL_FULL`, unconfirmed whether that's actually the active runlevel here).
**Not fully root-caused** — lowest priority of the four issues found today (purely a
display glitch, no functional/safety impact, unlike the other three), documented as-is
rather than continuing to dig with the time available before the meeting.

**Frame-by-frame video review, 2026-07-29 (post-revert, confirms symptom persists as-is)**:
Carlos shared a ~12s screen recording of `turtlebot-robot-sdk-test`'s Navigation tab,
still showing the oscillation after the `odometry.py` patch was reverted. Extracted 25
frames at 2fps (`gst-launch-1.0 filesrc ! decodebin ! videoconvert ! videorate !
"video/x-raw,framerate=2/1" ! pngenc ! multifilesink`) and reviewed each one:
- **Robot pose (`X: -1.267 Y: -0.401 theta: -0.262`) never changes across all 25
  frames** — the robot is 100% stationary the entire clip, not even a tiny drift.
- **Speed stays pinned at `0 m/sec`** the entire clip too.
- **Rotation cycles in a repeating sweep**: `0` → `-15.669` → `-10.455` → `0` →
  `+15.669` → `0` → `+15.669` → `0` → `+15.669` → `0` ... — always landing on either
  exactly `0` or very close to `±15.669` (with `-10.455` seen once, mid-sweep).
- This cycling is **independent of everything else visible in the frame**: it keeps
  sweeping through the "Cancel Navigation Goal: Action executed" toast appearing/
  disappearing, and through the LOCK/UNLOCK button + red "X" cancel button toggling.
  None of those UI state changes line up with when Rotation flips.

**Why this matters for the root-cause theory**: since the real pose never moves at all,
a correct `angular_speed` computed from real odometry should be a clean, boring `0` the
whole time — there's no real angular delta to amplify, even under the timestamp-mixing
bug described above. A value that instead sweeps cleanly and repeatably between `0` and
a fixed magnitude (~15.669) regardless of real robot state looks less like noisy/amplified
telemetry and more like **a periodic animation or placeholder value** — possibly a
frontend gauge behavior (e.g. an idle/loading sweep) that isn't sourced from
`OdometryDataMessage`/`odometry.py` at all. This would also explain why the reverted
`odometry.py` patch produced literally zero visible change: it may never have been the
code path feeding this specific widget.
**Next step (not yet done)**: inspect the raw value actually being published/received —
e.g. `inorbit expr eval turtlebot-robot-sdk-test "getValue('...')"` for whatever key
backs this widget, or sniff the agent's outgoing MQTT payload directly — to tell whether
the backend is really emitting this oscillating number (agent-side bug) or the frontend
gauge is rendering it without real backend input (frontend bug, out of our control).

---

The Teleop "Publish on" field had a trailing space (`"/cmd_vel "`), which ROS2
rejects as an invalid topic name (`InvalidTopicNameException`) — a simple UI data-entry
typo, not connected to the QoS bug. This one **caused a real, separate symptom**:
every teleop-related state change (even a velocity slider nudge) re-triggered
`RosTeleopAgentlet`'s load, which crashed on the trailing space every single time —
explaining both "joystick doesn't respond" (the `/cmd_vel` publisher never successfully
got created) and the "cancel X stuck / rotation oscillating" look (the module was stuck
in a load/crash loop). **Fixed** by Carlos re-typing the topic in InOrbit Control's
Settings → Teleop → "Publish on" field without the trailing space — confirmed working
immediately after.

**Fix scope and durability**: since `install.sh`'s update flow can overwrite local
patches, and this is vendor code, the durable fix has to come from InOrbit — this patch
only lives in `turtlebot-robot-sdk-test`'s current container/install and won't survive
an agent auto-update or a fresh `liftoff` install. Not applied to `turtlebot-demo-02`
(`295895248`) — deliberately left broken/unpatched there since it's useful as a
clean, reproducible "before" reference.

**What to tell InOrbit**: `MapAgentlet.set_state()` in `agentlets/map.py`, when handling
a `map_topic` change, builds a resubscription tuple without QoS, unlike `load()`'s
initial subscription — causing the agent to permanently stop receiving `/map` (and,
because `RosLocalizationAgentlet` gates on `map_published`, permanently stop reporting
pose and laser too) any time the map topic is reconfigured after startup, which is
**the very setup step InOrbit's own Navigation-tab UI asks you to do** for any robot
whose map isn't already on a topic literally named `map`.

---

### History of the investigation (kept for the reasoning trail, not because it's still believed)

Found by Carlos: he could drive the robot via InOrbit Control's teleop panel (confirmed
it physically moves), but the robot's icon on the Navigation map never moved.

Confirmed independently via CLI/ROS inspection, not just visually:

- `inorbit expr eval 295895248 "getValue('pose')"` kept returning the **exact same
  timestamp** (`ts: 1785159286577`) minutes apart, across repeated queries.
- Meanwhile `/amcl_pose` and `/odom` (checked directly via `ros2 topic echo`) **were**
  updating — the robot's real position moved from the seeded `(-2.0, -0.5)` to roughly
  `(2.5, -1.2)`. So the ROS side is healthy; only InOrbit's reported pose is stuck.
- `/scan` is publishing fine (~5 Hz, confirmed via `ros2 topic hz`), and the agent
  process is alive and burning CPU (not hung).
- **No exceptions or warnings appear anywhere in `inorbit_agent.log`** for this — no
  `LookupException`, no "No robot pose available". The publish loop's `_maybe_publish()`
  (in `~/.inorbit/dist/inorbit/agentlets/localization.py`) is InOrbit's own shipped code,
  wrapped in a catch-all that logs an exception **only once ever per process** via a
  dedup'd `once_logger` — so a silently-recurring failure after the first successful
  publish would look exactly like this: no new log lines, no new data.
- **Killed and restarted the agent process entirely** (`pkill` + rerun `start.sh`) —
  came back up cleanly (all agentlets reloaded, config intact), and the pose value in
  InOrbit was **still frozen at the identical old timestamp**, even ~90 seconds after
  restart (well past the 1-second default publish period). This rules out "one-off stuck
  thread" as the explanation.
- Ruled out a duplicate-session conflict: checked the earlier `turtlebot-robot-sdk-test`
  container (holds a copy of the same `INORBIT_ID=295895248` credentials) — confirmed no
  `inorbit.py` process running there, so there's no second agent fighting over the same
  robot identity.
- Other data channels on the *same* agent process kept working the whole time (teleop
  commands, laser config republish) — this isn't a general disconnect, it's specific to
  the pose/localization channel (`ros/loc/data2` MQTT topic, published by
  `RosLocalizationAgentlet._maybe_publish()` — note `RosPoseAgentlet` disables itself
  whenever `RosLocalizationAgentlet` is loaded, so the latter is the only thing that
  should be publishing pose here, per `pose.py`'s `inform_override()`/`_apply_runlevel()`
  logic).

**Not root-caused** — this is inside InOrbit's own shipped Python agent package, not our
code, and tracing further would mean debugging their closed-source-ish vendored library
by trial and error with no source access beyond what's unpacked on disk. Suspicion,
unconfirmed: the large AMCL relocalization jump caused by teleop-driven movement (the
`RosTeleopAgentlet: Robot movement is not as planned` warnings in the log line up in time
with when this started) may put `_ros_on_laser_all()`'s per-scan-timestamp transform
lookup (`self._get_robot_pose(data.header.stamp)`) into a state where it keeps failing
silently on every cycle after that. Also worth revisiting once the stray
`laser2_topic: robot1/scan_back` (still pointing at a nonexistent topic) is cleared — not
yet tested as a fix, just flagged as still-outstanding cleanup that happens to touch the
same code path.

### History of this investigation (kept so the reasoning trail is visible — read the final ✅ verdict at the bottom, not the middle steps)

This bug got mis-diagnosed twice in the same day before landing on solid ground. Keeping
the trail because each wrong turn was based on real (if incomplete) evidence:

1. **First (2026-07-27)**: found `turtlebot-demo-02` (`295895248`) frozen after teleop.
   Ruled out local causes (restart, duplicate session, stale cache) → concluded "InOrbit
   agent bug, not root-caused."
2. **Second (2026-07-28 morning)**: registered a second identity
   (`turtlebot-demo-02-clean-test`, `322464837`) on the same sim. It published live while
   `295895248` stayed frozen → concluded "backend-specific to `295895248`." **This later
   looked wrong**: `322464837` froze too, later that same session, right after teleop →
   revised conclusion to "generic teleop-triggered agent bug, affects any robot."
3. **Third (2026-07-28 afternoon)**: while chasing *that* theory, discovered Gazebo
   itself was unhealthy for unrelated reasons (see the Gazebo-hang section below) —
   meaning steps 1 and 2 were partly conducted against a flaky simulation, muddying the
   pose-bug evidence with simulation-instability noise.
4. **Fourth, final (2026-07-28, later)**: once Gazebo was confirmed genuinely healthy
   (camera sensor disabled, stale DDS shared-memory files cleaned, CPU normal, `/clock`
   ticking at ~10Hz, AMCL independently confirmed publishing `/amcl_pose` via raw
   `ros2 topic echo` — nothing InOrbit-related in that check), registered a **third**
   identity (`660828878`) on that healthy simulation and compared it directly against
   `295895248`, at the same instant:
   ```
   295895248  (turtlebot-demo-02):  ts 1785159286577  →  26 hours old, unmoving
   660828878  (brand new):          ts 1785252939223  →  5.7 seconds old, live
   ```
   Both robots see the *same* real AMCL pose (the sim robot hadn't been driven this
   round, so x/y coincidentally look "plausible" for the stale one too — the `ts` field
   is what actually proves it, not x/y). Identical simulation, identical account,
   identical account key, only difference is the robot identity.

### ✅ Final verdict

**`295895248` (`turtlebot-demo-02`) has something durably broken on InOrbit's own
backend/account state for that specific robot ID.** It has never published a fresh pose
since 2026-07-27, across: multiple agent restarts, a full container rebuild, a brand-new
container, and a simulation now confirmed independently healthy. A fresh identity on the
exact same simulation, same account, works immediately. This is not a Gazebo problem, not
a generic InOrbit-agent-code bug, not a teleop-triggered bug — it's specific to that one
robot ID. (The teleop-triggered freeze seen on `322464837` in step 2 above most likely
was real too, but is now a *separate*, still-open question — see "Open questions" below —
since it happened during the period when Gazebo itself also turned out to be flaky, so it
can't be cleanly separated from that noise anymore. Both `322464837` and `660828878`
have since been deleted/orphaned along with their containers; only `295895248` persists
as a robot identity worth keeping around, precisely because it's the one that reproduces
the backend bug on demand.)

**Recommendation**: report `295895248` to InOrbit support with this write-up — exact
robot ID, the `ts` comparison above, and the fact that a sibling identity on the identical
simulation works instantly. Don't spend more local debugging time on this specific robot;
there's no more to learn from our side without their backend visibility.

**Practical takeaway**: don't use `295895248` for pose-dependent demos. Register a fresh
identity when one is needed (takes ~2 minutes: `curl liftoff URL | sh`, see "Robot
identity" above) — confirmed to work cleanly against a healthy simulation. Everything
else validated on `295895248` (map upload, camera, custom data, agentlet config
mechanism) is unaffected — this bug is specific to the pose/localization publish path
for this one robot ID.
- `battery` key-value is `None` — Gazebo doesn't simulate a battery topic, same
  constraint the Edge SDK connector has to work around (it likely fakes/derives battery
  independently; the Robot SDK agent has no such workaround built in, would need a
  custom key-value publisher if we want a battery gauge here too).

**This confirms the core thesis for standard telemetry**: pose, map, camera, and laser
needed **zero C++, zero republisher, zero Python** — only correct agentlet config in
InOrbit Control's UI, once the underlying ROS graph publishes the standard topics
Nav2/TurtleBot3 already provide out of the box.

## ✅ RESOLVED: Gazebo itself was hanging on world load (2026-07-28)

Not about InOrbit at all — Gazebo classic was failing to finish loading the simulation
world. Confirmed independently of InOrbit via plain ROS2/Gazebo tooling (`ros2 topic hz
/clock` hung forever, `gz stats` hung forever, `ros2 lifecycle get /map_server` hung
forever), so Nav2/AMCL never got a working simulation clock. This is what was
contaminating the pose-bug investigation above with unrelated noise for a chunk of the
day.

**Two real, compounding causes found, both fixed:**

1. **The TurtleBot3 waffle_pi's camera sensor is genuinely expensive under this
   container's forced software OpenGL rendering** (`LIBGL_ALWAYS_SOFTWARE=1`, needed
   because there's no GPU). Isolated cleanly: empty Gazebo world, no robot → 6.7% CPU.
   Same world + TurtleBot3 with all sensors → 486%+ CPU, sustained. That's ~4-5 CPU
   cores spent purely on software-rasterizing a 640x480@30fps camera. **Fix**: set
   `<always_on>false</always_on>` (and `<update_rate>1</update_rate>`) on the `<sensor
   name="camera">` block in
   `/opt/ros/humble/share/turtlebot3_gazebo/models/turtlebot3_waffle_pi/model.sdf`
   inside the container — drops CPU to ~40-90%. (We also tried removing the sensor
   block entirely at one point — CPU dropped further but didn't fix anything extra, and
   it's not necessary; `always_on: false` is the right amount of change. A `.bak` of the
   original is kept next to the file before patching.)
2. **Stale root-owned FastRTPS shared-memory files piling up in `/dev/shm`.** Every
   `docker exec` diagnostic command run as root during the day (the default for `docker
   exec` without `-u ubuntu`) spins up its own throwaway DDS participant, which leaves
   `fastrtps_*` / `sem.fastrtps_*` files behind in `/dev/shm` that don't get cleaned up
   on exit — especially when a command times out (124) rather than exiting cleanly.
   These accumulated for hours and started colliding with the `ubuntu` user's real DDS
   participants (topics registered fine — discovery is metadata-only — but no actual
   data flowed, exactly the symptom that made this hard to tell apart from an app-level
   hang). **Fix**: `find /dev/shm -maxdepth 1 -user root \( -name 'fastrtps*' -o -name
   'sem.fastrtps*' \) -delete`. Also a stray root-owned `/tmp/gazebo-ubuntu-rtshaderlibcache`
   (created whenever *any* root-run `launch_sim.sh` touches it before the `ubuntu` user
   does) caused the exact same-looking Ogre shader-cache permission error from the very
   first thing this morning — same underlying pattern: **don't run Gazebo-adjacent
   commands as root in this container**, always `-u ubuntu` (or `sudo -u ubuntu`) to
   avoid leaving root-owned artifacts that block the real `ubuntu`-run session later.

**Also contributing, not a fix but a lesson**: several `kill -9`s during the day (used to
stop stuck processes fast) skip graceful cleanup. `launch_sim.sh` has its own `trap
cleanup EXIT INT TERM` — a **Ctrl+C in the terminal** running it is much cleaner than
killing the PID from outside, since it releases Gazebo Transport/DDS resources properly
instead of abandoning them.

**How this was confirmed fixed, not just "CPU looks better"**: with the camera disabled
and `/dev/shm` cleaned, did the full chain end-to-end — `/clock` ticking at ~10Hz,
`ros2 topic echo /amcl_pose` returning a real, live pose independent of InOrbit — then
used that healthy simulation as the control group for the pose-bug investigation above
(registering `660828878` on it, which worked immediately). That combination is what
finally separated "Gazebo is unhealthy" from "this specific InOrbit robot is broken" —
they turned out to be two different bugs that had been tangled together.

1. ~~Native ROS2 agent exists~~ — confirmed.
2. ~~Installer supports Humble non-interactively~~ — confirmed.
3. ~~Where agentlet config is edited~~ — confirmed: InOrbit Control web UI, Navigation
   tab, per-robot. Not scriptable via our CLI.
4. ~~Does standard telemetry (pose/map/camera) really work end-to-end~~ — confirmed
   above, against the real simulation.
5. ~~Battery~~ — confirmed and implemented (2026-08-03): no built-in equivalent exists,
   and it does feed via `CustomDataAgentlet` as suspected. See "Battery" below.
6. Still open: whether installing Agent Core in the **actual named** `docker/ros2_gazebo`
   compose container (the one `turtlebot_connector`/Edge SDK uses) — as opposed to our
   separate `turtlebot-robot-sdk-vnc` container — causes any conflict. Not tested;
   deliberately avoided touching the real container so far. Given both mechanisms use
   independent MQTT sessions under different robot identities and ROS pub/sub allows
   multiple subscribers per topic, this is expected to be safe, but unverified.
7. Still open: whether a Python Robot SDK binding exists for our account — lower
   priority now, since nothing we validated needed custom code at all, in any language.
8. ~~Republisher for custom data~~ — not needed, superseded by
   `mission_data_node.py` feeding `CustomDataAgentlet` directly. Confirmed.
9. New, still open: is the **teleop-triggered** pose freeze seen on `322464837` earlier
   today (2026-07-28 morning, see history above, step 2) a real, separate InOrbit bug, or
   was it actually caused by the same Gazebo/DDS instability that turned out to be at
   fault for most of the day? Can't tell anymore — `322464837`'s container is gone. Worth
   re-testing specifically (drive `295895248` or a fresh identity hard with teleop, on a
   confirmed-healthy simulation like today's final state) before assuming it's fixed.

## Environment inventory (updated 2026-07-28 end of day, so nothing gets lost)

The `turtlebot-robot-sdk-vnc` container was recreated several times today (full rebuild
of the underlying image, then a couple of fresh `docker run`s to shed accumulated cruft —
see the Gazebo section above). **The current one is the good one** — camera disabled,
`/dev/shm` clean, confirmed healthy end-to-end.

| Container | Image | Purpose |
|---|---|---|
| `turtlebot-connector-ros2-gazebo` | `deliverance/turtlebot-connector-ros2-gazebo:humble` | **Real Edge SDK demo.** Briefly started today to attempt a comparison test — its bind mount turned out to point at a stale path (`/home/carlos-fernandez/INORBIT/...`, pre-reorg) so the comparison didn't work. Stopped again afterward, otherwise untouched. |
| `turtlebot-robot-sdk-vnc` | `deliverance/turtlebot-connector-ros2-gazebo:humble` (rebuilt `--no-cache` today) | **Current Robot SDK container, confirmed healthy.** Ports `6081`/`5901`. Camera `always_on: false` patched into `turtlebot3_waffle_pi/model.sdf` (`.bak` kept alongside). Carlos drives Gazebo/Nav2 himself via VNC terminals; Claude only starts/stops the container and runs diagnostics (prefer `-u ubuntu` for anything Gazebo/ROS-adjacent — see the DDS/shared-memory lesson above). Holds two agent identities (below). |
| `turtlebot-robot-sdk-test` | `deliverance/turtlebot-robot-sdk-test:latest` | Original backup of `295895248`'s install (from 2026-07-27, before Gazebo/VNC support existed on that path). Still the source of truth for `295895248`'s credentials — `docker cp` from here if it's ever needed again after another container recreation. |

### Agent identities

| Identity | Robot id | Installed under | Status |
|---|---|---|---|
| `turtlebot-demo-02` | `295895248` | `/root/.inorbit` (installed as `root`, needs `sudo` to start — `/root` is `700`) | **Confirmed durably broken on InOrbit's backend** — see "✅ Final verdict" above. Keep it around specifically *because* it reproduces the bug on demand; don't expect live pose from it. |
| *(none currently)* | `660828878` | was `/home/ubuntu/.inorbit` in a now-recreated container | Registered today purely to prove `295895248` is uniquely broken (succeeded — see verdict above). Not persisted; orphaned like `322464837` was. Register a new one the same way (~2 min) whenever a working pose-tracking identity is needed. |
| ~~`turtlebot-demo-02-clean-test`~~ | ~~`322464837`~~ | — | Retired — Carlos deleted it from InOrbit Control (Fleet → delete). Its container no longer exists either. |

Starting `295895248`'s agent:
```bash
sudo bash -c "source /root/.inorbit/local/agent.env.sh && /root/.inorbit/dist/scripts/start.sh"
```

Registering a fresh identity when a working one is needed (reuses the same account,
`INORBIT_ACCOUNT_ID=rnLasGAxn5CP7bj32` — get a fresh `liftoff` URL from InOrbit Control →
Add Robot if the old key stops working):
```bash
curl -fsSL <liftoff URL from InOrbit Control> -o /tmp/liftoff.sh
source /opt/ros/humble/setup.bash && export ROS_DOMAIN_ID=42
printf '\n' | script -qec 'sh /tmp/liftoff.sh' /dev/null   # non-interactive install
source ~/.inorbit/local/agent.env.sh && ~/.inorbit/dist/scripts/start.sh
```

## Next steps

- [x] Confirm native ROS2 agent is real.
- [x] Get Account Key from Carlos (InOrbit Control → Add Robot).
- [x] Install Agent Core, register `295895248` / `turtlebot-demo-02`.
- [x] Find where agentlet config is edited (InOrbit Control UI, Navigation tab).
- [x] Full live validation against real Gazebo/Nav2 — pose, map, camera, laser all
      config-only, zero code.
- [x] Custom data (`mission_status`/`mission_tracking`-equivalent): confirmed a plain
      ROS2 node feeding `CustomDataAgentlet` directly works — no republisher, no
      `robot-sdk-cpp`, no InOrbit SDK at all needed.
- [x] Root-cause the pose-freeze bug — confirmed specific to robot `295895248` on
      InOrbit's backend, not our simulation/config/code. Ready to report to InOrbit
      support.
- [x] Root-cause and fix the separate Gazebo world-load hang — camera software-rendering
      cost + accumulated root-owned DDS shared-memory files. Fixed and documented.
- [x] Wire `mission_data_node.py` to real Nav2 state (2026-07-29) — see "Custom data"
      section below for the full writeup, including a real bug found and fixed
      (`goal_id` → `goal_info.goal_id`) and a false alarm chased for a while (a "second
      goal doesn't update" symptom that turned out to just be checking InOrbit faster
      than the node's own 2s publish cycle, not a bug). Validated with four consecutive
      goals, each correctly reporting Executing → Completed with the right label/target.
- [ ] Report `295895248` to InOrbit support (exact writeup in "✅ Final verdict" above).
- [ ] Re-test whether teleop-triggered freezing (seen on `322464837` yesterday morning)
      is a real separate bug or was Gazebo-instability noise — open question #9 above.
- [ ] Clear the stray `laser2_topic` value in the UI (cosmetic).
- [ ] `turtlebot-demo-02-clean-test` (`322464837`) still shows in `inorbit get robots` —
      Carlos intends to delete it from InOrbit Control (Fleet UI) but hasn't yet as of
      2026-07-29 morning; no CLI command exists for robot deletion (`inorbit delete` only
      handles CAC `config`), has to be done from the web UI.
- [ ] Decide whether to formalize `turtlebot-robot-sdk-vnc`'s setup into a real
      Dockerfile/compose in `turtlebot_robot_sdk/docker/` (currently ad hoc `docker run` +
      `docker cp`, not reproducible from a committed file, and rebuilt from scratch once
      already today) — including baking the camera `always_on: false` patch in properly
      instead of applying it by hand after each container recreation.
- [x] Battery key-value (2026-08-03) — added to `mission_data_node.py`, see "Battery"
      below. Confirmed live end-to-end all the way to the Deliverance platform.
- [ ] Custom commands (`CustomCommandsAgentlet`, `inorbit/custom_command` topic) —
      identified as the likely equivalent of Edge SDK's custom-command callbacks
      (`Go Station 1`/`Cancel Task`-style actions), not yet exercised.
