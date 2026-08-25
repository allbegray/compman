from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import typer

from compman.i18n import t
from compman.scheduling.cadence import Cadence, CadenceKind

REGISTRY_VERSION = 1

# Shared subprocess seam for the scheduling adapters; tests inject recording fakes.
Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class JobRecord:
    name: str
    platform: str
    kind: CadenceKind
    minutes: int | None
    time: str | None
    weekday: int | None
    workdir: str
    config_path: str
    args: list[str]
    log_path: str
    path_env: str
    created: str

    def cadence(self) -> Cadence:
        return Cadence(kind=self.kind, minutes=self.minutes, time=self.time, weekday=self.weekday)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobRecord:
        return cls(**data)


def registry_path() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "compman" / "schedules.json"
    return Path.home() / ".config" / "compman" / "schedules.json"


def _empty_registry() -> dict[str, Any]:
    return {"version": REGISTRY_VERSION, "jobs": {}}


def load_registry() -> dict[str, Any]:
    path = registry_path()
    if not path.is_file():
        return _empty_registry()
    data: Any = None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), dict):
        backup = path.with_name(path.name + ".bak")
        path.replace(backup)
        typer.echo(
            t("msg.schedule_registry_corrupt", path=path, backup=backup),
            err=True,
        )
        return _empty_registry()
    version = data.get("version")
    return {
        "version": version if isinstance(version, int) else REGISTRY_VERSION,
        "jobs": data["jobs"],
    }


def save_registry(registry: dict[str, Any]) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": registry.get("version", REGISTRY_VERSION),
        "jobs": {
            name: value.to_dict() if isinstance(value, JobRecord) else value
            for name, value in registry.get("jobs", {}).items()
        },
    }
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
