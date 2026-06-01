"""Configuration models for the Ezviz connector."""

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from inorbit_connector.models import ConnectorConfig, RobotConfig

CONNECTOR_TYPE = "ezviz"

DEFAULT_ENV_FILE = "config/.env"


class EzvizRobotConfig(RobotConfig):
    """Per-camera configuration.

    Attributes:
        robot_id: InOrbit robot ID.
        fleet_robot_id: Ezviz device serial (e.g. ``L45505505``).
        channel: Camera channel for multi-lens devices.
        default_map: frame_id of the InOrbit map this camera lives on.
            The connector publishes a static pose with this frame_id so the
            camera appears on the map; you can then drag it to its real
            position in the InOrbit UI.
        pose_x: Static x coordinate (metres) used with default_map. 0 by default.
        pose_y: Static y coordinate (metres) used with default_map. 0 by default.
        pose_theta: Static yaw (radians) used with default_map. 0 by default.
            Common values: 0 = facing +x, 1.5708 = +90°, -1.5708 = -90°, 3.1416 = 180°.
    """

    fleet_robot_id: str
    channel: int = 1
    default_map: str | None = None
    pose_x: float = 0.0
    pose_y: float = 0.0
    pose_theta: float = 0.0


class EzvizConfig(BaseSettings):
    """Connector-level settings.

    Loaded from YAML and overridden by env vars with the ``INORBIT_EZVIZ_``
    prefix (e.g. ``region_url`` → ``INORBIT_EZVIZ_REGION_URL``).
    """

    model_config = SettingsConfigDict(
        env_prefix=f"INORBIT_{CONNECTOR_TYPE.upper()}_",
        env_ignore_empty=True,
        case_sensitive=False,
        env_file=DEFAULT_ENV_FILE,
        extra="allow",
    )

    account: str
    password: str
    region_url: str = "apiieu.ezvizlife.com"
    request_timeout: float = 30.0
    metadata_poll_seconds: float = 60.0
    sms_code: int | None = None


class EzvizConnectorConfig(ConnectorConfig):
    """Top-level connector configuration."""

    connector_config: EzvizConfig  # type: ignore[assignment]
    fleet: list[EzvizRobotConfig]  # type: ignore[assignment]

    @field_validator("connector_type")
    @classmethod
    def check_connector_type(cls, v: str) -> str:
        if v != CONNECTOR_TYPE:
            raise ValueError(f"Expected connector type '{CONNECTOR_TYPE}' not '{v}'")
        return v

    @model_validator(mode="after")
    def validate_unique_serials(self) -> "EzvizConnectorConfig":
        ids = [r.fleet_robot_id for r in self.fleet]
        if len(ids) != len(set(ids)):
            raise ValueError("fleet_robot_id (camera serial) values must be unique")
        return self
