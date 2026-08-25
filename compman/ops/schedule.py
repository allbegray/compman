from __future__ import annotations

import platform
from datetime import datetime, timezone
from typing import Any, Protocol

import typer

from compman.config import Config, sanitize_project_name
from compman.errors import CommandError
from compman.i18n import t
from compman.scheduling import (
    JobRecord,
    cron_expr,
    crontab_status,
    load_registry,
    parse_cadence,
    pick_scheduler,
    resolve_executable,
    save_registry,
)
from compman.scheduling.cadence import EXACTLY_ONE_ERROR, WEEKDAY_NAMES
from compman.scheduling.crontab import CrontabAdapter
from compman.scheduling.launchd import LaunchdAdapter
from compman.scheduling.registry import Runner
from compman.scheduling.schtasks import SchtasksAdapter
from compman.scheduling.systemd import SystemdAdapter


class SchedulerAdapter(Protocol):
    def install(self, record: JobRecord, runner: Runner = ...) -> None: ...

    def remove(self, name: str, runner: Runner = ...) -> None: ...

    def exists(self, name: str, runner: Runner = ...) -> bool: ...


_ADAPTER_TYPES: dict[str, type[SchedulerAdapter]] = {
    "launchd": LaunchdAdapter,
    "systemd": SystemdAdapter,
    "cron": CrontabAdapter,
    "schtasks": SchtasksAdapter,
}


def _adapter_for(platform_name: str) -> SchedulerAdapter:
    return _ADAPTER_TYPES[platform_name]()


def _cadence_summary(job: dict[str, Any]) -> str:
    kind = job["kind"]
    if kind == "interval":
        minutes = job["minutes"]
        if minutes % 60 == 0 and minutes >= 60:
            return f"every {minutes // 60}h"
        return f"every {minutes}m"
    if kind == "daily":
        return f"daily at {job['time']}"
    weekday = WEEKDAY_NAMES[job["weekday"]]
    return f"weekly on {weekday} at {job['time']}"


def add_schedule(
    config: Config,
    *,
    every: str | None = None,
    daily: str | None = None,
    weekly: str | None = None,
    no_stop: bool = False,
    level: int = 6,
    profile: str | None = None,
    name: str | None = None,
    scheduler: str | None = None,
) -> JobRecord:
    try:
        cadence = parse_cadence(every, daily, weekly)
    except ValueError as exc:
        if str(exc) == EXACTLY_ONE_ERROR:
            raise CommandError(t("msg.schedule.cadence_conflict")) from exc
        value = next(value for value in (every, daily, weekly) if value is not None)
        raise CommandError(t("msg.schedule.cadence_invalid", value=value, reason=exc)) from exc

    system = platform.system().lower()
    if scheduler is not None and system != "linux":
        raise CommandError(t("msg.schedule.force_unsupported"))
    try:
        platform_name = pick_scheduler(system, scheduler)
    except ValueError as exc:
        raise CommandError(t("msg.schedule.unsupported_platform", system=system)) from exc

    try:
        executable = resolve_executable()
    except ValueError as exc:
        raise CommandError(t("msg.schedule.executable_not_found")) from exc

    job_name = sanitize_project_name(name or f"{config.name}.volume")
    config_path = str(config.source_path or config.root_dir / "compman.yml")
    args = [executable, "-c", config_path, "volume", "backup"]
    if no_stop:
        args.append("--no-stop")
    if level != 6:
        args.extend(["-z", str(level)])
    if profile:
        args.extend(["--profile", profile])

    record = JobRecord(
        name=job_name,
        platform=platform_name,
        kind=cadence.kind,
        minutes=cadence.minutes,
        time=cadence.time,
        weekday=cadence.weekday,
        workdir=str(config.root_dir),
        config_path=config_path,
        args=args,
        log_path=str(config.backup_dir / "schedule.log"),
        created=datetime.now(timezone.utc).isoformat(),
    )

    if platform_name == "cron":
        try:
            cron_expr(cadence)
        except ValueError as exc:
            raise CommandError(t("msg.schedule.cron_interval", value=every)) from exc
        available, detail = crontab_status()
        if not available:
            raise CommandError(t("msg.schedule.no_mechanism", detail=detail))

    registry = load_registry()
    existing = registry["jobs"].get(job_name)
    if existing is not None:
        raise CommandError(
            t("msg.schedule.exists", name=job_name, path=existing["config_path"])
        )

    _adapter_for(platform_name).install(record)
    registry["jobs"][job_name] = record
    save_registry(registry)
    typer.echo(t("msg.schedule.added", name=job_name, platform=platform_name))
    return record


def list_schedules() -> None:
    jobs = load_registry()["jobs"]
    if not jobs:
        typer.echo(t("msg.schedule.list_empty"))
        return
    typer.echo(t("msg.schedule.list_header"))
    for job_name, job in jobs.items():
        line = f"{job_name} ({job['platform']}, {_cadence_summary(job)}) - {job['config_path']}"
        if not _adapter_for(job["platform"]).exists(job_name):
            line += f" {t('msg.schedule.missing')}"
        typer.echo(line)


def remove_schedule(name: str) -> None:
    registry = load_registry()
    job = registry["jobs"].get(name)
    if job is None:
        raise CommandError(t("msg.schedule.not_found", name=name))
    adapter = _adapter_for(job["platform"])
    if not adapter.exists(name):
        typer.echo(t("msg.schedule.already_gone", name=name))
    adapter.remove(name)
    del registry["jobs"][name]
    save_registry(registry)
    typer.echo(t("msg.schedule.removed", name=name))
