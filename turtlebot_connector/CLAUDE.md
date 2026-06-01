# TurtleBot Connector — Context for Claude

## Project overview
Edge connector for InOrbit that integrates a TurtleBot3 waffle_pi simulated in Gazebo with the InOrbit platform. Uses the InOrbit Edge SDK (`inorbit-edge 2.1.0`) and `inorbit-connector` base framework.

## Repo structure
- `turtlebot_connector/src/connector.py` — main FleetConnector implementation
- `turtlebot_connector/src/backends/ros2_gazebo.py` — ROS2/Nav2 backend (pose, navigation, map subscription)
- `turtlebot_connector/src/backends/ros2_camera.py` — ROS2 camera adapter (subscribes to `/camera/image_raw`, converts to JPEG)
- `turtlebot_connector/src/backends/base.py` — base backend interface
- `turtlebot_connector/src/backends/simulator.py` — fake backend for testing without ROS
- `config/fleet.ros2.office.local.yaml` — fleet config for the office demo (ROS2/Gazebo backend)
- `cac/robot_camera.yaml` — InOrbit CAC for the TurtleBot camera
- `cac/actions.yaml` — InOrbit CAC for navigation actions
- `office_demo/maps/office_scanned.pgm` + `office_scanned.yaml` — SLAM-scanned map of the Gazebo office world
- `office_demo/worlds/office_world.world` — Gazebo world file
- `docker/ros2_gazebo/` — Dockerfile and scripts for the ROS2/Gazebo container

## Stack
- Python 3.10, ROS2 Humble, Gazebo Classic
- TurtleBot3 waffle_pi model (has camera + LiDAR)
- Nav2 for navigation, slam_toolbox for map scanning
- InOrbit Edge SDK for MQTT publishing
- Virtual env: `.venv-ros2/` (always use this, not system Python)

## How to run (inside the Docker container VNC at http://localhost:6080)
1. Terminal 1: `WORLD_FILE=/workspace/turtlebot_connector/office_demo/worlds/office_world.world /workspace/turtlebot_connector/docker/ros2_gazebo/scripts/launch_sim.sh`
2. Terminal 2: `/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/launch_nav2.sh /workspace/turtlebot_connector/office_demo/maps/office_scanned.yaml`
3. Terminal 3: `/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/set_initial_pose.sh`
4. Terminal 4: `/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/run_connector_ros2.sh`

To rescan the map (only needed once): use `launch_slam.sh` instead of `launch_nav2.sh`, teleop the robot, then save with `ros2 run nav2_map_server map_saver_cli -f /tmp/scanned_map/office_scanned`.

## InOrbit account
- Account ID: `config/.env` → `INORBIT_ACCOUNT_ID` — not committed
- Robot ID: `config/.env` → `INORBIT_ROBOT_ID` (default: `turtlebot-demo-01`) — not committed
- Connector API key: `config/.env` → `INORBIT_API_KEY` — not committed
- CLI API key: `~/INORBIT/.env-inorbit` → `INORBIT_CLI_API_KEY` — not committed
- MQTT broker: configured automatically by the Edge SDK from the API key

## Key decisions and lessons learned

### Camera — rosTopic must be the camera_id, not the ROS topic
For Edge SDK connectors (`2.1.0.edgesdk_py`), the `rosTopic` field in the `RobotCamera` CAC must be set to the `camera_id` (e.g. `"0"`), NOT the actual ROS topic name. The connector handles the ROS subscription internally and publishes frames via MQTT (`ros/camera2`). InOrbit uses `rosTopic` to identify which channel to read from — for Edge SDK it expects the camera_id.

For native ROS2 agents (`4.x.x.ros2`), `rosTopic` should be the actual ROS topic (e.g. `raspicam_node/image/compressed`).

### Camera settings (production reference)
From other robots in the account: `width: 380`, `height: 240`, `rate: 1`, `quality: 30`, `outputEncoding: rgb8`. For Gazebo demo the same values apply. For real cameras with good network: `quality: 75`, `rate: 2`.

### Map
The connector implements `fetch_robot_map()` which subscribes to `/map` (OccupancyGrid with transient-local QoS), converts to PNG and uploads to InOrbit. Nav2 must be running and publishing `/map` before the connector starts, otherwise the map fetch fails silently (only retries on restart). The scanned map is `office_scanned.yaml` — do NOT use `office_map.yaml` which is a pixel-converted PDF floorplan without real scan data.

### Action scopes
`ActionDefinition` CAC must use `scope: robot/<ACCOUNT_ID>/turtlebot-demo-01` to avoid actions appearing for all robots in the account. To delete and reapply: `inorbit delete config --kind ActionDefinition --scope account/<ACCOUNT_ID> <id>`.

### CAC apply
Use `yes | inorbit apply -f <file>` to auto-confirm. Source `/home/carlos-fernandez/INORBIT/.env-inorbit` first.
