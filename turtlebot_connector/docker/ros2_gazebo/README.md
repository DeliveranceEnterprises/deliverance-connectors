# ROS 2 / Gazebo TurtleBot Demo Container

This README is intentionally narrower than the root `turtlebot_connector`
README. It documents the containerized ROS 2 / Gazebo / Nav2 demo environment
used to reproduce, validate, and debug the TurtleBot simulation.

Both README files coexist on purpose:

- `turtlebot_connector/README.md` explains the connector itself, its
  configuration, and its InOrbit integration
- `turtlebot_connector/docker/ros2_gazebo/README.md` explains the validated
  simulation workflow for this specific demo environment

This folder prepares a single-container validation environment for:

- ROS 2 Humble
- Gazebo classic
- TurtleBot3
- Nav2
- `turtlebot_connector` with `backend=ros2_gazebo`

The goal is to avoid DDS networking issues between host and containers during
the first real Nav2 validation. Gazebo, Nav2, and the connector run in the same
container. InOrbit traffic still goes out over HTTPS/MQTT using the mounted
local `config/.env`; secrets are not copied into the image or declared in
Compose.

## Base Image Choice

The image is based on `tiryoh/ros2-desktop-vnc:humble` because it provides a
browser-accessible desktop/VNC environment and ROS 2 Humble. Humble is the
practical target for TurtleBot3, Nav2, and Gazebo classic. This is a demo
environment, not a production connector image.

## Build And Start

From `turtlebot_connector/`:

```bash
docker compose -f docker/ros2_gazebo/docker-compose.yml up -d
```

The Compose service starts the VNC desktop from the base image. The validated
demo flow used the browser desktop plus interactive shells inside the running
container.

Open the desktop at:

```text
http://localhost:6080
```

Open a shell inside the container when needed:

```bash
docker compose -f docker/ros2_gazebo/docker-compose.yml exec turtlebot-ros2-gazebo bash
```

## Prepare Connector Config

Inside or outside the container:

```bash
cp config/fleet.ros2.example.yaml config/fleet.ros2.local.yaml
```

Adjust waypoints only after checking the TurtleBot3 map. Keep them close to
free space for the first run.

## Validated Step-By-Step Flow

The sequence below reflects the flow that was actually used in the successful
validation sessions.

### 1. Start the container from the host

From `turtlebot_connector/`:

```bash
docker compose -f docker/ros2_gazebo/docker-compose.yml up -d
```

### 2. Open the desktop

In a browser:

```text
http://localhost:6080
```

### 3. Terminal 1 inside the container: launch Gazebo server and spawn the robot

Inside the container:

```bash
export DISPLAY=:1
export XAUTHORITY=/home/ubuntu/.Xauthority
export LIBGL_ALWAYS_SOFTWARE=1
docker/ros2_gazebo/scripts/launch_sim.sh
```

This launches `gzserver` with `GazeboRosFactory`, then starts
`robot_state_publisher` and spawns TurtleBot3 `waffle_pi`. The launcher uses the
VNC display with software GL so Gazebo can render the simulated camera without
starting `gzclient`. The GUI client can fail in VNC/OpenGL environments while
the ROS/Gazebo server remains valid for Nav2 and camera testing.

The default spawn location comes from `launch_sim.sh`:

```text
TB3_X_POSE=-2.0
TB3_Y_POSE=-0.5
```

### 4. Terminal 2 inside the container: optional Gazebo GUI client

The validated sessions launched the GUI client as user `ubuntu`, not as `root`:

```bash
su - ubuntu
cd /workspace/turtlebot_connector
source /opt/ros/humble/setup.bash
export DISPLAY=:1
export XAUTHORITY=/home/ubuntu/.Xauthority
export LIBGL_ALWAYS_SOFTWARE=1
gzclient
```

This step is useful for visual confirmation. The simulation itself can still run
without `gzclient`.

### 5. Terminal 3 inside the container: launch Nav2 / RViz

Inside the container:

```bash
cd /workspace/turtlebot_connector
docker/ros2_gazebo/scripts/launch_nav2.sh
```

Default map:

```text
/opt/ros/humble/share/turtlebot3_navigation2/map/map.yaml
```

This map must match the Gazebo world closely enough for Nav2 localization and
planning. InOrbit may still show a generic/no map unless the equivalent map is
configured there too.

After Nav2 starts, there are two ways to seed AMCL:

Option A, helper script:

```bash
docker/ros2_gazebo/scripts/set_initial_pose.sh
```

Option B, validated manual flow in RViz:

- use `2D Pose Estimate`
- click near the robot spawn location
- orient the arrow to match the robot heading seen in Gazebo

In the validated sessions, the manual RViz method was used instead of relying
on the script. This matters because the robot was visually aligned from the same
spawn position shown on the map and in Gazebo.

Expected Nav2 result:

- `/navigate_to_pose` appears in `ros2 action list`
- lifecycle nodes such as `/bt_navigator`, `/controller_server`, and
  `/planner_server` are `active`
- `tf2_echo map base_link` returns a transform

### 6. Optional ROS graph check

Inside the container:

```bash
cd /workspace/turtlebot_connector
docker/ros2_gazebo/scripts/check_ros_graph.sh
```

Expected:

- `/odom`
- `/cmd_vel`
- `/camera/image_raw`
- `/navigate_to_pose`
- `python3 -c "import rclpy"` succeeds

### 7. Terminal 4 inside the container: run the connector

Inside the container:

```bash
cd /workspace/turtlebot_connector
docker/ros2_gazebo/scripts/run_connector_ros2.sh config/fleet.ros2.local.yaml
```

The script loads `config/.env` and `config/.env.local` without printing secrets.

## Camera Validation Notes

During RViz validation, the `Image` display subscribed to:

```text
/camera/image_raw
```

and showed live simulated images. That confirms the ROS-side camera publisher is
working independently of InOrbit rendering.

If the connector later logs lines such as:

```text
Closing ROS camera adapter '0' after receiving 2187 frame(s)
```

that does not mean the robot camera stopped publishing in ROS. It means the
InOrbit-side camera subscription/stream was closed after frames had already been
received. RViz showing live images from `/camera/image_raw` is the stronger
signal for whether Gazebo/ROS is still publishing.

## Useful Evidence Collected So Far

The following observations are the most useful ones for debugging or escalation:

1. RViz can subscribe to `/camera/image_raw` and shows a live simulated image.
   This is the strongest evidence that Gazebo and ROS are still publishing
   camera frames correctly.

2. RViz also shows the Nav2 map, localization, and robot pose at the same time.
   That confirms the simulation, localization, and camera publisher are alive in
   the same session.

3. InOrbit `Navigation` can show the robot pose correctly on the map while the
   camera panel still says `No camera image available`. This proves navigation
   data is reaching InOrbit even when the camera image is not rendered.

4. A standalone `cameraWidget` using the same `cameraId: "0"` also fails to
   render the image. This shows the issue is not limited to the `navigation`
   widget alone.

5. Backend connector logs show all of the following:
   - the ROS camera is registered in InOrbit
   - the ROS camera adapter is opened
   - the first frame is received successfully
   - hundreds or thousands of frames are received before the adapter is closed

   This is the strongest evidence that the connector is not failing at the ROS
   subscription stage.

6. Browser console logs show InOrbit-side errors such as:
   - `configToken ... is null`
   - `useDirectClientMulti called with an empty or missing robotIds parameter`
   - `r.reduce is not a function`

   These errors are relevant because they point to a possible frontend or
   platform-side data/configuration problem after the backend stream has already
   started.

Taken together, these observations support the conclusion that ROS publishing is
working, the connector is receiving frames, and the remaining issue appears
later in the InOrbit-side rendering or data-consumption path.

## InOrbit Control Test

1. Open robot `turtlebot-demo-01`.
2. Run `Go Station 1`.
3. Confirm Gazebo moves the robot.
4. Confirm `/navigate_to_pose` receives a goal.
5. Confirm InOrbit KVs:
   - `operational_state=moving`
   - `current_waypoint=station_1`
   - `task_state=executing`
6. Wait for completion and check `task_state=completed`.
7. Run `Go Station 2`.
8. While moving, run `Cancel Task` and check `task_state=canceled`.
9. Open the camera panel and confirm whether the TurtleBot3 camera feed appears.

At the time of writing, navigation/tasks are validated, but camera rendering in
InOrbit remains unresolved even though `/camera/image_raw` is visible in RViz
and the backend receives frames.

## Map Notes

Frames:

- Nav2 map frame: `map`
- Odometry frame: `odom`
- Base frame: `base_link`

The connector publishes pose in `frame_id=map`. For a visually correct InOrbit
map, upload/register the same map used by Nav2, or configure an equivalent map
in InOrbit. If the InOrbit map does not match the Nav2 map, actions can still
drive Gazebo, but the robot position may not line up visually in InOrbit.

Automatic map upload is intentionally not implemented in this phase.
