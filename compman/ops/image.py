from __future__ import annotations

import shutil
from typing import Any

import typer

from compman.archive import create_tar, extract_tar, open_tarball
from compman.backup_store import (
    LocalBackupStore,
    archive_location,
    find_archive,
    new_backup_paths,
    put_archive,
    staged_archive,
)
from compman.config import Config
from compman.docker import ContainerRuntime, resolve_compose_context
from compman.errors import CommandError
from compman.history import append as append_journal
from compman.i18n import t
from compman.ops.common import echo_available_backups, prune_archives, select_backup_timestamp, validate_timestamp


def _journal(action: str, **fields: Any) -> None:
    """Best-effort activity-journal write: warn on stderr, never raise."""
    try:
        append_journal(action, **fields)
    except Exception as e:
        typer.echo(t("msg.command_failed", error=e), err=True)


def backup(
    runtime: ContainerRuntime,
    config: Config,
    source_mode: bool = False,
    profile: str | None = None,
    compression_level: int = 6,
    zstd_format: bool = False,
) -> None:
    context = resolve_compose_context(config, profile)
    if not runtime.stack_exists(config.name, context.files, context.env):
        raise CommandError(t("msg.stack_not_running", name=config.name))

    backup_dir, tarball = new_backup_paths(
        config.backup_store, config.name, "image", zstd_format=zstd_format
    )
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

        create_tar(backup_dir, tarball, zstd_format=zstd_format, gzip_level=compression_level)
    except Exception:
        tarball.unlink(missing_ok=True)
        raise
    finally:
        for tag in backup_tags:
            runtime.remove_image(tag)
        if isinstance(config.backup_store, LocalBackupStore):
            shutil.rmtree(backup_dir, ignore_errors=True)

    location = put_archive(config.backup_store, tarball.name, tarball)
    typer.echo(t("msg.backup_done", kind="Image", path=location))
    prune_archives(config, config.backup_store, config.name, "image")
    _journal("backup", kind="image", stack=config.name, archive=tarball.name)


def restore(
    runtime: ContainerRuntime,
    config: Config,
    timestamp: str | None = None,
    profile: str | None = None,
) -> None:
    if not timestamp:
        timestamp = select_backup_timestamp(config, "image")

    validate_timestamp(timestamp)

    store = config.backup_store
    backup_name = f"{config.name}.image.{timestamp}"
    archive_name = find_archive(store, config.name, "image", timestamp)
    if archive_name is None:
        echo_available_backups(config, "image")
        raise CommandError(
            t("msg.backup_not_found", tarball=archive_location(store, f"{backup_name}.tar.gz"))
        )

    with staged_archive(store, archive_name) as tarball:
        restore_dir = tarball.parent / backup_name
        restore_dir.mkdir(parents=True)
        try:
            with open_tarball(tarball) as tar:
                extract_tar(tar, restore_dir)

            for tar_file in restore_dir.glob("*.tar"):
                typer.echo(t("msg.loading_image", name=tar_file.name))
                runtime.load_image(tar_file)
        finally:
            shutil.rmtree(restore_dir, ignore_errors=True)
    typer.echo(t("msg.restore_done", kind="Image") + " " + t("msg.image_restore_hint"))
    _journal("restore", kind="image", stack=config.name, timestamp=timestamp)
