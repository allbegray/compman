from __future__ import annotations

import shutil
from pathlib import Path

from compman.archive_source import extract_archive, has_archive_suffix
from compman.errors import ConfigError


def fetch(source: str, tmp: Path) -> Path:
    # NOTE: absolute paths are allowed only for local source resolution.
    # This is separate from config._managed_path confinement which
    # restricts dirs.* / folder to stay inside the config directory.
    raw = source[7:] if source.startswith("file://") else source
    resolved = Path(raw).resolve()
    if not resolved.exists():
        raise ConfigError(f"local source not found: {source}")
    if resolved.is_dir():
        dest = tmp / "src"
        shutil.copytree(
            resolved,
            dest,
            ignore=shutil.ignore_patterns(".git", ".gitkeep"),
        )
        return dest
    if has_archive_suffix(str(resolved)):
        return extract_archive(resolved, tmp / "extract")
    dest = tmp / "src"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(resolved, dest / resolved.name)
    return dest
