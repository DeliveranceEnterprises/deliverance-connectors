#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pyezvizapi>=1.0.4",
#     "python-dotenv>=1.0",
#     "requests>=2.31",
# ]
# ///
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT
"""Verify an Ezviz camera is reachable through pyezvizapi.

Steps:
  1. Load credentials from config/.env (or env vars).
  2. Log in to the Ezviz Cloud.
  3. List every device on the account.
  4. Pick a target serial (CLI arg, env var, or the first listed device).
  5. Print device info, last alarm, and capture a snapshot to disk.

Run from the connector directory:
    uv run scripts/test_camera.py
    uv run scripts/test_camera.py <serial>
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime
from typing import Any

from dotenv import load_dotenv

# pyezvizapi is sync — fine for a one-shot diagnostic.
try:
    from pyezvizapi import EzvizClient  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — fallback if module layout differs
    from pyezvizapi.client import EzvizClient  # type: ignore[import-not-found]


REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
ENV_PATH = REPO_DIR / "config" / ".env"
SNAPSHOT_DIR = REPO_DIR / "snapshots"


def die(msg: str, code: int = 1) -> None:
    print(f"\033[31mERROR\033[0m  {msg}", file=sys.stderr)
    sys.exit(code)


def info(msg: str) -> None:
    print(f"\033[36m·\033[0m {msg}")


def ok(msg: str) -> None:
    print(f"\033[32m✓\033[0m {msg}")


def banner(msg: str) -> None:
    print(f"\n\033[1m{msg}\033[0m")
    print("─" * len(msg))


def mask(value: str | None) -> str:
    if not value:
        return "<unset>"
    return value[0] + "***" + value[-1] if len(value) > 2 else "***"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "serial",
        nargs="?",
        help="Camera serial number (overrides INORBIT_EZVIZ_DEVICE_SERIAL).",
    )
    parser.add_argument(
        "--skip-snapshot",
        action="store_true",
        help="Don't try to capture a snapshot.",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Load env
    # ------------------------------------------------------------------
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
        info(f"loaded env from {ENV_PATH.relative_to(REPO_DIR)}")
    else:
        info(f"no {ENV_PATH.relative_to(REPO_DIR)} — relying on shell env vars")

    account = os.getenv("INORBIT_EZVIZ_ACCOUNT")
    password = os.getenv("INORBIT_EZVIZ_PASSWORD")
    region = os.getenv("INORBIT_EZVIZ_REGION_URL", "apiieu.ezvizlife.com")
    sms_code = os.getenv("INORBIT_EZVIZ_SMS_CODE")
    target_serial = args.serial or os.getenv("INORBIT_EZVIZ_DEVICE_SERIAL") or ""

    if not account or account.startswith("your-"):
        die("INORBIT_EZVIZ_ACCOUNT is missing or still the placeholder.")
    if not password or password.startswith("your-"):
        die("INORBIT_EZVIZ_PASSWORD is missing or still the placeholder.")

    banner("Ezviz cloud connection")
    info(f"account:     {account}")
    info(f"password:    {mask(password)}")
    info(f"region:      {region}")
    info(f"sms_code:    {mask(sms_code) if sms_code else '<none>'}")

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------
    client = EzvizClient(account=account, password=password, url=region)
    try:
        # pyezvizapi exposes login() in modern versions.
        if hasattr(client, "login"):
            token = client.login(sms_code=int(sms_code)) if sms_code else client.login()
        else:
            token = client._login(smscode=int(sms_code)) if sms_code else client._login()
    except Exception as exc:  # noqa: BLE001 — surface anything during diagnostics
        die(f"login failed: {type(exc).__name__}: {exc}")

    ok("logged in successfully")
    if isinstance(token, dict):
        # The token dict contains session_id + rf_session_id; don't print raw secrets.
        info(f"token keys: {sorted(token.keys())}")

    # ------------------------------------------------------------------
    # List devices
    # ------------------------------------------------------------------
    banner("Devices on this account")
    try:
        devices = client.load_devices(refresh=True)
    except Exception as exc:  # noqa: BLE001
        die(f"load_devices failed: {type(exc).__name__}: {exc}")

    if not devices:
        die("no devices returned by the Ezviz cloud — is the account correct?")

    serials = list(devices.keys()) if isinstance(devices, dict) else [
        d.get("serial", "?") for d in devices
    ]
    ok(f"found {len(serials)} device(s): {serials}")

    if isinstance(devices, dict):
        for serial, dev in devices.items():
            name = dev.get("name") or dev.get("deviceName") or "?"
            status = dev.get("status")
            online = "online" if status == 1 else f"status={status}"
            print(f"    [{serial}] {name}  ({online})")

    # ------------------------------------------------------------------
    # Pick a target serial
    # ------------------------------------------------------------------
    if not target_serial:
        target_serial = serials[0]
        info(f"no serial specified — defaulting to {target_serial}")
    elif target_serial not in serials:
        die(f"serial {target_serial!r} not found in account devices: {serials}")

    # ------------------------------------------------------------------
    # Device info
    # ------------------------------------------------------------------
    banner(f"Device info — {target_serial}")
    try:
        details = client.get_device_infos(target_serial)
    except Exception as exc:  # noqa: BLE001
        die(f"get_device_infos failed: {type(exc).__name__}: {exc}")

    interesting = {
        "name": details.get("name"),
        "category": details.get("category"),
        "subcategory": details.get("subcategory"),
        "version": details.get("version"),
        "status": details.get("status"),
        "battery_level": details.get("battery_level"),
        "signal": details.get("signal"),
        "Motion_Trigger": details.get("Motion_Trigger"),
        "Seconds_Last_Trigger": details.get("Seconds_Last_Trigger"),
        "last_alarm_time": details.get("last_alarm_time"),
    }
    for key, value in interesting.items():
        if value is not None:
            print(f"    {key:<22} {value}")
    ok("device info retrieved")

    # ------------------------------------------------------------------
    # Last alarm
    # ------------------------------------------------------------------
    banner("Last alarm")
    try:
        alarms = client.get_alarminfo(target_serial, limit=1)
        print(json.dumps(_safe(alarms), indent=2, default=str)[:1200])
        ok("get_alarminfo returned")
    except Exception as exc:  # noqa: BLE001
        info(f"get_alarminfo skipped: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------
    if args.skip_snapshot:
        info("snapshot capture skipped (--skip-snapshot)")
        return

    banner(f"Snapshot — {target_serial}")
    try:
        snap = client.capture_picture(target_serial, channel=1)
    except Exception as exc:  # noqa: BLE001
        die(f"capture_picture failed: {type(exc).__name__}: {exc}")

    info("capture_picture response:")
    print(json.dumps(_safe(snap), indent=2, default=str)[:1200])

    url = _extract_url(snap)
    if not url:
        die("no snapshot URL found in capture_picture response — inspect output above")

    SNAPSHOT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    image_path = SNAPSHOT_DIR / f"{target_serial}-{ts}.jpg"

    # Stream the image bytes to disk.
    import requests

    try:
        with requests.get(url, stream=True, timeout=15) as resp:
            resp.raise_for_status()
            with image_path.open("wb") as fh:
                for chunk in resp.iter_content(8192):
                    fh.write(chunk)
    except Exception as exc:  # noqa: BLE001
        die(f"failed to download snapshot from {url!r}: {exc}")

    size_kb = image_path.stat().st_size / 1024
    ok(f"snapshot saved → {image_path.relative_to(REPO_DIR)}  ({size_kb:.1f} KB)")
    print(f"\nopen it with:  open {image_path}")


def _safe(value: Any) -> Any:
    """Best-effort conversion for JSON dump (handles model objects)."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__") and not isinstance(value, (str, bytes)):
        return {k: _safe(v) for k, v in vars(value).items() if not k.startswith("_")}
    if isinstance(value, dict):
        return {k: _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    return value


def _extract_url(payload: Any) -> str | None:
    """capture_picture's payload shape isn't formally documented — probe likely keys."""
    if isinstance(payload, str) and payload.startswith("http"):
        return payload
    if isinstance(payload, dict):
        for key in ("pic_url", "picUrl", "url", "imageUrl", "image_url"):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        for value in payload.values():
            found = _extract_url(value)
            if found:
                return found
    return None


if __name__ == "__main__":
    main()
