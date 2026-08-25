from __future__ import annotations

import json
import pathlib
import sys
import tarfile
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from compman.config import Config, Profile
from compman.errors import CommandError
from compman.ops import volume


def test_volume_backup(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    with patch("tarfile.open") as open_tar, patch("compman.ops.volume._inspect_mount", return_value={"container": "c1", "volume": "vol1", "destination": "/data"}):
        volume.backup(dummy_runtime, cfg, no_stop=False, compression_level=2)
        assert len(dummy_runtime.compose_runs) >= 1
        assert open_tar.call_args.kwargs["compresslevel"] == 2

        volume.backup(dummy_runtime, cfg, no_stop=True)
        assert open_tar.call_args.kwargs["compresslevel"] == 6


def test_volume_backup_no_volumes(dummy_runtime, temp_dir: pathlib.Path):
    dummy_runtime.list_volumes = MagicMock(return_value=[])
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    volume.backup(dummy_runtime, cfg)


def test_volume_backup_not_running(dummy_runtime, temp_dir: pathlib.Path):
    dummy_runtime.stack_exists = MagicMock(return_value=False)
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    with pytest.raises(CommandError):
        volume.backup(dummy_runtime, cfg)


def test_volume_backup_pushes_configured_upload_outside_paused_window(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    cfg.backup_upload = "s3://bucket/backups"
    events: list[str] = []
    original_run_compose = dummy_runtime.run_compose

    def recording_run_compose(args, **kwargs):
        events.append(f"compose:{args[0]}")
        return original_run_compose(args, **kwargs)

    dummy_runtime.run_compose = recording_run_compose

    client = MagicMock()
    uploaded: dict[str, str] = {}

    def record_upload(Filename, Bucket, Key, ExtraArgs=None):
        uploaded.update(Filename=Filename, Bucket=Bucket, Key=Key)
        events.append("upload")

    client.upload_file.side_effect = record_upload
    client.head_object.side_effect = lambda b, k: {
        "ContentLength": pathlib.Path(uploaded["Filename"]).stat().st_size
    }

    with patch("compman.ops.volume._inspect_mount", return_value=None), patch(
        "compman.ops.upload.create_client", return_value=client
    ):
        volume.backup(dummy_runtime, cfg)

    assert uploaded["Bucket"] == "bucket"
    assert uploaded["Key"] == f"backups/{pathlib.Path(uploaded['Filename']).name}"
    upload_idx = events.index("upload")
    assert "compose:start" in events[:upload_idx]
    assert not any(event.startswith("compose:") for event in events[upload_idx + 1 :])


def test_volume_backup_upload_failure_keeps_local_tarball(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    cfg.backup_upload = "s3://bucket/backups"
    client = MagicMock()
    client.upload_file.side_effect = ClientError({"Error": {"Code": "403"}}, "PutObject")

    with patch("compman.ops.volume._inspect_mount", return_value=None), patch(
        "compman.ops.upload.create_client", return_value=client
    ):
        with pytest.raises(CommandError) as excinfo:
            volume.backup(dummy_runtime, cfg)

    leftovers = list(cfg.backup_dir.glob("*.tar.gz"))
    assert len(leftovers) == 1
    assert leftovers[0].stat().st_size > 0
    assert str(leftovers[0]) in str(excinfo.value)


def test_volume_backup_without_upload_never_imports_boto3(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    saved = {
        name: sys.modules.pop(name)
        for name in ("boto3", "botocore", "botocore.exceptions")
        if name in sys.modules
    }
    try:
        with patch("compman.ops.volume._inspect_mount", return_value=None):
            volume.backup(dummy_runtime, cfg)
        assert "boto3" not in sys.modules
        assert "botocore" not in sys.modules
    finally:
        sys.modules.update(saved)


def test_volume_restore(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    backup_dir = cfg.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / "my_stack.volume.20260731_1200.tar.gz"

    map_file = temp_dir / "volume-map.json"
    map_file.write_text('{"container1": {"volume": "vol1", "destination": "/data"}}', encoding="utf-8")
    with tarfile.open(backup_file, "w:gz") as tar:
        tar.add(map_file, arcname="volume-map.json")

    with patch("compman.ops.common.prompt_select", return_value=0), patch("compman.ops.volume._inspect_mount", return_value={"container": "c1", "volume": "vol1", "destination": "/data"}):
        volume.restore(dummy_runtime, cfg, timestamp="20260731_1200", no_stop=False)
        volume.restore(dummy_runtime, cfg, timestamp="20260731_1200", no_stop=True)
        assert not any(call[0] == "exec" for call in dummy_runtime.commands_run)


def test_volume_restore_replace_clears_destination(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    backup_dir = cfg.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / "my_stack.volume.20260731_1200.tar.gz"

    map_file = temp_dir / "volume-map.json"
    map_file.write_text('{"container1": {"volume": "vol1", "destination": "/data"}}', encoding="utf-8")
    (temp_dir / "vol1").mkdir()
    (temp_dir / "vol1" / "data.txt").write_text("hello", encoding="utf-8")
    with tarfile.open(backup_file, "w:gz") as tar:
        tar.add(map_file, arcname="volume-map.json")
        tar.add(temp_dir / "vol1", arcname="vol1")

    with patch("compman.ops.common.prompt_select", return_value=0), patch("compman.ops.volume._inspect_mount", return_value={"container": "c1", "volume": "vol1", "destination": "/data"}):
        volume.restore(dummy_runtime, cfg, timestamp="20260731_1200", replace=True)

    exec_call = ["exec", "container1", "sh", "-c", 'rm -rf -- "$1"/* "$1"/.[!.]* "$1"/..?* 2>/dev/null || true', "_", "/data"]
    assert exec_call in dummy_runtime.commands_run
    exec_idx = dummy_runtime.commands_run.index(exec_call)
    cp_idx = next(i for i, call in enumerate(dummy_runtime.commands_run) if call[0] == "cp" and call[2] == "container1:/data")
    assert exec_idx < cp_idx


def test_volume_restore_replace_skips_missing_source(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    backup_dir = cfg.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / "my_stack.volume.20260731_1200.tar.gz"

    map_file = temp_dir / "volume-map.json"
    map_file.write_text('{"container1": {"volume": "vol1", "destination": "/data"}}', encoding="utf-8")
    with tarfile.open(backup_file, "w:gz") as tar:
        tar.add(map_file, arcname="volume-map.json")

    with patch("compman.ops.common.prompt_select", return_value=0):
        volume.restore(dummy_runtime, cfg, timestamp="20260731_1200", replace=True)

    assert not any(call[0] == "exec" for call in dummy_runtime.commands_run)


def test_volume_restore_invalid_timestamp(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    with pytest.raises(CommandError):
        volume.restore(dummy_runtime, cfg, timestamp="invalid_ts")


def test_volume_restore_not_found(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    cfg.backup_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(CommandError):
        volume.restore(dummy_runtime, cfg, timestamp="20260731_1200")


def test_volume_restore_not_running(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    backup_dir = cfg.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / "my_stack.volume.20260731_1200.tar.gz"

    map_file = temp_dir / "volume-map.json"
    map_file.write_text('{"container1": {"volume": "vol1", "destination": "/data"}}', encoding="utf-8")
    with tarfile.open(backup_file, "w:gz") as tar:
        tar.add(map_file, arcname="volume-map.json")

    dummy_runtime.stack_exists = MagicMock(return_value=False)
    volume.restore(dummy_runtime, cfg, timestamp="20260731_1200")


def test_volume_pull_push(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    with patch("compman.ops.volume._inspect_mount", return_value={"container": "container1", "volume": "vol1", "destination": "/data"}):
        volume.pull(dummy_runtime, cfg)
        assert (cfg.volume_dir / "volume-map.json").exists()

        vol_dir = cfg.volume_dir / "vol1"
        vol_dir.mkdir(parents=True, exist_ok=True)
        volume.push(dummy_runtime, cfg)
        assert len(dummy_runtime.commands_run) >= 1


def test_volume_push_replace_clears_destination(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    volume_dir = cfg.volume_dir
    (volume_dir / "vol1").mkdir(parents=True, exist_ok=True)
    (volume_dir / "volume-map.json").write_text(
        json.dumps([{"container": "container1", "volume": "vol1", "destination": "/data"}]), encoding="utf-8"
    )
    volume.push(dummy_runtime, cfg, replace=True)

    assert ["exec", "container1", "sh", "-c", 'rm -rf -- "$1"/* "$1"/.[!.]* "$1"/..?* 2>/dev/null || true', "_", "/data"] in dummy_runtime.commands_run


@pytest.mark.parametrize(
    "dest",
    ["/", "relative", "", "/data/", "/a/../b", "//x"],
)
def test_validate_replace_dest_rejects_unsafe_paths(dummy_runtime, dest):
    with pytest.raises(CommandError):
        volume._validate_replace_dest(dest)


@pytest.mark.parametrize("dest", ["/data", "/var/lib/app/data"])
def test_validate_replace_dest_accepts_absolute_paths(dest):
    volume._validate_replace_dest(dest)


def test_volume_pull_no_volumes(dummy_runtime, temp_dir: pathlib.Path):
    dummy_runtime.list_volumes = MagicMock(return_value=[])
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    volume.pull(dummy_runtime, cfg)


def test_volume_pull_not_running(dummy_runtime, temp_dir: pathlib.Path):
    dummy_runtime.stack_exists = MagicMock(return_value=False)
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    with pytest.raises(CommandError):
        volume.pull(dummy_runtime, cfg)


def test_volume_push_no_map(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    with pytest.raises(CommandError):
        volume.push(dummy_runtime, cfg)


def test_volume_mapping_preserves_multiple_mounts_per_container(temp_dir: pathlib.Path):
    mapping = [
        {"container": "db", "volume": "data", "destination": "/var/lib/data"},
        {"container": "db", "volume": "logs", "destination": "/var/log/db"},
    ]
    map_path = temp_dir / "volume-map.json"
    map_path.write_text(json.dumps(volume._merge_mapping(mapping)), encoding="utf-8")

    assert volume._load_mapping(map_path) == mapping


def test_volume_mapping_reads_legacy_format(temp_dir: pathlib.Path):
    map_path = temp_dir / "volume-map.json"
    map_path.write_text(
        '{"db": {"volume": "data", "destination": "/var/lib/data"}}',
        encoding="utf-8",
    )

    assert volume._load_mapping(map_path) == [
        {"container": "db", "volume": "data", "destination": "/var/lib/data"}
    ]


def _write_volume_backup(cfg: Config, temp_dir: pathlib.Path, entries: list[dict[str, str]]) -> None:
    backup_dir = cfg.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / "my_stack.volume.20260731_1200.tar.gz"
    map_file = temp_dir / "volume-map.json"
    map_file.write_text(json.dumps(entries), encoding="utf-8")
    with tarfile.open(backup_file, "w:gz") as tar:
        tar.add(map_file, arcname="volume-map.json")


def test_volume_restore_rejects_escaping_volume_name(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    _write_volume_backup(
        cfg,
        temp_dir,
        [{"container": "container1", "volume": "../escape", "destination": "/data"}],
    )

    with pytest.raises(CommandError, match="escapes the backup directory"):
        volume.restore(dummy_runtime, cfg, timestamp="20260731_1200")

    assert not any(call[0] == "cp" for call in dummy_runtime.commands_run)


@pytest.mark.parametrize("container", ["ghost", "../evil"])
def test_volume_restore_rejects_unknown_or_invalid_container(
    dummy_runtime, temp_dir: pathlib.Path, container: str
):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    _write_volume_backup(
        cfg,
        temp_dir,
        [{"container": container, "volume": "vol1", "destination": "/data"}],
    )

    with pytest.raises(CommandError, match="unknown container"):
        volume.restore(dummy_runtime, cfg, timestamp="20260731_1200")

    assert not any(call[0] == "cp" for call in dummy_runtime.commands_run)


def test_volume_restore_rejects_unsafe_destination(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    _write_volume_backup(
        cfg,
        temp_dir,
        [{"container": "container1", "volume": "vol1", "destination": "relative"}],
    )

    with pytest.raises(CommandError, match="Invalid --replace destination"):
        volume.restore(dummy_runtime, cfg, timestamp="20260731_1200")

    assert not any(call[0] == "cp" for call in dummy_runtime.commands_run)


def test_volume_push_rejects_escaping_volume_name(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    volume_dir = cfg.volume_dir
    (volume_dir / "vol1").mkdir(parents=True, exist_ok=True)
    (volume_dir / "volume-map.json").write_text(
        json.dumps([{"container": "container1", "volume": "../../secrets", "destination": "/data"}]),
        encoding="utf-8",
    )

    with pytest.raises(CommandError, match="escapes the backup directory"):
        volume.push(dummy_runtime, cfg)

    assert not any(call[0] == "cp" for call in dummy_runtime.commands_run)
