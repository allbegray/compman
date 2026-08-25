from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

EXECUTABLE_NOT_FOUND_ERROR = (
    "Could not resolve the installed compman executable. "
    "Install with 'uv tool install .' and retry."
)


def resolve_executable(
    which: Callable[[str], str | None] = shutil.which,
    argv: Sequence[str] | None = None,
) -> str:
    found = which("compman")
    if found:
        return found
    args = argv if argv is not None else sys.argv
    if args:
        candidate = Path(args[0]).resolve()
        if candidate.name.startswith("compman"):
            if sys.platform == "win32":
                return str(candidate)
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)
    raise ValueError(EXECUTABLE_NOT_FOUND_ERROR)
