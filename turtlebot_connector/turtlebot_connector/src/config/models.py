# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Pydantic configuration models for the demo TurtleBot connector."""

import os
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from inorbit_edge.robot import INORBIT_CLOUD_SDK_ROBOT_CONFIG_URL
from inorbit_connector.models import ConnectorConfig, RobotConfig

CONNECTOR_TYPE = "turtlebot"
DEFAULT_ENV_FILE = "config/.env"
REQUIRED_WAYPOINTS = {"home", "station_1", "station_2", "charger"}


class PoseConfig(BaseModel):
    """2D pose in a map frame."""

    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0


class WaypointConfig(PoseConfig):
    """Named target that the fake robot can navigate to."""

    name: str


class TurtlebotBackendType(str, Enum):
    """Runtime backend selection."""

    FAKE = "fake"
    ROS2_GAZEBO = "ros2_gazebo"


class Ros2PoseSource(str, Enum):
    """ROS pose topic preference."""

    ODOM = "odom"
    AMCL = "amcl"


class Ros2GazeboConfig(BaseModel):
    """ROS 2 / Gazebo / Nav2 backend settings."""

    enabled: bool = False
    pose_source: Ros2PoseSource = Ros2PoseSource.ODOM
    odom_topic: str = "/odom"
    amcl_pose_topic: str = "/amcl_pose"
    nav2_action_name: str = "/navigate_to_pose"
    cmd_vel_topic: str = "/cmd_vel"
    initialpose_topic: str = "/initialpose"
    # Open Teleop (d-pad) step sizes. Each click on an arrow nudges the robot
    # by these increments through Nav2 (relative to the robot frame).
    open_teleop_linear_step_m: float = 0.35
    open_teleop_angular_step_rad: float = 0.50
    map_frame: str = "map"
    odom_frame: str = "odom"
    base_frame: str = "base_link"
    use_sim_time: bool = True
    camera_enabled: bool = False
    camera_id: str = "camera"
    camera_topic: str = "/camera/image_raw"
    camera_rate_hz: float = Field(default=5.0, gt=0.0)
    camera_scaling: float = Field(default=0.5, gt=0.0, le=1.0)
    camera_quality: int = Field(default=35, ge=1, le=100)


class CleaningDemoConfig(BaseModel):
    """Static fake cleaning-robot telemetry for the TurtleBot Cleaning demo.

    Values are published as plain key-values on every cycle when enabled. They
    do not animate — drain/refill simulation can be layered on top later.
    """

    enabled: bool = False
    clean_water_tank: int = Field(default=72, ge=0, le=100)
    dirty_water_tank: int = Field(default=35, ge=0, le=100)
    detergent_tank: int = Field(default=58, ge=0, le=100)
    cleaning_mode: str = "eco"
    brush_status: str = "running"
    vacuum_status: str = "on"
    clean_faulting: bool = False
    clean_emergency_stop: bool = False
    cleaned_area_m2: float = 24.5


class TurtlebotRobotConfig(RobotConfig):
    """Per-robot configuration for the fake TurtleBot simulator."""

    name: str = "TurtleBot Demo"
    robot_model: str = "TurtleBot3 Waffle Pi"
    online: bool = True
    initial_pose: PoseConfig = Field(default_factory=PoseConfig)
    initial_battery: float = Field(default=0.95, ge=0.0, le=1.0)
    waypoints: list[WaypointConfig]

    @model_validator(mode="after")
    def validate_unique_waypoints(self) -> "TurtlebotRobotConfig":
        waypoint_names = [waypoint.name for waypoint in self.waypoints]
        if len(waypoint_names) != len(set(waypoint_names)):
            raise ValueError("waypoint names must be unique per robot")
        missing_waypoints = REQUIRED_WAYPOINTS - set(waypoint_names)
        if missing_waypoints:
            missing = ", ".join(sorted(missing_waypoints))
            raise ValueError(f"missing required waypoints: {missing}")
        return self


class TurtlebotConfig(BaseSettings):
    """Connector-level settings for the fake simulator.

    Values can be supplied in YAML under connector_config or by environment
    variables using the INORBIT_TURTLEBOT_ prefix.
    """

    model_config = SettingsConfigDict(
        env_prefix="INORBIT_TURTLEBOT_",
        env_ignore_empty=True,
        case_sensitive=False,
        env_file=DEFAULT_ENV_FILE,
        extra="ignore",
    )

    provider_name: str = "fake_turtlebot"
    backend: TurtlebotBackendType = TurtlebotBackendType.FAKE
    movement_speed_mps: float = Field(default=0.35, gt=0.0)
    battery_drain_per_second: float = Field(default=0.0005, ge=0.0)
    charge_rate_per_second: float = Field(default=0.002, ge=0.0)
    ros2: Ros2GazeboConfig = Field(default_factory=Ros2GazeboConfig)
    cleaning_demo: CleaningDemoConfig = Field(default_factory=CleaningDemoConfig)


class TurtlebotConnectorConfig(ConnectorConfig):
    """Top-level connector configuration."""

    api_key: str | None = Field(default_factory=lambda: os.getenv("INORBIT_API_KEY"))
    api_url: HttpUrl = Field(
        default_factory=lambda: os.getenv(
            "INORBIT_API_URL",
            INORBIT_CLOUD_SDK_ROBOT_CONFIG_URL,
        ),
        validate_default=True,
    )
    connector_config: TurtlebotConfig = Field(default_factory=TurtlebotConfig)  # type: ignore[assignment]
    fleet: list[TurtlebotRobotConfig]  # type: ignore[assignment]

    @field_validator("connector_type")
    @classmethod
    def check_connector_type(cls, value: str) -> str:
        if value != CONNECTOR_TYPE:
            raise ValueError(f"Expected connector_type '{CONNECTOR_TYPE}', got '{value}'")
        return value

    @model_validator(mode="after")
    def validate_unique_robot_ids(self) -> "TurtlebotConnectorConfig":
        robot_ids = [robot.robot_id for robot in self.fleet]
        if len(robot_ids) != len(set(robot_ids)):
            raise ValueError("robot_id values must be unique")
        return self
