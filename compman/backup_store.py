from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NoReturn

import typer

from compman._proc import _env_timeout
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


@dataclass(frozen=True)
class SshBackupStore:
    """Backups stored on a remote host under ``ssh://[user@]host[:port]/path``.

    Operations shell out to ``scp``/``ssh`` subprocesses. Authentication
    relies on pre-provisioned SSH keys (agent or default identity files);
    compman never stores or prompts for passwords or private keys.
    """

    host: str
    path: str
    user: str | None = None
    port: int | None = None

    @property
    def is_remote(self) -> bool:
        return True


def _parse_ssh_store(value: str, rest: str) -> SshBackupStore:
    """Parse the authority/path part of an ``ssh://`` backup URI."""
    _authority, sep, path = rest.partition("/")
    if not sep or not path:
        raise ConfigError(f"'dirs.backup' ssh:// URI is missing a remote path: {value}")
    user, _, host = _authority.rpartition("@")
    if not host:
        raise ConfigError(f"'dirs.backup' ssh:// URI is missing a host name: {value}")
    hostname, port = _split_ssh_port(host, value)
    return SshBackupStore(host=hostname, path=path.strip("/"), user=user or None, port=port)


def _split_ssh_port(host: str, value: str) -> tuple[str, int | None]:
    candidate, sep, port_text = host.rpartition(":")
    if not sep:
        return host, None
    if candidate and port_text.isdigit() and 1 <= int(port_text) <= 65535:
        return candidate, int(port_text)
    raise ConfigError(f"'dirs.backup' ssh:// URI has an invalid port: {value}")


BackupStore = LocalBackupStore | S3BackupStore | SshBackupStore


def parse_backup_store(value: str) -> BackupStore:
    """Parse a ``dirs.backup`` value into a typed backup store."""
    scheme, sep, rest = value.partition("://")
    if not sep:
        return LocalBackupStore(root=Path(value))
    if scheme != "s3" and scheme != "ssh":
        raise ConfigError(
            f"'dirs.backup' must be a relative path, an 's3://bucket/prefix' URI, "
            f"or an 'ssh://[user@]host[:port]/path' URI: {value}"
        )
    if scheme == "ssh":
        return _parse_ssh_store(value, rest)
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
    if isinstance(store, SshBackupStore):
        return f"ssh://{_ssh_authority(store)}/{store.path}/{name}"
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

    A local store keeps archives in place. A remote store uploads the archive
    and then deletes the staged copy together with its staging directory; on
    failure the staged archive is kept and named in the error.
    """
    if isinstance(store, LocalBackupStore):
        return str(local_path)
    if isinstance(store, SshBackupStore):
        return _ssh_put_archive(store, name, local_path)
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
    if isinstance(store, SshBackupStore):
        _ssh_fetch_archive(store, name, dest)
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
        if isinstance(store, SshBackupStore):
            proc = _run_ssh(store, ["test", "-f", f"{store.path}/{candidate}"])
            if proc.returncode == 0:
                return candidate
            if proc.returncode != 1:
                _raise_remote_failure(proc, store)
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

    Both gzip and zstd variants are removed when present; S3 deletions and
    remote ``rm -f`` calls are idempotent, so a missing archive is not an error.
    """
    if isinstance(store, LocalBackupStore):
        for suffix in (".tar.gz", ".tar.zst"):
            (store.root / f"{name}{suffix}").unlink(missing_ok=True)
        return
    if isinstance(store, SshBackupStore):
        for suffix in (".tar.gz", ".tar.zst"):
            proc = _run_ssh(store, ["rm", "-f", f"{store.path}/{name}{suffix}"])
            if proc.returncode != 0:
                _raise_remote_failure(proc, store)
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
    if isinstance(store, SshBackupStore):
        return _ssh_list_archives(store, stack, kind)
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


# ---- ssh:// remote store operations ----

_SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new")


def _ssh_authority(store: SshBackupStore) -> str:
    """Return ``[user@]host[:port]``, the form used in ``ssh://`` locations."""
    authority = f"{store.user}@{store.host}" if store.user else store.host
    if store.port is not None:
        authority = f"{authority}:{store.port}"
    return authority


def _scp_target(store: SshBackupStore) -> str:
    """Return the ``[user@]host`` prefix scp expects; ports travel via ``-P``."""
    return f"{store.user}@{store.host}" if store.user else store.host


def _require_binary(binary: str) -> str:
    path = shutil.which(binary)
    if path is None:
        raise CommandError(t("msg.ssh_unavailable", detail=binary))
    return path


def _run_proc(argv: list[str]) -> subprocess.CompletedProcess[str]:
    timeout = _env_timeout()
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise CommandError(t("msg.timeout_expired", seconds=int(timeout))) from exc
    except FileNotFoundError as exc:
        raise CommandError(t("msg.ssh_unavailable", detail=exc.filename or argv[0])) from exc


def _run_ssh(store: SshBackupStore, remote_command: list[str]) -> subprocess.CompletedProcess[str]:
    argv = [_require_binary("ssh")]
    if store.port is not None:
        argv += ["-p", str(store.port)]
    argv += [*_SSH_OPTIONS]
    argv.append(_ssh_authority(store))
    argv.append(" ".join(shlex.quote(token) for token in remote_command))
    return _run_proc(argv)


def _scp_options(store: SshBackupStore) -> list[str]:
    options = list(_SSH_OPTIONS)
    if store.port is not None:
        options += ["-P", str(store.port)]
    return options


def _raise_remote_failure(proc: subprocess.CompletedProcess[str], store: SshBackupStore) -> NoReturn:
    detail = proc.stderr.strip() or f"exit code {proc.returncode}"
    raise CommandError(
        t("msg.ssh_command_failed", target=f"{_ssh_authority(store)}/{store.path}", detail=detail)
    )


def _ssh_put_archive(store: SshBackupStore, name: str, local_path: Path) -> str:
    dest = f"{_scp_target(store)}:{store.path}/{name}"
    proc = _run_proc([_require_binary("scp"), *_scp_options(store), str(local_path), dest])
    if proc.returncode != 0:
        _raise_remote_failure(proc, store)
    workdir = local_path.parent
    local_path.unlink(missing_ok=True)
    shutil.rmtree(workdir, ignore_errors=True)
    return archive_location(store, name)


def _ssh_fetch_archive(store: SshBackupStore, name: str, dest: Path) -> None:
    typer.echo(t("msg.backup_downloading", name=name, path=archive_location(store, name)))
    source = f"{_scp_target(store)}:{store.path}/{name}"
    proc = _run_proc([_require_binary("scp"), *_scp_options(store), source, str(dest)])
    if proc.returncode != 0:
        _raise_remote_failure(proc, store)


def _ssh_list_archives(store: SshBackupStore, stack: str, kind: str) -> list[str]:
    marker = f"{stack}.{kind}."
    proc = _run_ssh(store, ["ls", "-1", store.path])
    if proc.returncode != 0:
        if "No such file or directory" in proc.stderr:
            return []
        _raise_remote_failure(proc, store)
    timestamps = []
    for line in proc.stdout.splitlines():
        if line.startswith(marker) and line.endswith((".tar.gz", ".tar.zst")):
            timestamps.append(_strip_suffix(line[len(marker):]))
    return sorted(timestamps, reverse=True)
