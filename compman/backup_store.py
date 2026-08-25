from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import typer

from compman.errors import CommandError, ConfigError
from compman.i18n import t
from compman.s3_source import create_client, s3_error_hint


@dataclass(frozen=True)
class LocalBackupStore:
    """Backups stored in a directory inside the config tree."""

    root: Path

    @property
    def is_remote(self) -> bool:
        return False


@dataclass(frozen=True)
class S3BackupStore:
    """Backups stored under ``s3://bucket/prefix``."""

    bucket: str
    prefix: str

    @property
    def is_remote(self) -> bool:
        return True


BackupStore = LocalBackupStore | S3BackupStore


def parse_backup_store(value: str) -> BackupStore:
    """Parse a ``dirs.backup`` value into a typed backup store."""
    scheme, sep, rest = value.partition("://")
    if not sep:
        return LocalBackupStore(root=Path(value))
    if scheme != "s3":
        raise ConfigError(
            f"'dirs.backup' must be a relative path or an 's3://bucket/prefix' URI: {value}"
        )
    bucket, _, prefix = rest.partition("/")
    if not bucket:
        raise ConfigError(f"'dirs.backup' S3 URI is missing a bucket name: {value}")
    return S3BackupStore(bucket=bucket, prefix=prefix.strip("/"))


def local_root(store: BackupStore) -> Path:
    """Return the filesystem root of a local store."""
    if not isinstance(store, LocalBackupStore):
        raise ValueError("backup store is not local")
    return store.root


def archive_location(store: BackupStore, name: str) -> str:
    """Return the user-facing location of an archive in the store."""
    if isinstance(store, LocalBackupStore):
        return str(store.root / name)
    prefix = f"{store.prefix}/" if store.prefix else ""
    return f"s3://{store.bucket}/{prefix}{name}"


def _object_key(store: S3BackupStore, name: str) -> str:
    return f"{store.prefix}/{name}" if store.prefix else name


def new_backup_paths(store: BackupStore, stack: str, kind: str, *, zstd_format: bool = False) -> tuple[Path, Path]:
    """Return a fresh (directory, tarball) pair for a new backup archive."""
    if isinstance(store, LocalBackupStore):
        root = store.root
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        backup_name = f"{stack}.{kind}.{timestamp}"
        backup_dir = root / backup_name
        tarball = root / f"{backup_name}{_suffix_for(zstd_format)}"
        if backup_dir.exists() or tarball.exists():
            timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
            backup_name = f"{stack}.{kind}.{timestamp}"
            backup_dir = root / backup_name
            tarball = root / f"{backup_name}{_suffix_for(zstd_format)}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir, tarball
    workdir = Path(tempfile.mkdtemp(prefix="compman-"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    tarball = workdir / f"{stack}.{kind}.{timestamp}{_suffix_for(zstd_format)}"
    return workdir, tarball


def put_archive(store: BackupStore, name: str, local_path: Path) -> str:
    """Publish the finished archive and return its user-facing location.

    A local store keeps archives in place. A remote store uploads the archive,
    verifies the stored size, and then deletes the staged copy together with
    its staging directory; on failure the staged archive is kept and named in
    the error.
    """
    if isinstance(store, LocalBackupStore):
        return str(local_path)
    uri = archive_location(store, name)
    local_size = local_path.stat().st_size
    try:
        key = _object_key(store, name)
        s3 = create_client()
        s3.upload_file(
            Filename=str(local_path),
            Bucket=store.bucket,
            Key=key,
            ExtraArgs={"ContentType": "application/zstd" if name.endswith(".tar.zst") else "application/gzip"},
        )
        remote_size = int(s3.head_object(Bucket=store.bucket, Key=key)["ContentLength"])
    except Exception as exc:
        hint = s3_error_hint(exc, uri) or exc
        detail = f"{hint}; staged archive kept at {local_path}"
        raise CommandError(t("msg.backup_store_error", detail=detail)) from exc
    if remote_size != local_size:
        detail = (
            f"uploaded size {remote_size} != local size {local_size}; "
            f"staged archive kept at {local_path}"
        )
        raise CommandError(t("msg.backup_store_error", detail=detail))
    workdir = local_path.parent
    local_path.unlink(missing_ok=True)
    shutil.rmtree(workdir, ignore_errors=True)
    return uri


def fetch_archive(store: BackupStore, name: str, dest: Path) -> None:
    """Materialize ``name`` at ``dest``.

    Local archives are read in place, so fetching is a no-op; remote stores
    download the object to ``dest``.
    """
    if isinstance(store, LocalBackupStore):
        return
    key = _object_key(store, name)
    typer.echo(t("msg.backup_downloading", name=name, path=f"s3://{store.bucket}/{key}"))
    try:
        create_client().download_file(store.bucket, key, str(dest))
    except Exception as exc:
        hint = s3_error_hint(exc, f"s3://{store.bucket}/{key}") or exc
        raise CommandError(t("msg.backup_store_error", detail=str(hint))) from exc


def find_archive(store: BackupStore, stack: str, kind: str, timestamp: str) -> str | None:
    """Return the stored base name (with suffix) for ``timestamp``, or None."""
    for suffix in (".tar.gz", ".tar.zst"):
        candidate = f"{stack}.{kind}.{timestamp}{suffix}"
        if isinstance(store, LocalBackupStore):
            if (store.root / candidate).is_file():
                return candidate
            continue
        try:
            create_client().head_object(Bucket=store.bucket, Key=_object_key(store, candidate))
            return candidate
        except Exception as exc:
            from botocore.exceptions import ClientError as _ClientError

            if isinstance(exc, _ClientError) and str(
                exc.response.get("Error", {}).get("Code", "")
            ) in ("404", "NoSuchKey", "NotFound"):
                continue
            raise
    return None


def delete_archive(store: BackupStore, name: str) -> None:
    """Delete the archive ``name`` (a base name without extension) from the store.

    Both gzip and zstd variants are removed when present; S3 deletions are
    idempotent, so a missing object is not an error.
    """
    if isinstance(store, LocalBackupStore):
        for suffix in (".tar.gz", ".tar.zst"):
            (store.root / f"{name}{suffix}").unlink(missing_ok=True)
        return
    client = create_client()
    for suffix in (".tar.gz", ".tar.zst"):
        try:
            client.delete_object(
                Bucket=store.bucket, Key=_object_key(store, f"{name}{suffix}")
            )
        except Exception as exc:
            uri = archive_location(store, f"{name}{suffix}")
            hint = s3_error_hint(exc, uri) or exc
            raise CommandError(t("msg.backup_store_error", detail=str(hint))) from exc


def list_archives(store: BackupStore, stack: str, kind: str) -> list[str]:
    """Return backup timestamps for ``stack`` and ``kind``, most recent first."""
    if isinstance(store, LocalBackupStore):
        pattern = f"{stack}.{kind}."
        names = [
            entry.name[len(pattern):]
            for entry in store.root.glob(f"{pattern}*")
            if entry.name.endswith((".tar.gz", ".tar.zst"))
        ]
        return sorted((_strip_suffix(n) for n in names), reverse=True)
    prefix = f"{store.prefix}/" if store.prefix else ""
    marker = f"{prefix}{stack}.{kind}."
    timestamps: list[str] = []
    try:
        paginator = create_client().get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=store.bucket, Prefix=prefix)
        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.startswith(marker) and key.endswith((".tar.gz", ".tar.zst")):
                    timestamps.append(_strip_suffix(key[len(marker):]))
    except Exception as exc:
        hint = s3_error_hint(exc, f"s3://{store.bucket}/{prefix}") or exc
        raise CommandError(t("msg.backup_store_error", detail=str(hint))) from exc
    return sorted(timestamps, reverse=True)


@contextmanager
def staged_archive(store: BackupStore, name: str) -> Iterator[Path]:
    """Yield a readable path for ``name``, staging remote archives in a tempdir.

    Local stores yield the archive where it lies; remote stores download into
    a private staging directory that is removed on exit.
    """
    if isinstance(store, LocalBackupStore):
        yield store.root / name
        return
    stage = Path(tempfile.mkdtemp(prefix="compman-"))
    try:
        tarball = stage / name
        fetch_archive(store, name, tarball)
        yield tarball
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _suffix_for(zstd_format: bool) -> str:
    return ".tar.zst" if zstd_format else ".tar.gz"


def _strip_suffix(name: str) -> str:
    for suffix in (".tar.zst", ".tar.gz"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name
