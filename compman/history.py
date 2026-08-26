"""Activity journal: an append-only JSONL record of deploy and backup events.

The journal lives next to the schedule registry (``%APPDATA%\\compman`` when
the ``APPDATA`` environment variable is set, otherwise ``~/.config/compman``)
so every compman installation — including scheduled, unattended jobs — shares
one timeline. Writes raise :class:`OSError` so callers decide whether to warn
and continue; reads never fail on a damaged file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from compman.ops.common import utc_now_iso
from compman.scheduling.registry import registry_dir

HISTORY_VERSION = 1


def history_path() -> Path:
    """Return the JSONL journal path beside the schedule registry."""
    return registry_dir() / "history.jsonl"


def append(action: str, **fields: Any) -> bool:
    """Append one entry as a single JSON line; returns True.

    Raises OSError when the write fails; callers decide whether to
    warn-and-continue or propagate.
    """
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {"ts": utc_now_iso(), "action": action, **fields}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return True


def entries(limit: int | None = None) -> list[dict[str, Any]]:
    """Return journal entries newest-first; malformed lines are skipped."""
    path = history_path()
    if not path.is_file():
        return []
    found: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            found.append(parsed)
    if limit is not None:
        found = found[-limit:]
    found.reverse()
    return found


def envelope(limit: int | None = None) -> dict[str, Any]:
    """Wrap entries in the house ``--json`` payload shape."""
    return {
        "schema_version": HISTORY_VERSION,
        "generated_at": utc_now_iso(),
        "entries": entries(limit),
    }
