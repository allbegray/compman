from __future__ import annotations

import pathlib
import tarfile
import zipfile

import pytest

from compman import local_source
from compman.errors import ConfigError


def test_fetch_local_archive_file_url(temp_dir: pathlib.Path):
    src_dir = temp_dir / "src_inner"
    src_dir.mkdir()
    (src_dir / "inner.txt").write_text("hello", encoding="utf-8")
    archive = temp_dir / "app.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(src_dir, arcname="src_inner")
    tmp = temp_dir / "tmp"
    tmp.mkdir()
    result = local_source.fetch(f"file://{archive}", tmp)
    # single top-level dir is flattened -> result is tmp/extract/src_inner
    assert (result / "inner.txt").read_text(encoding="utf-8") == "hello"


def test_fetch_local_archive_bare_relative(temp_dir: pathlib.Path):
    archive = temp_dir / "app.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("inner.txt", "bare-relative")
    tmp = temp_dir / "tmp"
    tmp.mkdir()
    result = local_source.fetch("app.zip", tmp)
    assert (result / "inner.txt").read_text(encoding="utf-8") == "bare-relative"


def test_fetch_local_archive_absolute_path(temp_dir: pathlib.Path):
    archive = temp_dir / "app.tgz"
    inner = temp_dir / "inner.txt"
    inner.write_text("absolute", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(inner, arcname="inner.txt")
    tmp = temp_dir / "tmp"
    tmp.mkdir()
    result = local_source.fetch(str(archive), tmp)
    assert (result / "inner.txt").read_text(encoding="utf-8") == "absolute"


@pytest.mark.parametrize("prefix", ["file://", ""])
def test_fetch_local_directory_variants(prefix: str, temp_dir: pathlib.Path):
    src = temp_dir / "project_src"
    src.mkdir()
    (src / "app.py").write_text("print(1)", encoding="utf-8")
    (src / ".gitkeep").write_text("", encoding="utf-8")
    git_dir = src / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("git", encoding="utf-8")
    tmp = temp_dir / "tmp"
    tmp.mkdir()
    source = f"{prefix}{src}" if prefix else "project_src"
    result = local_source.fetch(source, tmp)
    assert result == tmp / "src"
    assert (result / "app.py").exists()
    assert not (result / ".gitkeep").exists()
    assert not (result / ".git").exists()


def test_fetch_local_single_file_copy_file_url(temp_dir: pathlib.Path):
    single = temp_dir / "note.txt"
    single.write_text("plain file", encoding="utf-8")
    tmp = temp_dir / "tmp"
    tmp.mkdir()
    result = local_source.fetch(f"file://{single}", tmp)
    assert result == tmp / "src"
    assert (result / "note.txt").read_text(encoding="utf-8") == "plain file"


def test_fetch_local_single_file_copy_bare(temp_dir: pathlib.Path):
    single = temp_dir / "data.bin"
    single.write_bytes(b"\x00\x01")
    tmp = temp_dir / "tmp"
    tmp.mkdir()
    result = local_source.fetch("data.bin", tmp)
    assert result == tmp / "src"
    assert (result / "data.bin").read_bytes() == b"\x00\x01"


@pytest.mark.parametrize("source", ["file:///nonexistent/app.tar.gz", "no_such_dir"])
def test_fetch_local_nonexistent(source: str, temp_dir: pathlib.Path):
    tmp = temp_dir / "tmp"
    tmp.mkdir()
    with pytest.raises(ConfigError, match="local source not found"):
        local_source.fetch(source, tmp)


def test_fetch_local_traversal_archive_zip(temp_dir: pathlib.Path):
    archive = temp_dir / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../outside.txt", "unsafe")
    tmp = temp_dir / "tmp"
    tmp.mkdir()
    with pytest.raises(ValueError, match="Unsafe archive path"):
        local_source.fetch(f"file://{archive}", tmp)
    assert not (temp_dir / "outside.txt").exists()


def test_fetch_local_traversal_archive_tar(temp_dir: pathlib.Path):
    archive = temp_dir / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("../outside.txt")
        info.size = len(b"unsafe")
        import io

        tar.addfile(info, io.BytesIO(b"unsafe"))
    tmp = temp_dir / "tmp"
    tmp.mkdir()
    with pytest.raises(ValueError, match="Unsafe archive path"):
        local_source.fetch(str(archive), tmp)
    assert not (temp_dir / "outside.txt").exists()


def test_fetch_local_symlink_resolved(temp_dir: pathlib.Path):
    real = temp_dir / "real_dir"
    real.mkdir()
    (real / "hello.txt").write_text("real", encoding="utf-8")
    link = temp_dir / "link_dir"
    link.symlink_to(real)
    tmp = temp_dir / "tmp"
    tmp.mkdir()
    result = local_source.fetch(f"file://{link}", tmp)
    assert (result / "hello.txt").read_text(encoding="utf-8") == "real"
