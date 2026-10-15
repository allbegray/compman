from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import threading
from unittest.mock import MagicMock, patch

from compman import follow


def _env() -> dict[str, str]:
    return dict(os.environ)


def test_can_quit_requires_a_terminal():
    reader = MagicMock()
    reader.isatty.return_value = True
    assert follow.can_quit(reader) is True

    reader.isatty.return_value = False
    assert follow.can_quit(reader) is False


def test_stream_runs_the_child_without_an_inherited_stdin():
    proc = MagicMock()
    proc.wait.return_value = 0
    with patch("compman.follow.subprocess.Popen", return_value=proc) as popen:
        assert follow.stream(["docker", "logs", "-f"], env=_env(), reader=io.StringIO("")) == 0

    assert popen.call_args.args[0] == ["docker", "logs", "-f"]
    assert popen.call_args.kwargs["stdin"] == subprocess.DEVNULL


def test_stream_returns_the_child_exit_code_when_no_quit_line_arrives():
    code = follow.stream(
        [sys.executable, "-c", "raise SystemExit(3)"],
        env=_env(),
        reader=io.StringIO("noise\nquery\nquit\n"),
    )

    assert code == 3


def test_stream_ignores_quit_text_that_is_not_the_whole_line():
    code = follow.stream(
        [sys.executable, "-c", "raise SystemExit(3)"],
        env=_env(),
        reader=io.StringIO("qq\nquit\nquiet please\n"),
    )

    assert code == 3


def test_stream_quit_key_stops_the_stream_and_exits_zero():
    code = follow.stream(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        env=_env(),
        reader=io.StringIO("  Q  \n"),
    )

    assert code == 0


def test_stream_announces_the_quit_key_and_the_stop(capsys):
    follow.stream(
        [sys.executable, "-c", "pass"],
        env=_env(),
        reader=io.StringIO("q\n"),
    )

    assert capsys.readouterr().err.splitlines() == [
        follow.t("msg.follow_quit_hint"),
        follow.t("msg.follow_stopped"),
    ]


def test_stream_kills_the_child_when_the_wait_is_interrupted():
    proc = MagicMock()
    proc.wait.side_effect = KeyboardInterrupt
    with patch("compman.follow.subprocess.Popen", return_value=proc):
        try:
            follow.stream(["docker", "logs", "-f"], env=_env(), reader=io.StringIO(""))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("KeyboardInterrupt must propagate")

    proc.kill.assert_called_once()


def test_watch_quit_interrupts_the_child_on_the_quit_line():
    proc = MagicMock()
    quit_requested = threading.Event()

    follow._watch_quit(proc, io.StringIO("noise\nq\nafter\n"), quit_requested)

    proc.send_signal.assert_called_once_with(signal.SIGINT)
    assert quit_requested.is_set()


def test_watch_quit_stops_reading_at_end_of_input():
    proc = MagicMock()
    quit_requested = threading.Event()

    follow._watch_quit(proc, io.StringIO(""), quit_requested)

    proc.send_signal.assert_not_called()
    assert not quit_requested.is_set()


def test_interrupt_sends_sigint_on_posix():
    proc = MagicMock()
    with patch("sys.platform", "linux"):
        follow._interrupt(proc)

    proc.send_signal.assert_called_once_with(signal.SIGINT)
    proc.terminate.assert_not_called()


def test_interrupt_terminates_on_windows():
    proc = MagicMock()
    with patch("sys.platform", "win32"):
        follow._interrupt(proc)

    proc.terminate.assert_called_once()
    proc.send_signal.assert_not_called()


def test_interrupt_tolerates_a_stream_that_already_ended():
    proc = MagicMock()
    proc.send_signal.side_effect = ProcessLookupError

    follow._interrupt(proc)


def test_interrupt_lets_a_stream_that_stops_itself_stop():
    proc = MagicMock()
    proc.poll.side_effect = [0]

    follow._interrupt(proc)

    proc.kill.assert_not_called()


def test_interrupt_kills_a_stream_that_ignores_the_request():
    proc = MagicMock()
    proc.poll.return_value = None

    with patch.object(follow, "STOP_GRACE", 0.0):
        follow._interrupt(proc)

    proc.send_signal.assert_called_once_with(signal.SIGINT)
    proc.kill.assert_called_once()


def test_quit_key_stops_a_stream_that_ignores_the_interrupt():
    ignores_sigint = (
        "import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); time.sleep(30)"
    )

    code = follow.stream(
        [sys.executable, "-c", ignores_sigint], env=_env(), reader=io.StringIO("q\n")
    )

    assert code == 0