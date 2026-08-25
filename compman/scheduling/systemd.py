from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from compman.scheduling.cadence import require_minutes, systemd_oncalendar
from compman.scheduling.registry import JobRecord, Runner


def unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def unit_names(name: str) -> tuple[str, str]:
    return f"compman-{name}.service", f"compman-{name}.timer"


def _active_span(minutes: int) -> str:
    return f"{minutes // 60}h" if minutes % 60 == 0 else f"{minutes}min"


def build_systemd_units(record: JobRecord) -> tuple[str, str]:
    _service_name, timer_name = unit_names(record.name)
    description = f"compman scheduled volume backup ({record.name})"
    service = (
        "[Unit]\n"
        f"Description={description}\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"WorkingDirectory={record.workdir}\n"
        f"ExecStart={shlex.join(record.args)}\n"
    )
    cadence = record.cadence()
    if cadence.kind == "interval":
        schedule = f"OnBootSec=5min\nOnUnitActiveSec={_active_span(require_minutes(cadence))}\n"
    else:
        schedule = f"OnCalendar={systemd_oncalendar(cadence)}\n"
    timer = (
        "[Unit]\n"
        f"Description=Timer for {description}\n"
        "\n"
        "[Timer]\n"
        f"{schedule}"
        "Persistent=true\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    return service, timer


class SystemdAdapter:
    def install(self, record: JobRecord, runner: Runner = subprocess.run) -> None:
        directory = unit_dir()
        directory.mkdir(parents=True, exist_ok=True)
        service_name, timer_name = unit_names(record.name)
        service, timer = build_systemd_units(record)
        (directory / service_name).write_text(service, encoding="utf-8")
        (directory / timer_name).write_text(timer, encoding="utf-8")
        runner(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
            text=True,
            check=False,
        )
        runner(
            ["systemctl", "--user", "enable", "--now", timer_name],
            capture_output=True,
            text=True,
            check=False,
        )

    def remove(self, name: str, runner: Runner = subprocess.run) -> None:
        service_name, timer_name = unit_names(name)
        runner(
            ["systemctl", "--user", "disable", "--now", timer_name],
            capture_output=True,
            text=True,
            check=False,
        )
        directory = unit_dir()
        (directory / service_name).unlink(missing_ok=True)
        (directory / timer_name).unlink(missing_ok=True)
        runner(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
            text=True,
            check=False,
        )

    def exists(self, name: str, runner: Runner = subprocess.run) -> bool:
        _service_name, timer_name = unit_names(name)
        return (unit_dir() / timer_name).is_file()
