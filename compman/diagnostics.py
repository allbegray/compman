from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from compman.backup_store import archive_location, local_root
from compman.config import Config, ConfigError, load_config
from compman.docker import ContainerRuntime, detect_runtime, resolve_compose_context

StatusErrorCode = Literal["stack-missing", "runtime-error", "config-error", "compose-error"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CheckResult:
    id: str
    severity: Literal["required", "warning"]
    ok: bool
    message: str
    remediation: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "severity": self.severity,
            "ok": self.ok,
            "message": self.message,
            "remediation": self.remediation,
            "detail": self.detail,
        }


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
    error_code: StatusErrorCode | None = None
    generated_at: str = field(default_factory=_utc_now_iso)
    config_path: str | None = None

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
            "error_code": self.error_code,
            "generated_at": self.generated_at,
            "config_path": self.config_path,
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
        _collect_backup_store(config, checks)
        _collect_deploy_checksum(config, checks)
        _collect_deploy_auth(config, checks)
    return DoctorReport(tuple(checks))


def collect_status(config_path: str | None, profile: str | None = None) -> StatusReport:
    resolved_config_path = str(
        (Path(config_path) if config_path else Path.cwd() / "compman.yml").resolve()
    )
    try:
        config = load_config(config_path)
    except (ConfigError, OSError) as exc:
        return StatusReport(
            False, None, None, None, (), (), str(exc), "config-error", config_path=resolved_config_path
        )

    effective_profile = profile
    if effective_profile is None:
        effective_profile = next(iter(config.profiles))
    try:
        context = resolve_compose_context(config, effective_profile)
    except (ConfigError, OSError) as exc:
        return StatusReport(
            False,
            None,
            config.name,
            effective_profile,
            (),
            (),
            str(exc),
            "compose-error",
            config_path=resolved_config_path,
        )

    compose_files = tuple(str(path) for path in context.files)
    try:
        runtime = detect_runtime()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return StatusReport(
            False,
            None,
            context.project,
            effective_profile,
            compose_files,
            (),
            str(exc),
            "runtime-error",
            config_path=resolved_config_path,
        )

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
                "stack-missing",
                config_path=resolved_config_path,
            )
        rows = runtime.service_status(context.project, context.files, context.env)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return StatusReport(
            False,
            runtime.name,
            context.project,
            effective_profile,
            compose_files,
            (),
            str(exc),
            "runtime-error",
            config_path=resolved_config_path,
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
    return StatusReport(
        True,
        runtime.name,
        context.project,
        effective_profile,
        compose_files,
        services,
        config_path=resolved_config_path,
    )


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
        directories = [config.volume_dir, config.deploy_dir]
        if not config.backup_store.is_remote:
            directories.insert(0, local_root(config.backup_store))
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


def _aws_env_ready() -> bool:
    credentials_present = bool(os.environ.get("AWS_ACCESS_KEY_ID")) and bool(
        os.environ.get("AWS_SECRET_ACCESS_KEY")
    )
    region_present = bool(os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION"))
    return credentials_present and region_present


def _collect_secrets(config: Config, checks: list[CheckResult]) -> None:
    if not config.secrets:
        return
    ok = _aws_env_ready()
    message = (
        f"Secrets configured for {len(config.secrets)} env vars; "
        "AWS credentials and region are available."
        if ok
        else "Secrets configured but AWS credentials or region are missing."
    )
    checks.append(CheckResult("secrets", "warning", ok, message))


def _collect_backup_store(config: Config, checks: list[CheckResult]) -> None:
    if not config.backup_store.is_remote:
        return
    ok = _aws_env_ready()
    message = (
        f"Backup store configured for {archive_location(config.backup_store, '')}; "
        "AWS credentials and region are available."
        if ok
        else "Backup store configured but AWS credentials or region are missing."
    )
    checks.append(CheckResult("backup_store", "warning", ok, message))


def _collect_deploy_checksum(config: Config, checks: list[CheckResult]) -> None:
    if not config.deploy or config.deploy_sha256:
        return
    checks.append(
        CheckResult(
            "deploy_checksum",
            "warning",
            False,
            "Deploy source is configured without a SHA-256 integrity pin.",
            remediation="Add a 'sha256' key to the deploy mapping in compman.yml "
            "(64 hexadecimal characters) or pass --sha256 on deploy.",
        )
    )


def _collect_deploy_auth(config: Config, checks: list[CheckResult]) -> None:
    if config.deploy_auth is None:
        return
    value_env = config.deploy_auth.value_env
    value_present = bool(os.environ.get(value_env))
    message = (
        f"Deploy authentication environment variable '{value_env}' is set."
        if value_present
        else f"Deploy authentication environment variable '{value_env}' is not set."
    )
    checks.append(CheckResult("deploy_auth_env", "warning", value_present, message))
