from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest

from compman.backup_store import (
    LocalBackupStore,
    S3BackupStore,
    archive_location,
    delete_archive,
    fetch_archive,
    list_archives,
    local_root,
    new_backup_paths,
    parse_backup_store,
    put_archive,
    staged_archive,
)
from compman.errors import CommandError, ConfigError


class FakeS3:
    def __init__(
        self,
        pages: list[dict] | None = None,
        remote_size: int | None = None,
        error: Exception | None = None,
    ) -> None:
        self.pages = pages or []
        self.remote_size = remote_size
        self.error = error
        self.uploaded: dict[str, object] = {}
        self.downloads: list[tuple[str, str, str]] = []
        self.deleted: list[dict[str, str]] = []
        self.page_calls: list[dict] = []

    def delete_object(self, *, Bucket, Key):
        if self.error is not None:
            raise self.error
        self.deleted.append({"Bucket": Bucket, "Key": Key})

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):
        if self.error is not None:
            raise self.error
        self.uploaded.update(Filename=Filename, Bucket=Bucket, Key=Key, ExtraArgs=ExtraArgs)

    def head_object(self, *, Bucket, Key):
        size = self.remote_size
        if size is None:
            size = pathlib.Path(str(self.uploaded["Filename"])).stat().st_size
        return {"ContentLength": size}

    def download_file(self, bucket, key, destination):
        if self.error is not None:
            raise self.error
        self.downloads.append((bucket, key, destination))
        pathlib.Path(destination).write_bytes(b"archive")

    def get_paginator(self, operation_name):
        return self

    def paginate(self, **kwargs):
        self.page_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return iter(self.pages)


def _stage(temp_dir: pathlib.Path) -> pathlib.Path:
    return temp_dir / "stage"


def _patch_stage(temp_dir: pathlib.Path):
    def make_staging_directory(prefix=""):
        _stage(temp_dir).mkdir(parents=True, exist_ok=True)
        return str(_stage(temp_dir))

    return patch("compman.backup_store.tempfile.mkdtemp", side_effect=make_staging_directory)


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


# ---- new_backup_paths ----


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


def test_new_backup_paths_remote_stages_pair_inside_temp_workdir(temp_dir: pathlib.Path):
    with _patch_stage(temp_dir):
        workdir, tarball = new_backup_paths(S3BackupStore(bucket="b", prefix="p"), "app", "volume")
    assert workdir == _stage(temp_dir)
    assert tarball.parent == workdir
    assert tarball.name.startswith("app.volume.")
    assert tarball.name.endswith(".tar.gz")


# ---- put_archive ----


def test_put_archive_local_keeps_archive_and_reports_its_path(temp_dir: pathlib.Path):
    archive = temp_dir / "app.volume.1.tar.gz"
    archive.write_bytes(b"data")
    location = put_archive(LocalBackupStore(root=temp_dir), "app.volume.1.tar.gz", archive)
    assert location == str(archive)
    assert archive.read_bytes() == b"data"


def test_put_archive_remote_uploads_verifies_and_cleans_staging(temp_dir: pathlib.Path):
    store = S3BackupStore(bucket="bucket", prefix="backups")
    with _patch_stage(temp_dir):
        workdir, tarball = new_backup_paths(store, "app", "volume")
    tarball.write_bytes(b"gzip-data")
    fake = FakeS3()
    with patch("compman.backup_store.create_client", return_value=fake):
        location = put_archive(store, tarball.name, tarball)

    assert fake.uploaded["Bucket"] == "bucket"
    assert fake.uploaded["Key"] == f"backups/{tarball.name}"
    assert fake.uploaded["ExtraArgs"] == {"ContentType": "application/gzip"}
    assert location == f"s3://bucket/backups/{tarball.name}"
    assert not tarball.exists()
    assert not workdir.exists()


def test_put_archive_remote_size_mismatch_keeps_staged_tarball(temp_dir: pathlib.Path):
    store = S3BackupStore(bucket="bucket", prefix="")
    with _patch_stage(temp_dir):
        workdir, tarball = new_backup_paths(store, "app", "volume")
    tarball.write_bytes(b"gzip-data")
    fake = FakeS3(remote_size=len(b"gzip-data") + 5)
    with patch("compman.backup_store.create_client", return_value=fake), pytest.raises(
        CommandError, match="uploaded size"
    ) as excinfo:
        put_archive(store, tarball.name, tarball)

    assert tarball.exists()
    assert str(tarball) in str(excinfo.value)


def test_put_archive_remote_failure_wraps_hint_and_keeps_staged_tarball(temp_dir: pathlib.Path):
    store = S3BackupStore(bucket="bucket", prefix="backups")
    with _patch_stage(temp_dir):
        workdir, tarball = new_backup_paths(store, "app", "volume")
    tarball.write_bytes(b"gzip-data")
    fake = FakeS3(error=RuntimeError("connection reset"))
    with patch("compman.backup_store.create_client", return_value=fake), pytest.raises(
        CommandError, match="connection reset"
    ) as excinfo:
        put_archive(store, tarball.name, tarball)

    assert tarball.exists()
    assert str(tarball) in str(excinfo.value)


# ---- fetch_archive ----


def test_fetch_archive_local_is_a_no_op(temp_dir: pathlib.Path):
    dest = temp_dir / "dest.tar.gz"
    fetch_archive(LocalBackupStore(root=temp_dir), "missing.tar.gz", dest)
    assert not dest.exists()


def test_fetch_archive_remote_downloads_object_to_dest(temp_dir: pathlib.Path, capsys):
    store = S3BackupStore(bucket="bucket", prefix="backups")
    dest = temp_dir / "dest.tar.gz"
    fake = FakeS3()
    with patch("compman.backup_store.create_client", return_value=fake):
        fetch_archive(store, "app.volume.1.tar.gz", dest)

    assert fake.downloads == [("bucket", "backups/app.volume.1.tar.gz", str(dest))]
    assert "Downloading app.volume.1.tar.gz" in capsys.readouterr().out


def test_fetch_archive_remote_failure_raises_command_error(temp_dir: pathlib.Path):
    store = S3BackupStore(bucket="bucket", prefix="")
    fake = FakeS3(error=RuntimeError("timeout"))
    with patch("compman.backup_store.create_client", return_value=fake), pytest.raises(
        CommandError, match="timeout"
    ):
        fetch_archive(store, "app.volume.1.tar.gz", temp_dir / "dest.tar.gz")


# ---- delete_archive ----


def test_delete_archive_local_unlinks_file(temp_dir: pathlib.Path):
    archive = temp_dir / "app.volume.1.tar.gz"
    archive.touch()
    delete_archive(LocalBackupStore(root=temp_dir), "app.volume.1")
    assert not archive.exists()


def test_delete_archive_remote_calls_delete_object_with_exact_key():
    store = S3BackupStore(bucket="bucket", prefix="backups")
    fake = FakeS3()
    with patch("compman.backup_store.create_client", return_value=fake):
        delete_archive(store, "app.volume.20260731_1200")
    assert fake.deleted == [
        {"Bucket": "bucket", "Key": "backups/app.volume.20260731_1200.tar.gz"},
        {"Bucket": "bucket", "Key": "backups/app.volume.20260731_1200.tar.zst"},
    ]


def test_delete_archive_remote_without_prefix_uses_bare_key():
    store = S3BackupStore(bucket="bucket", prefix="")
    fake = FakeS3()
    with patch("compman.backup_store.create_client", return_value=fake):
        delete_archive(store, "app.volume.20260731_1200")
    assert fake.deleted == [
        {"Bucket": "bucket", "Key": "app.volume.20260731_1200.tar.gz"},
        {"Bucket": "bucket", "Key": "app.volume.20260731_1200.tar.zst"},
    ]


def test_delete_archive_remote_failure_raises_command_error():
    store = S3BackupStore(bucket="bucket", prefix="")
    fake = FakeS3(error=RuntimeError("access denied"))
    with patch("compman.backup_store.create_client", return_value=fake), pytest.raises(
        CommandError, match="access denied"
    ):
        delete_archive(store, "app.volume.1")


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
        "20260801_0900",
        "20260731_1200",
    ]


def test_list_archives_local_missing_directory_is_empty(temp_dir: pathlib.Path):
    assert list_archives(LocalBackupStore(root=temp_dir / "nope"), "app", "volume") == []


def test_list_archives_remote_paginates_filters_and_sorts():
    store = S3BackupStore(bucket="bucket", prefix="backups")
    fake = FakeS3(
        pages=[
            {
                "Contents": [
                    {"Key": "backups/app.volume.20260801_0900.tar.gz"},
                    {"Key": "backups/app.volume.20260731_1200.tar.gz"},
                    {"Key": "backups/other.volume.20260731_1300.tar.gz"},
                    {"Key": "backups/notes.txt"},
                ]
            },
            {
                "Contents": [
                    {"Key": "backups/app.volume.20260601_0000.tar.gz"},
                    {"Key": "backups/app.image.20260731_0000.tar.gz"},
                ]
            },
        ]
    )
    with patch("compman.backup_store.create_client", return_value=fake):
        assert list_archives(store, "app", "volume") == [
            "20260801_0900",
            "20260731_1200",
            "20260601_0000",
        ]
    assert fake.page_calls == [{"Bucket": "bucket", "Prefix": "backups/"}]


def test_list_archives_remote_without_prefix_uses_empty_prefix():
    store = S3BackupStore(bucket="bucket", prefix="")
    fake = FakeS3(pages=[{"Contents": [{"Key": "app.volume.20260731_1200.tar.gz"}]}])
    with patch("compman.backup_store.create_client", return_value=fake):
        assert list_archives(store, "app", "volume") == ["20260731_1200"]
    assert fake.page_calls == [{"Bucket": "bucket", "Prefix": ""}]


def test_list_archives_remote_empty_result_is_empty_list():
    store = S3BackupStore(bucket="bucket", prefix="backups")
    fake = FakeS3(pages=[{}])
    with patch("compman.backup_store.create_client", return_value=fake):
        assert list_archives(store, "app", "volume") == []


def test_list_archives_remote_failure_raises_command_error():
    store = S3BackupStore(bucket="bucket", prefix="")
    fake = FakeS3(error=RuntimeError("throttled"))
    with patch("compman.backup_store.create_client", return_value=fake), pytest.raises(
        CommandError, match="throttled"
    ):
        list_archives(store, "app", "volume")


# ---- staged_archive ----


def test_staged_archive_local_yields_in_place_path(temp_dir: pathlib.Path):
    archive = temp_dir / "app.volume.1.tar.gz"
    archive.touch()
    no_staging = patch(
        "compman.backup_store.tempfile.mkdtemp", side_effect=AssertionError("no staging")
    )
    with no_staging, staged_archive(LocalBackupStore(root=temp_dir), "app.volume.1.tar.gz") as tarball:
        assert tarball == archive


def test_staged_archive_remote_downloads_and_removes_staging(temp_dir: pathlib.Path):
    store = S3BackupStore(bucket="bucket", prefix="backups")
    fake = FakeS3()
    seen: list[pathlib.Path] = []
    with _patch_stage(temp_dir), patch("compman.backup_store.create_client", return_value=fake):
        with staged_archive(store, "app.volume.1.tar.gz") as tarball:
            seen.append(tarball)
            assert tarball.read_bytes() == b"archive"
    assert seen and seen[0].exists() is False
    assert fake.downloads[0][1] == "backups/app.volume.1.tar.gz"


# ---- helpers ----


def test_local_root_returns_local_filesystem_root(temp_dir: pathlib.Path):
    assert local_root(LocalBackupStore(root=temp_dir)) == temp_dir


def test_local_root_rejects_remote_store():
    with pytest.raises(ValueError, match="backup store is not local"):
        local_root(S3BackupStore(bucket="b", prefix=""))


def test_archive_location_local_and_remote_forms(temp_dir: pathlib.Path):
    assert archive_location(LocalBackupStore(root=temp_dir), "a.tar.gz") == str(temp_dir / "a.tar.gz")
    assert (
        archive_location(S3BackupStore(bucket="bucket", prefix="pre"), "a.tar.gz")
        == "s3://bucket/pre/a.tar.gz"
    )
    assert archive_location(S3BackupStore(bucket="bucket", prefix=""), "a.tar.gz") == "s3://bucket/a.tar.gz"


def test_strip_suffix_passthrough_without_known_suffix():
    from compman.backup_store import _strip_suffix

    assert _strip_suffix("plain-name") == "plain-name"
    assert _strip_suffix("app.volume.20260801_0900.tar.gz") == "app.volume.20260801_0900"
    assert _strip_suffix("app.volume.20260801_0900.tar.zst") == "app.volume.20260801_0900"


# ---- find_archive ----

class _HeadFake:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def head_object(self, *, Bucket, Key):
        self.calls.append(Key)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return {"ContentLength": 1}


def test_find_archive_local_prefers_gz_then_zst_then_none(tmp_path):
    from compman.backup_store import LocalBackupStore, find_archive

    store = LocalBackupStore(root=tmp_path)
    (tmp_path / "app.volume.20260801_0900.tar.gz").touch()
    assert find_archive(store, "app", "volume", "20260801_0900") == "app.volume.20260801_0900.tar.gz"

    (tmp_path / "app.volume.20260801_0900.tar.gz").unlink()
    (tmp_path / "app.volume.20260801_0900.tar.zst").touch()
    assert find_archive(store, "app", "volume", "20260801_0900") == "app.volume.20260801_0900.tar.zst"

    (tmp_path / "app.volume.20260801_0900.tar.zst").unlink()
    assert find_archive(store, "app", "volume", "20260801_0900") is None


def test_find_archive_remote_short_circuits_on_first_hit():
    from unittest.mock import patch

    from compman.backup_store import S3BackupStore, find_archive

    store = S3BackupStore(bucket="bucket", prefix="backups")
    calls = []

    class H:
        def __init__(self):
            pass

        def head_object(self, *, Bucket, Key):
            calls.append(Key)
            return {"ContentLength": 5}

    with patch("compman.backup_store.create_client", return_value=H()):
        assert find_archive(store, "app", "volume", "20260731_1200") == (
            "app.volume.20260731_1200.tar.gz"
        )


def test_find_archive_remote_both_missing_returns_none():
    from unittest.mock import patch

    from botocore.exceptions import ClientError

    from compman.backup_store import S3BackupStore, find_archive

    store = S3BackupStore(bucket="bucket", prefix="backups")

    class H:
        def head_object(self, *, Bucket, Key):
            raise ClientError({"Error": {"Code": "404", "Message": "nf"}}, "HeadObject")

    with patch("compman.backup_store.create_client", return_value=H()):
        assert find_archive(store, "app", "volume", "20260731_1200") is None


def test_find_archive_remote_unexpected_error_raises():
    import pytest

    from compman.backup_store import S3BackupStore, find_archive

    store = S3BackupStore(bucket="bucket", prefix="backups")

    class H:
        def head_object(self, *, Bucket, Key):
            raise RuntimeError("boom")

    with patch("compman.backup_store.create_client", return_value=H()), pytest.raises(
        RuntimeError, match="boom"
    ):
        find_archive(store, "app", "volume", "20260731_1200")


def test_find_archive_remote_falls_back_to_zst_when_gz_missing():
    from unittest.mock import patch

    from botocore.exceptions import ClientError

    from compman.backup_store import S3BackupStore, find_archive

    store = S3BackupStore(bucket="bucket", prefix="backups")

    class H:
        def head_object(self, *, Bucket, Key):
            if Key.endswith(".tar.gz"):
                raise ClientError({"Error": {"Code": "404", "Message": "nf"}}, "HeadObject")
            return {"ContentLength": 9}

    with patch("compman.backup_store.create_client", return_value=H()):
        assert find_archive(store, "app", "volume", "20260731_1200") == (
            "app.volume.20260731_1200.tar.zst"
        )
