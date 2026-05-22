# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Entry point for the demo TurtleBot InOrbit connector."""

import argparse
import logging
import signal
import sys
from pathlib import Path
from typing import NoReturn

from dotenv import load_dotenv
from inorbit_connector.utils import read_yaml

from turtlebot_connector import __version__
from turtlebot_connector.src.config.models import TurtlebotConnectorConfig
from turtlebot_connector.src.connector import TurtlebotConnector

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


class CustomParser(argparse.ArgumentParser):
    """Argument parser that prints help when required arguments are missing."""

    def error(self, message: str) -> NoReturn:
        sys.stderr.write(f"error: {message}\n")
        self.print_help()
        sys.exit(2)


def load_environment_files(config_filename: str) -> list[Path]:
    """Load local env files next to the YAML config without overriding shell env."""

    config_dir = Path(config_filename).expanduser().resolve().parent
    loaded_files: list[Path] = []

    for env_file in (config_dir / ".env", config_dir / ".env.local"):
        if env_file.exists():
            load_dotenv(env_file, override=False)
            loaded_files.append(env_file)

    return loaded_files


def start() -> None:
    """Load YAML configuration and start the connector."""

    parser = CustomParser(
        prog="turtlebot-connector",
        description="Demo InOrbit TurtleBot Connector",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        required=True,
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args()
    loaded_env_files = load_environment_files(args.config)
    if loaded_env_files:
        LOGGER.info(
            "Loaded environment file(s): %s",
            [str(path) for path in loaded_env_files],
        )

    try:
        yaml_data = read_yaml(args.config)
        config = TurtlebotConnectorConfig(**yaml_data)
        robot_ids = [robot.robot_id for robot in config.fleet]
        LOGGER.info("Configuration loaded for fleet of %s robots", len(robot_ids))
        LOGGER.info("Robot IDs: %s", robot_ids)
    except FileNotFoundError:
        LOGGER.error("Configuration file '%s' not found", args.config)
        sys.exit(1)
    except ValueError as exc:
        LOGGER.error("Configuration validation error: %s", exc)
        sys.exit(1)

    connector = TurtlebotConnector(config)
    LOGGER.info("Starting TurtleBot demo connector...")
    connector.start()

    level = logging.getLogger().getEffectiveLevel()
    if level <= logging.DEBUG:
        logging.getLogger("RobotSession").setLevel(logging.INFO)

    signal.signal(signal.SIGINT, lambda sig, frame: connector.stop())
    connector.join()


if __name__ == "__main__":
    start()
