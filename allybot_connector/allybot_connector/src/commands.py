# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Custom command definitions for the Allybot connector."""

from enum import StrEnum

from inorbit_connector.commands import CommandModel, ExcludeUnsetMixin  # noqa: F401


class CustomScripts(StrEnum):
    START_TASK = "start_task"
    PAUSE_TASK = "pause_task"
    RESUME_TASK = "resume_task"
    STOP_TASK = "stop_task"


class StartTaskCommand(CommandModel):
    task_id: str
    reach_charge_point: bool = True
