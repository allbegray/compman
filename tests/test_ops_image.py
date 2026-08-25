from __future__ import annotations

import pathlib
import sys
import tarfile
from unittest.mock import MagicMock, patch

import pytest

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
    backup_dir = cfg.backup_dir
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
    cfg.backup_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(CommandError):
        image.restore(dummy_runtime, cfg, timestamp="20260731_1200")


def test_image_restore_cleans_temp_dir_when_load_fails(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    cfg.backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = "20260731_1200"
    backup_file = cfg.backup_dir / f"my_stack.image.{timestamp}.tar.gz"
    image_tar = temp_dir / "broken-image.tar"
    image_tar.touch()
    with tarfile.open(backup_file, "w:gz") as tar:
        tar.add(image_tar, arcname=image_tar.name)

    dummy_runtime.load_image = MagicMock(side_effect=RuntimeError("load failed"))
    with pytest.raises(RuntimeError, match="load failed"):
        image.restore(dummy_runtime, cfg, timestamp=timestamp)

    assert not (cfg.backup_dir / f"my_stack.image.{timestamp}").exists()
