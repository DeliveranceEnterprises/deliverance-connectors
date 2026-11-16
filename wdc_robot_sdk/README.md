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

- `STOP`
- `CHARGE`
- `GOTO_<POINT>`, where `<POINT>` is one of the keys of `NAMED_POINTS` in the
  node (A to E, `HOME`, `RETURN_POINT` and `RECYCLING_POINT`).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `WDC_LOCAL_API_HOST` | none (required) | Address of the robot's tablet |
| `WDC_LOCAL_API_PORT` | `9015` | Port of the local API |
| `WDC_LOCAL_PGM_MAP_PATH` | empty | Optional map in `map_server` PGM format |
| `WDC_LOCAL_PGM_YAML_PATH` | empty | Metadata (`key: value` per line) of that map |

The map is taken from the robot itself (`cmd: "map"`). If that fails, the node
uses the PGM and YAML pair when configured, then the static image in
`src/espaitec1_map.jpg`, and finally a blank placeholder map. The map still has
to be aligned onto the shared floor plan by hand in InOrbit Control's Locations
editor.

## Requirements

- ROS1 with `rospy`, `tf2_ros`, `tf`, `geometry_msgs`, `nav_msgs`,
  `sensor_msgs` and `std_msgs`.
- [Pillow](https://python-pillow.org/).
- An InOrbit Agent Core for ROS1 on the same ROS master. Installing it is not
  covered here.

## InOrbit configuration

The `cac/` directory has the config-as-code for the robot:

- `actions.yaml`: the Stop, Go Charge and Go to Point actions, of type
  `PublishToTopic`.
- `mission_tracking.yaml`: how InOrbit interprets the `mission_tracking` key
  value.

## Notes and limitations

- The coordinates in `NAMED_POINTS` are the points saved in the robot's own
  app. They are copied by hand, so they must be updated if the points are
  redefined in the app.
- The local API has no mission history, so the mission progress is computed
  from the distance to the destination. A task started from the tablet itself
  is detected as well, without a known destination.
- The local API does not tag replies with a request id. The node serializes its
  own requests and ignores the error code of blank `info` replies, but running
  a second client against the same port at the same time can still mix up
  replies.
- The robot refuses a new destination while a previous job is pending (the
  reply is `BUSY!`). The node reports it instead of retrying: send `STOP`
  first.
