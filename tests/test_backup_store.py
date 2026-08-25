from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest

from compman.backup_store import (
    LocalBackupStore,
    S3BackupStore,
    list_archives,
    local_root,
    new_backup_paths,
    parse_backup_store,
    put_archive,
)
from compman.errors import ConfigError

# ---- parse_backup_store ----


def test_parse_backup_store_local_value_passthrough():
    store = parse_backup_store("backup")
    assert store == LocalBackupStore(root=pathlib.Path("backup"))
    assert store.is_remote is False


def test_parse_backup_store_s3_uri_with_prefix():
    store = parse_backup_store("s3://bucket/prefix")
    assert store == S3BackupStore(bucket="bucket", prefix="prefix")
    assert store.is_remote is True


def test_parse_backup_store_s3_uri_without_prefix():
    store = parse_backup_store("s3://bucket")
    assert store == S3BackupStore(bucket="bucket", prefix="")


def test_parse_backup_store_s3_uri_normalizes_trailing_slash():
    store = parse_backup_store("s3://bucket/prefix/")
    assert store == S3BackupStore(bucket="bucket", prefix="prefix")


def test_parse_backup_store_rejects_unsupported_scheme():
    with pytest.raises(ConfigError, match="'dirs.backup' must be a relative path"):
        parse_backup_store("https://bucket/backups")


def test_parse_backup_store_rejects_empty_bucket():
    with pytest.raises(ConfigError, match="missing a bucket name"):
        parse_backup_store("s3:///prefix")


# ---- new_backup_paths (local) ----


def test_new_backup_paths_local_creates_directory_and_tarball_pair(temp_dir: pathlib.Path):
    root = temp_dir / "bak"
    backup_dir, tarball = new_backup_paths(LocalBackupStore(root=root), "my_stack", "volume")
    assert backup_dir.parent == root
    assert tarball.name == f"{backup_dir.name}.tar.gz"
    assert backup_dir.is_dir()


def test_new_backup_paths_local_collision_falls_back_to_microseconds(temp_dir: pathlib.Path):
    root = temp_dir / "bak"
    root.mkdir()
    (root / "app.volume.20260731_120000.tar.gz").touch()
    fixed = MagicMock()
    fixed.strftime.side_effect = ["20260731_120000", "20260731_120000_123456"]
    with patch("compman.backup_store.datetime") as dt:
        dt.now.return_value = fixed
        backup_dir, tarball = new_backup_paths(LocalBackupStore(root=root), "app", "volume")
    assert backup_dir.name == "app.volume.20260731_120000_123456"
    assert tarball.name == "app.volume.20260731_120000_123456.tar.gz"


def test_new_backup_paths_remote_is_unsupported():
    with pytest.raises(ValueError, match="remote store support lands in the next change"):
        new_backup_paths(S3BackupStore(bucket="b", prefix=""), "app", "volume")


# ---- put_archive ----


def test_put_archive_local_is_a_no_op(temp_dir: pathlib.Path):
    archive = temp_dir / "app.volume.1.tar.gz"
    archive.write_bytes(b"data")
    put_archive(LocalBackupStore(root=temp_dir), "app.volume.1.tar.gz", archive)
    assert archive.read_bytes() == b"data"


def test_put_archive_remote_is_unsupported(temp_dir: pathlib.Path):
    with pytest.raises(ValueError, match="remote store support lands in the next change"):
        put_archive(S3BackupStore(bucket="b", prefix=""), "x.tar.gz", temp_dir / "x.tar.gz")


# ---- list_archives ----


def test_list_archives_local_returns_sorted_matching_timestamps(temp_dir: pathlib.Path):
    root = temp_dir / "bak"
    root.mkdir()
    for name in (
        "app.volume.20260731_1200.tar.gz",
        "app.volume.20260801_0900.tar.gz",
        "app.image.20260731_1300.tar.gz",
        "other.volume.20260731_1400.tar.gz",
        "notes.txt",
    ):
        (root / name).touch()
    assert list_archives(LocalBackupStore(root=root), "app", "volume") == [
        "20260731_1200",
        "20260801_0900",
    ]


def test_list_archives_local_missing_directory_is_empty(temp_dir: pathlib.Path):
    assert list_archives(LocalBackupStore(root=temp_dir / "nope"), "app", "volume") == []


def test_list_archives_remote_is_unsupported():
    with pytest.raises(ValueError, match="remote store support lands in the next change"):
        list_archives(S3BackupStore(bucket="b", prefix="p"), "app", "volume")


# ---- local_root ----


def test_local_root_returns_local_filesystem_root(temp_dir: pathlib.Path):
    assert local_root(LocalBackupStore(root=temp_dir)) == temp_dir


def test_local_root_rejects_remote_store():
    with pytest.raises(ValueError, match="remote store support lands in the next change"):
        local_root(S3BackupStore(bucket="b", prefix=""))
