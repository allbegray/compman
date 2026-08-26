from __future__ import annotations

import subprocess
from pathlib import Path

from compman.scheduling.cadence import require_minutes, systemd_oncalendar
from compman.scheduling.registry import JobRecord, Runner, require_success


def unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def unit_names(name: str) -> tuple[str, str]:
    return f"compman-{name}.service", f"compman-{name}.timer"


def _active_span(minutes: int) -> str:
    return f"{minutes // 60}h" if minutes % 60 == 0 else f"{minutes}min"


_SYSTEMD_ARG_SAFE_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "-_.:/=@+"
)


def systemd_quote(argument: str) -> str:
    """Quote one ExecStart argument using systemd syntax rather than POSIX shlex."""
    if argument and all(char in _SYSTEMD_ARG_SAFE_CHARS for char in argument):
        return argument
    escaped = argument.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'




def build_systemd_units(record: JobRecord) -> tuple[str, str]:
    _service_name, timer_name = unit_names(record.name)
    description = f"compman scheduled volume backup ({record.name})"
    service = (
        "[Unit]\n"
        f"Description={description}\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f'Environment="PATH={record.path_env}"\n'
        f"WorkingDirectory={record.workdir}\n"
        f"ExecStart={' '.join(systemd_quote(argument) for argument in record.args)}\n"
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
        reload_done = runner(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
            text=True,
            check=False,
        )
        require_success(reload_done, "systemd")
        enabled = runner(
            ["systemctl", "--user", "enable", "--now", timer_name],
            capture_output=True,
            text=True,
            check=False,
        )
        require_success(enabled, "systemd")

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
        state = runner(
            ["systemctl", "--user", "is-enabled", timer_name],
            capture_output=True,
            text=True,
            check=False,
        )
        return state.returncode == 0
