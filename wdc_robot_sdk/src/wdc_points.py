# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT
"""Named navigation points of a WDC robot, loaded from a YAML file.

The points are the ones saved in the robot's own app. They differ per site,
so they live in a deployment file (see config/points.example.yaml) instead
of in the code. ROS-free, so it can be unit tested without ROS.
"""

import math
import re
from typing import Dict, Optional, Tuple

import yaml

Point = Tuple[float, float, float]

GOTO_PREFIX = "GOTO_"
_NAME_RE = re.compile(r"^[A-Z0-9_]{1,32}$")


class PointsFileError(ValueError):
    """The points file is missing, malformed or has an invalid point."""


def normalize_point_name(name) -> Optional[str]:
    """Returns the upper-case point name, or None when it is not valid
    (letters, digits and underscores, up to 32 characters)."""
    if not isinstance(name, str):
        return None
    name = name.strip().upper()
    return name if _NAME_RE.match(name) else None


def _number(value, field: str, point: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PointsFileError(f"point {point!r}: {field} must be a finite number")
    return float(value)


def parse_points(document) -> Dict[str, Point]:
    """Validates a parsed points document:

        points:
          A: {x: 1.0, y: 2.0, yaw: 0.0}

    Returns {NAME: (x, y, yaw)}. `yaw` (radians) defaults to 0."""
    if document is None:
        return {}
    if not isinstance(document, dict) or not isinstance(document.get("points", {}), dict):
        raise PointsFileError("expected a mapping with a 'points' mapping")
    points: Dict[str, Point] = {}
    for raw_name, spec in (document.get("points") or {}).items():
        name = normalize_point_name(raw_name)
        if name is None:
            raise PointsFileError(f"invalid point name {raw_name!r}")
        if name in points:
            raise PointsFileError(f"duplicate point name {name!r}")
        if not isinstance(spec, dict) or "x" not in spec or "y" not in spec:
            raise PointsFileError(f"point {name!r} needs x and y")
        points[name] = (
            _number(spec["x"], "x", name),
            _number(spec["y"], "y", name),
            _number(spec.get("yaw", 0.0), "yaw", name),
        )
    return points


def load_points(path: str) -> Dict[str, Point]:
    """Loads and validates a points file. Raises PointsFileError."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            document = yaml.safe_load(f)
    except OSError as exc:
        raise PointsFileError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise PointsFileError(f"cannot parse {path}: {exc}") from exc
    return parse_points(document)


def resolve_goto(command: str, points: Dict[str, Point]) -> Tuple[Optional[str], Optional[Point]]:
    """Resolves a "GOTO_<NAME>" command against the loaded points.

    Returns (name, point); point is None when the name is invalid or not
    configured, so unknown points are always refused."""
    if not command.startswith(GOTO_PREFIX):
        return None, None
    name = normalize_point_name(command[len(GOTO_PREFIX):])
    if name is None:
        return None, None
    return name, points.get(name)
