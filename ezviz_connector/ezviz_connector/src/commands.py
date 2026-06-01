"""Custom command definitions for the Ezviz connector."""

from enum import StrEnum


class CustomScripts(StrEnum):
    """Script names for custom commands.

    Values must match the ``filename`` argument in the corresponding
    ActionDefinition in ``cac/actions.yaml``.
    """

    PTZ_UP = "ptz_up"
    PTZ_DOWN = "ptz_down"
    PTZ_LEFT = "ptz_left"
    PTZ_RIGHT = "ptz_right"
    PTZ_STOP = "ptz_stop"


# Map script name -> pyezvizapi direction constant.
PTZ_DIRECTIONS: dict[str, str] = {
    CustomScripts.PTZ_UP: "UP",
    CustomScripts.PTZ_DOWN: "DOWN",
    CustomScripts.PTZ_LEFT: "LEFT",
    CustomScripts.PTZ_RIGHT: "RIGHT",
}

# Default nudge duration in milliseconds — how long the camera moves on one click.
DEFAULT_PTZ_NUDGE_MS = 500
DEFAULT_PTZ_SPEED = 5
