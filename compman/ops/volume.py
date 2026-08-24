from __future__ import annotations

import json
import re
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any

import typer

from compman.archive import extract_tar
from compman.config import Config
from compman.docker import ComposeContext, ContainerRuntime, resolve_compose_context
from compman.errors import CommandError
from compman.i18n import t
from compman.ops.common import select_backup_timestamp, stack_paused, validate_timestamp


def backup(
    runtime: ContainerRuntime,
    config: Config,
    no_stop: bool = False,
    profile: str | None = None,
    compression_level: int = 6,
) -> None:
    context = resolve_compose_context(config, profile)
    if not runtime.stack_exists(config.name, context.files, context.env):
        raise CommandError(t("msg.stack_not_running", name=config.name))
    volumes = runtime.list_volumes(config.name)
    if not volumes:
        typer.echo(t("msg.no_volumes"))
        return
    containers = runtime.list_containers(config.name, context.files, context.env)

    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    backup_name = f"{config.name}.volume.{timestamp}"
    backup_dir = config.backup_dir / backup_name
    tarball = config.backup_dir / f"{backup_name}.tar.gz"
    if backup_dir.exists() or tarball.exists():
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
        backup_name = f"{config.name}.volume.{timestamp}"
        backup_dir = config.backup_dir / backup_name
        tarball = config.backup_dir / f"{backup_name}.tar.gz"
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        with stack_paused(runtime, context, enabled=not no_stop):
            mapping: list[dict[str, str]] = []
            for volume in volumes:
                for container in containers:
                    info = _inspect_mount(runtime, container, volume)
                    if info:
                        mapping.append(info)
                        target = backup_dir / volume
                        runtime.copy_from_container(container, info["destination"], target)

            map_path = backup_dir / "volume-map.json"
            merged = _merge_mapping(mapping)
            map_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")

            with tarfile.open(tarball, "w:gz", compresslevel=compression_level) as tar:
                tar.add(backup_dir, arcname=".")
    finally:
        shutil.rmtree(backup_dir, ignore_errors=True)

    typer.echo(t("msg.backup_done", kind="Volume", path=tarball))


def restore(
    runtime: ContainerRuntime,
    config: Config,
    timestamp: str | None = None,
    no_stop: bool = False,
    profile: str | None = None,
    replace: bool = False,
) -> None:
    context = resolve_compose_context(config, profile)
    if not timestamp:
        timestamp = select_backup_timestamp(config, "volume")

    validate_timestamp(timestamp)
    backup_name = f"{config.name}.volume.{timestamp}"
    tarball = config.backup_dir / f"{backup_name}.tar.gz"
    if not tarball.is_file():
        _list_backups(config, "volume")
        raise CommandError(t("msg.backup_not_found", tarball=tarball))

    if not runtime.stack_exists(config.name, context.files, context.env):
        raise CommandError(t("msg.stack_not_running", name=config.name))

    restore_dir = config.backup_dir / backup_name
    restore_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(tarball, "r:gz") as tar:
            extract_tar(tar, restore_dir)

        map_path = restore_dir / "volume-map.json"
        if not map_path.is_file():
            raise CommandError(t("msg.volume_map_not_found", path=map_path))

        mapping = _load_mapping(map_path)
        _validate_mapping_entries(mapping, restore_dir, config, runtime, context)

        if replace:
            for vol_info in mapping:
                container = vol_info["container"]
                volume_name = vol_info["volume"]
                dest = vol_info["destination"]
                src = restore_dir / volume_name
                if src.is_dir():
                    _clear_destination(runtime, container, dest)

        with stack_paused(runtime, context, enabled=not no_stop):
            for vol_info in mapping:
                container = vol_info["container"]
                volume_name = vol_info["volume"]
                dest = vol_info["destination"]
                src = restore_dir / volume_name
                if not src.is_dir():
                    typer.echo(t("msg.warning_missing_data", path=src, container=container))
                    continue
                typer.echo(t("msg.restoring_data", container=container, destination=dest))
                runtime.copy_to_container(f"{src}/.", container, dest)

            for vol_info in mapping:
                container = vol_info["container"]
                volume_name = vol_info["volume"]
                dest = vol_info["destination"]
                src = restore_dir / volume_name
                if not src.is_dir():
                    continue
                runtime.fix_permissions(container, dest)
    finally:
        shutil.rmtree(restore_dir, ignore_errors=True)

    typer.echo(t("msg.restore_done", kind="Volume"))


def pull(runtime: ContainerRuntime, config: Config, profile: str | None = None) -> None:
    context = resolve_compose_context(config, profile)
    if not runtime.stack_exists(config.name, context.files, context.env):
        raise CommandError(t("msg.stack_not_running", name=config.name))
    volumes = runtime.list_volumes(config.name)
    if not volumes:
        typer.echo(t("msg.no_volumes"))
        return
    containers = runtime.list_containers(config.name, context.files, context.env)

    volume_dir = config.volume_dir
    if volume_dir.is_dir():
        shutil.rmtree(volume_dir)
    volume_dir.mkdir(parents=True)

    mapping: list[dict[str, str]] = []
    for volume in volumes:
        for container in containers:
            info = _inspect_mount(runtime, container, volume)
            if info:
                mapping.append(info)
                target = volume_dir / volume
                runtime.copy_from_container(container, info["destination"], target)

    map_path = volume_dir / "volume-map.json"
    merged = _merge_mapping(mapping)
    map_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.echo(t("msg.restore_done", kind="Volume pull"))


def push(
    runtime: ContainerRuntime,
    config: Config,
    profile: str | None = None,
    replace: bool = False,
) -> None:
    context = resolve_compose_context(config, profile)
    volume_dir = config.volume_dir
    map_path = volume_dir / "volume-map.json"
    if not map_path.is_file():
        raise CommandError(t("msg.volume_map_not_found", path=map_path))
    if not runtime.stack_exists(config.name, context.files, context.env):
        raise CommandError(t("msg.stack_not_running", name=config.name))

    mapping = _load_mapping(map_path)
    _validate_mapping_entries(mapping, volume_dir, config, runtime, context)
    for vol_info in mapping:
        container = vol_info["container"]
        volume_name = vol_info["volume"]
        dest = vol_info["destination"]
        src = volume_dir / volume_name
        if not src.is_dir():
            typer.echo(t("msg.warning_missing_source", path=src, container=container))
            continue
        typer.echo(t("msg.pushing_data", container=container, destination=dest))
        if replace:
            _clear_destination(runtime, container, dest)
        runtime.copy_to_container(f"{src}/.", container, dest)
        runtime.fix_permissions(container, dest)
    typer.echo(t("msg.restore_done", kind="Volume push"))


def _inspect_mount(
    runtime: ContainerRuntime, container: str, volume: str
) -> dict[str, str] | None:
    result = runtime.inspect_container(container, check=False)
    if result.returncode != 0:
        return None
    data = json.loads(result.stdout)
    if not data:
        return None
    for mount in data[0].get("Mounts", []):
        if mount.get("Name") == volume:
            return {
                "container": container,
                "volume": volume,
                "destination": mount["Destination"],
            }
    return None


def _merge_mapping(mapping: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep every mount; a container can legitimately have several volumes."""
    return mapping


def _load_mapping(path) -> list[dict[str, str]]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        result = raw
    elif isinstance(raw, dict):
        # Backward compatibility with backups produced before the mapping was
        # changed to a list. Those archives can contain one mount per container.
        result = [
            {"container": str(container), **info}
            for container, info in raw.items()
            if isinstance(info, dict)
        ]
    else:
        raise CommandError(f"Invalid volume map in {path}: expected a list or mapping")

    required = {"container", "volume", "destination"}
    if any(not isinstance(item, dict) or not required.issubset(item) for item in result):
        raise CommandError(f"Invalid volume map in {path}: missing required fields")
    return [{key: str(item[key]) for key in required} for item in result]


def _list_backups(config: Config, kind: str) -> None:
    pattern = f"{config.name}.{kind}."
    typer.echo(t("msg.available_backups", kind=kind))
    for f in sorted(config.backup_dir.glob(f"{pattern}*.tar.gz")):
        name = f.name
        ts = name.replace(pattern, "").replace(".tar.gz", "")
        typer.echo(f"  {ts}")  # ponytail: color omitted, typer handles terminal


def _validate_replace_dest(dest: str) -> None:
    parts = dest.split("/")[1:]
    if not dest.startswith("/") or dest == "/" or not parts or "" in parts or ".." in parts:
        raise CommandError(t("msg.invalid_replace_dest", dest=dest))


_CONTAINER_NAME_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*")


def _validate_mapping_entries(
    mapping: list[dict[str, str]],
    base_dir: Path,
    config: Config,
    runtime: ContainerRuntime,
    context: ComposeContext,
) -> None:
    containers = set(runtime.list_containers(config.name, context.files, context.env))
    base = base_dir.resolve()
    for entry in mapping:
        target = (base_dir / entry["volume"]).resolve()
        if target == base or base not in target.parents:
            raise CommandError(t("msg.volume_map_escape", name=entry["volume"]))
        container = entry["container"]
        if not _CONTAINER_NAME_RE.fullmatch(container) or container not in containers:
            raise CommandError(t("msg.volume_map_container", container=container, name=config.name))
        _validate_replace_dest(entry["destination"])


def _clear_destination(runtime: ContainerRuntime, container: str, dest: str) -> None:
    _validate_replace_dest(dest)
    runtime.run_cli(
        [
            "exec",
            container,
            "sh",
            "-c",
            'rm -rf -- "$1"/* "$1"/.[!.]* "$1"/..?* 2>/dev/null || true',
            "_",
            dest,
        ],
        capture=True,
        check=False,
    )
