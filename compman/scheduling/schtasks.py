from __future__ import annotations

import subprocess

from compman.scheduling.cadence import schtasks_cadence_args
from compman.scheduling.registry import JobRecord, Runner, require_success

TR_MAX_LENGTH = 261

_CMD_ARG_SAFE_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "-_.\\/:=+"
)


def cmd_quote(argument: str) -> str:
    """Quote one cmd.exe payload argument holding whitespace or metacharacters."""
    if argument and all(char in _CMD_ARG_SAFE_CHARS for char in argument):
        return argument
    return f'"{argument}"'



def _tr_payload(record: JobRecord) -> str:
    rest = " ".join(cmd_quote(argument) for argument in record.args[1:])
    return f'cmd.exe /c ""{record.args[0]}" {rest} >> "{record.log_path}" 2>&1"'


def build_schtasks_command(record: JobRecord) -> list[str]:
    payload = _tr_payload(record)
    if len(payload) > TR_MAX_LENGTH:
        raise ValueError(
            f"The schtasks /TR payload is {len(payload)} characters; the limit is "
            f"{TR_MAX_LENGTH}. Shorten the executable, configuration, or log path."
        )
    return [
        "schtasks",
        "/Create",
        "/F",
        "/TN",
        record.name,
        *schtasks_cadence_args(record.cadence()),
        "/TR",
        payload,
    ]


class SchtasksAdapter:
    def install(self, record: JobRecord, runner: Runner = subprocess.run) -> None:
        created = runner(
            build_schtasks_command(record),
            capture_output=True,
            text=True,
            check=False,
        )
        require_success(created, "schtasks")

    def remove(self, name: str, runner: Runner = subprocess.run) -> None:
        runner(
            ["schtasks", "/Delete", "/TN", name, "/F"],
            capture_output=True,
            text=True,
            check=False,
        )

    def exists(self, name: str, runner: Runner = subprocess.run) -> bool:
        queried = runner(
            ["schtasks", "/Query", "/TN", name],
            capture_output=True,
            text=True,
            check=False,
        )
        return queried.returncode == 0
