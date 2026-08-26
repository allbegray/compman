from __future__ import annotations

import json

import typer

from compman._proc import PASSTHRU_UNBOUNDED
from compman.config import Config
from compman.docker import ContainerRuntime, resolve_compose_context
from compman.errors import CommandError
from compman.i18n import t
from compman.ops.common import parse_compose_ps, utc_now_iso


def ps(
    runtime: ContainerRuntime,
    config: Config,
    profile: str | None = None,
    all_containers: bool = False,
    json_output: bool = False,
) -> None:
    context = resolve_compose_context(config, profile)
    if json_output:
        result = runtime.run_compose(
            ["ps", "--format", "json", "--all"] if all_containers else ["ps", "--format", "json"],
            project=context.project,
            compose_files=context.files,
            env=context.env,
        )
        payload = {
            "schema_version": 1,
            "generated_at": utc_now_iso(),
            "stack": context.project,
            "containers": parse_compose_ps(result.stdout),
        }
        typer.echo(json.dumps(payload))
        return
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
    json_output: bool = False,
) -> None:
    if follow and json_output:
        raise CommandError(t("msg.stats_follow_json"))
    context = resolve_compose_context(config, profile)
    result = runtime.run_compose(
        ["ps", "--quiet"],
        project=context.project,
        compose_files=context.files,
        env=context.env,
    )
    container_ids = result.stdout.split()
    if not container_ids:
        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "schema_version": 1,
                        "generated_at": utc_now_iso(),
                        "stack": context.project,
                        "stats": [],
                    }
                )
            )
            return
        typer.echo(t("msg.no_running_containers"))
        return
    if json_output:
        result = runtime.run_compose(
            ["stats", "--format", "json", "--no-stream", *container_ids],
            project=context.project,
            compose_files=context.files,
            env=context.env,
        )
        entries = parse_compose_ps(result.stdout)
        typer.echo(
            json.dumps(
                {
                    "schema_version": 1,
                    "generated_at": utc_now_iso(),
                    "stack": context.project,
                    "stats": entries,
                }
            )
        )
        return
    args = ["stats"]
    if not follow:
        args.append("--no-stream")
    runtime.passthru_cli(
        [*args, *container_ids], timeout=PASSTHRU_UNBOUNDED if follow else None
    )
