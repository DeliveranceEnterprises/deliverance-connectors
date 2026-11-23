"""CLI entrypoint for read-only robot diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path
from typing import Any

from .common import ProviderNotConfigured, append_observation, normalize_validation_statuses
from .inorbit import describe_robots, infer_provider
from .providers import allybot, autoxing, keenon


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INORBIT_WORKSPACE = Path.home() / "INORBIT"
PROVIDERS = {
    "allybot": allybot.diagnose,
    "keenon": keenon.diagnose,
    "autoxing": autoxing.diagnose,
}


INVENTORY_COLUMNS = [
    "robot_id",
    "provider",
    "fleet_robot_id_masked",
    "configured_in_yaml",
    "exists_in_inorbit",
    "online",
    "last_seen",
    "location_tags",
    "active_map_present",
    "pose",
    "battery",
    "work_status",
    "water",
    "ws",
    "validated",
    "observations",
]


# Keys never written to public outputs (files and --format json/markdown):
# vendor ids that identify the robot or the account, and vendor map names and
# robot names, which are private to the customer.
PRIVATE_KEYS = frozenset(
    {
        "fleet_robot_id",
        "business_id",  # AutoXing account
        "store_id",  # Keenon store
        "openid",  # Allybot account
        "map_id",
        "map_name",
        "visible_name",
        "raw_line",
    }
)


def public_row(row: dict[str, Any]) -> dict[str, Any]:
    clean = {key: value for key, value in row.items() if key not in PRIVATE_KEYS}
    clean.setdefault("location_tags", "not_available_with_cli")
    return clean


def merge_inorbit(rows: list[dict[str, Any]], inorbit: dict[str, dict[str, Any]], include_related: bool) -> list[dict[str, Any]]:
    seen = {row.get("robot_id") for row in rows}
    for row in rows:
        robot_id = row.get("robot_id")
        io_robot = inorbit.get(str(robot_id))
        row["exists_in_inorbit"] = io_robot is not None
        if io_robot:
            row["visible_name"] = row.get("visible_name") or io_robot.get("visible_name")
            row["online"] = io_robot.get("online")
            row["last_seen"] = io_robot.get("last_seen")
            row["agent_version"] = io_robot.get("agent_version")

    if include_related:
        for robot_id, io_robot in inorbit.items():
            if robot_id in seen:
                continue
            provider, note = infer_provider(io_robot)
            if provider not in {"Allybot", "Keenon", "AutoXing"}:
                continue
            rows.append(
                {
                    "robot_id": robot_id,
                    "provider": provider,
                    "configured_in_yaml": False,
                    "exists_in_inorbit": True,
                    "online": io_robot.get("online"),
                    "last_seen": io_robot.get("last_seen"),
                    "agent_version": io_robot.get("agent_version"),
                    "visible_name": io_robot.get("visible_name"),
                    "validated": "pending",
                    "observations": note,
                }
            )
    return rows


def markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").replace("|", "\\|")


def render_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Robot Inventory",
        "",
        "| " + " | ".join(INVENTORY_COLUMNS) + " |",
        "| " + " | ".join("---" for _ in INVENTORY_COLUMNS) + " |",
    ]
    for row in rows:
        clean = public_row(row)
        lines.append("| " + " | ".join(markdown_cell(clean.get(col)) for col in INVENTORY_COLUMNS) + " |")
    return "\n".join(lines) + "\n"


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(rows), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVENTORY_COLUMNS)
        writer.writeheader()
        for row in rows:
            clean = public_row(row)
            writer.writerow({col: clean.get(col) for col in INVENTORY_COLUMNS})


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([public_row(row) for row in rows], indent=2, default=str), encoding="utf-8")


def print_human(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        print(f"\n== {row.get('robot_id')} ==")
        for key in [
            "provider",
            "configured_in_yaml",
            "fleet_robot_id_masked",
            "exists_in_inorbit",
            "online",
            "last_seen",
            "agent_version",
            "allybot_login",
            "rest_jwt_present",
            "device_status_present",
            "battery",
            "work_status",
            "have_task_running",
            "water",
            "active_map_present",
            "resolution",
            "origin",
            "has_image_url",
            "ws",
            "pose",
            "speed",
            "validated",
            "observations",
        ]:
            if key in row:
                print(f"{key}: {row.get(key)}")


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Read-only robot diagnostics and inventory")
    parser.add_argument("--provider", choices=["all", *PROVIDERS.keys()], default="allybot")
    parser.add_argument("--robot-id")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--ws-seconds", type=float, default=0.0)
    parser.add_argument(
        "--allow-login",
        action="store_true",
        help=(
            "Allow providers that keep one session per account (Allybot) to log in. "
            "Logging in ends the account's other sessions: use a dedicated account. "
            f"Same as {allybot.ALLOW_LOGIN_ENV}=1."
        ),
    )
    parser.add_argument("--no-inorbit", action="store_true")
    parser.add_argument("--include-inorbit-related", action="store_true")
    parser.add_argument("--inorbit-workspace", default=str(DEFAULT_INORBIT_WORKSPACE))
    parser.add_argument("--markdown")
    parser.add_argument("--csv")
    parser.add_argument("--json")
    parser.add_argument("--format", choices=["human", "json", "markdown"], default="human")
    args = parser.parse_args()

    provider_names = list(PROVIDERS) if args.provider == "all" else [args.provider]
    rows: list[dict[str, Any]] = []
    not_configured = 0
    for provider_name in provider_names:
        try:
            rows.extend(
                await PROVIDERS[provider_name](
                    REPO_ROOT,
                    args.robot_id,
                    args.all,
                    args.ws_seconds,
                    allow_login=args.allow_login,
                )
            )
        except ProviderNotConfigured as exc:
            not_configured += 1
            print(f"[{provider_name}] not configured ({exc}), skipping", file=sys.stderr)
    if not_configured == len(provider_names):
        print("No requested provider is configured", file=sys.stderr)
        return 1

    if not args.no_inorbit:
        inorbit, error = describe_robots(Path(args.inorbit_workspace))
        rows = merge_inorbit(rows, inorbit, args.include_inorbit_related)
        if error:
            for row in rows:
                append_observation(row, f"InOrbit CLI unavailable: {error}")

    rows = normalize_validation_statuses(rows)
    rows = sorted(rows, key=lambda item: str(item.get("robot_id")))

    if args.markdown:
        write_markdown(Path(args.markdown), rows)
    if args.csv:
        write_csv(Path(args.csv), rows)
    if args.json:
        write_json(Path(args.json), rows)

    if args.format == "json":
        print(json.dumps([public_row(row) for row in rows], indent=2, default=str))
    elif args.format == "markdown":
        print(render_markdown(rows), end="")
    else:
        print_human(rows)
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
