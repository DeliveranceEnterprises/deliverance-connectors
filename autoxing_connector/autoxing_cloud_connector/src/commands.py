# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Custom command definitions for the AutoXing Cloud connector."""

from enum import StrEnum

from inorbit_connector.commands import CommandModel, ExcludeUnsetMixin  # noqa: F401


class CustomScripts(StrEnum):
    NAVIGATE_TO_POI = "navigate_to_poi"
    GO_HOME = "go_home"
    CANCEL_TASK = "cancel_task"
    EXECUTE_TASK = "execute_task"


class NavigateToPoiCommand(CommandModel):
    poi_id: str
    task_type: int = 4   # Delivery (five-in-one)
    run_type: int = 22   # Direct delivery


class CancelTaskCommand(CommandModel):
    task_id: str = ""    # empty = use current task from state


class ExecuteTaskCommand(CommandModel):
    task_id: str
