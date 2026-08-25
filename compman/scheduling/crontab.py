from __future__ import annotations

import subprocess

from compman.scheduling.cadence import cron_expr
from compman.scheduling.registry import JobRecord, Runner


def begin_marker(name: str) -> str:
    return f"# BEGIN compman:{name}"


def end_marker(name: str) -> str:
    return f"# END compman:{name}"


def _escape_percent(value: str) -> str:
    return value.replace("%", r"\%")


def build_crontab_block(record: JobRecord) -> str:
    schedule = cron_expr(record.cadence())
    command = " ".join(_escape_percent(part) for part in record.args)
    log = _escape_percent(record.log_path)
    line = f"{schedule} {command} >> {log} 2>&1"
    return f"{begin_marker(record.name)}\nPATH={record.path_env}\n{line}\n{end_marker(record.name)}\n"


def without_block(content: str, name: str) -> str:
    begin = begin_marker(name)
    end = end_marker(name)
    kept: list[str] = []
    inside = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == begin:
            inside = True
            continue
        if stripped == end:
            inside = False
            continue
        if not inside:
            kept.append(line)
    if not kept:
        return ""
    return "\n".join(kept) + "\n"


def crontab_status(runner: Runner = subprocess.run) -> tuple[bool, str]:
    """Return ``(available, detail)`` for the crontab mechanism.

    Exit 0 means a readable table, exit 1 an empty table; both are usable.
    Any other exit code means the mechanism itself is unavailable.
    """
    listed = runner(["crontab", "-l"], capture_output=True, text=True, check=False)
    if listed.returncode in (0, 1):
        return True, ""
    return False, (listed.stderr or "").strip()


class CrontabAdapter:
    def install(self, record: JobRecord, runner: Runner = subprocess.run) -> None:
        current = self._read(runner)
        updated = without_block(current, record.name) + build_crontab_block(record)
        self._write(updated, runner)

    def remove(self, name: str, runner: Runner = subprocess.run) -> None:
        current = self._read(runner)
        self._write(without_block(current, name), runner)

    def exists(self, name: str, runner: Runner = subprocess.run) -> bool:
        listed = runner(["crontab", "-l"], capture_output=True, text=True, check=False)
        if listed.returncode != 0:
            return False
        return begin_marker(name) in listed.stdout

    @staticmethod
    def _read(runner: Runner) -> str:
        listed = runner(["crontab", "-l"], capture_output=True, text=True, check=False)
        return listed.stdout if listed.returncode == 0 else ""

    @staticmethod
    def _write(content: str, runner: Runner) -> None:
        runner(["crontab", "-"], input=content, capture_output=True, text=True, check=False)
