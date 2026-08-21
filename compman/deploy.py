from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urlparse

import boto3
import typer
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
)

from compman.archive_source import has_archive_suffix
from compman.config import Config, ConfigError, load_config, resolve_deploy, sanitize_project_name
from compman.docker import ContainerRuntime, detect_runtime
from compman.errors import CommandError
from compman.http_source import fetch as _fetch_http
from compman.i18n import t
from compman.local_source import fetch as _fetch_local
from compman.ops.common import ensure_runtime_ready, validate_timestamp
from compman.s3_source import download as _download  # noqa: F401
from compman.s3_source import download_recursive as _download_recursive  # noqa: F401
from compman.s3_source import fetch as _fetch
from compman.scaffold import generate as _generate_scaffold
from compman.scaffold import update_deploy as _update_compman_deploy  # noqa: F401


def _fetch_s3(source: str, tmp: Path) -> Path:
    parsed = urlparse(source)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket:
        raise ValueError(f"Invalid S3 path: {source}")
    endpoint = os.environ.get("AWS_ENDPOINT_URL_S3") or os.environ.get("AWS_ENDPOINT_URL")
    s3 = boto3.client("s3", endpoint_url=endpoint or None)
    return _fetch(s3, bucket, key, tmp)


_Scheme = Literal["s3", "http", "https", "file", "local"]


def _verify_checksum(source: str, project_root: Path, tmp: Path, checksum: str | None) -> None:
    if checksum is None:
        return
    raw_expected = checksum.split(":", 1)[1] if ":" in checksum else checksum
    expected = raw_expected.strip().lower()
    target: Path | None = None
    if project_root.is_file():
        target = project_root
    elif has_archive_suffix(str(project_root)):
        target = project_root
    elif has_archive_suffix(source):
        candidates = [p for p in tmp.rglob("*") if p.is_file() and has_archive_suffix(str(p))]
        if candidates:
            target = candidates[0]
        else:
            raw = source[7:] if source.startswith("file://") else source
            cand = Path(raw).resolve()
            if cand.is_file() and has_archive_suffix(str(cand)):
                target = cand
            else:
                return
    else:
        raw = source[7:] if source.startswith("file://") else source
        cand = Path(raw).resolve()
        if cand.is_file():
            files = [p for p in project_root.rglob("*") if p.is_file()]
            if len(files) == 1:
                target = files[0]
            else:
                return
        else:
            return
    if target is None or not target.is_file():
        return
    h = hashlib.sha256()
    with target.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != expected:
        raise CommandError(t("msg.deploy_checksum_mismatch", expected=checksum, actual=f"sha256:{actual}"))
    typer.echo(t("msg.deploy_checksum_ok", checksum=checksum))


def _collect_files(root: Path) -> set[str]:
    if root.is_file():
        return {root.name}
    files: set[str] = set()
    for p in root.rglob("*"):
        if p.is_file():
            files.add(p.relative_to(root).as_posix())
    return files


def deploy(
    build: bool = False,
    tag: str | None = None,
    s3_path: str | None = None,
    config: Config | None = None,
    runtime: ContainerRuntime | None = None,
    profile: str | None = None,
    strategy: str | None = None,
    dry_run: bool = False,
    keep: int = 3,
    no_build: bool = False,
) -> None:
    if config is None and (Path.cwd() / "compman.yml").exists():
        try:
            config = load_config()
        except ConfigError:
            pass

    source: str | None = s3_path
    deploy_spec = None
    if source is None:
        if config is None:
            try:
                config = load_config()
            except ConfigError as e:
                if "not found" in str(e).lower():
                    typer.echo(t("msg.empty_dir_deploy"), err=True)
                    typer.echo("", err=True)
                    typer.echo(t("msg.empty_dir_start"), err=True)
                    typer.echo(t("msg.deploy_direct_hint"), err=True)
                    typer.echo("     compman deploy --path s3://<your-bucket>/path/to/app.tar.gz", err=True)
                    typer.echo(t("msg.config_hint"), err=True)
                    typer.echo("     compman init", err=True)
                else:
                    typer.echo(t("msg.command_failed", error=e), err=True)
                raise SystemExit(1)
        if config.deploy is None:
            source = None
        else:
            try:
                deploy_spec = resolve_deploy(config.deploy, profile)
                source = deploy_spec.source
            except ConfigError as e:
                typer.echo(t("msg.command_failed", error=e), err=True)
                raise SystemExit(1)
    else:
        if config is not None and config.deploy is not None:
            try:
                deploy_spec = resolve_deploy(config.deploy, profile)
            except ConfigError:
                deploy_spec = None

    if not source:
        typer.echo(t("msg.deploy_path_not_configured"), err=True)
        typer.echo(t("msg.deploy_path_hint1"), err=True)
        typer.echo(t("msg.deploy_path_hint2"), err=True)
        raise SystemExit(1)

    s3_path = source

    project_subfolder = config.dirs.get("project", "project") if config else "project"

    root = Path.cwd()
    deploy_target = config.deploy_dir if config else root / project_subfolder

    tmp = Path(tempfile.mkdtemp(prefix=".deploy_tmp_"))

    stage = "validating the deploy source"
    try:
        parsed = urlparse(s3_path)
        scheme: str = parsed.scheme or "local"
        if scheme == "file":
            scheme = "local"
        fetchers: dict[str, Callable[[str, Path], Path]] = {
            "s3": _fetch_s3,
            "http": _fetch_http,
            "https": _fetch_http,
            "file": _fetch_local,
            "local": _fetch_local,
        }
        fetcher = fetchers.get(scheme)
        if fetcher is None:
            raise CommandError(t("msg.deploy_unsupported", source=s3_path))
        if scheme == "s3":
            stage = "downloading from S3"
            try:
                project_root = fetcher(s3_path, tmp)
            except (ClientError, EndpointConnectionError, NoCredentialsError, PartialCredentialsError) as e:
                _handle_s3_error(e, s3_path)
        elif scheme in ("http", "https"):
            stage = "downloading from HTTP"
            project_root = fetcher(s3_path, tmp)
        else:
            stage = "fetching local source"
            project_root = fetcher(s3_path, tmp)

        stage = "verifying checksum"
        checksum_value = deploy_spec.checksum if deploy_spec is not None else None
        _verify_checksum(s3_path, project_root, tmp, checksum_value)

        stage = "verifying size limits"
        if project_root.is_file():
            size = project_root.stat().st_size
        else:
            size = sum(p.stat().st_size for p in project_root.rglob("*") if p.is_file())
        limit = config.limits.get("max_archive_mb") if config else None
        if limit is not None and size > limit * 1024 * 1024:
            raise CommandError(t("msg.deploy_limit_exceeded", limit=limit, size=size))
        typer.echo(t("msg.deploy_provenance", source=s3_path, size=size))

        effective_strategy = strategy if strategy is not None else (deploy_spec.strategy if deploy_spec is not None else None)
        image = tag or sanitize_project_name(root.name)
        if build and not (effective_strategy == "pull-only" or no_build):
            stage = "building the container image"
            typer.echo(t("msg.deploy_building", image=image, path=project_subfolder))
            runtime = runtime or detect_runtime()
            ensure_runtime_ready(runtime)
            runtime.passthru_cli(["build", "-t", image, "."], cwd=project_root)

        if dry_run:
            stage = "dry-run diff"
            typer.echo(t("msg.deploy_dry_run"))
            typer.echo(t("msg.deploy_diff_header"))
            existing_files = _collect_files(deploy_target) if deploy_target.exists() else set()
            new_files = _collect_files(project_root)
            added = sorted(new_files - existing_files)
            removed = sorted(existing_files - new_files)
            common = new_files & existing_files
            modified: list[str] = []
            if project_root.is_dir() and deploy_target.exists() and deploy_target.is_dir():
                for name in sorted(common):
                    try:
                        new_p = project_root / name
                        old_p = deploy_target / name
                        if new_p.stat().st_size != old_p.stat().st_size:
                            modified.append(name)
                        elif new_p.read_bytes() != old_p.read_bytes():
                            modified.append(name)
                    except Exception:
                        modified.append(name)
            for name in added:
                typer.echo(f"  + {name}")
            for name in removed:
                typer.echo(f"  - {name}")
            for name in modified:
                typer.echo(f"  ~ {name}")
            if not added and not removed and not modified:
                typer.echo("  (no changes)")
            return

        stage = "replacing the deployed files"
        _swap(project_root, deploy_target)
        stage = "generating project configuration"
        _generate_scaffold(root, project_subfolder, s3_path, image)
        stage = "saving version backup"
        # backup_dir/.versions survives _swap; deploy_dir/.versions would be deleted (Metis R3)
        if config is not None:
            backup_versions = config.backup_dir / ".versions"
        else:
            backup_versions = root / "backup" / ".versions"
        backup_versions.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_version = backup_versions / timestamp
        if target_version.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            target_version = backup_versions / timestamp
        shutil.copytree(deploy_target, target_version)
        prune_versions(backup_versions, keep)
        typer.echo(t("msg.deploy_done"))
    except CommandError as e:
        typer.echo(e.message, err=True)
        raise SystemExit(1)
    except SystemExit:
        raise
    except Exception as e:
        typer.echo(t("msg.deploy_failed_stage", stage=stage, error=e), err=True)
        raise SystemExit(1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _swap(src: Path, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
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
            if item.name in (".git", ".gitkeep"):
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
        shutil.rmtree(backup, ignore_errors=True)


def prune_versions(backup_versions: Path, keep: int) -> None:
    versions = sorted(p for p in backup_versions.iterdir() if p.is_dir())
    if len(versions) > keep:
        for old in versions[: len(versions) - keep]:
            shutil.rmtree(old, ignore_errors=True)


def rollback(config: Config, timestamp: str) -> None:
    validate_timestamp(timestamp)
    backup_versions = config.backup_dir / ".versions"
    src = backup_versions / timestamp
    if not src.is_dir():
        raise CommandError(t("msg.backup_not_found", tarball=str(src)))
    deploy_target = config.deploy_dir
    tmp = Path(tempfile.mkdtemp(prefix=".rollback_tmp_"))
    try:
        tmp_src = tmp / "src"
        shutil.copytree(src, tmp_src)
        _swap(tmp_src, deploy_target)
        typer.echo(t("msg.rollback_done", timestamp=timestamp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _handle_s3_error(e: Exception, s3_path: str) -> None:
    typer.echo(t("msg.s3_failed", path=s3_path), err=True)
    if isinstance(e, (NoCredentialsError, PartialCredentialsError)):
        typer.echo(t("msg.s3_no_creds"), err=True)

    elif isinstance(e, ClientError):
        err_code = str(e.response.get("Error", {}).get("Code", ""))
        err_msg = str(e.response.get("Error", {}).get("Message", e))
        if err_code in ("403", "AccessDenied", "Forbidden"):
            typer.echo(t("msg.s3_403", path=s3_path), err=True)
        elif err_code in ("404", "NoSuchBucket", "NoSuchKey", "NotFound"):
            typer.echo(t("msg.s3_404", path=s3_path), err=True)
        else:
            typer.echo(t("msg.s3_client_error", code=err_code, error=err_msg), err=True)

    elif isinstance(e, EndpointConnectionError):
        typer.echo(t("msg.s3_network"), err=True)

    else:
        typer.echo(t("msg.download_error", error=e), err=True)

    raise SystemExit(1)
