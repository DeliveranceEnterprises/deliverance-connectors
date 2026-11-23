# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

"""Persistent record of when each AutoXing task started and whether it is closed."""

import json
import logging
import os
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_FILE_NAME = "task_start_ts_cache.json"
DEFAULT_MAX_AGE_S = 7 * 86400
DEFAULT_MAX_ENTRIES = 1000


class TaskStartCache:
    """task_id -> {start_ts (epoch ms), closed} shared by all robots of the poller.

    The missionId is the AutoXing task UUID; what this keeps stable across
    connector restarts is the mission's startTs (AutoXing reports no start
    time). It also remembers which tasks already had their terminal mission
    published, so a finished task still shown in taskObj after a restart is
    not published again.

    Entries older than max_age_s are dropped, and only the newest
    max_entries are kept. Every change is written to disk at once. With
    path=None the cache lives only in memory.
    """

    def __init__(
        self,
        path: str | Path | None,
        max_age_s: float = DEFAULT_MAX_AGE_S,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._path = Path(path) if path is not None else None
        self._max_age_ms = int(max_age_s * 1000)
        self._max_entries = max_entries
        self._entries: dict[str, dict] = self._load()
        if self._prune():
            self._save()

    def __contains__(self, task_id: str) -> bool:
        return task_id in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def start_ts(self, task_id: str, default_ms: int | None = None) -> int:
        """Start time of a task, recording default_ms (or now) the first time it is seen."""
        entry = self._entries.get(task_id)
        if entry is None:
            entry = {"start_ts": int(default_ms if default_ms is not None else time.time() * 1000), "closed": False}
            self._entries[task_id] = entry
            self._prune()
            self._save()
        return entry["start_ts"]

    def is_closed(self, task_id: str) -> bool:
        entry = self._entries.get(task_id)
        return bool(entry and entry.get("closed"))

    def close(self, task_id: str) -> None:
        """Mark a task whose terminal mission has been published."""
        entry = self._entries.get(task_id)
        if entry is None or entry.get("closed"):
            return
        entry["closed"] = True
        self._save()

    def _prune(self) -> bool:
        """Drop expired entries and the oldest beyond max_entries. Returns whether anything went."""
        before = len(self._entries)
        cutoff = int(time.time() * 1000) - self._max_age_ms
        kept = {k: v for k, v in self._entries.items() if v["start_ts"] >= cutoff}
        if len(kept) > self._max_entries:
            newest = sorted(kept.items(), key=lambda kv: kv[1]["start_ts"])[-self._max_entries :]
            kept = dict(newest)
        self._entries = kept
        return len(kept) != before

    def _load(self) -> dict[str, dict]:
        if self._path is None:
            return {}
        try:
            with open(self._path) as f:
                raw = json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as exc:
            logger.warning("Ignoring unreadable task cache %s: %s", self._path, exc)
            return {}
        entries: dict[str, dict] = {}
        if not isinstance(raw, dict):
            return entries
        for task_id, value in raw.items():
            # Older files held a bare start_ts per task.
            if isinstance(value, (int, float)):
                entries[task_id] = {"start_ts": int(value), "closed": False}
            elif isinstance(value, dict) and isinstance(value.get("start_ts"), (int, float)):
                entries[task_id] = {"start_ts": int(value["start_ts"]), "closed": bool(value.get("closed"))}
        return entries

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".task_cache.")
            with os.fdopen(fd, "w") as f:
                json.dump(self._entries, f)
            os.replace(tmp, self._path)
        except Exception as exc:
            logger.warning("Could not save task cache %s: %s", self._path, exc)
