"""Entry point for the InOrbit Ezviz Connector."""

import argparse
import logging
import signal
import sys
from typing import NoReturn

from inorbit_connector.utils import read_yaml

from ezviz_connector import __version__
from ezviz_connector.src.config.models import EzvizConnectorConfig
from ezviz_connector.src.connector import EzvizConnector

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


class CustomParser(argparse.ArgumentParser):
    """Argument parser that shows help on error."""

    def error(self, message: str) -> NoReturn:
        sys.stderr.write(f"error: {message}\n")
        self.print_help()
        sys.exit(2)


def start() -> None:
    parser = CustomParser(
        prog="ezviz-connector",
        description="InOrbit Ezviz Connector",
    )
    parser.add_argument("-c", "--config", type=str, required=True,
                        help="Path to YAML configuration file")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()
    config_filename = args.config

    try:
        yaml_data = read_yaml(config_filename)
        config = EzvizConnectorConfig(**yaml_data)
        serials = [r.fleet_robot_id for r in config.fleet]
        LOGGER.info("Configuration loaded for %d camera(s): %s", len(serials), serials)
    except FileNotFoundError:
        LOGGER.error("Configuration file '%s' not found", config_filename)
        sys.exit(1)
    except ValueError as exc:
        LOGGER.error("Configuration validation error: %s", exc)
        sys.exit(1)

    connector = EzvizConnector(config)
    LOGGER.info("Starting Ezviz Connector...")
    connector.start()

    # Trim noisy library logs.
    level = logging.getLogger().getEffectiveLevel()
    if level <= logging.DEBUG:
        logging.getLogger("urllib3").setLevel(logging.INFO)
        logging.getLogger("RobotSession").setLevel(logging.INFO)
    elif level == logging.INFO:
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("pyezvizapi").setLevel(logging.WARNING)

    signal.signal(signal.SIGINT, lambda sig, frame: connector.stop())
    connector.join()


if __name__ == "__main__":
    start()
