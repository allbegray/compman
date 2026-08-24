from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from compman.errors import CommandError
from compman.i18n import t


def extract_tar(archive: tarfile.TarFile, destination: Path, max_bytes: int | None = None) -> None:
    members = archive.getmembers()
    total = 0
    for member in members:
        _validate_path(destination, member.name)
        if member.issym() or member.islnk():
            raise ValueError(f"Archive links are not allowed: {member.name}")
        if member.isdev() or member.isfifo():
            raise ValueError(f"Unsupported archive member type: {member.name}")
        total += member.size
        if max_bytes is not None and total > max_bytes:
            raise CommandError(t("msg.deploy_limit_exceeded", limit=_limit_mb(max_bytes), size=total))
    for member in members:
        archive.extract(member, destination)


def extract_zip(archive: zipfile.ZipFile, destination: Path, max_bytes: int | None = None) -> None:
    if max_bytes is not None:
        total = sum(member.file_size for member in archive.infolist())
        if total > max_bytes:
            raise CommandError(t("msg.deploy_limit_exceeded", limit=_limit_mb(max_bytes), size=total))
    for member in archive.infolist():
        _validate_path(destination, member.filename)
        archive.extract(member, destination)


def _limit_mb(max_bytes: int) -> int:
    return (max_bytes + 1024 * 1024 - 1) // (1024 * 1024)


def _validate_path(destination: Path, name: str) -> None:
    if not name or PurePosixPath(name).is_absolute() or PureWindowsPath(name).is_absolute():
        raise ValueError(f"Unsafe archive path: {name}")
    root = destination.resolve()
    target = (destination / name).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Unsafe archive path: {name}")
