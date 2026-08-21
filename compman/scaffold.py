from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import typer
import yaml

from compman.config import sanitize_project_name
from compman.i18n import t


def generate(root: Path, project_subfolder: str, s3_path: str, image: str) -> None:
    compman_yml = root / "compman.yml"
    if not compman_yml.exists():
        content = (
            f"compman:\n"
            f"  name: {sanitize_project_name(root.name)}\n"
            f"  deploy: {s3_path}\n"
            f"  dirs:\n"
            f"    project: {project_subfolder}\n"
            f"  compose:\n"
            f"    default:\n"
            f"      file: docker-compose.yml\n"
        )
        compman_yml.write_text(content, encoding="utf-8")
        typer.echo(t("msg.created_compman"))
        typer.echo(f"----------------------------------------\n{content.strip()}\n----------------------------------------")
    else:
        update_deploy(compman_yml, s3_path)

    deploy_target = root / project_subfolder
    sub_compose = deploy_target / "docker-compose.yml"
    root_compose = root / "docker-compose.yml"

    if sub_compose.exists():
        shutil.move(str(sub_compose), str(root_compose))

    if not root_compose.exists():
        compose_content = (
            f"services:\n"
            f"  app:\n"
            f"    image: {image}\n"
            f"    ports:\n"
            f"      - \"127.0.0.1:18080:18080\"\n"
            f"    restart: unless-stopped\n"
        )
        root_compose.write_text(compose_content, encoding="utf-8")
        typer.echo(t("msg.created_compose"))
        typer.echo(f"----------------------------------------\n{compose_content.strip()}\n----------------------------------------")


def update_deploy(compman_yml: Path, s3_path: str | dict[str, Any]) -> None:
    content = compman_yml.read_text(encoding="utf-8-sig")
    try:
        raw = yaml.safe_load(content)
    except Exception:
        raw = None

    if isinstance(raw, dict) and isinstance(raw.get("compman"), dict):
        if raw["compman"].get("deploy") == s3_path:
            return

    if isinstance(s3_path, dict):
        deploy_dict: dict[str, Any] = s3_path
        if isinstance(raw, dict) and isinstance(raw.get("compman"), dict):
            raw["compman"]["deploy"] = deploy_dict
            dumped = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
            assert yaml.safe_load(dumped)["compman"]["deploy"] == deploy_dict
            compman_yml.write_text(dumped, encoding="utf-8")
            typer.echo(t("msg.updated_deploy", s3_path=deploy_dict))
            typer.echo(f"----------------------------------------\n{dumped.strip()}\n----------------------------------------")
            return
        minimal: dict[str, Any] = {"compman": {"deploy": deploy_dict}}
        dumped = yaml.safe_dump(minimal, sort_keys=False, allow_unicode=True)
        assert yaml.safe_load(dumped)["compman"]["deploy"] == deploy_dict
        compman_yml.write_text(dumped, encoding="utf-8")
        typer.echo(t("msg.updated_deploy", s3_path=deploy_dict))
        typer.echo(f"----------------------------------------\n{dumped.strip()}\n----------------------------------------")
        return

    lines = content.splitlines(keepends=True)
    updated = False
    new_lines = []
    in_compman = False
    compman_indent = 0

    for line in lines:
        stripped = line.strip()
        if re.match(r"^compman\s*:", line):
            in_compman = True
            compman_indent = len(line) - len(line.lstrip())
            new_lines.append(line)
            continue
        if in_compman:
            current_indent = len(line) - len(line.lstrip())
            if stripped and not stripped.startswith("#") and current_indent <= compman_indent:
                in_compman = False
            elif re.match(r"^\s*deploy\s*:", line):
                indent = " " * (len(line) - len(line.lstrip()))
                new_lines.append(f"{indent}deploy: {s3_path}\n")
                updated = True
                continue
        new_lines.append(line)

    if not updated:
        final_lines = []
        inserted = False
        in_compman = False
        for line in lines:
            final_lines.append(line)
            if not inserted and re.match(r"^compman\s*:", line):
                in_compman = True
                continue
            if in_compman and not inserted and line.strip() and not line.strip().startswith("#"):
                indent = " " * (len(line) - len(line.lstrip()))
                final_lines.append(f"{indent}deploy: {s3_path}\n")
                inserted = True
                in_compman = False
        if not inserted:
            final_lines.append(f"  deploy: {s3_path}\n")
        lines = final_lines
    else:
        lines = new_lines

    new_content = "".join(lines)
    try:
        check_raw = yaml.safe_load(new_content)
        if isinstance(check_raw, dict) and check_raw.get("compman", {}).get("deploy") == s3_path:
            compman_yml.write_text(new_content, encoding="utf-8")
            typer.echo(t("msg.updated_deploy", s3_path=s3_path))
            typer.echo(f"----------------------------------------\n{new_content.strip()}\n----------------------------------------")
            return
    except Exception:
        pass

    if isinstance(raw, dict) and isinstance(raw.get("compman"), dict):
        raw["compman"]["deploy"] = s3_path
        dumped = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
        compman_yml.write_text(dumped, encoding="utf-8")
        typer.echo(t("msg.updated_deploy", s3_path=s3_path))
        typer.echo(f"----------------------------------------\n{dumped.strip()}\n----------------------------------------")
