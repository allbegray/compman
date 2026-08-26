from __future__ import annotations

import io
import sys
import tarfile
from unittest.mock import MagicMock

import pytest

from compman import archive
from compman.archive import create_tar, open_tarball
from compman.errors import CommandError

requires_py314 = pytest.mark.skipif(
    sys.version_info < (3, 14), reason="compression.zstd requires Python 3.14+"
)


@requires_py314
def test_create_tar_zstd_roundtrip(tmp_path):
    src = tmp_path / "tree"
    src.mkdir()
    (src / "m.txt").write_text("zstd-roundtrip", encoding="utf-8")
    out = tmp_path / "arc.tar.zst"
    create_tar(src, out, zstd_format=True)
    assert out.name.endswith(".tar.zst") and out.stat().st_size > 0
    with open_tarball(out) as tar:
        names = {m.name for m in tar.getmembers()}
        content = tar.extractfile("./m.txt").read().decode()
    assert "./m.txt" in names
    assert content == "zstd-roundtrip"


def test_open_tarball_gzip_still_works(tmp_path):
    src = tmp_path / "tree"
    src.mkdir()
    (src / "a.txt").write_text("gz", encoding="utf-8")
    out = tmp_path / "arc.tar.gz"
    create_tar(src, out, zstd_format=False)
    assert out.name.endswith(".tar.gz")
    with open_tarball(out) as tar:
        assert {m.name for m in tar.getmembers()} >= {"./a.txt"}


def test_load_zstd_missing_module_raises_command_error(monkeypatch):
    import importlib

    def fake_import(name):
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(importlib, "import_module", fake_import)


    with pytest.raises(CommandError, match="3.14"):
        from compman.archive import _load_zstd

        _load_zstd()


# ---- folded from the retired coverage-sweep files ----


def test_extract_tar_rejects_symlink_members(temp_dir):
    link = tarfile.TarInfo("link")
    link.type = tarfile.SYMTYPE
    link.linkname = "target"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        tar.addfile(link)
        with pytest.raises(ValueError, match="links are not allowed"):
            archive.extract_tar(tar, temp_dir)


def test_validate_path_rejects_empty_names(temp_dir):
    with pytest.raises(ValueError, match="Unsafe archive path"):
        archive._validate_path(temp_dir, "")


def test_extract_tar_extracts_safe_members_via_tar_extract(temp_dir):
    member = tarfile.TarInfo("safe.txt")
    fake_tar = MagicMock()
    fake_tar.getmembers.return_value = [member]

    archive.extract_tar(fake_tar, temp_dir)

    fake_tar.extract.assert_called_once_with(member, temp_dir)


@pytest.mark.parametrize("member_type", [tarfile.FIFOTYPE, tarfile.BLKTYPE, tarfile.CHRTYPE])
def test_extract_tar_rejects_device_and_fifo_members_before_extraction(temp_dir, member_type):
    destination = temp_dir / "out"
    destination.mkdir()
    member = tarfile.TarInfo("special")
    member.type = member_type
    fake_tar = MagicMock()
    fake_tar.getmembers.return_value = [member]

    with pytest.raises(ValueError, match="Unsupported archive member"):
        archive.extract_tar(fake_tar, destination)

    fake_tar.extract.assert_not_called()
    assert list(destination.iterdir()) == []


def test_extract_tar_aborts_over_member_total_before_extraction(temp_dir):
    destination = temp_dir / "out"
    destination.mkdir()
    payload = io.BytesIO(b"\0" * (1024 * 1024))
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo("big.bin")
        info.size = payload.getbuffer().nbytes
        tar.addfile(info, payload)
    buffer.seek(0)
    with tarfile.open(fileobj=buffer, mode="r") as tar:
        with pytest.raises(CommandError, match="1 MB size limit"):
            archive.extract_tar(tar, destination, max_bytes=1024 * 1024 - 1)

    assert list(destination.iterdir()) == []


def test_extract_tar_extracts_archives_under_the_size_limit(temp_dir):
    destination = temp_dir / "out"
    destination.mkdir()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo("small.txt")
        data = b"hello"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    buffer.seek(0)
    with tarfile.open(fileobj=buffer, mode="r") as tar:
        archive.extract_tar(tar, destination, max_bytes=1024 * 1024)

    assert (destination / "small.txt").read_text(encoding="utf-8") == "hello"


def test_extract_zip_aborts_over_member_total_before_extraction(temp_dir):
    import zipfile

    destination = temp_dir / "out"
    destination.mkdir()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("big.bin", b"\0" * (2 * 1024 * 1024))
    buffer.seek(0)
    with zipfile.ZipFile(buffer) as zip_file:
        with pytest.raises(CommandError, match="1 MB size limit"):
            archive.extract_zip(zip_file, destination, max_bytes=1024 * 1024)

    assert list(destination.iterdir()) == []
