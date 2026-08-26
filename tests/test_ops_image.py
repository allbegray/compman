from __future__ import annotations

import pathlib
import re
import sys
import tarfile
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from test_backup_store import FakeS3, _patch_stage, _stage

from compman.backup_store import S3BackupStore, local_root
from compman.config import Config, Profile
from compman.errors import CommandError
from compman.ops import image

requires_py314 = pytest.mark.skipif(
    sys.version_info < (3, 14), reason="compression.zstd requires Python 3.14+"
)

def test_image_backup(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    with patch("tarfile.open") as open_tar:
        image.backup(dummy_runtime, cfg, source_mode=False, compression_level=3)
        assert open_tar.call_args.kwargs["compresslevel"] == 3
    assert len(dummy_runtime.commands_run) >= 1

    image.backup(dummy_runtime, cfg, source_mode=True)
    assert len(dummy_runtime.commands_run) >= 2


def test_image_backup_without_upload_never_imports_boto3(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    saved = {
        name: sys.modules.pop(name)
        for name in ("boto3", "botocore", "botocore.exceptions")
        if name in sys.modules
    }
    try:
        image.backup(dummy_runtime, cfg)
        assert "boto3" not in sys.modules
        assert "botocore" not in sys.modules
    finally:
        sys.modules.update(saved)


def test_image_backup_not_running(dummy_runtime, temp_dir: pathlib.Path):
    dummy_runtime.stack_exists = MagicMock(return_value=False)
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    with pytest.raises(CommandError):
        image.backup(dummy_runtime, cfg)


def test_image_backup_no_containers(dummy_runtime, temp_dir: pathlib.Path):
    dummy_runtime.run_compose = MagicMock(return_value=MagicMock(stdout=""))
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    image.backup(dummy_runtime, cfg)


def test_image_backup_prunes_old_archives_after_backup_done(
    dummy_runtime, temp_dir: pathlib.Path, capsys
):
    cfg = Config(
        name="my_stack",
        profiles={"default": Profile(file="docker-compose.yml")},
        max_backups=1,
    )
    backup_root = local_root(cfg.backup_store)
    backup_root.mkdir(parents=True)
    kept_archive = backup_root / "my_stack.image.20260201_0000.tar.gz"
    pruned_archive = backup_root / "my_stack.image.20260101_0000.tar.gz"
    kept_archive.touch()
    pruned_archive.touch()

    with patch("tarfile.open"):
        image.backup(dummy_runtime, cfg)

    assert kept_archive.exists()
    assert not pruned_archive.exists()
    out = capsys.readouterr().out
    assert out.index("Image backup done:") < out.index(
        "Pruned old backup my_stack.image.20260101_0000"
    )


def test_image_restore(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    backup_dir = local_root(cfg.backup_store)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / "my_stack.image.20260731_1200.tar.gz"

    dummy_tar = temp_dir / "img.tar"
    dummy_tar.touch()
    with tarfile.open(backup_file, "w:gz") as tar:
        tar.add(dummy_tar, arcname="img.tar")

    with patch("compman.ops.common.prompt_select", return_value=0), patch("subprocess.run"):
        image.restore(dummy_runtime, cfg, timestamp="20260731_1200")


def test_image_restore_invalid_ts(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    with pytest.raises(CommandError):
        image.restore(dummy_runtime, cfg, timestamp="invalid_ts")


def test_image_restore_missing(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    store_root = local_root(cfg.backup_store)
    store_root.mkdir(parents=True, exist_ok=True)
    fallback = str(store_root / "my_stack.image.20260731_1200.tar.gz")
    with pytest.raises(CommandError, match=re.escape(fallback)):
        image.restore(dummy_runtime, cfg, timestamp="20260731_1200")


def test_image_restore_cleans_temp_dir_when_load_fails(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    local_root(cfg.backup_store).mkdir(parents=True, exist_ok=True)
    timestamp = "20260731_1200"
    backup_file = local_root(cfg.backup_store) / f"my_stack.image.{timestamp}.tar.gz"
    image_tar = temp_dir / "broken-image.tar"
    image_tar.touch()
    with tarfile.open(backup_file, "w:gz") as tar:
        tar.add(image_tar, arcname=image_tar.name)

    dummy_runtime.load_image = MagicMock(side_effect=RuntimeError("load failed"))
    with pytest.raises(RuntimeError, match="load failed"):
        image.restore(dummy_runtime, cfg, timestamp=timestamp)

    assert not (local_root(cfg.backup_store) / f"my_stack.image.{timestamp}").exists()


def _remote_config() -> Config:
    return Config(
        name="my_stack",
        profiles={"default": Profile(file="docker-compose.yml")},
        backup_store=S3BackupStore(bucket="bucket", prefix="backups"),
    )


def test_image_backup_remote_store_uploads_and_cleans_staging(dummy_runtime, temp_dir: pathlib.Path):
    cfg = _remote_config()
    dummy_runtime.run_compose = MagicMock(return_value=MagicMock(stdout="cid1\n"))
    dummy_runtime.run_cli = MagicMock(return_value=MagicMock(stdout="/name\n"))
    fake = FakeS3()
    with patch("compman.backup_store.create_client", return_value=fake), _patch_stage(temp_dir):
        image.backup(dummy_runtime, cfg)

    key = str(fake.uploaded["Key"])
    assert key.startswith("backups/my_stack.image.")
    assert key.endswith(".tar.gz")
    assert fake.uploaded["ExtraArgs"] == {"ContentType": "application/gzip"}
    assert not _stage(temp_dir).exists()


def test_image_backup_remote_failure_keeps_staged_tarball(dummy_runtime, temp_dir: pathlib.Path):
    cfg = _remote_config()
    dummy_runtime.run_compose = MagicMock(return_value=MagicMock(stdout="cid1\n"))
    dummy_runtime.run_cli = MagicMock(return_value=MagicMock(stdout="/name\n"))
    fake = FakeS3(error=ClientError({"Error": {"Code": "500", "Message": "boom"}}, "PutObject"))
    with patch("compman.backup_store.create_client", return_value=fake), _patch_stage(temp_dir):
        with pytest.raises(CommandError) as excinfo:
            image.backup(dummy_runtime, cfg)

    leftovers = list(_stage(temp_dir).glob("*.tar.gz"))
    assert len(leftovers) == 1
    assert str(leftovers[0]) in str(excinfo.value)


def test_image_restore_remote_fetches_from_store(dummy_runtime, temp_dir: pathlib.Path):
    cfg = _remote_config()
    inner_tar = temp_dir / "name.image.backup.tar"
    with tarfile.open(inner_tar, "w") as tar:
        info = tarfile.TarInfo("placeholder")
        info.size = 0
        tar.addfile(info)
    outer = temp_dir / "source.tar.gz"
    with tarfile.open(outer, "w:gz") as tar:
        tar.add(inner_tar, arcname=inner_tar.name)
    payload = outer.read_bytes()

    class DownloadFake(FakeS3):
        def download_file(self, bucket, key, destination):
            self.downloads.append((bucket, key, destination))
            pathlib.Path(destination).write_bytes(payload)

    fake = DownloadFake(
        pages=[{"Contents": [{"Key": "backups/my_stack.image.20260731_1200.tar.gz"}]}],
        remote_size=1,
    )
    dummy_runtime.load_image = MagicMock()
    with patch("compman.backup_store.create_client", return_value=fake), _patch_stage(temp_dir):
        image.restore(dummy_runtime, cfg, timestamp="20260731_1200")

    assert fake.downloads[0][1] == "backups/my_stack.image.20260731_1200.tar.gz"
    assert dummy_runtime.load_image.called
    assert not _stage(temp_dir).exists()


def test_select_backup_timestamp_remote_lists_from_store(dummy_runtime, temp_dir: pathlib.Path):
    from compman.ops import common

    cfg = _remote_config()
    fake = FakeS3(pages=[{"Contents": [{"Key": "backups/my_stack.volume.20260731_1200.tar.gz"}]}])
    with patch("compman.backup_store.create_client", return_value=fake), patch(
        "compman.ops.common.prompt_select", return_value=0
    ):
        ts = common.select_backup_timestamp(cfg, "volume")
    assert ts == "20260731_1200"


def test_image_backup_default_gzip_names_tarball_gz(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    backup_root = local_root(cfg.backup_store)
    image.backup(dummy_runtime, cfg)
    gz = list(backup_root.glob("*.tar.gz"))
    assert len(gz) == 1
    assert gz[0].name.startswith("my_stack.image.")
    assert list(backup_root.glob("*.tar.zst")) == []


@requires_py314
def test_image_backup_zstd_writes_tar_zst_archive(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    backup_root = local_root(cfg.backup_store)
    image.backup(dummy_runtime, cfg, zstd_format=True)
    zst = list(backup_root.glob("*.tar.zst"))
    assert len(zst) == 1
    assert zst[0].name.startswith("my_stack.image.")
    assert list(backup_root.glob("*.tar.gz")) == []


@requires_py314
def test_image_restore_resolves_zstd_suffixed_archive(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    backup_dir = local_root(cfg.backup_store)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = "20260826_1200"
    archive = backup_dir / f"my_stack.image.{timestamp}.tar.zst"
    from compression import zstd as pyzstd

    inner = temp_dir / "img.tar"
    inner.touch()
    with pyzstd.open(archive, "wb") as zout:
        with tarfile.open(fileobj=zout, mode="w") as tar:
            tar.add(inner, arcname=inner.name)

    dummy_runtime.load_image = MagicMock()
    image.restore(dummy_runtime, cfg, timestamp=timestamp)

    loaded = dummy_runtime.load_image.call_args.args[0]
    assert loaded.name == "img.tar"


def test_image_backup_skips_blank_container_ids(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.run_compose = MagicMock(return_value=MagicMock(stdout="cid1\n \nX"))
    dummy_runtime.run_cli = MagicMock(return_value=MagicMock(stdout="/name\n"))

    with patch("tarfile.open"):
        image.backup(dummy_runtime, cfg, source_mode=True)

    inspect_calls = [c.args[0][-1] for c in dummy_runtime.run_cli.call_args_list if c.args[0][0] == "inspect"]
    assert "X" in inspect_calls


def test_image_restore_lists_available_backups_before_missing_archive_error(
    dummy_runtime, temp_dir: pathlib.Path, capsys
):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    local_root(cfg.backup_store).mkdir(parents=True, exist_ok=True)
    (local_root(cfg.backup_store) / "my_stack.image.19990101_0000.tar.gz").write_bytes(b"placeholder")

    with patch("compman.ops.image.select_backup_timestamp", return_value="20000101_0000"):
        with pytest.raises(CommandError, match="20000101_0000"):
            image.restore(dummy_runtime, cfg)

    assert "19990101_0000" in capsys.readouterr().out


def test_image_backup_removes_partial_archive_when_save_fails(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.run_compose = MagicMock(return_value=MagicMock(stdout="cid"))
    dummy_runtime.commit_container = MagicMock()
    dummy_runtime.save_image = MagicMock(side_effect=RuntimeError("save failed"))
    dummy_runtime.remove_image = MagicMock()

    with pytest.raises(RuntimeError, match="save failed"):
        image.backup(dummy_runtime, cfg)

    assert list(local_root(cfg.backup_store).glob("*.tar.gz")) == []
    dummy_runtime.remove_image.assert_called_once()
