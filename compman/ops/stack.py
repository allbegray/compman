from __future__ import annotations

import time
from typing import Any

import typer

from compman.config import Config
from compman.docker import ContainerRuntime, resolve_compose_context
from compman.errors import CommandError
from compman.i18n import t
from compman.ops.common import ensure_runtime_ready, parse_compose_ps


def up(runtime: ContainerRuntime, config: Config, profile: str | None = None, wait: bool = False) -> None:
    context = resolve_compose_context(config, profile)
    ensure_runtime_ready(runtime)
    runtime.passthru_compose(
        ["up", "-d", "--force-recreate"],
        project=context.project,
        compose_files=context.files,
        env=context.env,
    )
    if wait:
        _wait_until_ready(runtime, context)


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
    runtime.passthru_compose(
        ["up", "-d", "--build", "--force-recreate"],
        project=context.project,
        compose_files=context.files,
        env=context.env,
    )
    if wait:
        _wait_until_ready(runtime, context)


def _service_readiness(entry: dict[str, Any]) -> tuple[str, bool]:
    name = str(entry.get("Service") or entry.get("ServiceName") or entry.get("Name") or "?")
    state = str(entry.get("State") or entry.get("state") or "")
    health = str(entry.get("Health") or entry.get("health") or "")
    ready = state == "running" and health in ("", "none", "healthy")
    return name, ready


def _unready_detail(entries: list[dict[str, Any]]) -> str:
    parts = []
    for entry in entries:
        name, ready = _service_readiness(entry)
        if not ready:
            state = str(entry.get("State") or entry.get("state") or "unknown")
            health = str(entry.get("Health") or entry.get("health") or "-")
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
