# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Tests for TurtleBot connector entrypoint helpers."""

from __future__ import annotations

import os

from turtlebot_connector.turtlebot_connector import load_environment_files
from turtlebot_connector.src.config.models import TurtlebotConnectorConfig


def test_load_environment_files_reads_env_next_to_config(
    tmp_path,
    monkeypatch,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "my_fleet.yaml"
    config_file.write_text("connector_type: turtlebot\n", encoding="utf-8")
    (config_dir / ".env").write_text("INORBIT_TURTLEBOT_PROVIDER_NAME=from-env\n", encoding="utf-8")

    monkeypatch.delenv("INORBIT_TURTLEBOT_PROVIDER_NAME", raising=False)

    loaded_files = load_environment_files(str(config_file))

    assert loaded_files == [config_dir / ".env"]
    assert loaded_files[0].is_absolute()
    assert os.environ["INORBIT_TURTLEBOT_PROVIDER_NAME"] == "from-env"


def test_load_environment_files_does_not_override_shell_env(
    tmp_path,
    monkeypatch,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "my_fleet.yaml"
    config_file.write_text("connector_type: turtlebot\n", encoding="utf-8")
    (config_dir / ".env").write_text(
        "INORBIT_TURTLEBOT_PROVIDER_NAME=from-file\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("INORBIT_TURTLEBOT_PROVIDER_NAME", "from-shell")

    load_environment_files(str(config_file))

    assert os.environ["INORBIT_TURTLEBOT_PROVIDER_NAME"] == "from-shell"


def test_connector_config_reads_api_key_after_env_file_load(
    tmp_path,
    monkeypatch,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "my_fleet.yaml"
    config_file.write_text("connector_type: turtlebot\n", encoding="utf-8")
    (config_dir / ".env").write_text("INORBIT_API_KEY=test-key\n", encoding="utf-8")

    monkeypatch.delenv("INORBIT_API_KEY", raising=False)
    load_environment_files(str(config_file))

    config = TurtlebotConnectorConfig(
        connector_type="turtlebot",
        connector_config={},
        fleet=[
            {
                "robot_id": "turtlebot-demo-01",
                "waypoints": [
                    {"name": "home", "x": 0.0, "y": 0.0, "yaw": 0.0},
                    {"name": "station_1", "x": 1.0, "y": 0.0, "yaw": 0.0},
                    {"name": "station_2", "x": -1.0, "y": 0.0, "yaw": 3.14},
                    {"name": "charger", "x": 0.0, "y": -1.0, "yaw": -1.57},
                ],
            }
        ],
    )

    assert config.api_key == "test-key"
