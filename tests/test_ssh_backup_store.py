from __future__ import annotations

import os
import pathlib
import subprocess
from unittest.mock import patch

import pytest

from compman.backup_store import (
    SshBackupStore,
    archive_location,
    delete_archive,
    fetch_archive,
    find_archive,
    list_archives,
    local_root,
    new_backup_paths,
    parse_backup_store,
    put_archive,
    staged_archive,
)
from compman.config import Config
from compman.errors import CommandError, ConfigError
from compman.ops.common import prune_archives


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _stage(temp_dir: pathlib.Path) -> pathlib.Path:
    stage = temp_dir / "stage"
    stage.mkdir()
    return stage


# ---- parse_backup_store: ssh:// URIs ----


def test_parse_backup_store_ssh_minimal_uri():
    store = parse_backup_store("ssh://host.example/backups")
    assert store == SshBackupStore(host="host.example", path="backups")
    assert store.is_remote is True


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (
            "ssh://amy@host/backups",
            SshBackupStore(host="host", path="backups", user="amy"),
        ),
        (
            "ssh://host:2222/backups",
            SshBackupStore(host="host", path="backups", port=2222),
        ),
        (
            "ssh://amy@host:2222/backups",
            SshBackupStore(host="host", path="backups", user="amy", port=2222),
        ),
        (
            "ssh://host//srv/bak/",
            SshBackupStore(host="host", path="srv/bak"),
        ),
        ("ssh://host:1/bk", SshBackupStore(host="host", path="bk", port=1)),
        ("ssh://host:65535/bk", SshBackupStore(host="host", path="bk", port=65535)),
    ],
)
def test_parse_backup_store_ssh_uri_variants(uri: str, expected: SshBackupStore):
    assert parse_backup_store(uri) == expected


@pytest.mark.parametrize(
    ("uri", "match"),
    [
        ("ssh://host", "missing a remote path"),
        ("ssh://host/", "missing a remote path"),
        ("ssh:///backups", "missing a host name"),
        ("ssh://amy@/backups", "missing a host name"),
        ("ssh://host:abc/backups", "invalid port"),
        ("ssh://host:/backups", "invalid port"),
        ("ssh://host:0/backups", "invalid port"),
        ("ssh://host:70000/backups", "invalid port"),
    ],
)
def test_parse_backup_store_ssh_uri_rejects_malformed(uri: str, match: str):
    with pytest.raises(ConfigError, match=match):
        parse_backup_store(uri)


def test_local_root_rejects_ssh_store():
    with pytest.raises(ValueError, match="backup store is not local"):
        local_root(SshBackupStore(host="h", path="bk"))


# ---- archive_location ----


def test_archive_location_ssh_forms():
    assert (
        archive_location(SshBackupStore(host="host", path="backups"), "a.tar.gz")
        == "ssh://host/backups/a.tar.gz"
    )
    assert (
        archive_location(
            SshBackupStore(host="host", path="backups", user="amy", port=2222), "a.tar.zst"
        )
        == "ssh://amy@host:2222/backups/a.tar.zst"
    )


# ---- put_archive ----


def test_put_archive_scp_uploads_and_cleans_staging(temp_dir: pathlib.Path):
    stage = _stage(temp_dir)
    tarball = stage / "app.volume.1.tar.gz"
    tarball.write_bytes(b"data")
    store = SshBackupStore(host="host", path="backups", user="amy", port=2222)
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/scp"),
        patch("compman.backup_store.subprocess.run", return_value=_proc()) as run,
    ):
        location = put_archive(store, tarball.name, tarball)
    assert location == "ssh://amy@host:2222/backups/app.volume.1.tar.gz"
    argv = run.call_args.args[0]
    assert argv[0] == "/usr/bin/scp"
    assert argv[argv.index("-P") + 1] == "2222"
    assert argv[argv.index("-o") + 1] == "BatchMode=yes"
    assert "StrictHostKeyChecking=accept-new" in argv
    assert str(tarball) in argv
    assert argv[-1] == "amy@host:backups/app.volume.1.tar.gz"
    assert not tarball.exists()
    assert not stage.exists()


def test_put_archive_failure_keeps_staged_tarball(temp_dir: pathlib.Path):
    stage = _stage(temp_dir)
    tarball = stage / "app.volume.1.tar.gz"
    tarball.write_bytes(b"data")
    store = SshBackupStore(host="host", path="backups")
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/scp"),
        patch(
            "compman.backup_store.subprocess.run",
            return_value=_proc(returncode=1, stderr="permission denied\n"),
        ) as run,
        pytest.raises(CommandError, match="Remote operation failed") as excinfo,
    ):
        put_archive(store, tarball.name, tarball)
    assert run.call_args.args[0][-1] == "host:backups/app.volume.1.tar.gz"
    assert "permission denied" in str(excinfo.value)
    assert tarball.exists()
    assert stage.exists()


def test_put_archive_failure_without_stderr_reports_exit_code(temp_dir: pathlib.Path):
    stage = _stage(temp_dir)
    tarball = stage / "app.volume.1.tar.gz"
    tarball.write_bytes(b"data")
    store = SshBackupStore(host="host", path="backups")
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/scp"),
        patch("compman.backup_store.subprocess.run", return_value=_proc(returncode=3)),
        pytest.raises(CommandError, match="exit code 3"),
    ):
        put_archive(store, tarball.name, tarball)


def test_put_archive_missing_scp_binary_raises_command_error(temp_dir: pathlib.Path):
    tarball = temp_dir / "a.tar.gz"
    tarball.write_bytes(b"data")
    store = SshBackupStore(host="host", path="bk")
    with (
        patch("compman.backup_store.shutil.which", return_value=None),
        pytest.raises(CommandError, match="not available on PATH"),
    ):
        put_archive(store, tarball.name, tarball)


def test_put_archive_timeout_is_mapped_to_command_error(temp_dir: pathlib.Path):
    stage = _stage(temp_dir)
    tarball = stage / "app.volume.1.tar.gz"
    tarball.write_bytes(b"data")
    store = SshBackupStore(host="host", path="bk")
    expired = subprocess.TimeoutExpired(cmd=["scp"], timeout=7)
    with (
        patch.dict(os.environ, {"COMPMAN_TIMEOUT": "7"}),
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/scp"),
        patch("compman.backup_store.subprocess.run", side_effect=expired),
        pytest.raises(CommandError, match="Operation timed out after 7s"),
    ):
        put_archive(store, tarball.name, tarball)


def test_put_archive_honors_compman_timeout_kwarg(temp_dir: pathlib.Path):
    tarball = temp_dir / "a.tar.gz"
    tarball.write_bytes(b"data")
    store = SshBackupStore(host="host", path="bk")
    with (
        patch.dict(os.environ, {"COMPMAN_TIMEOUT": "9"}),
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/scp"),
        patch("compman.backup_store.subprocess.run", return_value=_proc()) as run,
    ):
        put_archive(store, tarball.name, tarball)
    assert run.call_args.kwargs["timeout"] == 9.0


# ---- fetch_archive ----


def test_fetch_archive_scp_downloads_to_dest(temp_dir: pathlib.Path):
    dest = temp_dir / "dest.tar.gz"
    store = SshBackupStore(host="host", path="bk", user="amy")
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/scp"),
        patch("compman.backup_store.subprocess.run", return_value=_proc()) as run,
    ):
        fetch_archive(store, "app.volume.1.tar.gz", dest)
    argv = run.call_args.args[0]
    assert argv[0] == "/usr/bin/scp"
    assert "-P" not in argv
    assert argv[-2] == "amy@host:bk/app.volume.1.tar.gz"
    assert argv[-1] == str(dest)


def test_fetch_archive_failure_raises_command_error():
    store = SshBackupStore(host="host", path="bk", port=2200)
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/scp"),
        patch(
            "compman.backup_store.subprocess.run",
            return_value=_proc(returncode=255, stderr="connection refused\n"),
        ),
        pytest.raises(CommandError, match="connection refused") as excinfo,
    ):
        fetch_archive(store, "app.volume.1.tar.gz", pathlib.Path("/tmp/dest"))
    assert "host:2200/bk" in str(excinfo.value)


def test_fetch_archive_missing_binary_raises_command_error(temp_dir: pathlib.Path):
    store = SshBackupStore(host="host", path="bk")
    with (
        patch("compman.backup_store.shutil.which", return_value=None),
        pytest.raises(CommandError, match="not available on PATH"),
    ):
        fetch_archive(store, "a.tar.gz", temp_dir / "d")


def test_fetch_archive_vanishing_binary_maps_to_unavailable(temp_dir: pathlib.Path):
    store = SshBackupStore(host="host", path="bk")
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/scp"),
        patch(
            "compman.backup_store.subprocess.run",
            side_effect=FileNotFoundError(2, "No such file or directory"),
        ),
        pytest.raises(CommandError, match="not available on PATH"),
    ):
        fetch_archive(store, "a.tar.gz", temp_dir / "d")


# ---- find_archive ----


def test_find_archive_ssh_prefers_gz_short_circuit():
    store = SshBackupStore(host="host", path="backups")
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/ssh"),
        patch("compman.backup_store.subprocess.run", return_value=_proc()) as run,
    ):
        found = find_archive(store, "app", "volume", "20260731_1200")
    assert found == "app.volume.20260731_1200.tar.gz"
    run.assert_called_once()
    argv = run.call_args.args[0]
    assert argv[0] == "/usr/bin/ssh"
    assert argv[-2] == "host"
    assert argv[-1] == "test -f backups/app.volume.20260731_1200.tar.gz"


def test_find_archive_ssh_falls_back_to_zst():
    store = SshBackupStore(host="host", path="backups")
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/ssh"),
        patch(
            "compman.backup_store.subprocess.run",
            side_effect=[_proc(returncode=1), _proc()],
        ) as run,
    ):
        found = find_archive(store, "app", "volume", "20260731_1200")
    assert found == "app.volume.20260731_1200.tar.zst"
    assert run.call_count == 2
    assert run.call_args_list[1].args[0][-1].endswith(".tar.zst")


def test_find_archive_ssh_both_missing_returns_none():
    store = SshBackupStore(host="host", path="backups")
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/ssh"),
        patch(
            "compman.backup_store.subprocess.run",
            side_effect=[_proc(returncode=1), _proc(returncode=1)],
        ) as run,
    ):
        assert find_archive(store, "app", "volume", "20260731_1200") is None
    assert run.call_count == 2


def test_find_archive_ssh_probe_error_raises():
    store = SshBackupStore(host="host", path="backups")
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/ssh"),
        patch(
            "compman.backup_store.subprocess.run",
            return_value=_proc(returncode=255, stderr="Host key verification failed."),
        ),
        pytest.raises(CommandError, match="Host key verification failed"),
    ):
        find_archive(store, "app", "volume", "20260731_1200")


# ---- delete_archive ----


def test_delete_archive_removes_both_suffixes():
    store = SshBackupStore(host="host", path="bk")
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/ssh"),
        patch(
            "compman.backup_store.subprocess.run",
            side_effect=[_proc(), _proc()],
        ) as run,
    ):
        delete_archive(store, "app.volume.1")
    commands = [call.args[0][-1] for call in run.call_args_list]
    assert commands == ["rm -f bk/app.volume.1.tar.gz", "rm -f bk/app.volume.1.tar.zst"]


def test_delete_archive_failure_stops_after_first_suffix():
    store = SshBackupStore(host="host", path="bk")
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/ssh"),
        patch(
            "compman.backup_store.subprocess.run",
            return_value=_proc(returncode=1, stderr="read-only file system"),
        ) as run,
        pytest.raises(CommandError, match="read-only file system"),
    ):
        delete_archive(store, "app.volume.1")
    assert run.call_count == 1


def test_delete_archive_uses_dash_p_free_ssh_port_flag():
    store = SshBackupStore(host="host", path="bk", port=2223)
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/ssh"),
        patch("compman.backup_store.subprocess.run", return_value=_proc()) as run,
    ):
        delete_archive(store, "n")
    argv = run.call_args.args[0]
    assert argv[argv.index("-p") + 1] == "2223"
    assert "-P" not in argv


# ---- list_archives ----


def test_list_archives_filters_prefix_suffix_and_sorts_desc():
    store = SshBackupStore(host="host", path="backups")
    listing = "\n".join(
        [
            "app.volume.20260801_0900.tar.gz",
            "app.volume.20260731_1200.tar.zst",
            "other.volume.20260601_0000.tar.gz",
            "app.volume.notes.txt",
            "app.service.20260505_0505.tar.gz",
        ]
    )
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/ssh"),
        patch("compman.backup_store.subprocess.run", return_value=_proc(stdout=listing)) as run,
    ):
        assert list_archives(store, "app", "volume") == ["20260801_0900", "20260731_1200"]
    argv = run.call_args.args[0]
    assert argv[-2] == "host"
    assert argv[-1] == "ls -1 backups"


def test_list_archives_missing_remote_directory_is_empty():
    store = SshBackupStore(host="host", path="nope")
    stderr = "ls: cannot access 'nope': No such file or directory"
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/ssh"),
        patch(
            "compman.backup_store.subprocess.run",
            return_value=_proc(returncode=1, stderr=stderr),
        ),
    ):
        assert list_archives(store, "app", "volume") == []


def test_list_archives_empty_output_is_empty():
    store = SshBackupStore(host="host", path="backups")
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/ssh"),
        patch("compman.backup_store.subprocess.run", return_value=_proc()),
    ):
        assert list_archives(store, "app", "volume") == []


def test_list_archives_other_failure_raises_command_error():
    store = SshBackupStore(host="host", path="backups")
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/ssh"),
        patch(
            "compman.backup_store.subprocess.run",
            return_value=_proc(returncode=2, stderr="Permission denied"),
        ),
        pytest.raises(CommandError, match="Permission denied"),
    ):
        list_archives(store, "app", "volume")


# ---- staged_archive ----


def test_staged_archive_ssh_fetches_into_stage_and_cleans_up(temp_dir: pathlib.Path):
    stage = _stage(temp_dir)
    store = SshBackupStore(host="host", path="bk")
    with (
        patch("compman.backup_store.tempfile.mkdtemp", return_value=str(stage)),
        patch("compman.backup_store.fetch_archive") as fetch,
        staged_archive(store, "app.volume.1.tar.gz") as tarball,
    ):
        assert tarball == stage / "app.volume.1.tar.gz"
        assert stage.exists()
    fetch.assert_called_once_with(store, "app.volume.1.tar.gz", stage / "app.volume.1.tar.gz")
    assert not stage.exists()


def test_staged_archive_cleans_stage_when_fetch_fails(temp_dir: pathlib.Path):
    stage = _stage(temp_dir)
    store = SshBackupStore(host="host", path="bk")
    with (
        patch("compman.backup_store.tempfile.mkdtemp", return_value=str(stage)),
        patch("compman.backup_store.fetch_archive", side_effect=CommandError("scp boom")),
        pytest.raises(CommandError, match="scp boom"),
    ):
        with staged_archive(store, "app.volume.1.tar.gz"):
            pass
    assert not stage.exists()


# ---- new_backup_paths ----


@pytest.mark.parametrize(("zstd", "suffix"), [(False, ".tar.gz"), (True, ".tar.zst")])
def test_new_backup_paths_ssh_stages_in_temp_workdir(
    temp_dir: pathlib.Path, zstd: bool, suffix: str
):
    stage = _stage(temp_dir)
    with patch("compman.backup_store.tempfile.mkdtemp", return_value=str(stage)):
        workdir, tarball = new_backup_paths(
            SshBackupStore(host="host", path="bk"), "app", "volume", zstd_format=zstd
        )
    assert workdir == stage
    assert tarball.parent == workdir
    assert tarball.name.startswith("app.volume.")
    assert tarball.name.endswith(suffix)


# ---- prune boundary through the shared ops helper ----


def test_prune_archives_over_ssh_keeps_newest_max_backups():
    store = SshBackupStore(host="host", path="bk")
    config = Config(name="app", max_backups=2, backup_store=store)
    listing = "\n".join(
        [
            "app.volume.20260801_0900.tar.gz",
            "app.volume.20260731_1200.tar.gz",
            "app.volume.20260730_1100.tar.gz",
            "app.volume.20260729_1000.tar.gz",
        ]
    )
    with (
        patch("compman.backup_store.shutil.which", return_value="/usr/bin/ssh"),
        patch(
            "compman.backup_store.subprocess.run",
            side_effect=[
                _proc(stdout=listing),
                _proc(),
                _proc(),
                _proc(),
                _proc(),
            ],
        ) as run,
    ):
        prune_archives(config, store, "app", "volume")
    commands = [call.args[0][-1] for call in run.call_args_list][1:]
    assert commands == [
        "rm -f bk/app.volume.20260730_1100.tar.gz",
        "rm -f bk/app.volume.20260730_1100.tar.zst",
        "rm -f bk/app.volume.20260729_1000.tar.gz",
        "rm -f bk/app.volume.20260729_1000.tar.zst",
    ]
