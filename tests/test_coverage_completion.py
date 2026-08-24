from __future__ import annotations

import io
import pathlib
import runpy
import shutil
import subprocess
import sys
import tarfile
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from typer.core import TyperGroup

import compman.archive as archive
import compman.cli as cli
import compman.deploy as deploy
from compman.config import Config, ConfigError, Profile, load_config
from compman.docker import (
    ComposeContext,
    ContainerRuntime,
    _raise_probe_failure,
    resolve_compose_context,
    resolve_compose_files,
)
from compman.errors import CommandError
from compman.ops import common, image, seed, volume


def test_archive_rejects_links_and_empty_names(temp_dir):
    link = tarfile.TarInfo("link")
    link.type = tarfile.SYMTYPE
    link.linkname = "target"
    with tarfile.open(fileobj=io.BytesIO(), mode="w") as tar:
        tar.addfile(link)
        with pytest.raises(ValueError, match="links are not allowed"):
            archive.extract_tar(tar, temp_dir)

    with pytest.raises(ValueError, match="Unsafe archive path"):
        archive._validate_path(temp_dir, "")

    member = tarfile.TarInfo("safe.txt")
    fake_tar = MagicMock()
    fake_tar.getmembers.return_value = [member]
    archive.extract_tar(fake_tar, temp_dir)
    fake_tar.extract.assert_called_once_with(member, temp_dir)


@pytest.mark.parametrize("member_type", [tarfile.FIFOTYPE, tarfile.BLKTYPE, tarfile.CHRTYPE])
def test_archive_rejects_device_and_fifo_members(temp_dir, member_type):
    destination = temp_dir / "out"
    destination.mkdir()
    member = tarfile.TarInfo("special")
    member.type = member_type
    fake_tar = MagicMock()
    fake_tar.getmembers.return_value = [member]

    with pytest.raises(ValueError, match="Unsupported archive member"):
        archive.extract_tar(fake_tar, destination)

    fake_tar.extract.assert_not_called()
    assert list(destination.iterdir()) == []


def test_archive_extract_tar_aborts_over_member_total_before_extraction(temp_dir):
    destination = temp_dir / "out"
    destination.mkdir()
    payload = io.BytesIO(b"\0" * (1024 * 1024))
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo("big.bin")
        info.size = payload.getbuffer().nbytes
        tar.addfile(info, payload)
    buffer.seek(0)
    with tarfile.open(fileobj=buffer, mode="r") as tar:
        with pytest.raises(CommandError, match="1 MB size limit"):
            archive.extract_tar(tar, destination, max_bytes=1024 * 1024 - 1)

    assert list(destination.iterdir()) == []


def test_archive_extract_tar_under_limit_extracts(temp_dir):
    destination = temp_dir / "out"
    destination.mkdir()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo("small.txt")
        data = b"hello"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    buffer.seek(0)
    with tarfile.open(fileobj=buffer, mode="r") as tar:
        archive.extract_tar(tar, destination, max_bytes=1024 * 1024)

    assert (destination / "small.txt").read_text(encoding="utf-8") == "hello"


def test_archive_extract_zip_aborts_over_total_before_extraction(temp_dir):
    destination = temp_dir / "out"
    destination.mkdir()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("big.bin", b"\0" * (2 * 1024 * 1024))
    buffer.seek(0)
    with zipfile.ZipFile(buffer) as zip_file:
        with pytest.raises(CommandError, match="1 MB size limit"):
            archive.extract_zip(zip_file, destination, max_bytes=1024 * 1024)

    assert list(destination.iterdir()) == []


def test_main_module_can_be_loaded_without_running_cli():
    namespace = runpy.run_module("compman.__main__", run_name="compman.not_main")
    assert "app" in namespace


def test_cli_group_converts_command_error(capsys: pytest.CaptureFixture[str]):
    group = cli.HelpOnUnknownCommandGroup(name="test")
    with patch.object(TyperGroup, "main", side_effect=CommandError("boom", code=7)):
        with pytest.raises(SystemExit) as exc:
            group.main()
    assert exc.value.code == 7
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "boom\n"
    assert "Traceback" not in captured.err


def test_config_rejects_non_string_folder(temp_dir):
    path = temp_dir / "compman.yml"
    path.write_text("compman:\n  folder: 123\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="folder"):
        load_config(str(path))


def test_deploy_handles_s3_exception_at_boundary(temp_dir):
    from botocore.exceptions import NoCredentialsError

    with patch("boto3.client", side_effect=NoCredentialsError()):
        with pytest.raises(SystemExit):
            deploy.deploy(s3_path="s3://bucket/key")


@pytest.mark.parametrize("new_kind", ["file", "directory"])
def test_deploy_swap_rolls_back_new_entries(temp_dir, new_kind):
    root = temp_dir / "target"
    src = temp_dir / "source"
    root.mkdir()
    src.mkdir()
    (root / "old.txt").write_text("old", encoding="utf-8")
    first = src / "a-new"
    if new_kind == "directory":
        first.mkdir()
        (first / "data.txt").write_text("new", encoding="utf-8")
    else:
        first.write_text("new", encoding="utf-8")
    (src / "b-new").write_text("new", encoding="utf-8")
    (src / "z-fail").write_text("fail", encoding="utf-8")

    real_move = shutil.move

    def move_then_fail(source, destination):
        if pathlib.Path(source).name == "z-fail":
            raise OSError("swap failed")
        return real_move(source, destination)

    with patch("compman.deploy.shutil.move", side_effect=move_then_fail):
        with pytest.raises(OSError, match="swap failed"):
            deploy._swap(src, root)

    assert (root / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (root / "a-new").exists()


def test_deploy_swap_skips_repository_markers(temp_dir):
    root = temp_dir / "target"
    src = temp_dir / "source"
    root.mkdir()
    src.mkdir()
    (root / ".git").mkdir()
    (root / ".gitkeep").touch()
    (src / ".gitkeep").touch()
    (src / "app.txt").write_text("new", encoding="utf-8")

    deploy._swap(src, root)

    assert (root / ".git").is_dir()
    assert (root / ".gitkeep").is_file()
    assert (root / "app.txt").is_file()


def test_deploy_swap_rollback_tolerates_already_missing_new_entry(temp_dir):
    root = temp_dir / "target"
    src = temp_dir / "source"
    root.mkdir()
    src.mkdir()
    (src / "a-disappears").write_text("new", encoding="utf-8")
    (src / "z-fail").write_text("fail", encoding="utf-8")

    def disappear_then_fail(source, destination):
        source_path = pathlib.Path(source)
        if source_path.name == "a-disappears":
            source_path.unlink()
            return str(destination)
        raise OSError("swap failed")

    with patch("compman.deploy.shutil.move", side_effect=disappear_then_fail):
        with pytest.raises(OSError, match="swap failed"):
            deploy._swap(src, root)

    assert not (root / "a-disappears").exists()


def test_deploy_swap_rollback_cleanup_is_platform_independent(temp_dir):
    root = temp_dir / "target"
    src = temp_dir / "source"
    root.mkdir()
    src.mkdir()
    (src / "a-directory").mkdir()
    (src / "b-disappears").touch()
    (src / "z-fail").touch()

    def controlled_move(source, destination):
        name = pathlib.Path(source).name
        if name == "a-directory":
            pathlib.Path(destination).mkdir()
            return str(destination)
        if name == "b-disappears":
            pathlib.Path(source).unlink()
            return str(destination)
        raise OSError("swap failed")

    with patch("compman.deploy.shutil.move", side_effect=controlled_move):
        with pytest.raises(OSError, match="swap failed"):
            deploy._swap(src, root)

    assert not (root / "a-directory").exists()
    assert not (root / "b-disappears").exists()


def test_windows_key_reader_on_every_platform():
    fake_msvcrt = MagicMock()
    with patch.dict(sys.modules, {"msvcrt": fake_msvcrt}), patch.object(common.sys, "platform", "win32"):
        fake_msvcrt.getch.side_effect = [b"\x00", b"H"]
        assert common.get_key() == "up"
        fake_msvcrt.getch.side_effect = [b"\xe0", b"P"]
        assert common.get_key() == "down"
        fake_msvcrt.getch.side_effect = [b"\x00", b"X"]
        assert common.get_key() == "other"
        fake_msvcrt.getch.side_effect = [b"\r"]
        assert common.get_key() == "enter"
        fake_msvcrt.getch.side_effect = [b"\x1b"]
        assert common.get_key() == "esc"
        fake_msvcrt.getch.side_effect = [b"\x03"]
        with pytest.raises(KeyboardInterrupt):
            common.get_key()
        fake_msvcrt.getch.side_effect = [b"x"]
        assert common.get_key() == "other"


def test_container_runtime_passthru_helpers_and_shell():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    with patch("compman.docker._passthru", return_value=0) as passthru:
        assert runtime.passthru_compose(["ps"]) == 0
        assert runtime.passthru_cli(["ps"]) == 0
        assert runtime.logs("cid", follow=True, tail=7) == 0
        assert runtime.logs("cid", follow=False, tail=7) == 0
        assert runtime.exec_shell("cid") == 0
    assert passthru.call_count == 5


def test_container_runtime_commands_without_optional_filters(temp_dir):
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    assert runtime._compose_cmd(None, None) == ["docker", "compose"]
    with patch.object(runtime, "run_cli", return_value=MagicMock(stdout="cid\n")) as run_cli:
        assert runtime.get_container_id("web") == "cid"
    command = run_cli.call_args.args[0]
    assert "com.docker.compose.project" not in " ".join(command)


def test_probe_failure_and_compose_context_error_paths(temp_dir):
    failed = subprocess.CompletedProcess(["docker", "ps"], 1, "", "failed")
    with pytest.raises(RuntimeError, match="Command failed"):
        _raise_probe_failure(failed)

    compose = temp_dir / "base.yml"
    compose.touch()
    cfg = Config(name="app", compose_base="base.yml", profiles={"dev": Profile()})
    files, env = resolve_compose_files(cfg, "dev")
    assert files == [compose]
    assert env == {}

    with pytest.raises(ConfigError, match="Unknown profile"):
        resolve_compose_context(Config(name="app", profiles={}), "dev")


def test_stack_paused_restart_failure_paths(temp_dir, capsys):
    context = ComposeContext("app", (temp_dir / "compose.yml",), {})
    runtime = MagicMock()
    runtime.run_compose.side_effect = [MagicMock(), RuntimeError("restart failed")]
    with pytest.raises(RuntimeError, match="restart failed"):
        with common.stack_paused(runtime, context):
            pass

    runtime.reset_mock()
    runtime.run_compose.side_effect = [MagicMock(), RuntimeError("restart failed")]
    with pytest.raises(ValueError, match="operation failed"):
        with common.stack_paused(runtime, context):
            raise ValueError("operation failed")
    assert "failed to restart" in capsys.readouterr().err


def test_image_backup_removes_partial_archive_on_failure(dummy_runtime, temp_dir):
    cfg = Config("app", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.run_compose = MagicMock(return_value=MagicMock(stdout="cid"))
    dummy_runtime.commit_container = MagicMock()
    dummy_runtime.save_image = MagicMock(side_effect=RuntimeError("save failed"))
    dummy_runtime.remove_image = MagicMock()

    with pytest.raises(RuntimeError, match="save failed"):
        image.backup(dummy_runtime, cfg)

    assert list(cfg.backup_dir.glob("*.tar.gz")) == []
    dummy_runtime.remove_image.assert_called_once()


@pytest.mark.parametrize("port", [0, 65536])
def test_seed_rejects_out_of_range_ports(temp_dir, port):
    with pytest.raises(CommandError, match="port"):
        seed.generate_seed(port=port)


def test_volume_backup_uses_collision_timestamp(dummy_runtime, temp_dir):
    cfg = Config("app", profiles={"default": Profile(file="docker-compose.yml")})
    fixed = MagicMock()
    fixed.strftime.side_effect = ["20260731_120000", "20260731_120000_123456"]
    existing = cfg.backup_dir / "app.volume.20260731_120000.tar.gz"
    existing.parent.mkdir(parents=True)
    existing.touch()
    with patch("compman.ops.volume.datetime") as dt, patch(
        "compman.ops.volume._inspect_mount", return_value=None
    ):
        dt.now.return_value = fixed
        volume.backup(dummy_runtime, cfg, no_stop=True)
    assert (cfg.backup_dir / "app.volume.20260731_120000_123456.tar.gz").is_file()


@pytest.mark.parametrize("content", ["42", '[{"container": "c"}]'])
def test_volume_mapping_rejects_invalid_shapes(temp_dir, content):
    path = temp_dir / "volume-map.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(CommandError, match="Invalid volume map"):
        volume._load_mapping(path)
