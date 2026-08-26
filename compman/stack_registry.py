"""Multi-stack registry: a name -> config-dir map so any command can target a
registered deployment with the root ``--stack NAME`` option.

The JSON file lives next to the schedules registry (same APPDATA-aware base
directory). Concurrency choice: no advisory lock. Every write stages under a
unique temp name and lands via ``os.replace``, so readers only ever see one
complete snapshot; concurrent recorders are last-writer-wins on the whole
mapping, which is acceptable for advisory bookkeeping data.
"""

from __future__ import annotations

import json
import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import typer

from compman.config import sanitize_project_name
from compman.i18n import t
from compman.scheduling.registry import registry_dir, unique_tmp_path

STACKS_VERSION = 1

# Root ``--stack NAME`` selection for the current invocation, mirroring how
# compman.i18n carries the chosen language across command boundaries.
_CURRENT_STACK: ContextVar[str | None] = ContextVar("compman_stack", default=None)


def set_current_stack(name: str) -> None:
    """Record the ``--stack NAME`` value parsed by the root callback."""
    _CURRENT_STACK.set(name)


def current_stack() -> str | None:
    """Return the stack name selected via the root ``--stack`` option."""
    return _CURRENT_STACK.get()


def stacks_path() -> Path:
    return registry_dir() / "stacks.json"


def _load_entries() -> dict[str, str]:
    path = stacks_path()
    if not path.is_file():
        return {}
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = None
    stacks = data.get("stacks") if isinstance(data, dict) else None
    if not isinstance(stacks, dict):
        backup = path.with_name(path.name + ".bak")
        path.replace(backup)
        typer.echo(
            t("msg.stacks_registry_corrupt", path=path, backup=backup),
            err=True,
        )
        return {}
    # Values must be directory strings; anything else is treated as absent.
    return {str(key): value for key, value in stacks.items() if isinstance(value, str)}


def _save(stacks: dict[str, str]) -> None:
    path = stacks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = unique_tmp_path(path)
    try:
        tmp.write_text(
            json.dumps({"version": STACKS_VERSION, "stacks": stacks}, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def record(name: str, directory: str) -> None:
    """Add or update the entry for stack ``name`` pointing at ``directory``."""
    stacks = _load_entries()
    stacks[sanitize_project_name(name)] = directory
    _save(stacks)


def remove(name: str) -> bool:
    """Drop the entry for ``name``; return False when it was not registered."""
    key = sanitize_project_name(name)
    stacks = _load_entries()
    if key not in stacks:
        return False
    del stacks[key]
    _save(stacks)
    return True


def entries() -> dict[str, str]:
    """Return all registered stacks sorted by name."""
    return dict(sorted(_load_entries().items()))


def resolve(name: str) -> Path | None:
    """Return the registered config directory for ``name``, or None."""
    directory = _load_entries().get(sanitize_project_name(name))
    return Path(directory) if directory is not None else None
