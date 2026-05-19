"""Read-only Allybot diagnostics."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import time
from pathlib import Path
from typing import Any

import aiohttp
import httpx
import yaml

from ..common import append_observation, exception_summary


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def mask(value: str | None, visible: int = 6) -> str | None:
    if value is None:
        return None
    if len(value) <= visible * 2:
        return "<set>"
    return f"{value[:visible]}...{value[-visible:]}"


def is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).lower()
    return not text or "your-" in text or "placeholder" in text


def quaternion_to_yaw(qx: float, qy: float, qz: float, qw: float) -> float:
    return 2.0 * math.atan2(qz, qw)


def load_config(config_path: Path, env_path: Path) -> dict[str, Any]:
    load_env_file(env_path)
    with config_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    connector_config = data.setdefault("connector_config", {})
    connector_config.setdefault("base_url", os.getenv("INORBIT_ALLYBOT_BASE_URL"))
    connector_config.setdefault("username", os.getenv("INORBIT_ALLYBOT_USERNAME"))
    connector_config.setdefault("password", os.getenv("INORBIT_ALLYBOT_PASSWORD"))
    connector_config.setdefault("verify_ssl", True)
    connector_config.setdefault("request_timeout", 30.0)
    return data


def select_fleet(config: dict[str, Any], robot_id: str | None, all_robots: bool) -> list[dict[str, Any]]:
    fleet = list(config.get("fleet") or [])
    if all_robots:
        return fleet
    if robot_id:
        matches = [robot for robot in fleet if robot.get("robot_id") == robot_id]
        if not matches:
            known = ", ".join(str(robot.get("robot_id")) for robot in fleet)
            raise ValueError(f"Robot '{robot_id}' is not in Allybot YAML. Known: {known}")
        return matches
    return fleet[:1]


class AllybotReadOnlyClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.base_url = str(config["base_url"]).rstrip("/")
        self.username = str(config["username"])
        self.password = str(config["password"])
        self.verify_ssl = bool(config.get("verify_ssl", True))
        self.timeout = float(config.get("request_timeout", 30.0))
        self.http = httpx.AsyncClient(
            base_url=self.base_url,
            verify=self.verify_ssl,
            timeout=self.timeout,
        )
        self.mobile_token: str | None = None
        self.openid: str | None = None
        self.rest_token: str | None = None

    async def close(self) -> None:
        await self.http.aclose()

    async def login(self) -> None:
        password_b64 = base64.b64encode(self.password.encode()).decode()
        resp = await self.http.post(
            "/fleetapi/account/login",
            headers={"X-Api-Version": "184"},
            data={"username": self.username, "password": password_b64},
        )
        resp.raise_for_status()
        data = (resp.json().get("data") or {})
        self.mobile_token = data.get("token")
        self.openid = data.get("openid")
        if not self.mobile_token or not self.openid:
            raise RuntimeError("Mobile login did not return token/openid")

        try:
            rest = await self.http.post(
                "/user/login",
                json={"account": self.username, "password": self.password},
            )
            rest.raise_for_status()
            token = rest.headers.get("x-token")
            body = rest.json()
            rest_data = body.get("data")
            if not token and isinstance(rest_data, str):
                token = rest_data
            if not token and isinstance(rest_data, dict):
                token = rest_data.get("token") or rest_data.get("x-token")
            self.rest_token = token or None
        except Exception:
            self.rest_token = None

    def mobile_headers(self) -> dict[str, str]:
        return {
            "Token": self.mobile_token or "",
            "Mobile-User-Id": self.openid or "",
            "X-Api-Version": "184",
            "Language": "en_US",
        }

    async def post_mobile(self, path: str, data: dict[str, Any]) -> dict[str, Any] | None:
        resp = await self.http.post(path, headers=self.mobile_headers(), data=data)
        resp.raise_for_status()
        body = resp.json()
        ok = str(body.get("message", "")).lower() == "success" or body.get("code") == 200
        if not ok:
            raise RuntimeError(f"Allybot API error on {path}: {body.get('message')} ({body.get('code')})")
        value = body.get("data")
        return value if isinstance(value, dict) else None

    async def get_device_status(self, fleet_robot_id: str) -> dict[str, Any] | None:
        return await self.post_mobile(
            "/fleetapi/device/usestatus",
            {"openid": self.openid, "token": self.mobile_token, "id": fleet_robot_id},
        )

    async def get_active_map(self, fleet_robot_id: str) -> dict[str, Any] | None:
        return await self.post_mobile(
            "/fleetapi/device/usemap",
            {"openid": self.openid, "token": self.mobile_token, "id": fleet_robot_id},
        )


async def sample_ws(
    base_url: str,
    openid: str,
    token: str,
    robot_id: str,
    fleet_robot_id: str,
    seconds: float,
) -> dict[str, Any]:
    ws_base = base_url.rstrip("/").replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_base}/fleetapi/websocketapp/{openid}/{token}"
    state: dict[str, Any] = {"ws": "not_seen"}
    deadline = time.time() + seconds
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            while time.time() < deadline:
                timeout = max(0.1, deadline - time.time())
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
                except TimeoutError:
                    break
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    body = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if body.get("type") == "device_position":
                    try:
                        inner = json.loads(body.get("msg") or "{}")
                    except json.JSONDecodeError:
                        continue
                    if inner.get("serial") != fleet_robot_id:
                        continue
                    pos = inner.get("position") or {}
                    ori = inner.get("orientation") or {}
                    state.update(
                        {
                            "ws": "seen",
                            "x": float(pos["x"]),
                            "y": float(pos["y"]),
                            "yaw": quaternion_to_yaw(
                                float(ori.get("x", 0)),
                                float(ori.get("y", 0)),
                                float(ori.get("z", 0)),
                                float(ori.get("w", 1)),
                            ),
                            "speed": float(inner.get("speed", 0)),
                        }
                    )
                    break
                if body.get("type") == "devicestatus":
                    data = body.get("data") or {}
                    if data.get("id") == fleet_robot_id:
                        state["ws"] = "seen"
    return state


async def diagnose(
    repo_root: Path,
    robot_id: str | None,
    all_robots: bool,
    ws_seconds: float,
) -> list[dict[str, Any]]:
    config_path = repo_root / "allybot_connector" / "config" / "my_fleet.local.yaml"
    env_path = repo_root / "allybot_connector" / "config" / ".env.local"
    config = load_config(config_path, env_path)
    connector_config = config.get("connector_config") or {}
    fleet = select_fleet(config, robot_id, all_robots)

    rows: list[dict[str, Any]] = []
    base_row = {
        "provider": "Allybot",
        "configured_in_yaml": True,
        "allybot_login": "not_checked",
        "rest_jwt_present": None,
    }
    required = ["base_url", "username", "password"]
    missing = [key for key in required if is_placeholder(connector_config.get(key))]
    if missing:
        for robot in fleet:
            rows.append(
                {
                    **base_row,
                    "robot_id": robot.get("robot_id"),
                    "fleet_robot_id": robot.get("fleet_robot_id"),
                    "fleet_robot_id_masked": mask(robot.get("fleet_robot_id")),
                    "validated": "pending_credentials",
                    "observations": f"Missing/placeholder Allybot config: {', '.join(missing)}",
                }
            )
        return rows

    client = AllybotReadOnlyClient(connector_config)
    login_ok = False
    login_error = ""
    try:
        try:
            await client.login()
            login_ok = True
        except Exception as exc:
            login_error = exception_summary(exc)

        for robot in fleet:
            fleet_robot_id = str(robot.get("fleet_robot_id") or "")
            row = {
                **base_row,
                "robot_id": robot.get("robot_id"),
                "fleet_robot_id": fleet_robot_id,
                "fleet_robot_id_masked": mask(fleet_robot_id),
                "allybot_login": "OK" if login_ok else "FAIL",
                "rest_jwt_present": bool(client.rest_token),
            }
            if not login_ok:
                row.update({"validated": "failed", "observations": f"Allybot login failed: {login_error}"})
                rows.append(row)
                continue

            status = None
            try:
                status = await client.get_device_status(fleet_robot_id)
            except Exception as exc:
                append_observation(row, f"device_status failed: {exception_summary(exc)}")
            row["device_status_present"] = bool(status)
            if status:
                row.update(
                    {
                        "battery": status.get("battery"),
                        "work_status": status.get("work_status"),
                        "have_task_running": status.get("haveTaskRunning"),
                        "fresh_water": status.get("freshWater"),
                        "sewage_water": status.get("sewageWater"),
                        "water": f"fresh={status.get('freshWater')}; sewage={status.get('sewageWater')}",
                        "visible_name": status.get("name") or status.get("robotName"),
                    }
                )

            active_map = None
            try:
                active_map = await client.get_active_map(fleet_robot_id)
            except Exception as exc:
                append_observation(row, f"active_map failed: {exception_summary(exc)}")
            row["active_map_present"] = bool(active_map)
            if active_map:
                mapinfo = active_map.get("mapinfo") or {}
                row.update(
                    {
                        "map_id": mapinfo.get("id"),
                        "map_name": mapinfo.get("name"),
                        "resolution": mapinfo.get("resolution"),
                        "origin": mapinfo.get("original"),
                        "has_image_url": bool(active_map.get("image_url")),
                    }
                )

            if ws_seconds > 0 and client.openid and client.mobile_token:
                try:
                    ws_state = await sample_ws(
                        connector_config["base_url"],
                        client.openid,
                        client.mobile_token,
                        str(robot.get("robot_id")),
                        fleet_robot_id,
                        ws_seconds,
                    )
                except Exception as exc:
                    ws_state = {"ws": "failed"}
                    append_observation(row, f"websocket failed: {exception_summary(exc)}")
                row.update(ws_state)
                if {"x", "y", "yaw"} <= ws_state.keys():
                    row["pose"] = f"x={ws_state['x']}; y={ws_state['y']}; yaw={ws_state['yaw']}"
            else:
                row["ws"] = "skipped"

            row["validated"] = "yaml_only"
            rows.append(row)
    finally:
        await client.close()
    return rows
