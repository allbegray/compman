"""Stopping a live stream without leaving the terminal.

Every follow command (`log -f`, `stack logs -f`, `stats -f`) is a passthru
subprocess writing straight to the terminal, so nothing in compman sees the
keystrokes. This module owns the whole quit seam in one place: the child is
spawned with its stdin closed so the keystroke can only reach compman, a
watcher thread reads the terminal on the parent's behalf, and "the user asked
to stop" is reported as a successful exit instead of a failure.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Sequence, TextIO

import typer

from compman.i18n import t

QUIT_INPUT = "q"
"""The whole line a user types to stop streaming, compared case-insensitively.

Not a single keystroke: canonical mode keeps `q` a normal line of input, so
paste, terminal history, and Ctrl-C behave exactly as they do everywhere else.
"""

STOP_GRACE = 1.0
"""Seconds a stream may take to honor the interrupt before it is killed."""

STOP_POLL = 0.05
"""How often that grace is re-checked while waiting for the stream to stop."""


def can_quit(reader: TextIO) -> bool:
    """Report whether ``reader`` is a terminal someone can type the quit key on.

    A piped stdin — cron, CI, `... | grep` — has nobody to type `q`, so the
    follow seam stays off and the stream is left to Ctrl-C alone.
    """
    return reader.isatty()


def stream(
    cmd: Sequence[str],
    *,
    env: dict[str, str],
    reader: TextIO,
    cwd: Path | str | None = None,
) -> int:
    """Run ``cmd`` attached to the terminal until it ends or the user quits.

    Returns the child's exit code, or 0 when the quit key stopped the stream —
    an interrupt the user asked for is not a failure. Ctrl-C still works and
    keeps its exit code, because the signal reaches the whole process group.
    """
    typer.echo(t("msg.follow_quit_hint"), err=True)
    proc = subprocess.Popen(cmd, env=env, cwd=cwd, stdin=subprocess.DEVNULL)
    quit_requested = threading.Event()
    watcher = threading.Thread(
        target=_watch_quit,
        args=(proc, reader, quit_requested),
        name="compman-follow",
        daemon=True,
    )
    watcher.start()
    try:
        code = proc.wait()
    except BaseException:
        proc.kill()
        raise
    if not quit_requested.is_set():
        return code
    typer.echo(t("msg.follow_stopped"), err=True)
    return 0


def _watch_quit(proc: subprocess.Popen, reader: TextIO, quit_requested: threading.Event) -> None:
    """Interrupt ``proc`` when the quit line arrives; give up at end of input."""
    while True:
        line = reader.readline()
        if not line:
            return
        if line.strip().lower() == QUIT_INPUT:
            # Recorded before the signal: the signal is what unblocks wait(),
            # so the flag can never be observed before it is written.
            quit_requested.set()
            _interrupt(proc)
            return


def _interrupt(proc: subprocess.Popen) -> None:
    """Ask a live stream to stop the way Ctrl-C would, then insist if it won't.

    A stream attached to a terminal routinely ignores both SIGINT and SIGTERM —
    `docker logs -f` and `docker compose logs -f` both do, and so does anything
    else that defers signal handling to the tty. Ctrl-C still stops a stream
    today only because the parent kills the child when the signal raises
    KeyboardInterrupt, so the quit key needs the same insistence or `q` would
    do nothing exactly where it is most wanted. `docker stats` does honor
    SIGINT, so the common case still stops the way the tool intends.
    """
    try:
        if sys.platform == "win32":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGINT)
    except ProcessLookupError:
        return  # the stream ended on its own between the keypress and the signal
    deadline = time.monotonic() + STOP_GRACE
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(STOP_POLL)
    proc.kill()