from __future__ import annotations

import subprocess

from compman.scheduling.registry import Runner

SCHEDULER_FORCE_CHOICES = ("systemd", "cron")


def _has_systemd_user_session(probe_runner: Runner | None) -> bool:
    run = probe_runner if probe_runner is not None else subprocess.run
    probed = run(
        ["systemctl", "--user", "show-environment"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probed.returncode == 0


def pick_scheduler(
    system: str,
    force: str | None,
    systemd_probe_runner: Runner | None = None,
) -> str:
    if system == "darwin":
        return "launchd"
    if system == "win32":
        return "schtasks"
    if system == "linux":
        if force is not None:
            if force not in SCHEDULER_FORCE_CHOICES:
                raise ValueError(f"Unknown scheduler '{force}'; expected one of: systemd, cron.")
            return force
        return "systemd" if _has_systemd_user_session(systemd_probe_runner) else "cron"
    raise ValueError(f"Scheduling is not supported on {system}.")
