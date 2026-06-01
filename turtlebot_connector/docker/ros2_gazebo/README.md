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
- TurtleBot3 waffle_pi (camera + LiDAR)
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

The validated fleet config is already at:

```text
config/fleet.ros2.office.local.yaml
```

Do not use `fleet.ros2.local.yaml` — that file uses the generic Nav2 default
map and does not configure camera or the office world correctly.

## Validated Step-By-Step Flow

The sequence below reflects the flow that was actually validated end-to-end,
including camera and map upload to InOrbit.

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
WORLD_FILE=/workspace/turtlebot_connector/office_demo/worlds/office_world.world \
  /workspace/turtlebot_connector/docker/ros2_gazebo/scripts/launch_sim.sh
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

### 5. Terminal 3 inside the container: launch Nav2 with the scanned office map

Inside the container:

```bash
/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/launch_nav2.sh \
  /workspace/turtlebot_connector/office_demo/maps/office_scanned.yaml
```

Always use `office_scanned.yaml` — this is the SLAM-scanned map of the Gazebo
office world. Do not use `office_map.yaml`, which is a pixel-converted PDF
floorplan without real scan data and will cause localization failures.

Nav2 publishes `/map` with transient-local QoS as soon as it starts. The
connector subscribes to this topic and uploads the map to InOrbit on startup.

After Nav2 starts, seed AMCL initial pose:

Option A, helper script:

```bash
/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/set_initial_pose.sh
```

Option B, manual in RViz:

- use `2D Pose Estimate`
- click near the robot spawn location (`x=-2.0, y=-0.5`)
- orient the arrow to match the robot heading

### 6. Optional ROS graph check

Inside the container:

```bash
/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/check_ros_graph.sh
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
/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/run_connector_ros2.sh \
  config/fleet.ros2.office.local.yaml
```

The script loads `config/.env` and `config/.env.local` without printing secrets.

## What the connector publishes to InOrbit

- **Pose**: from `/odom`, frame `map`
- **Map**: from `/map` (OccupancyGrid), uploaded as `turtlebot_office_map` on
  startup. Nav2 must be running and publishing `/map` before the connector
  starts, otherwise the map upload is silently skipped until the next restart.
- **Camera**: frames from `/camera/image_raw` published over MQTT as camera
  channel `0`. Validated at 1 fps, 380x240, quality 30 (rgb8 encoding).
- **Battery, KVs, navigation actions**: standard connector telemetry

## Camera Notes

The RobotCamera CAC (`cac/robot_camera.yaml`) uses:

```yaml
rosTopic: "0"
```

For Edge SDK connectors (`2.1.0.edgesdk_py`), `rosTopic` must be the
`camera_id`, not the actual ROS topic name. The connector registers the ROS
topic internally and publishes frames over MQTT. InOrbit uses `rosTopic` to
identify the MQTT camera channel.

For native ROS2 agents (`4.x.x.ros2`), `rosTopic` should be the actual ROS
topic (e.g. `raspicam_node/image/compressed`).

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
9. Confirm camera feed appears in InOrbit Navigation widget.

## Map Notes

Frames:

- Nav2 map frame: `map`
- Odometry frame: `odom`
- Base frame: `base_link`

The connector publishes pose in `frame_id=map`. The scanned map
(`office_scanned.yaml`) is used by both Nav2 and the connector, so the robot
position lines up correctly in InOrbit.

## Re-scanning the map (only if needed)

If the Gazebo world changes and the map needs to be re-scanned:

```bash
/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/launch_slam.sh
```

This launches slam_toolbox and Nav2. Teleop the robot to cover the full office
world, then save:

```bash
ros2 run nav2_map_server map_saver_cli \
  -f /tmp/scanned_map/office_scanned
```

Copy the resulting `.pgm` and `.yaml` to
`office_demo/maps/office_scanned.pgm` and `office_demo/maps/office_scanned.yaml`.
