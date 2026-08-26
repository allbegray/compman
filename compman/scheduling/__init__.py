"""Platform-native backup scheduling: cadences, registry, and scheduler adapters."""

from compman.scheduling.cadence import (
    Cadence,
    cron_expr,
    launchd_start_spec,
    parse_cadence,
    schtasks_cadence_args,
    systemd_oncalendar,
)
from compman.scheduling.crontab import CrontabAdapter, build_crontab_block, crontab_status
from compman.scheduling.launchd import LaunchdAdapter, build_plist_xml
from compman.scheduling.pick import pick_scheduler
from compman.scheduling.registry import (
    JobRecord,
    load_registry,
    registry_dir,
    registry_lock,
    registry_path,
    save_registry,
)
from compman.scheduling.resolve import resolve_executable
from compman.scheduling.schtasks import SchtasksAdapter, build_schtasks_command
from compman.scheduling.systemd import SystemdAdapter, build_systemd_units

__all__ = [
    "Cadence",
    "CrontabAdapter",
    "JobRecord",
    "LaunchdAdapter",
    "SchtasksAdapter",
    "SystemdAdapter",
    "build_crontab_block",
    "build_plist_xml",
    "build_schtasks_command",
    "build_systemd_units",
    "cron_expr",
    "crontab_status",
    "launchd_start_spec",
    "load_registry",
    "parse_cadence",
    "pick_scheduler",
    "registry_dir",
    "registry_lock",
    "registry_path",
    "resolve_executable",
    "save_registry",
    "schtasks_cadence_args",
    "systemd_oncalendar",
]
