# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Configuration models for the Allybot connector."""

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from inorbit_connector.models import ConnectorConfig, RobotConfig

CONNECTOR_TYPE = "allybot"
DEFAULT_ENV_FILE = "config/.env"


class AllybotRobotConfig(RobotConfig):
    """Per-robot configuration.

    Attributes:
        robot_id: InOrbit robot ID.
        fleet_robot_id: Allybot robot UUID — matches ``robotId`` in REST responses
            and ``serial`` in App WS ``device_position`` messages.
    """

    fleet_robot_id: str  # UUID string


class AllybotConfig(BaseSettings):
    """Connector-level settings for the Ally Fleet Robot API.

    Fields can be supplied via YAML or environment variables.
    Environment variables use the ``INORBIT_ALLYBOT_`` prefix
    (e.g. ``base_url`` → ``INORBIT_ALLYBOT_BASE_URL``).
    """

    model_config = SettingsConfigDict(
        env_prefix=f"INORBIT_{CONNECTOR_TYPE.upper()}_",
        env_ignore_empty=True,
        case_sensitive=False,
        env_file=DEFAULT_ENV_FILE,
        extra="allow",
    )

    base_url: str  # e.g. "http://116.205.178.152:28080"
    username: str
    password: str  # stored in plain text; base64 encoding applied internally for App WS
    verify_ssl: bool = True
    request_timeout: float = 30.0


class AllybotConnectorConfig(ConnectorConfig):
    """Top-level connector configuration."""

    connector_config: AllybotConfig  # type: ignore[assignment]
    fleet: list[AllybotRobotConfig]  # type: ignore[assignment]

    @field_validator("connector_type")
    @classmethod
    def check_connector_type(cls, v: str) -> str:
        if v != CONNECTOR_TYPE:
            raise ValueError(
                f"Expected connector type '{CONNECTOR_TYPE}' not '{v}'"
            )
        return v

    @model_validator(mode="after")
    def validate_unique_fleet_robot_ids(self) -> "AllybotConnectorConfig":
        ids = [r.fleet_robot_id for r in self.fleet]
        if len(ids) != len(set(ids)):
            raise ValueError("fleet_robot_id values must be unique")
        return self
