from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest

from compman.config import Config, Profile
from compman.docker import ComposeContext
from compman.errors import CommandError
from compman.ops import common


def test_select_backup_timestamp_single(temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    backup_dir = cfg.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_file = backup_dir / "my_stack.volume.20260731_1200.tar.gz"
    backup_file.touch()

    with patch("compman.ops.common.prompt_select", return_value=0):
        ts = common.select_backup_timestamp(cfg, "volume")
    assert ts == "20260731_1200"


def test_stack_paused_restores_after_failure(temp_dir: pathlib.Path):
    runtime = MagicMock()
    context = ComposeContext("app", (temp_dir / "docker-compose.yml",), {})
    with pytest.raises(RuntimeError, match="operation failed"):
        with common.stack_paused(runtime, context):
            raise RuntimeError("operation failed")
    assert [call.args[0] for call in runtime.run_compose.call_args_list] == [["stop"], ["start"]]


def test_select_backup_timestamp_none(temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    with pytest.raises(CommandError):
        common.select_backup_timestamp(cfg, "volume")


def test_select_backup_timestamp_empty_dir(temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    cfg.backup_dir.mkdir(parents=True, exist_ok=True)
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


def test_get_key_win32():
    fake_msvcrt = MagicMock()
    with patch("sys.platform", "win32"), patch.dict("sys.modules", {"msvcrt": fake_msvcrt}):
        fake_msvcrt.getch.side_effect = [b"\r"]
        assert common.get_key() == "enter"

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
