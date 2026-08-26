from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import typer

from compman.archive_source import has_archive_suffix
from compman.config import SHA256_PATTERN, Config, ConfigError, load_config, sanitize_project_name
from compman.docker import ContainerRuntime, detect_runtime
from compman.errors import CommandError
from compman.history import append as append_history
from compman.http_source import fetch as _fetch_http
from compman.i18n import t
from compman.ops.common import ensure_runtime_ready
from compman.s3_source import create_client, s3_error_hint
from compman.s3_source import download as _download  # noqa: F401
from compman.s3_source import download_recursive as _download_recursive  # noqa: F401
from compman.s3_source import fetch as _fetch
from compman.scaffold import generate as _generate_scaffold
from compman.scaffold import update_deploy as _update_compman_deploy  # noqa: F401
from compman.stack_registry import record as record_stack


def deploy(
    build: bool = False,
    tag: str | None = None,
    s3_path: str | None = None,
    config: Config | None = None,
    runtime: ContainerRuntime | None = None,
    sha256: str | None = None,
) -> None:
    """Fetch an application package, swap the managed tree, and scaffold it.

    Before the new tree lands, the previous managed tree and the previous
    root ``compman.yml`` bytes are captured into ``<root>/.compman/rollback``
    (replacing any earlier snapshot). A scaffold-generation failure AFTER the
    swap therefore remains recoverable with ``compman rollback``. Snapshot
    capture problems warn and continue; they never fail the deploy.
    """
    parse_error: ConfigError | None = None
    if config is None and (Path.cwd() / "compman.yml").exists():
        try:
            config = load_config()
        except ConfigError as e:
            parse_error = e

    if not s3_path and config:
        s3_path = config.deploy

    if not s3_path and not config:
        if parse_error is not None:
            typer.echo(t("msg.deploy_config_invalid", err=parse_error), err=True)
            raise typer.Exit(1)


        try:
            s3_path = load_config().deploy
        except ConfigError:
            typer.echo(t("msg.empty_dir_deploy"), err=True)
            typer.echo("", err=True)
            typer.echo(t("msg.empty_dir_start"), err=True)
            typer.echo(t("msg.deploy_direct_hint"), err=True)
            typer.echo("     compman deploy --path s3://<your-bucket>/path/to/app.tar.gz", err=True)
            typer.echo(t("msg.config_hint"), err=True)
            typer.echo("     compman init", err=True)
            raise CommandError("", code=1) from None
    if not s3_path:
        typer.echo(t("msg.deploy_path_not_configured"), err=True)
        typer.echo(t("msg.deploy_path_hint1"), err=True)
        typer.echo(t("msg.deploy_path_hint2"), err=True)
        raise CommandError("", code=1)

    project_subfolder = config.dirs.get("project", "project") if config else "project"

    root = Path.cwd()
    deploy_target = config.deploy_dir if config else root / project_subfolder

    tmp = Path(tempfile.mkdtemp(prefix=".deploy_tmp_", dir=root))

    parsed = urlparse(s3_path)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")

    stage = "validating the deploy source"
    limit_mb = config.max_archive_mb if config else None
    max_bytes = limit_mb * 1024 * 1024 if limit_mb is not None else None
    try:
        if sha256 is not None:
            if not SHA256_PATTERN.fullmatch(sha256):
                raise ValueError(f"Invalid --sha256 digest (expected 64 hexadecimal characters): {sha256}")
            sha256 = sha256.lower()
        effective_sha256 = sha256 or (
            config.deploy_sha256 if config is not None and s3_path == config.deploy else None
        )
        effective_auth = (
            config.deploy_auth if config is not None and s3_path == config.deploy else None
        )
        if parsed.scheme == "s3":
            if not bucket:
                raise ValueError(f"Invalid S3 path: {s3_path}")
            stage = "downloading from S3"
            from botocore.exceptions import (
                ClientError,
                EndpointConnectionError,
                NoCredentialsError,
                PartialCredentialsError,
            )

            try:
                s3 = create_client()
                project_root = _fetch(s3, bucket, key, tmp, max_bytes=max_bytes, sha256=effective_sha256)
            except (ClientError, EndpointConnectionError, NoCredentialsError, PartialCredentialsError) as e:
                _handle_s3_error(e, s3_path)
        elif parsed.scheme in ("http", "https"):
            if not bucket or not has_archive_suffix(parsed.path):
                raise ValueError(f"HTTP source must be a .tar.gz, .tgz, or .zip archive: {s3_path}")
            stage = "downloading from HTTP"
            project_root = _fetch_http(s3_path, tmp, max_bytes=max_bytes, sha256=effective_sha256, auth=effective_auth)
        else:
            raise ValueError(f"Unsupported deploy source: {s3_path}")

        limit = config.max_archive_mb if config else None
        if limit is not None:
            size = sum(p.stat().st_size for p in project_root.rglob("*") if p.is_file())
            if size > limit * 1024 * 1024:
                raise CommandError(t("msg.deploy_limit_exceeded", limit=limit, size=size))
            typer.echo(t("msg.deploy_provenance", source=s3_path, size=size))
        if effective_sha256 is not None:
            typer.echo(t("msg.deploy_checksum_verified", digest=effective_sha256))

        image = tag or sanitize_project_name(root.name)
        if build:
            stage = "building the container image"
            typer.echo(t("msg.deploy_building", image=image, path=project_subfolder))
            runtime = runtime or detect_runtime()
            ensure_runtime_ready(runtime)
            runtime.passthru_cli(["build", "-t", image, "."], cwd=project_root)
        stage = "replacing the deployed files"
        try:
            target_rel = str(deploy_target.relative_to(root))
        except ValueError:
            target_rel = str(deploy_target)
        prev_config_bytes: bytes | None = None
        config_path = root / "compman.yml"
        if config_path.is_file():
            prev_config_bytes = config_path.read_bytes()
        try:
            _capture_rollback_snapshot(
                root, project_root, deploy_target, prev_config_bytes, target_rel
            )
        except Exception as e:
            # Snapshot capture is best-effort and must never fail the deploy:
            # fall back to a plain tree swap without keeping the old files.
            typer.echo(t("msg.command_failed", error=e), err=True)
            _swap(project_root, deploy_target)
        _generate_scaffold(root, project_subfolder, s3_path, image)
        typer.echo(t("msg.deploy_done"))
        if config is not None:
            try:
                record_stack(config.name, str(config.root_dir))
            except Exception as e:
                # Registry bookkeeping is best-effort: warn and keep the
                # successful deploy result intact.
                typer.echo(t("msg.command_failed", error=e), err=True)
            try:
                append_history(
                    "deploy",
                    stack=config.name,
                    source=s3_path,
                    tag=tag or None,
                    built=build,
                )
            except Exception as e:
                # Journal bookkeeping is best-effort: warn and keep the
                # successful deploy result intact.
                typer.echo(t("msg.command_failed", error=e), err=True)
    except CommandError:
        raise
    except Exception as e:
        typer.echo(t("msg.deploy_failed_stage", stage=stage, error=e), err=True)
        raise SystemExit(1) from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _swap(src: Path, root: Path, old_dest: Path | None = None) -> None:
    """Two-phase managed-tree replacement with rollback on failure.

    Existing entries of ``root`` are moved aside, then ``src`` entries move
    in; any failure restores the original layout before re-raising. ``.git``
    and ``.gitkeep`` are never moved. When ``old_dest`` is given, the previous
    entries are preserved there (rollback snapshots) instead of being deleted
    with the throwaway staging directory.
    """
    root.mkdir(parents=True, exist_ok=True)
    if old_dest is not None:
        backup = old_dest
        backup.mkdir(parents=True, exist_ok=True)
    else:
        backup = Path(tempfile.mkdtemp(prefix=f".{root.name}.swap-", dir=root.parent))
    moved_old: list[str] = []
    moved_new: list[str] = []
    try:
        for item in list(root.iterdir()):
            if item.name in (".git", ".gitkeep"):
                continue
            shutil.move(str(item), str(backup / item.name))
            moved_old.append(item.name)

        for item in src.iterdir():
            if item.name == ".gitkeep":
                continue
            shutil.move(str(item), str(root / item.name))
            moved_new.append(item.name)
    except Exception:
        for name in moved_new:
            dest = root / name
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            elif dest.exists():
                dest.unlink()
        for name in moved_old:
            shutil.move(str(backup / name), str(root / name))
        raise
    finally:
        if old_dest is None:
            shutil.rmtree(backup, ignore_errors=True)


_ROLLBACK_SNAPSHOT_DIR = Path(".compman") / "rollback"


def rollback_snapshot_dir(root: Path) -> Path:
    """Return the rollback snapshot directory for project ``root``."""
    return root / _ROLLBACK_SNAPSHOT_DIR


def _begin_rollback_snapshot(root: Path) -> tuple[Path, Path]:
    """Stage a fresh snapshot directory; returns (staging_dir, tree_dir)."""
    base = root / ".compman"
    base.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".rollback_tmp_", dir=base))
    tree = staging / "tree"
    tree.mkdir()
    return staging, tree


def _commit_rollback_snapshot(
    root: Path,
    staging: Path,
    prev_config_bytes: bytes | None,
    target_rel: str,
) -> None:
    """Atomically publish the staged snapshot and echo the hint once."""
    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": target_rel,
    }
    (staging / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if prev_config_bytes is not None:
        (staging / "compman.yml").write_bytes(prev_config_bytes)
    final = rollback_snapshot_dir(root)
    final.parent.mkdir(parents=True, exist_ok=True)
    replaced: Path | None = None
    if final.exists():
        replaced = final.with_name(f"{final.name}.old-{uuid.uuid4().hex[:12]}")
        os.replace(final, replaced)
    try:
        os.replace(staging, final)
    except OSError:
        if replaced is not None:
            os.replace(replaced, final)
        raise
    if replaced is not None:
        shutil.rmtree(replaced, ignore_errors=True)
    typer.echo(t("msg.rollback_created_hint", path=str(final)))


def _capture_rollback_snapshot(
    root: Path,
    project_root: Path,
    deploy_target: Path,
    prev_config_bytes: bytes | None,
    target_rel: str,
) -> None:
    """Swap the new tree in while keeping the previous one as a snapshot.

    A failure of the swap itself propagates after internal rollback; a
    failure while publishing the snapshot warns to stderr but keeps the
    completed swap (warn-and-continue contract).
    """
    staging, tree = _begin_rollback_snapshot(root)
    try:
        _swap(project_root, deploy_target, old_dest=tree)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    try:
        _commit_rollback_snapshot(root, staging, prev_config_bytes, target_rel)
    except Exception as e:
        shutil.rmtree(staging, ignore_errors=True)
        typer.echo(t("msg.command_failed", error=e), err=True)


def restore_rollback(root: Path) -> str:
    """Restore the previous deployment snapshot for project ``root``.

    Swaps the current managed tree with the snapshot tree transactionally,
    restores the saved ``compman.yml``, then deletes the snapshot. Returns
    the UTC timestamp recorded when the snapshot was captured. Raises
    CommandError when no usable snapshot exists.
    """
    snap = rollback_snapshot_dir(root)
    tree = snap / "tree"
    meta_path = snap / "meta.json"
    if not tree.is_dir() or not meta_path.is_file():
        raise CommandError(t("msg.no_rollback_snapshot"))
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        timestamp = str(meta["timestamp"])
        target_raw = str(meta["target"])
    except (OSError, ValueError, KeyError, TypeError):
        raise CommandError(t("msg.no_rollback_snapshot")) from None
    target = Path(target_raw)
    if not target.is_absolute():
        target = root / target
    _swap(tree, target)
    saved_config = snap / "compman.yml"
    if saved_config.is_file():
        (root / "compman.yml").write_bytes(saved_config.read_bytes())
    shutil.rmtree(snap)
    try:
        snap.parent.rmdir()
    except OSError:
        pass
    return timestamp


def _handle_s3_error(e: Exception, s3_path: str) -> None:
    typer.echo(t("msg.s3_failed", path=s3_path), err=True)
    hint = s3_error_hint(e, s3_path)
    typer.echo(hint if hint is not None else t("msg.download_error", error=e), err=True)
    raise CommandError("", code=1) from e
