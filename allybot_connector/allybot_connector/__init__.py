# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Top-level package for InOrbit Allybot Connector."""

from importlib import metadata

__author__ = """InOrbit Inc."""
__email__ = "eduardo.munera@deliverance.enterprises"
# Read the installed package version from metadata
try:
    __version__ = metadata.version("allybot-connector")
except metadata.PackageNotFoundError:
    __version__ = "unknown"
