# Office Demo — TurtleBot3 Gazebo World

This directory contains the assets for the TurtleBot3 Gazebo simulation based on a real office floorplan. The goal is for Gazebo, Nav2, and InOrbit to share a coherent metric coordinate system.

## Scale And Coordinates

The office world is built to match the **Floorplan0** reference used in InOrbit:

| Parameter | Value |
|---|---|
| Resolution | `0.0104908 m/px` |
| World size | `8.6444 m × 6.4203 m` |
| Nav2 origin (centered) | `[-4.3222, -3.2102, 0.0]` |
| Robot spawn / Home | `x = -2.0, y = -0.5` |

The resolution was derived from the usable area of the PDF floorplan (`55.50 m²`) and the pixel dimensions of the cropped region (`824 × 612 px`):

```
resolution = sqrt(55.50 / (824 * 612)) ≈ 0.0104908 m/px
```

This gives a final map size of:

```
width  = 824 × 0.0104908 = 8.6444 m
height = 612 × 0.0104908 = 6.4203 m
area   ≈ 55.50 m²
```

The aspect ratio was cross-checked against real robot scans of the same area (Allybot: 1.299, AutoXing: 1.322, Floorplan0: 1.346) — close enough for a demo without a full metric calibration.

---

## Files

| File | Description |
|---|---|
| `maps/office_scanned.yaml` + `maps/office_scanned.pgm` | SLAM-scanned map (slam_toolbox). **Use this for Nav2 and the connector.** Resolution 0.05 m/px, 168×126 cells, origin `[-4.32, -3.16, 0]`. |
| `maps/office_map.yaml` + `maps/office_map.pgm` | Map generated from the PDF floorplan. Reference only — do not use for Nav2, AMCL localization will fail without real scan data. |
| `worlds/office_world.world` | Gazebo world file: floor (`8.6444 × 6.4203 m`), exterior and interior walls, shelving unit, double door. |

---

## Step-By-Step Launch (inside the Docker container)

All commands run inside the container at `/workspace/turtlebot_connector`.

### Step 1 — Gazebo simulation

```bash
export DISPLAY=:1
export XAUTHORITY=/home/ubuntu/.Xauthority
export LIBGL_ALWAYS_SOFTWARE=1
WORLD_FILE=/workspace/turtlebot_connector/office_demo/worlds/office_world.world \
  /workspace/turtlebot_connector/docker/ros2_gazebo/scripts/launch_sim.sh
```

### Step 2 — Optional Gazebo GUI client (VNC desktop only, run as `ubuntu`)

```bash
su - ubuntu
source /opt/ros/humble/setup.bash
export DISPLAY=:1
export XAUTHORITY=/home/ubuntu/.Xauthority
export LIBGL_ALWAYS_SOFTWARE=1
gzclient
```

### Step 3 — Nav2 with the scanned map

```bash
/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/launch_nav2.sh \
  /workspace/turtlebot_connector/office_demo/maps/office_scanned.yaml
```

Seed the AMCL initial pose after Nav2 is active:

```bash
/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/set_initial_pose.sh
```

Or use `2D Pose Estimate` in RViz at `x=-2.0, y=-0.5`.

### Step 4 — InOrbit connector

```bash
/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/run_connector_ros2.sh \
  config/fleet.ros2.office.local.yaml
```

---

## World Geometry Notes

### Shelving unit

Modelled as `shelves_left`: `0.70 m × 4.00 m × 1.50 m`, flush against the left wall. The TurtleBot3 LiDAR can detect it and Nav2 treats it as an obstacle.

### Double door

Modelled as `door_double`: `1.40 m × 0.05 m × 2.00 m`, positioned at the far-left opening of the top wall. It closes the geometric gap in the wall so the scan and the physics match.
