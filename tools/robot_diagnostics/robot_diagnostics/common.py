"""Shared helpers for read-only robot diagnostics."""

from __future__ import annotations

import re
from typing import Any


VALIDATION_STATES = {
    "yaml_only",
    "pending_credentials",
    "source_partial",
    "source_ok",
    "inorbit_ok",
    "full_flow_ok",
    "failed",
}

def sanitize_text(value: Any) -> str:
    """Return a printable message with obvious secrets redacted."""
    text = str(value)
    text = re.sub(
        r"(?i)(token|api[_-]?key|password|secret|authorization)(\s*[=:]\s*)([^\s,;]+)",
        r"\1\2<redacted>",
        text,
    )
    text = re.sub(r"(?i)(/fleetapi/websocketapp/)[^/\s]+/[^/\s]+", r"\1<redacted>/<redacted>", text)
    text = re.sub(r"(?i)([?&](?:token|api[_-]?key|password|secret)=)[^&\s]+", r"\1<redacted>", text)
    text = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1<redacted>", text)
    return text


def exception_summary(exc: BaseException) -> str:
    """Return a short, sanitized exception message."""
    message = str(exc).splitlines()[-1] if str(exc).splitlines() else exc.__class__.__name__
    return sanitize_text(message)


def append_observation(row: dict[str, Any], message: Any) -> None:
    clean = sanitize_text(message)
    row["observations"] = f"{row.get('observations')}; {clean}" if row.get("observations") else clean


def classify_validation_status(row: dict[str, Any]) -> str:
    """Classify validation without implying robot control or operational success."""
    current = row.get("validated")
    if current in {"failed", "pending_credentials"}:
        return str(current)

    source_signals = [
        bool(row.get("device_status_present")),
        bool(row.get("active_map_present")),
        bool(row.get("pose")),
        row.get("ws") == "seen",
    ]
    source_count = sum(source_signals)
    source_ok = bool(row.get("device_status_present")) and bool(row.get("active_map_present"))
    inorbit_ok = row.get("exists_in_inorbit") is True and row.get("online") is True

    if source_ok and inorbit_ok:
        return "full_flow_ok"
    if inorbit_ok:
        return "inorbit_ok"
    if source_ok:
        return "source_ok"
    if source_count:
        return "source_partial"
    return "yaml_only"


def normalize_validation_statuses(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        row["validated"] = classify_validation_status(row)
    return rows
