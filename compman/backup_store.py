from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from compman.errors import ConfigError

_REMOTE_UNSUPPORTED = "remote store support lands in the next change"


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
    # Fail closed: any future non-local variant must land in the raise below.
    if not isinstance(store, LocalBackupStore):
        raise ValueError(_REMOTE_UNSUPPORTED)
    return store.root


def new_backup_paths(store: BackupStore, stack: str, kind: str) -> tuple[Path, Path]:
    """Return a fresh (directory, tarball) pair for a new backup archive."""
    root = local_root(store)
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    backup_name = f"{stack}.{kind}.{timestamp}"
    backup_dir = root / backup_name
    tarball = root / f"{backup_name}.tar.gz"
    if backup_dir.exists() or tarball.exists():
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
        backup_name = f"{stack}.{kind}.{timestamp}"
        backup_dir = root / backup_name
        tarball = root / f"{backup_name}.tar.gz"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir, tarball


def put_archive(store: BackupStore, name: str, local_path: Path) -> None:
    """Place the finished archive into the store.

    A local store keeps archives in place, so this is a no-op; remote stores
    upload ``local_path`` once support lands.
    """
    local_root(store)


def list_archives(store: BackupStore, stack: str, kind: str) -> list[str]:
    """Return sorted backup timestamps for ``stack`` and ``kind``."""
    root = local_root(store)
    pattern = f"{stack}.{kind}."
    return sorted(
        entry.name.replace(pattern, "").replace(".tar.gz", "")
        for entry in sorted(root.glob(f"{pattern}*.tar.gz"))
    )
