from __future__ import annotations

import pathlib
from typing import Annotated

import typer

from compman.i18n import t


def register(app: typer.Typer, deploy_cb, dump_config_cb) -> None:
    @app.command("init", help=t("cmd.init"))
    def init_cmd(
        scaffold: Annotated[bool, typer.Option("--scaffold", help=t("opt.scaffold"))] = False,
        s3: Annotated[str | None, typer.Option("--s3", help=t("opt.s3"))] = None,
        seed_mode: Annotated[bool, typer.Option("--seed", help=t("opt.seed"))] = False,
        output: Annotated[str, typer.Option("-o", "--output", help=t("opt.output"))] = "project",
        archive: Annotated[bool, typer.Option("-a", "--archive", help=t("opt.archive"))] = False,
        port: Annotated[int, typer.Option("-p", "--port", help=t("opt.port"))] = 18080,
        build: Annotated[bool, typer.Option("--build", help=t("opt.build"))] = False,
        tag: Annotated[str | None, typer.Option("--tag", help=t("opt.tag"))] = None,
        force: Annotated[bool, typer.Option("--force", help=t("opt.force"))] = False,
        config: Annotated[str, typer.Option("--config", "-c", help=t("opt.config"))] = "compman.yml",
    ) -> None:
        from compman.ops.common import prompt_select

        # Direct mode routing if explicit flag passed
        if scaffold:
            choice = 0
        elif s3 is not None:
            choice = 1
        elif seed_mode or archive:
            choice = 2
        else:
            # Interactive mode selection
            modes = [
                t("msg.init_mode_scaffold"),
                t("msg.init_mode_s3"),
                t("msg.init_mode_seed"),
            ]
            choice = prompt_select(t("msg.init_select_mode"), modes, default_index=0)

        if choice == 0:
            # Mode 1: Scaffold compman.yml
            path = pathlib.Path(config)
            if path.is_file() and not force:
                typer.echo(t("msg.config_exists", config=config))
                return
            content = dump_config_cb(pathlib.Path.cwd().name)
            path.write_text(content, encoding="utf-8")
            typer.echo(t("msg.config_created", config=config, content=content.strip()))

        elif choice == 1:
            # Mode 2: S3 URL
            s3_url = s3
            if not s3_url:
                s3_url = typer.prompt(t("msg.enter_s3_url"))
            # Resolve _deploy through compman.cli at call time so tests that
            # patch compman.cli._deploy keep intercepting the deploy path.
            from compman import cli as _cli

            _cli._deploy(build=build, tag=tag, s3_path=s3_url)

        elif choice == 2:
            # Mode 3: Test Seed Project
            from compman.ops import seed

            seed.generate_seed(output=output, archive=archive, port=port, force=force)
