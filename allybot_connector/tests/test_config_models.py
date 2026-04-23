# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for allybot_connector.src.config.models."""

from __future__ import annotations

import copy

import pytest

from allybot_connector.src.config.models import (
    CONNECTOR_TYPE,
    AllybotConfig,
    AllybotConnectorConfig,
    AllybotRobotConfig,
)


@pytest.fixture()
def base_config_data() -> dict:
    return {
        "connector_type": "allybot",
        "connector_config": {
            "base_url": "http://192.168.1.50:28080",
            "username": "admin",
            "password": "secret",
        },
        "fleet": [
            {
                "robot_id": "robot-alpha",
                "fleet_robot_id": "6d70603da0cb3d00ba104a191770170b",
            },
            {
                "robot_id": "robot-beta",
                "fleet_robot_id": "ba17e07275ac9bb21cf964ecbe2bd5c8",
            },
        ],
    }


def test_connector_type_must_match(base_config_data: dict) -> None:
    config = AllybotConnectorConfig(**base_config_data)
    assert config.connector_type == CONNECTOR_TYPE


def test_invalid_connector_type_raises(base_config_data: dict) -> None:
    data = copy.deepcopy(base_config_data)
    data["connector_type"] = "not-allybot"
    with pytest.raises(ValueError, match="Expected connector type 'allybot'"):
        AllybotConnectorConfig(**data)


def test_unique_fleet_robot_ids_required(base_config_data: dict) -> None:
    data = copy.deepcopy(base_config_data)
    data["fleet"][1]["fleet_robot_id"] = data["fleet"][0]["fleet_robot_id"]
    with pytest.raises(ValueError, match="fleet_robot_id values must be unique"):
        AllybotConnectorConfig(**data)


def test_valid_config_instantiates_models(base_config_data: dict) -> None:
    config = AllybotConnectorConfig(**base_config_data)
    assert isinstance(config.connector_config, AllybotConfig)
    assert all(isinstance(r, AllybotRobotConfig) for r in config.fleet)


def test_fleet_robot_id_is_string(base_config_data: dict) -> None:
    config = AllybotConnectorConfig(**base_config_data)
    assert config.fleet[0].fleet_robot_id == "6d70603da0cb3d00ba104a191770170b"


def test_allybot_config_defaults(base_config_data: dict) -> None:
    config = AllybotConnectorConfig(**base_config_data)
    assert config.connector_config.verify_ssl is True
    assert config.connector_config.request_timeout == 30.0


def test_allybot_config_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INORBIT_ALLYBOT_BASE_URL", "http://env-host:28080")
    monkeypatch.setenv("INORBIT_ALLYBOT_USERNAME", "env-user")
    monkeypatch.setenv("INORBIT_ALLYBOT_PASSWORD", "env-pass")
    config = AllybotConfig(
        base_url="http://env-host:28080",
        username="env-user",
        password="env-pass",
    )
    assert config.base_url == "http://env-host:28080"
    assert config.username == "env-user"
