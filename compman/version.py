"""Package version lookup shared by `compman version` and notifications."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    """Return the installed compman version, or 'dev' from a source checkout."""
    try:
        return version("compman")
    except PackageNotFoundError:
        return "dev"