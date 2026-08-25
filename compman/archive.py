from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from compman.errors import CommandError
from compman.i18n import t

ZSTD_SUFFIX = ".tar.zst"


def _load_zstd(import_module=None):
    import importlib

    loader = import_module or importlib.import_module
    try:
        return loader("compression.zstd")  # Python 3.14+
    except ImportError as exc:
        raise CommandError(t("msg.zstd_requires_py314")) from exc


def create_tar(source_dir: Path, dest: Path, *, zstd_format: bool = False, gzip_level: int = 6) -> None:
    """Write ``source_dir`` as a tarball at ``dest`` (gzip default, zstd opt-in)."""
    if not zstd_format:
        with tarfile.open(dest, "w:gz", compresslevel=gzip_level) as tar:
            tar.add(source_dir, arcname=".")
        return
    zstd = _load_zstd()
    with zstd.open(dest, "wb") as zout:
        with tarfile.open(fileobj=zout, mode="w") as tar:
            tar.add(source_dir, arcname=".")


def open_tarball(path: Path):
    """Open a local backup archive for extraction, gating zstd on 3.14+."""
    if path.name.lower().endswith(ZSTD_SUFFIX):
        _load_zstd()
        return tarfile.open(path, "r:*")
    return tarfile.open(path, "r:gz")


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
