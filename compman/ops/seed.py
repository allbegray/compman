from __future__ import annotations

import tarfile
from pathlib import Path

import typer

from compman._seed_assets import SEED_INDEX_HTML
from compman.config import sanitize_project_name
from compman.errors import CommandError
from compman.i18n import t
from compman.ops.common import DEFAULT_SEED_PORT


def generate_seed(
    output: str = "project",
    archive: bool = False,
    port: int = DEFAULT_SEED_PORT,
    force: bool = False,
) -> None:
    if not 1 <= port <= 65535:
        raise CommandError(t("msg.invalid_port", port=port))
    cwd = Path.cwd()
    target_dir = (cwd / output).resolve()

    compman_yml = cwd / "compman.yml"
    compose_yml = cwd / "docker-compose.yml"

    if (compman_yml.exists() or compose_yml.exists()) and not force:
        raise CommandError(t("msg.seed_exists", path="compman.yml / docker-compose.yml"))

    target_dir.mkdir(parents=True, exist_ok=True)

    (target_dir / "index.html").write_text(SEED_INDEX_HTML, encoding="utf-8")

    dockerfile_content = (
        "FROM nginx:alpine\n"
        "COPY index.html /usr/share/nginx/html/index.html\n"
        "EXPOSE 80\n"
    )
    (target_dir / "Dockerfile").write_text(dockerfile_content, encoding="utf-8")

    rel_build_path = f"./{output}" if output != "." else "."
    compose_content = (
        "services:\n"
        "  app:\n"
        f"    build: {rel_build_path}\n"
        "    ports:\n"
        f'      - "127.0.0.1:{port}:80"\n'
        "    restart: unless-stopped\n"
    )
    compose_yml.write_text(compose_content, encoding="utf-8")

    project_name = sanitize_project_name(cwd.name)
    compman_content = (
        "compman:\n"
        f"  name: {project_name}\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n"
    )
    compman_yml.write_text(compman_content, encoding="utf-8")

    typer.echo(t("msg.seed_created", path=output))
    typer.echo("----------------------------------------")
    typer.echo("[compman.yml]")
    typer.echo(compman_content.strip())
    typer.echo("----------------------------------------")
    typer.echo("[docker-compose.yml]")
    typer.echo(compose_content.strip())
    typer.echo("----------------------------------------")

    if archive:
        archive_file = cwd / f"{output}.tar.gz"
        with tarfile.open(archive_file, "w:gz") as tar:
            tar.add(target_dir, arcname=target_dir.name)
        typer.echo(t("msg.seed_archive_created", path=archive_file.name))
