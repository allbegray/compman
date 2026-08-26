from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest
from test_backup_store import FakeS3

from compman.backup_store import S3BackupStore, local_root
from compman.config import Config, Profile
from compman.docker import ComposeContext
from compman.errors import CommandError
from compman.ops import common


def test_select_backup_timestamp_single(temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    backup_root = local_root(cfg.backup_store)
    backup_root.mkdir(parents=True, exist_ok=True)

    backup_file = backup_root / "my_stack.volume.20260731_1200.tar.gz"
    backup_file.touch()

    with patch("compman.ops.common.prompt_select", return_value=0):
        ts = common.select_backup_timestamp(cfg, "volume")
    assert ts == "20260731_1200"


def test_stack_paused_restores_after_failure(temp_dir: pathlib.Path):
    runtime = MagicMock()
    runtime.run_compose.return_value = MagicMock(stdout="web\ndb\n")
    context = ComposeContext("app", (temp_dir / "docker-compose.yml",), {})
    with pytest.raises(RuntimeError, match="operation failed"):
        with common.stack_paused(runtime, context):
            raise RuntimeError("operation failed")
    calls = runtime.run_compose.call_args_list
    assert [call.args[0] for call in calls] == [
        ["ps", "--services", "--filter", "status=running"],
        ["stop", "web", "db"],
        ["start", "web", "db"],
    ]
    assert calls[0].kwargs["capture"] is True
    assert calls[1].kwargs["capture"] is False
    assert calls[2].kwargs["capture"] is False


def test_stack_paused_empty_running_set_skips_stop_and_start(temp_dir: pathlib.Path):
    runtime = MagicMock(return_value=MagicMock(stdout="  \n"))
    context = ComposeContext("app", (temp_dir / "docker-compose.yml",), {})
    ran = False
    with common.stack_paused(runtime, context):
        ran = True
    assert ran
    assert [call.args[0] for call in runtime.run_compose.call_args_list] == [
        ["ps", "--services", "--filter", "status=running"]
    ]


def test_stack_paused_disabled_makes_no_compose_calls(temp_dir: pathlib.Path):
    runtime = MagicMock()
    context = ComposeContext("app", (temp_dir / "docker-compose.yml",), {})
    ran = False
    with common.stack_paused(runtime, context, enabled=False):
        ran = True
    assert ran
    runtime.run_compose.assert_not_called()


def test_stack_paused_stop_failure_still_restarts_captured_services(temp_dir: pathlib.Path):
    runtime = MagicMock()
    ok = MagicMock(stdout="web\ndb\n")
    runtime.run_compose.side_effect = [ok, RuntimeError("stop boom"), ok]
    context = ComposeContext("app", (temp_dir / "docker-compose.yml",), {})
    with pytest.raises(RuntimeError, match="stop boom"):
        with common.stack_paused(runtime, context):
            pass
    assert [call.args[0] for call in runtime.run_compose.call_args_list] == [
        ["ps", "--services", "--filter", "status=running"],
        ["stop", "web", "db"],
        ["start", "web", "db"],
    ]


def test_stack_paused_restart_failure_propagates_when_body_succeeds(temp_dir: pathlib.Path):
    runtime = MagicMock()
    ok = MagicMock(stdout="web\n")
    runtime.run_compose.side_effect = [ok, None, RuntimeError("restart boom")]
    context = ComposeContext("app", (temp_dir / "docker-compose.yml",), {})
    with pytest.raises(RuntimeError, match="restart boom"):
        with common.stack_paused(runtime, context):
            pass


def test_stack_paused_restart_failure_logged_when_body_failed(
    temp_dir: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    runtime = MagicMock()
    ok = MagicMock(stdout="web\n")
    runtime.run_compose.side_effect = [ok, None, RuntimeError("restart boom")]
    context = ComposeContext("app", (temp_dir / "docker-compose.yml",), {})
    with pytest.raises(RuntimeError, match="body failed"):
        with common.stack_paused(runtime, context):
            raise RuntimeError("body failed")
    assert "restart boom" in capsys.readouterr().err


def _make_local_backups(cfg: Config, kind: str, timestamps: list[str]) -> pathlib.Path:
    backup_root = local_root(cfg.backup_store)
    backup_root.mkdir(parents=True, exist_ok=True)
    for ts in timestamps:
        (backup_root / f"{cfg.name}.{kind}.{ts}.tar.gz").touch()
    return backup_root


def test_prune_archives_noop_when_unset(temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    _make_local_backups(cfg, "volume", ["20260801_0900", "20260731_1200"])
    with patch("compman.ops.common.delete_archive") as mock_delete:
        common.prune_archives(cfg, cfg.backup_store, "my_stack", "volume")
    mock_delete.assert_not_called()


def test_prune_archives_keeps_newest_n(temp_dir: pathlib.Path, capsys):
    cfg = Config(
        name="my_stack",
        profiles={"default": Profile(file="docker-compose.yml")},
        max_backups=2,
    )
    backup_root = _make_local_backups(
        cfg, "volume", ["20260601_0000", "20260701_0000", "20260731_1200", "20260801_0900"]
    )
    common.prune_archives(cfg, cfg.backup_store, "my_stack", "volume")

    remaining = sorted(p.name for p in backup_root.glob("*.tar.gz"))
    assert remaining == [
        "my_stack.volume.20260731_1200.tar.gz",
        "my_stack.volume.20260801_0900.tar.gz",
    ]
    out = capsys.readouterr().out
    assert out.count("Pruned old backup") == 2
    assert out.index("20260701_0000") < out.index("20260601_0000")


def test_prune_archives_within_limit_is_noop(temp_dir: pathlib.Path, capsys):
    cfg = Config(
        name="my_stack",
        profiles={"default": Profile(file="docker-compose.yml")},
        max_backups=5,
    )
    backup_root = _make_local_backups(cfg, "volume", ["20260801_0900", "20260731_1200"])
    common.prune_archives(cfg, cfg.backup_store, "my_stack", "volume")

    assert len(list(backup_root.glob("*.tar.gz"))) == 2
    assert capsys.readouterr().out == ""


def test_prune_archives_warns_and_continues_when_delete_fails(temp_dir: pathlib.Path, capsys):
    cfg = Config(
        name="my_stack",
        profiles={"default": Profile(file="docker-compose.yml")},
        max_backups=1,
    )
    _make_local_backups(cfg, "volume", ["20260801_0900", "20260701_0000", "20260601_0000"])
    with patch(
        "compman.ops.common.delete_archive", side_effect=[OSError("locked"), None]
    ) as mock_delete:
        common.prune_archives(cfg, cfg.backup_store, "my_stack", "volume")

    assert [call.args[1] for call in mock_delete.call_args_list] == [
        "my_stack.volume.20260701_0000",
        "my_stack.volume.20260601_0000",
    ]
    captured = capsys.readouterr()
    assert "Could not prune old backup my_stack.volume.20260701_0000" in captured.err
    assert "Pruned old backup my_stack.volume.20260601_0000" in captured.out


def test_prune_archives_remote_deletes_beyond_limit():
    cfg = Config(
        name="my_stack",
        profiles={"default": Profile(file="docker-compose.yml")},
        max_backups=1,
        backup_store=S3BackupStore(bucket="bucket", prefix="backups"),
    )
    fake = FakeS3(
        pages=[
            {
                "Contents": [
                    {"Key": "backups/my_stack.volume.20260801_0900.tar.gz"},
                    {"Key": "backups/my_stack.volume.20260701_0000.tar.gz"},
                    {"Key": "backups/my_stack.volume.20260601_0000.tar.gz"},
                ]
            }
        ]
    )
    with patch("compman.backup_store.create_client", return_value=fake):
        common.prune_archives(cfg, cfg.backup_store, "my_stack", "volume")

    assert fake.deleted == [
        {"Bucket": "bucket", "Key": "backups/my_stack.volume.20260701_0000.tar.gz"},
        {"Bucket": "bucket", "Key": "backups/my_stack.volume.20260701_0000.tar.zst"},
        {"Bucket": "bucket", "Key": "backups/my_stack.volume.20260601_0000.tar.gz"},
        {"Bucket": "bucket", "Key": "backups/my_stack.volume.20260601_0000.tar.zst"},
    ]


def test_select_backup_timestamp_none(temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    with pytest.raises(CommandError):
        common.select_backup_timestamp(cfg, "volume")


def test_select_backup_timestamp_empty_dir(temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    local_root(cfg.backup_store).mkdir(parents=True, exist_ok=True)
    with pytest.raises(CommandError):
        common.select_backup_timestamp(cfg, "volume")


def test_prompt_select_non_tty(temp_dir: pathlib.Path):
    with patch("sys.stdin.isatty", return_value=False), patch("typer.prompt", return_value="1"):
        res = common.prompt_select("Title", ["Option 1", "Option 2"])
        assert res == 0

    with patch("sys.stdin.isatty", return_value=False), patch("typer.prompt", return_value="invalid"):
        res_invalid = common.prompt_select("Title", ["Option 1", "Option 2"], default_index=0)
        assert res_invalid == 0


def test_prompt_select_interactive_arrows(temp_dir: pathlib.Path, capsys: pytest.CaptureFixture[str]):
    with patch("sys.stdin.isatty", return_value=True), patch("compman.ops.common.get_key", side_effect=["down", "up", "enter"]):
        res = common.prompt_select("Title", ["Option 1", "Option 2"])
        assert res == 0
    output = capsys.readouterr().out
    assert "Title (Use Up/Down or number keys, Enter to select, Esc to cancel):" in output
    assert "> Option 1" in output
    assert output.isascii()


def test_prompt_select_interactive_esc(temp_dir: pathlib.Path):
    with patch("sys.stdin.isatty", return_value=True), patch("compman.ops.common.get_key", return_value="esc"):
        with pytest.raises(SystemExit):
            common.prompt_select("Title", ["Option 1", "Option 2"])


def test_prompt_select_interactive_number(temp_dir: pathlib.Path):
    with patch("sys.stdin.isatty", return_value=True), patch(
        "compman.ops.common.get_key", side_effect=["5", "2"]
    ):
        res = common.prompt_select("Title", ["a", "b", "c"])
        assert res == 1


def test_prompt_select_interactive_sigint(temp_dir: pathlib.Path):
    with patch("sys.stdin.isatty", return_value=True), patch("compman.ops.common.get_key", side_effect=KeyboardInterrupt):
        with pytest.raises(SystemExit):
            common.prompt_select("Title", ["Option 1", "Option 2"])


def test_get_key_posix():
    mock_termios = MagicMock()
    mock_tty = MagicMock()
    mock_select = MagicMock()
    with patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty, "select": mock_select}):
        with patch("sys.platform", "linux"), patch("sys.stdin.fileno", return_value=0):
            with patch("os.read", return_value=b"\r"):
                assert common.get_key() == "enter"

            with patch("os.read", return_value=b"\x03"):
                with pytest.raises(KeyboardInterrupt):
                    common.get_key()

            mock_select.select.side_effect = [([0], [], []), ([0], [], []), ([], [], [])]
            with patch("os.read", side_effect=[b"\x1b", b"[", b"A"]):
                assert common.get_key() == "up"

            mock_select.select.side_effect = [([0], [], []), ([0], [], []), ([], [], [])]
            with patch("os.read", side_effect=[b"\x1b", b"[", b"B"]):
                assert common.get_key() == "down"

            mock_select.select.side_effect = [([0], [], []), ([0], [], []), ([], [], [])]
            with patch("os.read", side_effect=[b"\x1b", b"O", b"A"]):
                assert common.get_key() == "up"

            mock_select.select.side_effect = [([0], [], []), ([0], [], []), ([], [], [])]
            with patch("os.read", side_effect=[b"\x1b", b"O", b"B"]):
                assert common.get_key() == "down"

            mock_select.select.side_effect = [([], [], [])]
            with patch("os.read", side_effect=[b"\x1b"]):
                assert common.get_key() == "esc"

            mock_select.select.side_effect = [([0], [], [])] * 7
            with patch("os.read", side_effect=[b"\x1b"] + [b"x"] * 7):
                assert common.get_key() == "esc"

            with patch("os.read", return_value=b"7"):
                assert common.get_key() == "7"

            with patch("os.read", return_value=b"x"):
                assert common.get_key() == "other"


def test_get_key_win32():
    fake_msvcrt = MagicMock()
    with patch("sys.platform", "win32"), patch.dict("sys.modules", {"msvcrt": fake_msvcrt}):
        fake_msvcrt.getch.side_effect = [b"\r"]
        assert common.get_key() == "enter"
        fake_msvcrt.getch.side_effect = [b"\x00", b"H"]
        assert common.get_key() == "up"

        fake_msvcrt.getch.side_effect = [b"\xe0", b"H"]
        assert common.get_key() == "up"

        fake_msvcrt.getch.side_effect = [b"\xe0", b"P"]
        assert common.get_key() == "down"

        fake_msvcrt.getch.side_effect = [b"\xe0", b"X"]
        assert common.get_key() == "other"

        fake_msvcrt.getch.side_effect = [b"\x1b"]
        assert common.get_key() == "esc"

        fake_msvcrt.getch.side_effect = [b"\x03"]
        with pytest.raises(KeyboardInterrupt):
            common.get_key()

        fake_msvcrt.getch.side_effect = [b"4"]
        assert common.get_key() == "4"

        fake_msvcrt.getch.side_effect = [b"x"]
        assert common.get_key() == "other"


def test_parse_compose_ps_skips_non_dict_entries():
    from compman.ops.common import parse_compose_ps

    parsed = parse_compose_ps('{"Service":"a"}\n123\n')
    assert len(parsed) == 1 and parsed[0]["Service"] == "a"


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("", []),
        ("   \n\t\n", []),
        ("web\ndb\n", ["web", "db"]),
        ("  web  \nweb\n", ["web"]),
        ("web\r\n db \n", ["web", "db"]),
    ],
)
def test_parse_running_services_parses_plain_service_lines(stdout: str, expected: list[str]):
    assert common.parse_running_services(stdout) == expected


def test_prompt_select_interactive_ignores_unmapped_keys_until_enter():
    with patch("sys.stdin.isatty", return_value=True), patch(
        "compman.ops.common.get_key", side_effect=["other", "enter"]
    ):
        assert common.prompt_select("x", ["a"]) == 0
