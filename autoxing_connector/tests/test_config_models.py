# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for autoxing_cloud_connector.src.config.models."""

from __future__ import annotations

import copy

import pytest

from autoxing_cloud_connector.src.config.models import (
    CONNECTOR_TYPE,
    AutoxingConnectorConfig,
    AutoxingFleetConnectorConfig,
    AutoxingRobotConfig,
)

_VALID_CONNECTOR_CONFIG = {
    "login_name": "user@example.com",
    "password": "secret",
    "business_id": "biz456",
}

_BASE_CONFIG = {
    "connector_type": CONNECTOR_TYPE,
    "connector_config": _VALID_CONNECTOR_CONFIG,
    "fleet": [
        {"robot_id": "robot-1", "fleet_robot_id": "AAA111"},
        {"robot_id": "robot-2", "fleet_robot_id": "BBB222"},
    ],
}


def test_valid_config_loads() -> None:
    config = AutoxingFleetConnectorConfig(**_BASE_CONFIG)
    assert config.connector_type == CONNECTOR_TYPE
    assert len(config.fleet) == 2


def test_wrong_connector_type_raises() -> None:
    data = copy.deepcopy(_BASE_CONFIG)
    data["connector_type"] = "wrong"
    with pytest.raises(ValueError, match="Expected connector_type"):
        AutoxingFleetConnectorConfig(**data)


def test_duplicate_fleet_robot_ids_raises() -> None:
    data = copy.deepcopy(_BASE_CONFIG)
    data["fleet"][1]["fleet_robot_id"] = data["fleet"][0]["fleet_robot_id"]
    with pytest.raises(ValueError, match="unique"):
        AutoxingFleetConnectorConfig(**data)


def test_robot_config_area_map_config_defaults_empty() -> None:
    robot = AutoxingRobotConfig(robot_id="r1", fleet_robot_id="X1")
    assert robot.area_map_config == {}


def test_connector_config_defaults() -> None:
    cfg = AutoxingConnectorConfig(**_VALID_CONNECTOR_CONFIG)
    assert cfg.base_url == "https://apiglobal.autoxing.com"
    assert cfg.verify_ssl is True
    assert cfg.request_timeout == 30.0


def test_connector_config_reads_password_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INORBIT_AUTOXING_PASSWORD", "env-pass")
    cfg = AutoxingConnectorConfig(
        login_name="u@e.com",
        business_id="b",
        password="env-pass",
    )
    assert cfg.password == "env-pass"
