from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from compman.errors import CommandError
from compman.i18n import t

CadenceKind = Literal["interval", "daily", "weekly", "monthly"]

EXACTLY_ONE_ERROR = "Specify exactly one of --every, --daily, --weekly, or --monthly."

_EVERY_PATTERN = re.compile(r"^(\d+)(m|h)$")
_TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{1,2})$")

WEEKDAY_NAMES: tuple[str, ...] = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
_WEEKDAY_INDEX: dict[str, int] = {name.lower(): index for index, name in enumerate(WEEKDAY_NAMES)}


@dataclass(frozen=True)
class Cadence:
    kind: CadenceKind
    minutes: int | None = None
    time: str | None = None
    weekday: int | None = None
    day: int | None = None


def parse_time_value(time: str | None) -> tuple[int, int]:
    """Split a stored ``HH:MM`` value into ``(hour, minute)``."""
    if time is None:
        raise ValueError("A time (HH:MM) is required for daily and weekly cadences.")
    match = _TIME_PATTERN.match(time)
    if match is None:
        raise ValueError(f"Invalid time '{time}': expected HH:MM between 00:00 and 23:59.")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError(f"Invalid time '{time}': expected HH:MM between 00:00 and 23:59.")
    return hour, minute


def require_minutes(cadence: Cadence) -> int:
    if cadence.minutes is None:
        raise ValueError("Interval cadence requires a minute count.")
    return cadence.minutes


def require_weekday(cadence: Cadence) -> int:
    if cadence.weekday is None:
        raise ValueError("Weekly cadence requires a weekday (0=Sun .. 6=Sat).")
    return cadence.weekday


def require_day(cadence: Cadence) -> int:
    if cadence.day is None:
        raise ValueError("Monthly cadence requires a day of month (1-31).")
    return cadence.day


def parse_cadence(
    every: str | None,
    daily: str | None,
    weekly: str | None,
    monthly: str | None = None,
) -> Cadence:
    given = [value for value in (every, daily, weekly, monthly) if value is not None]
    if len(given) != 1:
        raise ValueError(EXACTLY_ONE_ERROR)
    if every is not None:
        return _parse_every(every)
    if daily is not None:
        parse_time_value(daily)
        return Cadence(kind="daily", time=daily)
    if weekly is not None:
        parts = weekly.split()
        if len(parts) != 2 or parts[0].lower() not in _WEEKDAY_INDEX:
            raise ValueError(
                f"Invalid --weekly value '{weekly}': expected '<day> HH:MM' with day sun..sat."
            )
        parse_time_value(parts[1])
        return Cadence(kind="weekly", time=parts[1], weekday=_WEEKDAY_INDEX[parts[0].lower()])
    assert monthly is not None
    return _parse_monthly(monthly)


def _parse_every(value: str) -> Cadence:
    match = _EVERY_PATTERN.match(value)
    if match is None or int(match.group(1)) < 1:
        raise ValueError(f"Invalid --every value '{value}': expected <N>m or <N>h with N >= 1.")
    count, unit = int(match.group(1)), match.group(2)
    return Cadence(kind="interval", minutes=count if unit == "m" else count * 60)


def _parse_monthly(value: str) -> Cadence:
    parts = value.split()
    if len(parts) != 2:
        raise ValueError(
            f"Invalid --monthly value '{value}': expected '<day> HH:MM' with day 1-31."
        )
    day_text, time_text = parts
    if not day_text.isdigit() or not 1 <= int(day_text) <= 31:
        raise CommandError(t("msg.invalid_month_day", value=day_text))
    parse_time_value(time_text)
    return Cadence(kind="monthly", day=int(day_text), time=time_text)


def cron_expr(cadence: Cadence) -> str:
    if cadence.kind == "interval":
        minutes = require_minutes(cadence)
        if minutes % 60 == 0:
            return f"0 */{minutes // 60} * * *"
        if 60 % minutes == 0:
            return f"*/{minutes} * * * *"
        raise ValueError(
            f"An interval of {minutes} minutes cannot be expressed in cron; use a divisor of "
            "60 (minutes) or 24 (hours), or force the systemd scheduler instead."
        )
    hour, minute = parse_time_value(cadence.time)
    if cadence.kind == "daily":
        return f"{minute} {hour} * * *"
    if cadence.kind == "monthly":
        return f"{minute} {hour} {require_day(cadence)} * *"
    return f"{minute} {hour} * * {require_weekday(cadence)}"


def launchd_start_spec(cadence: Cadence) -> int | dict[str, int]:
    if cadence.kind == "interval":
        return require_minutes(cadence) * 60
    hour, minute = parse_time_value(cadence.time)
    if cadence.kind == "monthly":
        return {"Day": require_day(cadence), "Hour": hour, "Minute": minute}
    spec: dict[str, int] = {"Hour": hour, "Minute": minute}
    if cadence.kind == "weekly":
        spec["Weekday"] = require_weekday(cadence)
    return spec


def systemd_oncalendar(cadence: Cadence) -> str:
    if cadence.kind == "interval":
        raise ValueError("Interval cadences use OnBootSec/OnUnitActiveSec timers, not OnCalendar.")
    hour, minute = parse_time_value(cadence.time)
    prefix = "" if cadence.weekday is None else f"{WEEKDAY_NAMES[cadence.weekday]} "
    day_spec = "*" if cadence.day is None else f"{cadence.day:02d}"
    return f"{prefix}*-*-{day_spec} {hour:02d}:{minute:02d}:00"


def schtasks_cadence_args(cadence: Cadence) -> list[str]:
    if cadence.kind == "interval":
        minutes = require_minutes(cadence)
        if minutes % 60 == 0:
            return ["/SC", "HOURLY", "/MO", str(minutes // 60)]
        return ["/SC", "MINUTE", "/MO", str(minutes)]
    hour, minute = parse_time_value(cadence.time)
    start_time = f"{hour:02d}:{minute:02d}"
    if cadence.kind == "daily":
        return ["/SC", "DAILY", "/ST", start_time]
    if cadence.kind == "monthly":
        return ["/SC", "MONTHLY", "/D", str(require_day(cadence)), "/ST", start_time]
    weekday_name = WEEKDAY_NAMES[require_weekday(cadence)].upper()
    return ["/SC", "WEEKLY", "/D", weekday_name, "/ST", start_time]
