"""Read-only InOrbit CLI helpers."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any


def _load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _parse_bool(value: str) -> bool | None:
    low = value.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return None


def parse_describe_robots(output: str) -> dict[str, dict[str, Any]]:
    robots: dict[str, dict[str, Any]] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("Usage:"):
            continue
        parts = re.split(r"\s{2,}", line)
        if len(parts) < 5:
            continue
        name, robot_id, agent_version, online, last_seen = parts[:5]
        if robot_id.lower() == "id":
            continue
        robots[robot_id] = {
            "visible_name": name,
            "robot_id": robot_id,
            "agent_version": agent_version,
            "online": _parse_bool(online),
            "last_seen": last_seen,
            "raw_line": raw_line,
        }
    return robots


def describe_robots(workspace: Path) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Run `inorbit describe robots` in read-only mode."""
    inorbit_bin = workspace / ".venv-inorbit" / "bin" / "inorbit"
    env_file = workspace / ".env-inorbit"
    if not inorbit_bin.exists():
        return {}, f"InOrbit CLI not found at {inorbit_bin}"
    if not env_file.exists():
        return {}, f"InOrbit env file not found at {env_file}"

    env = os.environ.copy()
    env.update(_load_env_file(env_file))
    result = subprocess.run(
        [str(inorbit_bin), "describe", "robots"],
        check=False,
        text=True,
        capture_output=True,
        env=env,
        cwd=str(workspace),
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        lines = [line for line in message.splitlines() if line.strip()]
        return {}, lines[-1] if lines else f"inorbit describe robots exited {result.returncode}"
    return parse_describe_robots(result.stdout), None


def infer_provider(robot: dict[str, Any]) -> tuple[str, str]:
    robot_id = str(robot.get("robot_id") or "").lower()
    name = str(robot.get("visible_name") or "").lower()
    haystack = f"{robot_id} {name}"
    if "allybot" in haystack:
        return "Allybot", "Inferred from InOrbit robot id/name"
    if "keenon" in haystack:
        return "Keenon", "Inferred from InOrbit robot id/name"
    if "autoxing" in haystack:
        return "AutoXing", "Inferred from InOrbit robot id/name"
    return "unknown", "Exists in InOrbit but is not configured in a local connector YAML"

