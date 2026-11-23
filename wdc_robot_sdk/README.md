<!--
SPDX-FileCopyrightText: 2026 Deliverance Enterprises

SPDX-License-Identifier: MIT
-->

# WDC robot bridge for InOrbit

A plain ROS1 node that republishes the telemetry of a WDC delivery robot as
standard ROS topics and tf, so that InOrbit's Agent Core can detect them, and
that turns InOrbit robot actions into commands for the robot.

Unlike the Edge SDK connectors in this repository, it does not run a connector
process that talks to InOrbit. It runs next to an InOrbit Agent Core (ROS1) on
a machine that can reach the robot's tablet, and the Agent Core does the
talking to InOrbit.

## How it works

The robot's own tablet app serves a local WebSocket API (port 9015, path
`/robot`). It is a simple JSON request/response protocol without
authentication, for example `{"cmd": "getPoses"}`. No cloud server is
involved. The node polls it every 2 seconds and publishes:

| Topic | Type | Content |
|---|---|---|
| `/scan` | `sensor_msgs/LaserScan` | Laser scan (frame `laser_link`) |
| `/battery_state` | `sensor_msgs/BatteryState` | Battery percentage |
| `/map` | `nav_msgs/OccupancyGrid` | Floor plan (latched) |
| `/inorbit/custom_data/0` | `std_msgs/String` | Key values for InOrbit: battery, robot `info` fields, `mission_status` and `mission_tracking` |
| tf `map` to `base_link` | | Robot pose |
| tf `base_link` to `laser_link` | | Static laser offset |

It subscribes to `/inorbit/custom_command` and accepts three kinds of command,
which are what the actions in `cac/actions.yaml` send:

- `STOP`: sent ahead of the polling (which pauses meanwhile) and retried up
  to 3 times until the robot's `info` reports `agvStop`. The result is
  logged and published as the `stop_status` key value (`confirmed` or
  `failed`); a confirmed stop closes the current mission as `Canceled`.
- `CHARGE`
- `GOTO_<POINT>`, where `<POINT>` is a point of the points file (see
  [Named points](#named-points)). Any other name is refused.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `WDC_LOCAL_API_HOST` | none (required) | Address of the robot's tablet |
| `WDC_LOCAL_API_PORT` | `9015` | Port of the local API |
| `WDC_LOCAL_PGM_MAP_PATH` | empty | Optional map in `map_server` PGM format |
| `WDC_LOCAL_PGM_YAML_PATH` | empty | Metadata (`key: value` per line) of that map |
| `WDC_POINTS_FILE` | empty | YAML file with the named points (the `~points_file` ROS parameter overrides it) |

The map is taken from the robot itself (`cmd: "map"`). If that fails, the node
uses the PGM and YAML pair when configured, then the static image in
`src/static_map.jpg` (optional, not included in the repository), and finally a blank
placeholder map. The map still has
to be aligned onto the shared floor plan by hand in InOrbit Control's Locations
editor.

## Named points

The coordinates of the points are site data, so they are not in the code.
Copy `config/points.example.yaml`, replace the example values with the
points saved in the robot's own app (map frame, metres, yaw in radians), and
set `WDC_POINTS_FILE` to the copy. Without a points file, every `GOTO_`
command is refused.

To add a point:

1. Add it under `points:` in your file, for example
   `DOCK_2: {x: 1.25, y: -0.5, yaw: 0.0}`. Names are case-insensitive and
   use letters, digits and underscores.
2. Add an action to `cac/actions.yaml` that publishes `GOTO_DOCK_2` (copy
   one of the `wdc-goto-*` actions) and apply it.
3. Restart the node.

Only list points that are inside the robot's current map.

## Requirements

- ROS1 with `rospy`, `tf2_ros`, `tf`, `geometry_msgs`, `nav_msgs`,
  `sensor_msgs` and `std_msgs`.
- [Pillow](https://python-pillow.org/) and PyYAML (shipped with ROS1).
- An InOrbit Agent Core for ROS1 on the same ROS master. Installing it is not
  covered here.

## InOrbit configuration

The `cac/` directory has the config-as-code for the robot:

- `actions.yaml`: the Stop, Go Charge and Go to Point actions, of type
  `PublishToTopic`.
- `mission_tracking.yaml`: how InOrbit interprets the `mission_tracking` key
  value.

## Notes and limitations

- The coordinates in the points file are copied by hand from the robot's
  app, so they must be updated if the points are redefined there.
- The local API has no mission history, so the mission progress is computed
  from the distance to the destination. A task started from the tablet itself
  is detected as well, without a known destination.
- The local API does not tag replies with a request id. The node serializes its
  own requests, drops replies whose shape does not match the command, and
  ignores the error code of blank `info` replies, but running a second client
  against the same port at the same time can still mix up replies.
- The robot refuses a new destination while a previous job is pending (the
  reply is `BUSY!`). The node reports it and closes the mission as
  `Aborted` instead of retrying: send `STOP` first.
