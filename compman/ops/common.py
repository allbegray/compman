from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

import typer

from compman.config import Config
from compman.docker import ComposeContext, ContainerRuntime, resolve_compose_context
from compman.errors import CommandError
from compman.i18n import t

DEFAULT_SEED_PORT = 18080


@dataclass(frozen=True)
class VolumeTargets:
    """Volumes and containers of a running stack, with its compose context."""

    context: ComposeContext
    volumes: tuple[str, ...]
    containers: tuple[str, ...]


def require_stack(
    runtime: ContainerRuntime,
    config: Config,
    profile: str | None = None,
    *,
    context: ComposeContext | None = None,
) -> ComposeContext:
    """Resolve the compose context and require the stack to exist."""
    if context is None:
        context = resolve_compose_context(config, profile)
    if not runtime.stack_exists(config.name, context.files, context.env):
        raise CommandError(t("msg.stack_not_running", name=config.name))
    return context


def resolve_volume_targets(
    runtime: ContainerRuntime,
    config: Config,
    profile: str | None = None,
) -> VolumeTargets | None:
    """Require a running stack and collect its volumes and containers."""
    context = require_stack(runtime, config, profile)
    volumes = runtime.list_volumes(config.name)
    if not volumes:
        typer.echo(t("msg.no_volumes"))
        return None
    containers = runtime.list_containers(config.name, context.files, context.env)
    return VolumeTargets(context=context, volumes=tuple(volumes), containers=tuple(containers))


def unique_backup_paths(config: Config, kind: str) -> tuple[Path, Path]:
    """Return a fresh (directory, tarball) pair under the backup directory."""
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    backup_name = f"{config.name}.{kind}.{timestamp}"
    backup_dir = config.backup_dir / backup_name
    tarball = config.backup_dir / f"{backup_name}.tar.gz"
    if backup_dir.exists() or tarball.exists():
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
        backup_name = f"{config.name}.{kind}.{timestamp}"
        backup_dir = config.backup_dir / backup_name
        tarball = config.backup_dir / f"{backup_name}.tar.gz"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir, tarball


def collect_mounts(
    runtime: ContainerRuntime,
    volumes: Sequence[str],
    containers: Sequence[str],
    target_dir: Path,
    *,
    inspect_mount: Callable[[ContainerRuntime, str, str], dict[str, str] | None],
) -> list[dict[str, str]]:
    """Map every volume mount and copy the data into ``target_dir``."""
    mapping: list[dict[str, str]] = []
    for volume in volumes:
        for container in containers:
            info = inspect_mount(runtime, container, volume)
            if info:
                mapping.append(info)
                target = target_dir / volume
                runtime.copy_from_container(container, info["destination"], target)
    return mapping


def write_volume_map(
    directory: Path,
    mapping: list[dict[str, str]],
    *,
    merge: Callable[[list[dict[str, str]]], list[dict[str, str]]],
) -> None:
    """Write the merged volume-map.json into ``directory``."""
    map_path = directory / "volume-map.json"
    merged = merge(mapping)
    map_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")


def validate_timestamp(ts: str) -> None:
    if not any(
        _valid_timestamp(ts, fmt)
        for fmt in ("%Y%m%d_%H%M", "%Y%m%d_%H%M%S", "%Y%m%d_%H%M%S_%f")
    ):
        raise CommandError(t("msg.invalid_timestamp", ts=ts))


def _valid_timestamp(value: str, fmt: str) -> bool:
    try:
        datetime.strptime(value, fmt)
        return True
    except ValueError:
        return False


def ensure_runtime_ready(runtime: ContainerRuntime) -> None:
    runtime.ensure_ready_for_start(
        lambda: typer.confirm(
            t("msg.docker_desktop_prompt"), default=True, abort=False
        )
    )


def get_key() -> str:
    if sys.platform == "win32":
        import msvcrt

        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            ch2 = msvcrt.getch()
            if ch2 == b"H":
                return "up"
            elif ch2 == b"P":
                return "down"
            return "other"
        elif ch in (b"\r", b"\n"):
            return "enter"
        elif ch == b"\x1b":
            return "esc"
        elif ch == b"\x03":
            raise KeyboardInterrupt()
        elif ch in b"123456789":
            return ch.decode()
        return "other"
    else:
        import os
        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = os.read(fd, 1)
            if ch == b"\x1b":
                seq = b"\x1b"
                while len(seq) < 8:
                    rlist, _, _ = select.select([fd], [], [], 0.2)
                    if not rlist:
                        break
                    seq += os.read(fd, 1)
                if seq.startswith(b"\x1b[A") or seq.startswith(b"\x1bOA"):
                    return "up"
                if seq.startswith(b"\x1b[B") or seq.startswith(b"\x1bOB"):
                    return "down"
                return "esc"
            elif ch in (b"\r", b"\n"):
                return "enter"
            elif ch == b"\x03":
                raise KeyboardInterrupt()
            elif ch in b"123456789":
                return ch.decode()
            return "other"
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def prompt_select(title: str, options: list[str], default_index: int = 0) -> int:
    if not sys.stdin.isatty():
        typer.echo(title)
        for i, opt in enumerate(options, 1):
            typer.echo(f"  [{i}] {opt}")
        choice = typer.prompt(t("msg.select_option", count=len(options)), default=str(default_index + 1))
        return int(choice) - 1 if choice.isdigit() and 1 <= int(choice) <= len(options) else default_index

    selected = default_index

    def render(redraw: bool = False) -> None:
        if redraw:
            sys.stdout.write(f"\033[{len(options)}A")
        for i, option in enumerate(options):
            if i == selected:
                sys.stdout.write(f"\033[K \033[36m> {option}\033[0m\n")
            else:
                sys.stdout.write(f"\033[K   {option}\n")
        sys.stdout.flush()

    typer.echo(t("msg.prompt_nav", title=title))
    render(redraw=False)

    while True:
        try:
            key = get_key()
            if key == "up":
                selected = (selected - 1) % len(options)
                render(redraw=True)
            elif key == "down":
                selected = (selected + 1) % len(options)
                render(redraw=True)
            elif key.isdigit() and 1 <= int(key) <= len(options):
                selected = int(key) - 1
                break
            elif key == "enter":
                break
            elif key == "esc":
                typer.echo(t("msg.operation_cancelled"))
                raise SystemExit(0)
        except KeyboardInterrupt:
            typer.echo("")
            raise SystemExit(0)

    return selected


def select_backup_timestamp(config: Config, kind: str) -> str:
    pattern = f"{config.name}.{kind}."
    if not config.backup_dir.is_dir():
        raise CommandError(t("msg.backup_dir_not_found", path=config.backup_dir))

    files = sorted(config.backup_dir.glob(f"{pattern}*.tar.gz"))
    if not files:
        raise CommandError(t("msg.no_backups", kind=kind, path=config.backup_dir))

    timestamps = [f.name.replace(pattern, "").replace(".tar.gz", "") for f in files]

    idx = prompt_select(
        t("msg.available_backups_title", kind=kind),
        timestamps,
        default_index=len(timestamps) - 1,
    )
    selected = timestamps[idx]
    typer.echo(t("msg.selected_backup", name=selected))
    return selected


@contextmanager
def stack_paused(runtime: ContainerRuntime, context: ComposeContext, enabled: bool = True):
    stopped = False
    if enabled:
        typer.echo(t("msg.stack_stopping"))
        runtime.run_compose(
            ["stop"], project=context.project, compose_files=context.files,
            env=context.env, capture=False,
        )
        stopped = True
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        if stopped:
            try:
                typer.echo(t("msg.stack_starting"))
                runtime.run_compose(
                    ["start"], project=context.project, compose_files=context.files,
                    env=context.env, capture=False,
                )
            except Exception as error:
                if not failed:
                    raise
                typer.echo(t("msg.stack_restart_failed", error=error), err=True)
