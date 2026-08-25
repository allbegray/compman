

# ---- zstd opt-in format (Python 3.14+) ----

def test_create_tar_zstd_roundtrip(tmp_path):
    from compman.archive import create_tar, open_tarball

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

    from compman.archive import create_tar, open_tarball

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

    import pytest

    from compman.archive import _load_zstd
    from compman.errors import CommandError

    def fake_import(name):
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(importlib, "import_module", fake_import)
    with pytest.raises(CommandError, match="3.14"):
        _load_zstd()
