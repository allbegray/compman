from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Literal

from compman.config import Config, ConfigError, load_config
from compman.docker import ContainerRuntime, detect_runtime, resolve_compose_context
from compman.i18n import t


@dataclass(frozen=True)
class CheckResult:
    id: str
    severity: Literal["required", "warning", "info"]
    ok: bool
    message: str

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "severity": self.severity, "ok": self.ok, "message": self.message}


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks if check.severity == "required")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True)
class ServiceStatus:
    service: str
    container: str
    state: str
    status: str
    health: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "service": self.service,
            "container": self.container,
            "state": self.state,
            "status": self.status,
            "health": self.health,
        }


@dataclass(frozen=True)
class StatusReport:
    ok: bool
    runtime: str | None
    stack: str | None
    profile: str | None
    compose_files: tuple[str, ...]
    services: tuple[ServiceStatus, ...]
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ok": self.ok,
            "runtime": self.runtime,
            "stack": self.stack,
            "profile": self.profile,
            "compose_files": list(self.compose_files),
            "services": [service.to_dict() for service in self.services],
            "error": self.error,
        }


def collect_doctor(config_path: str | None, profile: str | None = None) -> DoctorReport:
    checks: list[CheckResult] = []
    config = _collect_config(config_path, checks)
    if config is not None:
        _collect_compose_files(config, profile, checks)
    runtime = _collect_runtime(checks)
    if runtime is not None:
        _collect_runtime_connection(runtime, checks)
    if config is not None:
        _collect_managed_dirs(config, checks)
    _collect_aws(checks)
    if config is not None:
        _collect_secrets(config, checks)
    if config is not None:
        _collect_env_files(config, checks)
    if config is not None:
        _collect_deploy_checksum(config, checks)
    if config is not None:
        _collect_versions(config, checks)
    return DoctorReport(tuple(checks))


def collect_status(config_path: str | None, profile: str | None = None) -> StatusReport:
    try:
        config = load_config(config_path)
    except (ConfigError, OSError) as exc:
        return StatusReport(False, None, None, None, (), (), str(exc))

    effective_profile = profile
    if effective_profile is None:
        effective_profile = next(iter(config.profiles))
    try:
        context = resolve_compose_context(config, effective_profile)
    except (ConfigError, OSError) as exc:
        return StatusReport(False, None, config.name, effective_profile, (), (), str(exc))

    compose_files = tuple(str(path) for path in context.files)
    try:
        runtime = detect_runtime()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return StatusReport(False, None, context.project, effective_profile, compose_files, (), str(exc))

    try:
        if not runtime.stack_exists(context.project, context.files, context.env):
            return StatusReport(
                False,
                runtime.name,
                context.project,
                effective_profile,
                compose_files,
                (),
                f"Stack '{context.project}' is not running.",
            )
        rows = runtime.service_status(context.project, context.files, context.env)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return StatusReport(
            False, runtime.name, context.project, effective_profile, compose_files, (), str(exc)
        )

    services = tuple(
        ServiceStatus(
            service=str(row.get("service", "")),
            container=str(row.get("container", "")),
            state=str(row.get("state", "")),
            status=str(row.get("status", "")),
            health=str(row["health"]) if row.get("health") else None,
        )
        for row in rows
    )
    return StatusReport(True, runtime.name, context.project, effective_profile, compose_files, services)


def _collect_config(config_path: str | None, checks: list[CheckResult]) -> Config | None:
    try:
        config = load_config(config_path)
    except (ConfigError, OSError) as exc:
        checks.append(CheckResult("config", "required", False, str(exc)))
        return None
    checks.append(CheckResult("config", "required", True, f"Loaded configuration for {config.name}."))
    return config


def _collect_compose_files(config: Config, profile: str | None, checks: list[CheckResult]) -> None:
    try:
        context = resolve_compose_context(config, profile)
    except (ConfigError, OSError) as exc:
        checks.append(CheckResult("compose_files", "required", False, str(exc)))
        return
    checks.append(
        CheckResult(
            "compose_files",
            "required",
            True,
            f"Resolved {len(context.files)} Compose file(s).",
        )
    )


def _collect_runtime(checks: list[CheckResult]) -> ContainerRuntime | None:
    try:
        runtime = detect_runtime()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        checks.append(CheckResult("runtime", "required", False, str(exc)))
        return None
    checks.append(CheckResult("runtime", "required", True, f"Detected {runtime.name} runtime."))
    return runtime


def _collect_runtime_connection(runtime: ContainerRuntime, checks: list[CheckResult]) -> None:
    try:
        result = runtime.run_cli(["info"], check=False)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        checks.append(CheckResult("runtime_connection", "required", False, str(exc)))
        return
    if result.returncode != 0:
        checks.append(
            CheckResult("runtime_connection", "required", False, f"Runtime info failed (exit={result.returncode}).")
        )
        return
    checks.append(CheckResult("runtime_connection", "required", True, "Runtime connection succeeded."))


def _collect_managed_dirs(config: Config, checks: list[CheckResult]) -> None:
    try:
        directories = (config.backup_dir, config.volume_dir, config.deploy_dir)
        unwritable = []
        for directory in directories:
            probe = directory
            while not probe.exists() and probe.parent != probe:
                probe = probe.parent
            if not os.access(probe, os.W_OK | os.X_OK):
                unwritable.append(probe)
    except (ConfigError, OSError) as exc:
        checks.append(CheckResult("managed_dirs", "required", False, str(exc)))
        return
    if unwritable:
        checks.append(
            CheckResult(
                "managed_dirs",
                "required",
                False,
                f"Managed directory location is not writable/searchable: {unwritable[0]}",
            )
        )
        return
    checks.append(
        CheckResult("managed_dirs", "required", True, "Managed directory locations are writable/searchable.")
    )


def _collect_aws(checks: list[CheckResult]) -> None:
    credentials_present = bool(os.environ.get("AWS_ACCESS_KEY_ID")) and bool(
        os.environ.get("AWS_SECRET_ACCESS_KEY")
    )
    message = "AWS credentials are available." if credentials_present else "AWS credentials are not configured."
    checks.append(CheckResult("aws", "warning", credentials_present, message))


def _collect_secrets(config: Config, checks: list[CheckResult]) -> None:
    if not config.secrets:
        return
    credentials_present = bool(os.environ.get("AWS_ACCESS_KEY_ID")) and bool(
        os.environ.get("AWS_SECRET_ACCESS_KEY")
    )
    region_present = bool(os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION"))
    ok = credentials_present and region_present
    message = (
        f"Secrets configured for {len(config.secrets)} env vars; "
        "AWS credentials and region are available."
        if ok
        else "Secrets configured but AWS credentials or region are missing."
    )
    checks.append(CheckResult("secrets", "warning", ok, message))


def _collect_env_files(config: Config, checks: list[CheckResult]) -> None:
    for prof in config.profiles.values():
        for p in prof.env_file:
            candidate = config.root_dir / p
            if not candidate.exists():
                msg = t("check.env_file_missing", path=p)
                if msg == "check.env_file_missing":
                    msg = f"Env file not found: {p}"
                checks.append(CheckResult("env_file", "warning", False, msg))


def _collect_deploy_checksum(config: Config, checks: list[CheckResult]) -> None:
    deploy = config.deploy
    if deploy is None:
        return
    try:
        values = list(deploy.values())
    except Exception:
        return
    missing = 0
    for spec in values:
        try:
            if getattr(spec, "checksum", None) is None:
                missing += 1
        except Exception:
            missing += 1
    if missing == 0:
        return
    msg = t("check.deploy_checksum", count=missing)
    if msg == "check.deploy_checksum":
        msg = f"{missing} deploy profile(s) without checksum"
    checks.append(CheckResult("deploy_checksum", "warning", False, msg))


def _collect_versions(config: Config, checks: list[CheckResult]) -> None:
    backup_versions = config.backup_dir / ".versions"
    try:
        if backup_versions.is_dir():
            count = len(list(backup_versions.iterdir()))
            msg = f"{count} versions kept"
            checks.append(CheckResult("versions", "info", True, msg))
        else:
            checks.append(CheckResult("versions", "info", True, "no versions"))
    except OSError:
        checks.append(CheckResult("versions", "info", True, "no versions"))
