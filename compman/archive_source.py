from __future__ import annotations

import hashlib
import tarfile
import zipfile
from pathlib import Path

from compman.archive import extract_tar, extract_zip
from compman.errors import CommandError
from compman.i18n import t

ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".zip")
_HASH_CHUNK_SIZE = 1024 * 1024


def has_archive_suffix(path: str) -> bool:
    return path.lower().endswith(ARCHIVE_SUFFIXES)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_digest(actual: str, expected: str) -> None:
    if actual.lower() != expected.lower():
        raise CommandError(t("msg.deploy_checksum_mismatch", expected=expected, actual=actual))


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
