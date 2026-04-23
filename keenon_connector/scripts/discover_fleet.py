#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT
"""Print all Keenon stores and their robots to help populate my_fleet.yaml.

Usage (from the keenon_connector directory):
    source config/.env && uv run python scripts/discover_fleet.py
"""

import os
import sys

import httpx

API_DOMAIN = os.environ.get("INORBIT_KEENON_API_DOMAIN", "https://es.robotkeenon.com")
CLIENT_ID = os.environ.get("INORBIT_KEENON_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("INORBIT_KEENON_CLIENT_SECRET", "")

ONLINE_TYPE = {2: "wifi", 3: "3G", 4: "4G", 5: "unknown"}


def get_token(client: httpx.Client) -> str:
    resp = client.post(
        "/api/open/oauth/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
    )
    resp.raise_for_status()
    body = resp.json()
    if "access_token" not in body:
        print(f"Token error: {body}", file=sys.stderr)
        sys.exit(1)
    return body["access_token"]


def api_get(client: httpx.Client, token: str, path: str, **params) -> list | dict:
    resp = client.get(path, headers={"Authorization": f"bearer {token}"}, params=params)
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 610000:
        print(f"API error on {path}: {body}", file=sys.stderr)
        return []
    return body.get("data", [])


def main() -> None:
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Set INORBIT_KEENON_CLIENT_ID and INORBIT_KEENON_CLIENT_SECRET", file=sys.stderr)
        sys.exit(1)

    with httpx.Client(base_url=API_DOMAIN, timeout=30) as client:
        token = get_token(client)
        print(f"Token OK\n")

        stores = api_get(client, token, "/api/open/data/v1/store/list")
        if not stores:
            print("No stores found.")
            return

        print(f"Found {len(stores)} store(s):\n")
        fleet_entries = []

        for store in stores:
            store_id = store["storeId"]
            store_name = store.get("storeName", "")
            print(f"  Store: {store_name!r}  (storeId={store_id})")

            robots = api_get(
                client, token, "/api/open/data/v1/store/robot/list", storeId=store_id
            )
            if not isinstance(robots, list):
                robots = []

            if not robots:
                print("    (no robots)\n")
                continue

            for robot in robots:
                rid = robot.get("robotId", "?")
                name = robot.get("robotName", "")
                model = robot.get("robotModel", "?")
                power = robot.get("power", "?")
                online = robot.get("onlineStatus", 0)
                net = ONLINE_TYPE.get(robot.get("onlineType", 5), "unknown")
                status = "ONLINE" if online == 1 else "offline"
                print(f"    [{status}] {name!r}  robotId={rid}  model={model}  "
                      f"battery={power}%  network={net}")
                slug = name.lower().replace(" ", "-").replace(":", "") or rid.replace(":", "")
                fleet_entries.append(
                    f"  - robot_id: keenon-{slug}\n"
                    f"    fleet_robot_id: \"{rid}\"\n"
                    f"    store_id: {store_id}"
                )
            print()

        if fleet_entries:
            print("=" * 60)
            print("fleet.yaml snippet — paste into config/my_fleet.yaml:\n")
            print("fleet:")
            for entry in fleet_entries:
                print(entry)


if __name__ == "__main__":
    main()
