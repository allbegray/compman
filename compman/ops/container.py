from __future__ import annotations

import typer

from compman._proc import PASSTHRU_UNBOUNDED
from compman.config import Config
from compman.docker import ContainerRuntime, resolve_compose_context
from compman.i18n import t


def ps(
    runtime: ContainerRuntime,
    config: Config,
    profile: str | None = None,
    all_containers: bool = False,
) -> None:
    context = resolve_compose_context(config, profile)
    args = ["ps"]
    if all_containers:
        args.append("--all")
    runtime.passthru_compose(
        args,
        project=context.project,
        compose_files=context.files,
        env=context.env,
    )


def stats(
    runtime: ContainerRuntime,
    config: Config,
    profile: str | None = None,
    follow: bool = False,
) -> None:
    context = resolve_compose_context(config, profile)
    result = runtime.run_compose(
        ["ps", "--quiet"],
        project=context.project,
        compose_files=context.files,
        env=context.env,
    )
    container_ids = result.stdout.split()
    if not container_ids:
        typer.echo(t("msg.no_running_containers"))
        return
    args = ["stats"]
    if not follow:
        args.append("--no-stream")
    runtime.passthru_cli(
        [*args, *container_ids], timeout=PASSTHRU_UNBOUNDED if follow else None
    )
