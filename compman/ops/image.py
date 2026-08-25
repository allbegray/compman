from __future__ import annotations

import shutil
import tarfile

import typer

from compman.archive import extract_tar
from compman.config import Config
from compman.docker import ContainerRuntime, resolve_compose_context
from compman.errors import CommandError
from compman.i18n import t
from compman.ops.common import select_backup_timestamp, unique_backup_paths, validate_timestamp


def backup(
    runtime: ContainerRuntime,
    config: Config,
    source_mode: bool = False,
    profile: str | None = None,
    compression_level: int = 6,
) -> None:
    context = resolve_compose_context(config, profile)
    if not runtime.stack_exists(config.name, context.files, context.env):
        raise CommandError(t("msg.stack_not_running", name=config.name))

    backup_dir, tarball = unique_backup_paths(config, "image")
    backup_tags: list[str] = []

    try:
        result = runtime.run_compose(
            ["ps", "-q"], project=context.project, compose_files=context.files, env=context.env, capture=True
        )
        container_ids = result.stdout.strip().splitlines()
        if not container_ids:
            typer.echo(t("msg.no_running_containers"))
            return

        for cid in container_ids:
            cid = cid.strip()
            if not cid:
                continue
            container_name = runtime.inspect_value(cid, "{{.Name}}").strip("/")

            if source_mode:
                image_id = runtime.inspect_value(cid, "{{.Image}}")
                runtime.save_image(
                    image_id, backup_dir / f"{container_name}.image.backup.tar"
                )
            else:
                tag = f"{container_name}:backup"
                backup_tags.append(tag)
                runtime.commit_container(cid, tag)
                runtime.save_image(tag, backup_dir / f"{container_name}.image.backup.tar")

        with tarfile.open(tarball, "w:gz", compresslevel=compression_level) as tar:
            tar.add(backup_dir, arcname=".")
    except Exception:
        tarball.unlink(missing_ok=True)
        raise
    finally:
        for tag in backup_tags:
            runtime.remove_image(tag)
        shutil.rmtree(backup_dir, ignore_errors=True)

    typer.echo(t("msg.backup_done", kind="Image", path=tarball))


def restore(
    runtime: ContainerRuntime,
    config: Config,
    timestamp: str | None = None,
    profile: str | None = None,
) -> None:
    if not timestamp:
        timestamp = select_backup_timestamp(config, "image")

    validate_timestamp(timestamp)

    backup_name = f"{config.name}.image.{timestamp}"
    tarball = config.backup_dir / f"{backup_name}.tar.gz"
    if not tarball.is_file():
        _list_backups(config)
        raise CommandError(t("msg.backup_not_found", tarball=tarball))

    restore_dir = config.backup_dir / backup_name
    restore_dir.mkdir(parents=True)
    try:
        with tarfile.open(tarball, "r:gz") as tar:
            extract_tar(tar, restore_dir)

        for tar_file in restore_dir.glob("*.tar"):
            typer.echo(t("msg.loading_image", name=tar_file.name))
            runtime.load_image(tar_file)
    finally:
        shutil.rmtree(restore_dir, ignore_errors=True)
    typer.echo(t("msg.restore_done", kind="Image") + " " + t("msg.image_restore_hint"))


def _list_backups(config: Config) -> None:
    typer.echo(t("msg.available_backups", kind="image"))
    for f in sorted(config.backup_dir.glob(f"{config.name}.image.*.tar.gz")):
        ts = f.name.replace(f"{config.name}.image.", "").replace(".tar.gz", "")
        typer.echo(f"  {ts}")
