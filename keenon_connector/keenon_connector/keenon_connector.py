# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Entry point for the InOrbit Keenon Connector."""

# Standard
import argparse
import logging
import os
import signal
import sys
from pathlib import Path
from typing import NoReturn

# Third-party
from dotenv import load_dotenv

# InOrbit
from inorbit_connector.utils import read_yaml

# Local
from keenon_connector import __version__
from keenon_connector.src.config.models import KeenonConnectorConfig
from keenon_connector.src.connector import KeenonConnector

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


class CustomParser(argparse.ArgumentParser):
    """Custom argument parser that shows help on error."""

    def error(self, message: str) -> NoReturn:
        """Handle parser errors by showing help.

        Args:
            message: Error message to display
        """
        sys.stderr.write(f"error: {message}\n")
        self.print_help()
        sys.exit(2)


def start() -> None:
    """Main entry point for the connector.

    Parses command-line arguments, loads configuration, and starts the connector.
    Handles graceful shutdown on SIGINT.
    """
    parser = CustomParser(
        prog="keenon-connector",
        description="InOrbit Keenon Connector",
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
    config_filename = args.config

    # Load .env and .env.local next to the YAML config (same pattern as TurtleBot connector).
    config_dir = Path(config_filename).resolve().parent
    loaded_env_files = []
    for env_file in (config_dir / ".env", config_dir / ".env.local"):
        if env_file.exists():
            load_dotenv(env_file, override=False)
            loaded_env_files.append(env_file)
    if loaded_env_files:
        LOGGER.info("Loaded environment file(s): %s", [str(f) for f in loaded_env_files])

    try:
        yaml_data = read_yaml(config_filename)
        # api_key default is evaluated at import time (BaseModel, not BaseSettings).
        # Re-read from env here so dotenv values are picked up correctly.
        yaml_data.setdefault("api_key", os.getenv("INORBIT_API_KEY"))
        config = KeenonConnectorConfig(**yaml_data)

        robot_ids = [robot.robot_id for robot in config.fleet]
        LOGGER.info(f"Configuration loaded for fleet of {len(robot_ids)} robots")
        LOGGER.info(f"Robot IDs: {robot_ids}")

    except FileNotFoundError:
        LOGGER.error(f"Configuration file '{config_filename}' not found")
        sys.exit(1)
    except ValueError as e:
        LOGGER.error(f"Configuration validation error: {e}")
        sys.exit(1)

    # Create and start the fleet connector
    connector = KeenonConnector(config)
    LOGGER.info("Starting Keenon Connector...")
    connector.start()

    # Adjust the log level of certain libraries to reduce noise
    level = logging.getLogger().getEffectiveLevel()
    if level <= logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.INFO)
        logging.getLogger("RobotSession").setLevel(logging.INFO)
    elif level == logging.INFO:
        logging.getLogger("httpx").setLevel(logging.WARNING)

    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, lambda sig, frame: connector.stop())

    # Wait for the connector to finish
    connector.join()


if __name__ == "__main__":
    start()
