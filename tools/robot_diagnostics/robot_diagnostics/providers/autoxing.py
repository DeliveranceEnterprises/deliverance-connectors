"""Read-only AutoXing inventory skeleton."""

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
    return not text or "your-" in text or "placeholder" in text or "<" in text


async def diagnose(repo_root: Path, robot_id: str | None, all_robots: bool, ws_seconds: float) -> list[dict[str, Any]]:
    config_path = repo_root / "autoxing_connector" / "config" / "my_fleet.local.yaml"
    env_path = repo_root / "autoxing_connector" / "config" / ".env.local"
    with config_path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    fleet = list(config.get("fleet") or [])
    if robot_id:
        fleet = [robot for robot in fleet if robot.get("robot_id") == robot_id]
    elif not all_robots:
        fleet = fleet[:1]

    connector_config = config.get("connector_config") or {}
    env_text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    missing = []
    if _placeholder(connector_config.get("login_name")):
        missing.append("login_name")
    if _placeholder(connector_config.get("business_id")):
        missing.append("business_id")
    password_line = next((item for item in env_text.splitlines() if item.startswith("INORBIT_AUTOXING_PASSWORD=")), "")
    if not password_line or _placeholder(password_line.split("=", 1)[1]):
        missing.append("INORBIT_AUTOXING_PASSWORD")

    rows = []
    for robot in fleet:
        robot_missing = list(missing)
        if _placeholder(robot.get("fleet_robot_id")):
            robot_missing.append("fleet_robot_id")
        row = {
            "provider": "AutoXing",
            "robot_id": robot.get("robot_id"),
            "fleet_robot_id": robot.get("fleet_robot_id"),
            "fleet_robot_id_masked": _mask(robot.get("fleet_robot_id")),
            "configured_in_yaml": True,
            "business_id": connector_config.get("business_id"),
            "validated": "pending_credentials" if robot_missing else "yaml_only",
            "observations": f"AutoXing API read-only checks not implemented yet; missing/placeholder: {', '.join(robot_missing)}" if robot_missing else "AutoXing API read-only checks not implemented yet",
        }
        rows.append(row)
    return rows
