# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Custom command definitions for the Keenon connector."""

from enum import StrEnum

from inorbit_connector.commands import CommandModel, ExcludeUnsetMixin


class CustomScripts(StrEnum):
    """Script names for custom commands.

    Values must match the ``filename`` argument in the corresponding
    ActionDefinition in ``cac/actions.yaml``.
    """

    CALL_TO_POINT = "call_to_point"
    RETURN_TO_ORIGIN = "return_to_origin"
    CANCEL_TASK = "cancel_task"
    CLEAN_RECHARGE = "clean_recharge"
    CLEAN_FINISH = "clean_finish"
    CLEAN_PAUSE = "clean_pause"
    CLEAN_TEMPORARY_TASK = "clean_temporary_task"
    OPEN_CABIN = "open_cabin"
    CLOSE_CABIN = "close_cabin"


class CallToPointCommand(ExcludeUnsetMixin, CommandModel):
    """Arguments for calling a robot to a specific point."""

    point_uuid: str
    point_id: str
    scene_code: str | None = None


class CancelTaskCommand(ExcludeUnsetMixin, CommandModel):
    """Arguments for cancelling an active task."""

    task_no: str


class CleanTemporaryTaskCommand(ExcludeUnsetMixin, CommandModel):
    """Arguments for starting a temporary cleaning task."""

    area_id_list: str  # JSON-encoded list, e.g. '["id1","id2"]'
    clean_model_id: str
    clean_times: int = 1
    back_point_id: int


class CabinControlCommand(ExcludeUnsetMixin, CommandModel):
    """Arguments for opening or closing a hotel robot cabin door."""

    cabin: str
