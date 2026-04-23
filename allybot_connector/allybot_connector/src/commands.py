# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Custom command definitions for the Allybot connector.

The Ally Fleet Robot API does not expose control endpoints, so this connector
is monitoring-only.  This module is retained for future use.
"""

from enum import StrEnum

from inorbit_connector.commands import CommandModel, ExcludeUnsetMixin  # noqa: F401


class CustomScripts(StrEnum):
    """Script names for custom commands — currently empty (monitoring-only)."""
