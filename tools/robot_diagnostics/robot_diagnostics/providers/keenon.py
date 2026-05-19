"""Read-only Keenon inventory skeleton.

This module currently parses local config and detects missing placeholders.
API read-only calls can be added once real Keenon credentials are available.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _mask(value: str | None, visible: int = 6) -> str | None:
    if value is None:
        return None
    if len(value) <= visible * 2:
        return "<set>"
    return f"{value[:visible]}...{value[-visible:]}"


def _placeholder(value: Any) -> bool:
    text = str(value or "").lower()
    return not text or "your-" in text or "placeholder" in text


async def diagnose(repo_root: Path, robot_id: str | None, all_robots: bool, ws_seconds: float) -> list[dict[str, Any]]:
    config_path = repo_root / "keenon_connector" / "config" / "my_fleet.local.yaml"
    env_path = repo_root / "keenon_connector" / "config" / ".env.local"
    with config_path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    fleet = list(config.get("fleet") or [])
    if robot_id:
        fleet = [robot for robot in fleet if robot.get("robot_id") == robot_id]
    elif not all_robots:
        fleet = fleet[:1]

    env_text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    missing = []
    for key in ("INORBIT_KEENON_CLIENT_ID", "INORBIT_KEENON_CLIENT_SECRET"):
        line = next((item for item in env_text.splitlines() if item.startswith(f"{key}=")), "")
        if not line or _placeholder(line.split("=", 1)[1]):
            missing.append(key)

    rows = []
    for robot in fleet:
        row = {
            "provider": "Keenon",
            "robot_id": robot.get("robot_id"),
            "fleet_robot_id": robot.get("fleet_robot_id"),
            "fleet_robot_id_masked": _mask(robot.get("fleet_robot_id")),
            "configured_in_yaml": True,
            "store_id": robot.get("store_id"),
            "validated": "pending_credentials" if missing else "yaml_only",
            "observations": f"Keenon API read-only checks not implemented yet; missing/placeholder: {', '.join(missing)}" if missing else "Keenon API read-only checks not implemented yet",
        }
        rows.append(row)
    return rows
