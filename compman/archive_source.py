from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

from compman.archive import extract_tar, extract_zip

ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".zip")


def has_archive_suffix(path: str) -> bool:
    return path.lower().endswith(ARCHIVE_SUFFIXES)


def extract_archive(archive_path: Path, extract_dir: Path, max_bytes: int | None = None) -> Path:
    extract_dir.mkdir()
    if archive_path.name.lower().endswith(".zip"):
        with zipfile.ZipFile(archive_path) as zip_source:
            extract_zip(zip_source, extract_dir, max_bytes=max_bytes)
    else:
        with tarfile.open(archive_path) as tar_source:
            extract_tar(tar_source, extract_dir, max_bytes=max_bytes)

    contents = [path for path in extract_dir.iterdir() if path.name != ".gitkeep"]
    return contents[0] if len(contents) == 1 and contents[0].is_dir() else extract_dir
