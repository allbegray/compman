from __future__ import annotations

import pathlib
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
    local_root(cfg.backup_store).mkdir(parents=True, exist_ok=True)
    with pytest.raises(CommandError):
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

    fake = DownloadFake(pages=[{"Contents": [{"Key": "backups/my_stack.image.20260731_1200.tar.gz"}]}])
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
