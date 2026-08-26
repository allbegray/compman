from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Protocol

import typer

from compman.config import Config, sanitize_project_name
from compman.errors import CommandError
from compman.i18n import t
from compman.ops.common import utc_now_iso
from compman.scheduling import (
    JobRecord,
    cron_expr,
    crontab_status,
    load_registry,
    parse_cadence,
    pick_scheduler,
    registry_dir,
    registry_lock,
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
    if kind == "monthly":
        return f"monthly on day {job['day']} at {job['time']}"
    weekday = WEEKDAY_NAMES[job["weekday"]]
    return f"weekly on {weekday} at {job['time']}"


def add_schedule(
    config: Config,
    *,
    every: str | None = None,
    daily: str | None = None,
    weekly: str | None = None,
    monthly: str | None = None,
    no_stop: bool = False,
    level: int = 6,
    profile: str | None = None,
    name: str | None = None,
    scheduler: str | None = None,
) -> JobRecord:
    try:
        cadence = parse_cadence(every, daily, weekly, monthly)
    except ValueError as exc:
        if str(exc) == EXACTLY_ONE_ERROR:
            raise CommandError(t("msg.schedule.cadence_conflict")) from exc
        value = next(
            value for value in (every, daily, weekly, monthly) if value is not None
        )
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
    args = [
        executable,
        "schedule",
        "_exec",
        job_name,
        "volume",
        "backup",
        "-c",
        config_path,
    ]
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
        day=cadence.day,
        workdir=str(config.root_dir),
        config_path=config_path,
        args=args,
        log_path=str(registry_dir() / "schedule.log"),
        path_env=os.environ.get("PATH", "/usr/bin:/bin"),
        created=utc_now_iso(),
    )

    if platform_name == "cron":
        try:
            cron_expr(cadence)
        except ValueError as exc:
            raise CommandError(t("msg.schedule.cron_interval", value=every)) from exc
        available, detail = crontab_status()
        if not available:
            raise CommandError(t("msg.schedule.no_mechanism", detail=detail))

    with registry_lock():
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


def list_schedules(json_output: bool = False) -> None:
    jobs = load_registry()["jobs"]
    entries = []
    for job_name, job in jobs.items():
        missing = not _adapter_for(job["platform"]).exists(job_name)
        entry = {
            "name": job_name,
            "platform": job["platform"],
            "cadence": _cadence_summary(job),
            "config_path": job["config_path"],
            "missing": missing,
        }
        entries.append(entry)

    if json_output:
        payload = {
            "schema_version": 1,
            "generated_at": utc_now_iso(),
            "jobs": entries,
        }
        typer.echo(json.dumps(payload))
        return

    if not jobs:
        typer.echo(t("msg.schedule.list_empty"))
        return
    typer.echo(t("msg.schedule.list_header"))
    for entry in entries:
        line = f"{entry['name']} ({entry['platform']}, {entry['cadence']}) - {entry['config_path']}"
        if entry["missing"]:
            line += f" {t('msg.schedule.missing')}"
        typer.echo(line)


def remove_schedule(name: str) -> None:
    with registry_lock():
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


def runs_path(name: str) -> Path:
    """JSONL run-log location for one scheduled job."""
    return registry_dir() / "runs" / f"{name}.jsonl"


def _append_run_event(name: str, event: dict[str, Any]) -> None:
    path = runs_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


def run_tracked_job(name: str, command: list[str], runner: Runner | None = None) -> None:
    """Run a scheduled job's command, appending start/finish events to its run log.

    The child inherits stdio so scheduled output keeps flowing into the
    platform redirect (schedule.log); the process exits with the child's rc.
    """
    _append_run_event(name, {"started_at": utc_now_iso()})
    if runner is None:
        runner = subprocess.run
    started = time.monotonic()
    try:
        completed = runner(command, check=False)
    except KeyboardInterrupt:
        _record_finish(name, started, 130)
        sys.exit(130)
    _record_finish(name, started, completed.returncode)
    sys.exit(completed.returncode)


def _record_finish(name: str, started: float, exit_code: int) -> None:
    _append_run_event(
        name,
        {
            "finished_at": utc_now_iso(),
            "exit_code": exit_code,
            "seconds": round(time.monotonic() - started, 3),
        },
    )


def show_status(name: str) -> None:
    """Print the live install state and last recorded run for one job."""
    job = load_registry()["jobs"].get(name)
    if job is None:
        raise CommandError(t("msg.schedule.not_found", name=name))
    registered = _adapter_for(job["platform"]).exists(name)
    if registered:
        typer.echo(t("msg.schedule.state_registered"))
    else:
        typer.echo(t("msg.schedule.state_missing_entry"))
    _print_last_run(name)


def _print_last_run(name: str) -> None:
    events: list[dict[str, Any]] = []
    path = runs_path(name)
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                events.append(parsed)
    if not events:
        typer.echo(t("msg.schedule.no_runs"))
        typer.echo(t("msg.schedule.runs_tracking_hint"))
        return
    last = events[-1]
    if "started_at" in last and "finished_at" not in last:
        typer.echo(t("msg.schedule.run_started", started=last["started_at"]))
        return
    complete = next((event for event in reversed(events) if "finished_at" in event), None)
    if complete is None:
        typer.echo(t("msg.schedule.no_runs"))
        typer.echo(t("msg.schedule.runs_tracking_hint"))
        return
    typer.echo(
        t(
            "msg.schedule.last_run",
            finished=complete["finished_at"],
            code=complete["exit_code"],
            seconds=complete["seconds"],
        )
    )
