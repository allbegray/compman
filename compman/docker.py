from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from compman._proc import PASSTHRU_UNBOUNDED, _env_timeout
from compman.config import Config, ConfigError, Profile


@dataclass
class ContainerRuntime:
    name: str
    cli: list[str]
    compose: list[str]
    timeout: float = 300.0

    def run_cli(
        self,
        args: Sequence[str],
        capture: bool = True,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess:
        run_timeout = self.timeout if timeout is None else timeout
        return _run(self.cli + list(args), capture=capture, check=check, timeout=run_timeout)

    def ensure_ready_for_start(
        self, confirm_start: Callable[[], bool], timeout: float = 60.0
    ) -> None:
        """Ensure Docker Desktop is ready before an interactive stack start."""
        if self.name != "docker" or sys.platform != "win32":
            return
        if self._docker_is_ready():
            return
        if not sys.stdin.isatty():
            raise RuntimeError(
                "Docker Desktop is not ready and cannot be started from a non-interactive session. "
                "Start Docker Desktop manually and retry."
            )
        if not confirm_start():
            raise RuntimeError(
                "Docker Desktop startup was declined. Start Docker Desktop manually and retry."
            )

        desktop = shutil.which("Docker Desktop.exe")
        if not desktop:
            program_files = os.environ.get("ProgramFiles")
            if program_files:
                candidate = Path(program_files) / "Docker" / "Docker" / "Docker Desktop.exe"
                if candidate.is_file():
                    desktop = str(candidate)
        if not desktop:
            raise RuntimeError("Docker Desktop executable was not found.")

        try:
            subprocess.Popen(
                [desktop], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        except OSError as exc:
            raise RuntimeError(f"Could not start Docker Desktop: {exc}") from exc

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sleep_for = min(1.0, remaining)
            time.sleep(sleep_for)
            probe_timeout = min(5.0, deadline - time.monotonic())
            if probe_timeout <= 0:
                break
            if self._docker_is_ready(probe_timeout):
                return
        raise RuntimeError(f"Docker Desktop did not become ready within {timeout:g} seconds.")

    def _docker_is_ready(self, timeout: float = 5.0) -> bool:
        try:
            result = self.run_cli(["info"], capture=True, check=False, timeout=timeout)
        except (RuntimeError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def run_compose(
        self,
        args: Sequence[str],
        project: str | None = None,
        compose_files: Sequence[Path] | None = None,
        env: dict[str, str] | None = None,
        capture: bool = True,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess:
        cmd = self._compose_cmd(project, compose_files) + list(args)
        run_timeout = self.timeout if timeout is None else timeout
        return _run(cmd, extra_env=env, capture=capture, check=check, timeout=run_timeout)

    def passthru_compose(
        self,
        args: Sequence[str],
        project: str | None = None,
        compose_files: Sequence[Path] | None = None,
        env: dict[str, str] | None = None,
    ) -> int:
        cmd = self._compose_cmd(project, compose_files) + list(args)
        return _passthru(cmd, extra_env=env)

    def passthru_cli(
        self,
        args: Sequence[str],
        cwd: Path | str | None = None,
        timeout: float | None = None,
    ) -> int:
        return _passthru(self.cli + list(args), cwd=cwd, timeout=timeout)

    def logs(self, container: str, follow: bool = False, tail: int = 50) -> int:
        args = ["logs"]
        if follow:
            args.append("-f")
        args.extend(["-n", str(tail), container])
        return self.passthru_cli(args, timeout=PASSTHRU_UNBOUNDED if follow else None)

    def exec_shell(self, container: str) -> int:
        return self.passthru_cli(
            [
                "exec",
                "-it",
                container,
                "sh",
                "-c",
                "if command -v bash >/dev/null 2>&1; then exec bash; else exec sh; fi",
            ],
            timeout=PASSTHRU_UNBOUNDED,
        )

    def inspect_container(self, container: str, check: bool = True) -> subprocess.CompletedProcess:
        return self.run_cli(["inspect", container], capture=True, check=check)

    def copy_from_container(self, container: str, source: str, destination: Path) -> None:
        self.run_cli(["cp", f"{container}:{source}", str(destination)], capture=False)

    def copy_to_container(self, source: Path | str, container: str, destination: str) -> None:
        self.run_cli(["cp", f"{source}", f"{container}:{destination}"], capture=False)

    def fix_permissions(self, container: str, destination: str) -> None:
        result = self.run_cli(
            ["exec", container, "stat", "-c", "%U %G", destination],
            capture=True,
            check=False,
        )
        if result.returncode != 0:
            return
        parts = result.stdout.strip().split()
        if len(parts) >= 2:
            self.run_cli(
                ["exec", "-u", "root", container, "chown", "-R", f"{parts[0]}:{parts[1]}", destination],
                capture=False,
                check=False,
            )

    def inspect_value(self, container: str, format_string: str) -> str:
        result = self.run_cli(
            ["inspect", "--format", format_string, container], capture=True
        )
        return result.stdout.strip()

    def commit_container(self, container: str, tag: str) -> None:
        self.run_cli(["commit", container, tag], capture=False)

    def save_image(self, image: str, destination: Path) -> None:
        self.run_cli(["save", "-o", str(destination), image], capture=False)

    def remove_image(self, image: str) -> None:
        self.run_cli(["rmi", image], capture=False, check=False)

    def load_image(self, source: Path) -> None:
        self.run_cli(["load", "-i", str(source)], capture=False)

    def _compose_cmd(
        self,
        project: str | None,
        compose_files: Sequence[Path] | None,
    ) -> list[str]:
        cmd: list[str] = []
        cmd += self.compose
        if project:
            cmd += ["-p", project]
        if compose_files:
            for f in compose_files:
                cmd += ["-f", str(f)]
        return cmd

    def stack_exists(
        self,
        name: str,
        compose_files: Sequence[Path] | None = None,
        env: dict[str, str] | None = None,
    ) -> bool:
        result = self.run_cli(
            [
                "ps",
                "-a",
                "--filter",
                f"label=com.docker.compose.project={name}",
                "--format",
                "{{.Names}}",
            ],
            check=False,
        )
        _raise_probe_failure(result)
        return bool(result.stdout.strip())

    def list_containers(
        self,
        project: str,
        compose_files: Sequence[Path] | None = None,
        env: dict[str, str] | None = None,
    ) -> list[str]:
        result = self.run_compose(
            ["ps", "-a", "--format", "{{.Names}}"],
            project=project,
            compose_files=compose_files,
            env=env,
            check=False,
        )
        _raise_probe_failure(result)
        return [c for c in result.stdout.strip().splitlines() if c]

    def service_status(
        self,
        project: str,
        compose_files: Sequence[Path] | None = None,
        env: dict[str, str] | None = None,
    ) -> list[dict[str, object]]:
        result = self.run_compose(
            ["ps", "-a", "--format", "json"],
            project=project,
            compose_files=compose_files,
            env=env,
            check=False,
        )
        _raise_probe_failure(result)
        return _parse_service_status(result.stdout)

    def list_volumes(self, project: str) -> list[str]:
        result = self.run_cli(
            [
                "volume",
                "ls",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{.Name}}",
            ],
            check=False,
        )
        _raise_probe_failure(result)
        return [v for v in result.stdout.strip().splitlines() if v]

    def get_container_id(self, name: str, project: str | None = None) -> str:
        filters = [f"name=^{name}$"]
        if project:
            filters.append(f"label=com.docker.compose.project={project}")
        result = self.run_cli(
            [
                "ps",
                "-a",
                *sum((["--filter", value] for value in filters), []),
                "--format",
                "{{.ID}}",
            ],
        )
        return result.stdout.strip()


_RUNTIME_CANDIDATES: list[tuple[str, str, list[str], list[str], list[str]]] = [
    ("docker", "docker", ["docker"], ["docker", "compose"], ["docker", "compose", "version"]),
    ("podman", "podman", ["podman"], ["podman", "compose"], ["podman", "compose", "version"]),
    ("podman", "podman", ["podman"], ["podman-compose"], ["podman-compose", "--version"]),
    ("docker", "docker", ["docker"], ["docker-compose"], ["docker-compose", "--version"]),
]


def detect_runtime() -> ContainerRuntime:
    override = os.environ.get("CONTAINER_RUNTIME", "").lower()
    timeout = _env_timeout()

    for override_key, name, cli, compose, probe_argv in _RUNTIME_CANDIDATES:
        if override and override != override_key:
            continue
        ok, _ = _check_cmd(probe_argv)
        if ok:
            return ContainerRuntime(name=name, cli=list(cli), compose=list(compose), timeout=timeout)

    msg = "No container runtime found. Install Docker or Podman."
    if override:
        msg = f"Runtime '{override}' not found."
    raise RuntimeError(msg)


def _check_cmd(cmd: list[str]) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return r.returncode == 0, r.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, ""


def _run(
    cmd: Sequence[str],
    extra_env: dict[str, str] | None = None,
    capture: bool = True,
    check: bool = True,
    timeout: float = 300.0,
) -> subprocess.CompletedProcess:
    env = _merged_env(extra_env)
    kwargs: dict = {}
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
        kwargs["encoding"] = "utf-8"
        kwargs["errors"] = "replace"
    try:
        r = subprocess.run(list(cmd), env=env, **kwargs, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError(f"Command not found: {cmd[0]}")
    if check and r.returncode != 0:
        _die(cmd, r)
    return r


def _passthru(
    cmd: Sequence[str],
    extra_env: dict[str, str] | None = None,
    cwd: Path | str | None = None,
    timeout: float | None = None,
) -> int:
    env = _merged_env(extra_env)
    resolved = _env_timeout() if timeout is None else timeout
    kwargs: dict = {"env": env, "cwd": cwd}
    if resolved != PASSTHRU_UNBOUNDED:
        kwargs["timeout"] = resolved
    try:
        r = subprocess.run(list(cmd), **kwargs)
    except FileNotFoundError:
        raise RuntimeError(f"Command not found: {cmd[0]}")
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Command timed out after {resolved:g} seconds: {' '.join(cmd)}") from e
    if r.returncode != 0:
        _die(cmd, r)
    return r.returncode


def _merged_env(extra: dict[str, str] | None) -> dict[str, str]:
    if not extra:
        merged = dict(os.environ)
    else:
        merged = {**os.environ, **extra}
    merged.pop("PYTHONPATH", None)
    return merged


def _die(cmd: Sequence[str], r: subprocess.CompletedProcess) -> None:
    msg = f"Command failed: {' '.join(cmd)} (exit={r.returncode})"
    if r.stderr:
        msg += f"\nstderr: {r.stderr.strip()}"
    if r.stdout:
        msg += f"\nstdout: {r.stdout.strip()}"
    raise RuntimeError(msg)


def _raise_probe_failure(result: subprocess.CompletedProcess) -> None:
    code = getattr(result, "returncode", 0)
    if isinstance(code, int) and code != 0:
        _die(getattr(result, "args", ["container runtime"]), result)


def _parse_service_status(payload: str | None) -> list[dict[str, object]]:
    if not payload or not payload.strip():
        return []
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        try:
            parsed = [json.loads(line) for line in payload.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise RuntimeError("Invalid service status JSON") from exc
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list) or not all(isinstance(row, dict) for row in parsed):
        raise RuntimeError("Invalid service status JSON")
    normalized: list[dict[str, object]] = []
    for row in parsed:
        labels = row.get("Labels")
        service = row.get("Service")
        if not service and isinstance(labels, dict):
            service = labels.get("com.docker.compose.service")

        container = row.get("Name")
        names = row.get("Names")
        if not container and isinstance(names, list) and names:
            container = names[0]

        state = str(row.get("State") or "")
        status = row.get("Status")
        if not status:
            exit_code = row.get("ExitCode")
            if exit_code is None or exit_code == "":
                status = state
            elif state:
                status = f"{state} (exit {exit_code})"
            else:
                status = f"exit {exit_code}"

        health = row.get("Health")
        normalized.append(
            {
                "service": str(service or ""),
                "container": str(container or ""),
                "state": state,
                "status": str(status or ""),
                "health": str(health) if health else None,
            }
        )
    return normalized


def _profile_or_error(config: Config, profile: str) -> Profile:
    prof = config.profiles.get(profile)
    if not prof:
        known = ", ".join(config.profiles)
        raise ConfigError(f"Unknown profile: {profile}. Known: {known}")
    return prof


def _fallback_file(prof: Profile, config: Config) -> str:
    return prof.file or config.compose_base or "docker-compose.yml"


def resolve_compose_files(
    config: Config, profile: str
) -> tuple[list[Path], dict[str, str]]:
    prof = _profile_or_error(config, profile)

    project_dir = config.project_dir
    compose_file = project_dir / _fallback_file(prof, config)
    if not compose_file.is_file():
        raise ConfigError(f"Compose file not found: {compose_file}")

    files = [compose_file]
    if config.compose_base and prof.file:
        base = project_dir / config.compose_base
        if not base.is_file():
            raise ConfigError(f"Base compose file not found: {base}")
        files.insert(0, base)

    return files, dict(prof.env)


@dataclass(frozen=True)
class ComposeContext:
    project: str
    files: tuple[Path, ...]
    env: dict[str, str]


def resolve_compose_context(config: Config, profile: str | None = None) -> ComposeContext:
    if profile is None:
        profile = next(iter(config.profiles))
    prof = _profile_or_error(config, profile)

    if config.source_path:
        files, env = resolve_compose_files(config, profile)
    else:
        files = [config.project_dir / _fallback_file(prof, config)]
        env = dict(prof.env)

    if any("${secrets:" in v for v in env.values()):
        from compman.env_source import interpolate_secrets, resolve_secrets

        merged = {**config.secrets, **prof.secrets}
        env = interpolate_secrets(env, resolve_secrets(merged))
    return ComposeContext(config.name, tuple(files), env)
