from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import typer

from compman.archive_source import has_archive_suffix
from compman.config import SHA256_PATTERN, Config, ConfigError, load_config, sanitize_project_name
from compman.docker import ContainerRuntime, detect_runtime
from compman.errors import CommandError
from compman.http_source import fetch as _fetch_http
from compman.i18n import t
from compman.ops.common import ensure_runtime_ready
from compman.s3_source import create_client, s3_error_hint
from compman.s3_source import download as _download  # noqa: F401
from compman.s3_source import download_recursive as _download_recursive  # noqa: F401
from compman.s3_source import fetch as _fetch
from compman.scaffold import generate as _generate_scaffold
from compman.scaffold import update_deploy as _update_compman_deploy  # noqa: F401


def deploy(
    build: bool = False,
    tag: str | None = None,
    s3_path: str | None = None,
    config: Config | None = None,
    runtime: ContainerRuntime | None = None,
    sha256: str | None = None,
) -> None:
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
            raise SystemExit(1)

    if not s3_path:
        typer.echo(t("msg.deploy_path_not_configured"), err=True)
        typer.echo(t("msg.deploy_path_hint1"), err=True)
        typer.echo(t("msg.deploy_path_hint2"), err=True)
        raise SystemExit(1)

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
        _swap(project_root, deploy_target)
        stage = "generating project configuration"
        _generate_scaffold(root, project_subfolder, s3_path, image)
        typer.echo(t("msg.deploy_done"))
    except SystemExit:
        raise
    except CommandError:
        raise
    except Exception as e:
        typer.echo(t("msg.deploy_failed_stage", stage=stage, error=e), err=True)
        raise SystemExit(1) from e
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
        shutil.rmtree(backup, ignore_errors=True)


def _handle_s3_error(e: Exception, s3_path: str) -> None:
    typer.echo(t("msg.s3_failed", path=s3_path), err=True)
    hint = s3_error_hint(e, s3_path)
    typer.echo(hint if hint is not None else t("msg.download_error", error=e), err=True)
    raise SystemExit(1)
