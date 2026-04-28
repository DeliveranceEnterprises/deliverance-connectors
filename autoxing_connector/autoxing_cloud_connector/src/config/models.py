# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Configuration models for the AutoXing Cloud connector."""

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from inorbit_connector.models import ConnectorConfig, RobotConfig

CONNECTOR_TYPE = "autoxing"

# Fixed APPCODEs — login uses a different code from all other endpoints.
_LOGIN_APPCODE = "8184850f6ebe4edea8ba3e37ae46a35b"
_API_APPCODE = "dd7afee0a068431abb2425ac622e70d2"


class AutoxingRobotConfig(RobotConfig):
    """Per-robot configuration for the AutoXing Cloud connector.

    Attributes:
        fleet_robot_id: AutoXing robot ID string.
        area_map_config: Optional per-area map metadata overrides keyed by areaId.
            Each value may have: origin_x (float), origin_y (float), resolution (float m/px).
    """

    fleet_robot_id: str
    area_map_config: dict[str, dict] = {}


class AutoxingConnectorConfig(BaseSettings):
    """AutoXing Cloud connection settings.

    Loaded from YAML connector_config section; missing fields fall back to
    environment variables with the INORBIT_AUTOXING_ prefix.
    """

    model_config = SettingsConfigDict(
        env_prefix="INORBIT_AUTOXING_",
        case_sensitive=False,
        env_ignore_empty=True,
    )

    base_url: str = "https://apiglobal.autoxing.com"
    login_name: str
    password: str
    business_id: str
    login_appcode: str = _LOGIN_APPCODE
    api_appcode: str = _API_APPCODE
    verify_ssl: bool = True
    request_timeout: float = 30.0


class AutoxingFleetConnectorConfig(ConnectorConfig):
    """Top-level connector configuration."""

    connector_config: AutoxingConnectorConfig  # type: ignore[assignment]
    fleet: list[AutoxingRobotConfig]  # type: ignore[assignment]

    @field_validator("connector_type")
    @classmethod
    def check_connector_type(cls, v: str) -> str:
        if v != CONNECTOR_TYPE:
            raise ValueError(f"Expected connector_type '{CONNECTOR_TYPE}', got '{v}'")
        return v

    @model_validator(mode="after")
    def validate_unique_fleet_ids(self) -> "AutoxingFleetConnectorConfig":
        ids = [r.fleet_robot_id for r in self.fleet]
        if len(ids) != len(set(ids)):
            raise ValueError("fleet_robot_id values must be unique")
        return self
