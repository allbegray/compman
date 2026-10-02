from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

import typer

from compman.compose_spec import VolumeMount, read_volume_mounts
from compman.config import Config
from compman.docker import ComposeContext, ContainerRuntime, resolve_compose_context
from compman.errors import CommandError
from compman.i18n import t
from compman.notify import (
    ServiceState,
    StackEvent,
    VolumeInfo,
    host_name,
    local_timestamp,
    missing_env_name,
    notify_stack_event,
    resolve_webhook,
)
from compman.ops.common import ensure_runtime_ready, parse_compose_ps


def up(runtime: ContainerRuntime, config: Config, profile: str | None = None, wait: bool = False) -> None:
    context = resolve_compose_context(config, profile)
    ensure_runtime_ready(runtime)
    started_at = datetime.now()
    clock = time.monotonic()
    runtime.passthru_compose(
        ["up", "-d", "--force-recreate"],
        project=context.project,
        compose_files=context.files,
        env=context.env,
    )
    elapsed = time.monotonic() - clock
    if wait:
        _wait_until_ready(runtime, context)
    _notify_started(runtime, config, context, profile, "up", started_at, elapsed)


def down(runtime: ContainerRuntime, config: Config, profile: str | None = None) -> None:
    context = resolve_compose_context(config, profile)
    if not runtime.stack_exists(config.name, context.files, context.env):
        typer.echo(t("msg.stack_not_running", name=config.name), err=True)
        return
    runtime.passthru_compose(
        ["down"], project=context.project, compose_files=context.files, env=context.env
    )


def logs(
    runtime: ContainerRuntime,
    config: Config,
    services: tuple[str, ...] = (),
    follow: bool = False,
    tail: int | None = None,
    profile: str | None = None,
) -> None:
    """Print or follow aggregated compose logs for the stack's services."""
    context = resolve_compose_context(config, profile)
    args = ["logs"]
    if tail is not None:
        args += ["--tail", str(tail)]
    if follow:
        args.append("-f")
    args += list(services)
    runtime.passthru_compose(
        args, project=context.project, compose_files=context.files, env=context.env
    )


def update(
    runtime: ContainerRuntime,
    config: Config,
    profile: str | None = None,
    wait: bool = False,
) -> None:
    context = resolve_compose_context(config, profile)
    ensure_runtime_ready(runtime)
    started_at = datetime.now()
    clock = time.monotonic()
    runtime.passthru_compose(
        ["up", "-d", "--build", "--force-recreate"],
        project=context.project,
        compose_files=context.files,
        env=context.env,
    )
    elapsed = time.monotonic() - clock
    if wait:
        _wait_until_ready(runtime, context)
    _notify_started(runtime, config, context, profile, "update", started_at, elapsed)


def _service_lines(
    runtime: ContainerRuntime, context: ComposeContext
) -> tuple[ServiceState, ...]:
    """Read service state, image, ports, and exit code for the notification.

    Uses `ps --all` on purpose: a plain `ps` omits containers that exited
    immediately, so a crashed service would vanish from the notification and
    the message would claim everything is healthy. Best-effort as well — an
    unreadable `compose ps` yields no rows instead of failing a successful
    start.
    """
    try:
        result = runtime.run_compose(
            ["ps", "--all", "--format", "json"],
            project=context.project,
            compose_files=context.files,
            env=context.env,
            capture=True,
            check=False,
        )
        entries = parse_compose_ps(result.stdout)
    except (OSError, RuntimeError):
        return ()
    return tuple(
        ServiceState(
            name=_service_name(entry),
            state=_text(entry, "State") or "unknown",
            health=_text(entry, "Health"),
            image=_text(entry, "Image"),
            ports=_published_ports(entry),
            exit_code=_exit_code(entry),
        )
        for entry in entries
    )


def _published_ports(entry: dict[str, Any]) -> tuple[str, ...]:
    """Render `compose ps` Publishers as ``18080→80/tcp`` entries.

    Docker reports each mapping twice (IPv4 and IPv6), so identical
    published/target/protocol triples are collapsed.
    """
    publishers = entry.get("Publishers")
    if not isinstance(publishers, list):
        return ()
    ports: list[str] = []
    for publisher in publishers:
        if not isinstance(publisher, dict):
            continue
        published = publisher.get("PublishedPort")
        target = publisher.get("TargetPort")
        if not published or not target:
            continue  # 0 published means exposed but not published to a host port
        protocol = str(publisher.get("Protocol") or "tcp")
        rendered = f"{published}→{target}" + ("" if protocol == "tcp" else f"/{protocol}")
        if rendered not in ports:
            ports.append(rendered)
    return tuple(ports)


def _exit_code(entry: dict[str, Any]) -> int | None:
    code = entry.get("ExitCode")
    return code if isinstance(code, int) and code != 0 else None


def _volume_infos(
    runtime: ContainerRuntime, context: ComposeContext
) -> tuple[VolumeInfo, ...]:
    """Describe the stack's named volumes: mount points and on-disk size.

    Sizes come from `docker system df -v`, the only Docker surface that reports
    them. It scans every image and volume on the host, so it runs only when the
    compose files actually declare a volume, and any failure just drops the
    sizes rather than the volumes.
    """
    mounts = read_volume_mounts(context.files)
    if not mounts:
        return ()
    found = _volume_sizes(runtime, context.project)
    infos: list[VolumeInfo] = []
    for declared, grouped in _group_mounts(mounts).items():
        runtime_name, size = found.get(declared, (declared, ""))
        infos.append(
            VolumeInfo(
                name=runtime_name,
                mounts=tuple(mount.label for mount in grouped),
                size=size,
            )
        )
    return tuple(infos)


def _group_mounts(mounts: tuple[VolumeMount, ...]) -> dict[str, list[VolumeMount]]:
    grouped: dict[str, list[VolumeMount]] = {}
    for mount in mounts:
        grouped.setdefault(mount.declared, []).append(mount)
    return grouped


def _volume_sizes(runtime: ContainerRuntime, project: str) -> dict[str, tuple[str, str]]:
    """Map a compose volume name to its (runtime name, size) for this project."""
    try:
        result = runtime.run_cli(
            ["system", "df", "-v", "--format", "json"], capture=True, check=False
        )
        if result.returncode != 0:
            return {}
        report = json.loads(result.stdout)
    except (OSError, RuntimeError, json.JSONDecodeError):
        return {}
    if not isinstance(report, dict):
        return {}
    entries = report.get("Volumes")
    if not isinstance(entries, list):
        return {}
    sizes: dict[str, tuple[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        labels = _label_map(entry.get("Labels"))
        if labels.get("com.docker.compose.project") != project:
            continue
        declared = labels.get("com.docker.compose.volume")
        if declared:
            sizes[declared] = (_text(entry, "Name"), _text(entry, "Size"))
    return sizes


def _label_map(raw: Any) -> dict[str, str]:
    """Parse the comma-separated ``key=value`` label blob Docker reports."""
    labels: dict[str, str] = {}
    for part in str(raw or "").split(","):
        name, _, value = part.partition("=")
        if name.strip():
            labels[name.strip()] = value.strip()
    return labels


def _text(entry: dict[str, Any], key: str) -> str:
    """Read a `compose ps` field, tolerating the lower-cased Podman spelling."""
    return str(entry.get(key) or entry.get(key.lower()) or "")


def _notify_started(
    runtime: ContainerRuntime,
    config: Config,
    context: ComposeContext,
    profile: str | None,
    event: str,
    started_at: datetime,
    elapsed: float,
) -> None:
    """Post a Slack notification unless no webhook is configured.

    A stack that never opted in costs nothing: the extra `compose ps` query
    only runs once a webhook resolves (or a configured variable is missing).
    """
    settings = config.notify_slack
    if resolve_webhook(settings) is None and missing_env_name(settings) is None:
        return
    notify_stack_event(
        settings,
        StackEvent(
            kind=event,
            stack=context.project,
            profile=profile or next(iter(config.profiles), ""),
            duration=elapsed,
            runtime=runtime.name,
            host=host_name(),
            started_at=local_timestamp(started_at),
            command=f"stack {event}",
            services=_service_lines(runtime, context),
            volumes=_volume_infos(runtime, context),
        ),
    )


def _service_name(entry: dict[str, Any]) -> str:
    return str(entry.get("Service") or entry.get("ServiceName") or entry.get("Name") or "?")


def _service_readiness(entry: dict[str, Any]) -> tuple[str, bool]:
    state = _text(entry, "State")
    health = _text(entry, "Health")
    ready = state == "running" and health in ("", "none", "healthy")
    return _service_name(entry), ready


def _unready_detail(entries: list[dict[str, Any]]) -> str:
    parts = []
    for entry in entries:
        name, ready = _service_readiness(entry)
        if not ready:
            state = _text(entry, "State") or "unknown"
            health = _text(entry, "Health") or "-"
            parts.append(f"{name}({state}/{health})")
    return ", ".join(parts)


def _wait_until_ready(runtime: ContainerRuntime, context) -> None:
    deadline = time.monotonic() + float(getattr(runtime, "timeout", 300.0))
    last_entries: list[dict[str, Any]] = []
    while True:
        result = runtime.run_compose(
            ["ps", "--format", "json"],
            project=context.project,
            compose_files=context.files,
            env=context.env,
            capture=True,
            check=False,
        )
        last_entries = parse_compose_ps(result.stdout)
        if last_entries and all(_service_readiness(e)[1] for e in last_entries):
            return
        if time.monotonic() >= deadline:
            raise CommandError(
                t(
                    "msg.stack_wait_timeout",
                    seconds=int(float(getattr(runtime, 'timeout', 300.0))),
                    detail=_unready_detail(last_entries),
                )
            )
        time.sleep(1.0)
