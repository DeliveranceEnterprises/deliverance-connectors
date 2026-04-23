# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for keenon_connector.src.config.models."""

from __future__ import annotations

import copy

import pytest

from keenon_connector.src.config.models import (
    CONNECTOR_TYPE,
    KeenonConfig,
    KeenonConnectorConfig,
    KeenonRobotConfig,
)


@pytest.fixture()
def base_config_data() -> dict:
    return {
        "connector_type": "keenon",
        "connector_config": {
            "api_domain": "https://es.robotkeenon.com",
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
        },
        "fleet": [
            {"robot_id": "robot-alpha", "fleet_robot_id": "AA:BB:CC:DD:EE:01", "store_id": "S00000001"},
            {"robot_id": "robot-beta", "fleet_robot_id": "AA:BB:CC:DD:EE:02", "store_id": "S00000001"},
        ],
    }


def test_connector_type_must_match(base_config_data: dict) -> None:
    config = KeenonConnectorConfig(**base_config_data)
    assert config.connector_type == CONNECTOR_TYPE


def test_invalid_connector_type_raises(base_config_data: dict) -> None:
    data = copy.deepcopy(base_config_data)
    data["connector_type"] = "not-keenon"
    with pytest.raises(ValueError, match="Expected connector type 'keenon'"):
        KeenonConnectorConfig(**data)


def test_unique_fleet_robot_ids_required(base_config_data: dict) -> None:
    data = copy.deepcopy(base_config_data)
    data["fleet"][1]["fleet_robot_id"] = data["fleet"][0]["fleet_robot_id"]
    with pytest.raises(ValueError, match="fleet_robot_id values must be unique"):
        KeenonConnectorConfig(**data)


def test_valid_config_instantiates_models(base_config_data: dict) -> None:
    config = KeenonConnectorConfig(**base_config_data)
    assert isinstance(config.connector_config, KeenonConfig)
    assert all(isinstance(r, KeenonRobotConfig) for r in config.fleet)


def test_fleet_robot_id_is_string(base_config_data: dict) -> None:
    config = KeenonConnectorConfig(**base_config_data)
    assert config.fleet[0].fleet_robot_id == "AA:BB:CC:DD:EE:01"


def test_robot_config_has_store_id(base_config_data: dict) -> None:
    config = KeenonConnectorConfig(**base_config_data)
    assert config.fleet[0].store_id == "S00000001"


def test_keenon_config_default_values(base_config_data: dict) -> None:
    config = KeenonConnectorConfig(**base_config_data)
    assert config.connector_config.verify_ssl is True
    assert config.connector_config.request_timeout == 30.0
    assert config.connector_config.webhook_host == "0.0.0.0"
    assert config.connector_config.webhook_port is None


def test_keenon_config_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INORBIT_KEENON_API_DOMAIN", "https://cn.example.com")
    monkeypatch.setenv("INORBIT_KEENON_CLIENT_ID", "env-id")
    monkeypatch.setenv("INORBIT_KEENON_CLIENT_SECRET", "env-secret")
    config = KeenonConfig(
        api_domain="https://cn.example.com",
        client_id="env-id",
        client_secret="env-secret",
    )
    assert config.api_domain == "https://cn.example.com"


def test_webhook_port_can_be_set(base_config_data: dict) -> None:
    data = copy.deepcopy(base_config_data)
    data["connector_config"]["webhook_port"] = 9090
    config = KeenonConnectorConfig(**data)
    assert config.connector_config.webhook_port == 9090
