from __future__ import annotations

import tarfile
from pathlib import Path

import typer

from compman.config import sanitize_project_name
from compman.errors import CommandError
from compman.i18n import t


def generate_seed(
    output: str = "project",
    archive: bool = False,
    port: int = 18080,
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

    index_html_content = (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '    <meta charset="UTF-8">\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">\n'
        '    <meta http-equiv="Pragma" content="no-cache">\n'
        '    <meta http-equiv="Expires" content="0">\n'
        '    <title>compman Seed App</title>\n'
        '    <style>\n'
        '        body { font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }\n'
        '        .card { background: #1e293b; border-radius: 1rem; padding: 2.5rem; border: 1px solid #334155; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5); text-align: center; max-width: 480px; width: 100%; }\n'
        '        h1 { color: #38bdf8; margin-top: 0; font-size: 1.75rem; }\n'
        '        .badge { background: #0284c7; color: white; padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.875rem; font-weight: 600; }\n'
        '        .time { font-size: 1.15rem; font-family: monospace; color: #a5f3fc; margin: 1.5rem 0; background: #0f172a; padding: 0.75rem; border-radius: 0.5rem; border: 1px solid #1e293b; }\n'
        '    </style>\n'
        '</head>\n'
        '<body>\n'
        '    <div class="card">\n'
        '        <h1>compman Seed App</h1>\n'
        '        <p><span class="badge">Nginx Alpine High-Performance</span></p>\n'
        '        <div class="time" id="clock">Loading time...</div>\n'
        '        <p style="color: #94a3b8; font-size: 0.875rem;">Instant Sub-Millisecond Container Response</p>\n'
        '    </div>\n'
        '    <script>\n'
        '        function updateTime() {\n'
        '            document.getElementById("clock").innerText = new Date().toLocaleString();\n'
        '        }\n'
        '        setInterval(updateTime, 1000);\n'
        '        updateTime();\n'
        '    </script>\n'
        '</body>\n'
        '</html>\n'
    )
    (target_dir / "index.html").write_text(index_html_content, encoding="utf-8")

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
