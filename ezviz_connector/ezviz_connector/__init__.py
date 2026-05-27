"""Top-level package for InOrbit Ezviz Connector."""

from importlib import metadata

__author__ = """Deliverance Enterprises"""
__email__ = "eduardo.munera@deliverance.enterprises"

try:
    __version__ = metadata.version("ezviz-connector")
except metadata.PackageNotFoundError:
    __version__ = "unknown"
