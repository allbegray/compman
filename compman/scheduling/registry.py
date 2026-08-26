from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import typer

from compman.errors import CommandError
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
    # Absent in pre-monthly records; defaults keep old schedules.json loadable.
    day: int | None = None

    def cadence(self) -> Cadence:
        return Cadence(
            kind=self.kind,
            minutes=self.minutes,
            time=self.time,
            weekday=self.weekday,
            day=self.day,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobRecord:
        return cls(**data)


def registry_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "compman"
    return Path.home() / ".config" / "compman"


def registry_path() -> Path:
    return registry_dir() / "schedules.json"


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
    tmp = unique_tmp_path(path)
    try:
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def failure_detail(result: subprocess.CompletedProcess[str]) -> str:
    """Concise one-line rc/stderr summary for a failed scheduler command."""
    stderr = " ".join((result.stderr or "").split())
    if stderr:
        return f"exit {result.returncode}: {stderr}"
    return f"exit {result.returncode}"


def require_success(result: subprocess.CompletedProcess[str], scheduler: str) -> None:
    """Raise CommandError when a scheduler registration subprocess failed."""
    if result.returncode == 0:
        return
    raise CommandError(
        t(
            "msg.schedule_register_failed",
            scheduler=scheduler,
            detail=failure_detail(result),
        )
    )


def unique_tmp_path(target: Path) -> Path:
    """Collision-free staging name so concurrent writers never share a temp file."""
    return target.with_name(f"{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")


@contextmanager
def registry_lock() -> Iterator[None]:
    """Advisory lock serializing load->mutate->save cycles on the schedule registry."""
    path = registry_path()
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
