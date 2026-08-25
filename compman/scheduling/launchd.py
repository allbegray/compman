from __future__ import annotations

import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from compman.scheduling.cadence import parse_time_value, require_minutes, require_weekday
from compman.scheduling.registry import JobRecord, Runner

LABEL_PREFIX = "com.compman.volume."


def label_for(name: str) -> str:
    return f"{LABEL_PREFIX}{name}"


def plist_path(name: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label_for(name)}.plist"


def _string(value: str) -> ET.Element:
    element = ET.Element("string")
    element.text = value
    return element


def _integer(value: int) -> ET.Element:
    element = ET.Element("integer")
    element.text = str(value)
    return element


def build_plist_xml(record: JobRecord) -> str:
    plist = ET.Element("plist", {"version": "1.0"})
    root = ET.SubElement(plist, "dict")

    def entry(key: str, value: ET.Element) -> None:
        key_element = ET.SubElement(root, "key")
        key_element.text = key
        root.append(value)

    entry("Label", _string(label_for(record.name)))
    program = ET.Element("array")
    for argument in record.args:
        program.append(_string(argument))
    entry("ProgramArguments", program)
    environment = ET.Element("dict")
    path_key = ET.SubElement(environment, "key")
    path_key.text = "PATH"
    environment.append(_string(record.path_env))
    entry("EnvironmentVariables", environment)

    cadence = record.cadence()
    if cadence.kind == "interval":
        entry("StartInterval", _integer(require_minutes(cadence) * 60))
    else:
        hour, minute = parse_time_value(cadence.time)
        calendar = ET.Element("dict")
        for calendar_key, calendar_value in (("Hour", hour), ("Minute", minute)):
            key_element = ET.SubElement(calendar, "key")
            key_element.text = calendar_key
            calendar.append(_integer(calendar_value))
        if cadence.kind == "weekly":
            weekday_element = ET.SubElement(calendar, "key")
            weekday_element.text = "Weekday"
            calendar.append(_integer(require_weekday(cadence)))
        entry("StartCalendarInterval", calendar)

    entry("WorkingDirectory", _string(record.workdir))
    entry("StandardOutPath", _string(record.log_path))
    entry("StandardErrorPath", _string(record.log_path))
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(plist, encoding="unicode")


class LaunchdAdapter:
    def install(self, record: JobRecord, runner: Runner = subprocess.run) -> None:
        path = plist_path(record.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_plist_xml(record), encoding="utf-8")
        uid = os.getuid()
        runner(
            ["launchctl", "bootstrap", f"gui/{uid}", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )

    def remove(self, name: str, runner: Runner = subprocess.run) -> None:
        uid = os.getuid()
        runner(
            ["launchctl", "bootout", f"gui/{uid}/{label_for(name)}"],
            capture_output=True,
            text=True,
            check=False,
        )
        plist_path(name).unlink(missing_ok=True)

    def exists(self, name: str, runner: Runner = subprocess.run) -> bool:
        return plist_path(name).is_file()
