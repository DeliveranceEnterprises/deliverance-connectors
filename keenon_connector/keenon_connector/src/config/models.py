# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Configuration models for the Keenon connector."""

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from inorbit_connector.models import ConnectorConfig, RobotConfig

CONNECTOR_TYPE = "keenon"

# Loaded automatically when running from the project root.
DEFAULT_ENV_FILE = "config/.env"


class KeenonRobotConfig(RobotConfig):
    """Per-robot configuration.

    Attributes:
        robot_id: InOrbit robot ID.
        fleet_robot_id: Keenon robot MAC address (e.g. ``AA:BB:CC:DD:EE:FF``).
        store_id: Keenon store ID the robot belongs to (e.g. ``S00000001``).
    """

    fleet_robot_id: str  # MAC address format
    store_id: str


class KeenonConfig(BaseSettings):
    """Connector-level settings for the Keenon Cloud API.

    Fields can be supplied via YAML or environment variables.
    Environment variables use the ``INORBIT_KEENON_`` prefix
    (e.g. ``api_domain`` → ``INORBIT_KEENON_API_DOMAIN``).
    """

    model_config = SettingsConfigDict(
        env_prefix=f"INORBIT_{CONNECTOR_TYPE.upper()}_",
        env_ignore_empty=True,
        case_sensitive=False,
        env_file=DEFAULT_ENV_FILE,
        extra="allow",
    )

    api_domain: str  # e.g. "https://es.robotkeenon.com"
    client_id: str
    client_secret: str
    verify_ssl: bool = True
    request_timeout: float = 30.0
    webhook_host: str = "0.0.0.0"
    webhook_port: int | None = None  # None disables the webhook receiver


class KeenonConnectorConfig(ConnectorConfig):
    """Top-level connector configuration.

    Attributes:
        connector_config: Keenon Cloud API settings.
        fleet: List of robot configurations.
    """

    connector_config: KeenonConfig  # type: ignore[assignment]
    fleet: list[KeenonRobotConfig]  # type: ignore[assignment]

    @field_validator("connector_type")
    @classmethod
    def check_connector_type(cls, v: str) -> str:
        if v != CONNECTOR_TYPE:
            raise ValueError(
                f"Expected connector type '{CONNECTOR_TYPE}' not '{v}'"
            )
        return v

    @model_validator(mode="after")
    def validate_unique_fleet_robot_ids(self) -> "KeenonConnectorConfig":
        ids = [r.fleet_robot_id for r in self.fleet]
        if len(ids) != len(set(ids)):
            raise ValueError("fleet_robot_id values must be unique")
        return self
