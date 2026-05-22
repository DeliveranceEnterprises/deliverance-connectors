# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Custom command definitions for the demo TurtleBot connector."""

from enum import Enum

from inorbit_connector.commands import CommandModel, ExcludeUnsetMixin  # noqa: F401


class CustomScripts(str, Enum):
    """RunScript command names accepted from InOrbit."""

    GO_TO = "go_to"
    DISPATCH = "dispatch"
    CANCEL_TASK = "cancel_task"


class GoToCommand(CommandModel):
    """Navigate to a named waypoint."""

    waypoint: str
    task_id: str = ""


class DispatchCommand(CommandModel):
    """Dispatch a fake task to a named waypoint."""

    waypoint: str
    task_id: str = ""
    label: str = ""


class CancelTaskCommand(CommandModel):
    """Cancel the active task, optionally checking a task id."""

    task_id: str = ""
