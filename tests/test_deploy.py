from __future__ import annotations

import io
import pathlib
import tarfile
import time
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
)
from typer.testing import CliRunner

from compman import deploy, http_source
from compman.archive_source import extract_archive, has_archive_suffix
from compman.cli import app
from compman.config import load_config
from compman.errors import CommandError


def test_deploy_no_s3_path(temp_dir: pathlib.Path):
    with pytest.raises(SystemExit):
        deploy.deploy(s3_path=None)


@pytest.mark.parametrize("name", ["app.tar.gz", "app.tgz", "app.zip", "APP.ZIP"])
def test_archive_source_recognizes_supported_suffixes(name: str):
    assert has_archive_suffix(name)


def test_archive_source_rejects_unsupported_suffix():
    assert not has_archive_suffix("app.tar")


def test_archive_source_extracts_and_flattens_single_directory(temp_dir: pathlib.Path):
    archive = temp_dir / "app.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("app/main.py", "print('ok')")

    extracted = extract_archive(archive, temp_dir / "extract")

    assert extracted == temp_dir / "extract" / "app"
    assert (extracted / "main.py").is_file()


def test_archive_source_keeps_multiple_root_entries(temp_dir: pathlib.Path):
    archive = temp_dir / "app.tgz"
    first = temp_dir / "first.txt"
    second = temp_dir / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as tar_file:
        tar_file.add(first, arcname=first.name)
        tar_file.add(second, arcname=second.name)

    extracted = extract_archive(archive, temp_dir / "extract")

    assert extracted == temp_dir / "extract"


@pytest.mark.parametrize(
    ("url", "archive_name"),
    [
        ("http://example.test/app.zip", "app.zip"),
        ("https://example.test/app.zip?token=public", "app.zip"),
    ],
)
def test_http_source_downloads_archive(url: str, archive_name: str, temp_dir: pathlib.Path):
    archive = temp_dir / archive_name
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("app.txt", "hello")
    response = io.BytesIO(archive.read_bytes())
    download_dir = temp_dir / "download"
    download_dir.mkdir()

    with patch("compman.http_source.urlopen", return_value=response) as urlopen:
        extracted = http_source.fetch(url, download_dir)

    urlopen.assert_called_once_with(url, timeout=30)
    assert (extracted / "app.txt").read_text(encoding="utf-8") == "hello"


@pytest.mark.parametrize("url", ["https://example.test/app.tar", "ftp://example.test/app.zip"])
def test_http_source_rejects_invalid_source(url: str, temp_dir: pathlib.Path):
    with patch("compman.http_source.urlopen") as urlopen:
        with pytest.raises(ValueError):
            http_source.fetch(url, temp_dir)

    urlopen.assert_not_called()


def test_deploy_invalid_s3_path(temp_dir: pathlib.Path):
    with pytest.raises(SystemExit):
        deploy.deploy(s3_path="https://bucket/key")


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_deploy_dispatches_http_archive_without_s3(scheme: str, temp_dir: pathlib.Path):
    source = temp_dir / "http-source"
    source.mkdir()
    (source / "app.txt").write_text("http", encoding="utf-8")
    url = f"{scheme}://example.test/app.zip"

    with patch("compman.deploy._fetch_http", return_value=source) as fetch_http, patch("boto3.client") as boto_client:
        deploy.deploy(s3_path=url)

    fetch_http.assert_called_once()
    assert fetch_http.call_args.args[0] == url
    boto_client.assert_not_called()
    assert (temp_dir / "project" / "app.txt").read_text(encoding="utf-8") == "http"


def test_deploy_reports_http_download_stage(temp_dir: pathlib.Path, capsys):
    with patch("compman.deploy._fetch_http", side_effect=OSError("connection reset")):
        with pytest.raises(SystemExit):
            deploy.deploy(s3_path="https://example.test/app.zip")

    error = capsys.readouterr().err
    assert "downloading from HTTP" in error
    assert "connection reset" in error


def test_deploy_rejects_unsupported_source_scheme(temp_dir: pathlib.Path):
    with pytest.raises(SystemExit):
        deploy.deploy(s3_path="ftp://example.test/app.zip")


def test_deploy_rejects_s3_source_without_bucket(temp_dir: pathlib.Path):
    with pytest.raises(SystemExit):
        deploy.deploy(s3_path="s3:///app.zip")


def test_deploy_empty_dir_help_exit(temp_dir: pathlib.Path):
    with pytest.raises(SystemExit):
        deploy.deploy(s3_path=None)


def test_deploy_config_without_path_exits(temp_dir: pathlib.Path, capsys):
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        deploy.deploy(s3_path=None)
    assert "not configured" in capsys.readouterr().err


def test_deploy_existing_config_s3(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  deploy: s3://b/k.tar.gz\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    mock_s3 = MagicMock()
    tar_path = temp_dir / "k.tar.gz"
    with tarfile.open(tar_path, "w:gz"):
        pass
    mock_s3.download_file.side_effect = lambda b, k, dst: pathlib.Path(dst).write_bytes(tar_path.read_bytes())

    calls: list[str] = []
    dummy_runtime.ensure_ready_for_start = MagicMock(side_effect=lambda callback: calls.append("ready"))

    def build_call(*_args, **_kwargs):
        calls.append("build")
        assert not (temp_dir / "project").exists()

    dummy_runtime.passthru_cli = MagicMock(side_effect=build_call)
    with patch("boto3.client", return_value=mock_s3), patch(
        "compman.deploy.detect_runtime", return_value=dummy_runtime
    ) as detect:
        deploy.deploy(build=True, tag="my_tag", s3_path=None)
        assert (temp_dir / "compman.yml").exists()
    assert calls == ["ready", "build"]
    detect.assert_called_once()
    dummy_runtime.ensure_ready_for_start.assert_called_once()
    build_cwd = dummy_runtime.passthru_cli.call_args.kwargs["cwd"]
    assert ".deploy_tmp_" in str(build_cwd)
    assert (temp_dir / "project").exists()


def test_deploy_zip_archive(temp_dir: pathlib.Path):
    mock_s3 = MagicMock()
    zip_path = temp_dir / "app.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.txt", "hello")
    mock_s3.download_file.side_effect = lambda b, k, dst: pathlib.Path(dst).write_bytes(zip_path.read_bytes())

    with patch("boto3.client", return_value=mock_s3), patch(
        "compman.deploy.detect_runtime"
    ) as detect:
        deploy.deploy(build=False, tag=None, s3_path="s3://my-bucket/app.zip")
        assert (temp_dir / "project" / "test.txt").exists()
    detect.assert_not_called()


def test_deploy_rejects_zip_path_traversal(temp_dir: pathlib.Path):
    zip_path = temp_dir / "unsafe.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../outside.txt", "unsafe")

    mock_s3 = MagicMock()
    mock_s3.download_file.side_effect = lambda b, k, dst: pathlib.Path(dst).write_bytes(zip_path.read_bytes())
    (temp_dir / "tmp").mkdir()
    with patch("boto3.client", return_value=mock_s3):
        with pytest.raises(ValueError, match="Unsafe archive path"):
            deploy._fetch(mock_s3, "bucket", "unsafe.zip", temp_dir / "tmp")

    assert not (temp_dir / "outside.txt").exists()


def test_deploy_rejects_tar_path_traversal(temp_dir: pathlib.Path):
    tar_path = temp_dir / "unsafe.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        info = tarfile.TarInfo("../outside.txt")
        info.size = len(b"unsafe")
        import io
        tar.addfile(info, io.BytesIO(b"unsafe"))

    mock_s3 = MagicMock()
    mock_s3.download_file.side_effect = lambda b, k, dst: pathlib.Path(dst).write_bytes(tar_path.read_bytes())
    (temp_dir / "tmp").mkdir()
    with pytest.raises(ValueError, match="Unsafe archive path"):
        deploy._fetch(mock_s3, "bucket", "unsafe.tar.gz", temp_dir / "tmp")

    assert not (temp_dir / "outside.txt").exists()


def test_deploy_targz_single_dir(dummy_runtime, temp_dir: pathlib.Path):
    mock_s3 = MagicMock()
    src_dir = temp_dir / "src_inner"
    src_dir.mkdir()
    (src_dir / "inner.txt").write_text("inner", encoding="utf-8")

    tar_path = temp_dir / "app.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(src_dir, arcname="src_inner")

    mock_s3.download_file.side_effect = lambda b, k, dst: pathlib.Path(dst).write_bytes(tar_path.read_bytes())

    with patch("boto3.client", return_value=mock_s3), patch("compman.deploy.detect_runtime", return_value=dummy_runtime):
        deploy.deploy(build=False, tag=None, s3_path="s3://my-bucket/app.tar.gz")
        assert (temp_dir / "project" / "inner.txt").exists()


def test_update_compman_deploy(temp_dir: pathlib.Path):
    compman_yml = temp_dir / "compman.yml"
    compman_yml.write_text("compman:\n  name: app\n  deploy: s3://old/path\n", encoding="utf-8")

    deploy._update_compman_deploy(compman_yml, "s3://new/path")
    assert "s3://new/path" in compman_yml.read_text(encoding="utf-8")

    # Already matching
    deploy._update_compman_deploy(compman_yml, "s3://new/path")

    # Invalid yaml fallback
    compman_yml.write_text("compman:\n  name: app\n", encoding="utf-8")
    deploy._update_compman_deploy(compman_yml, "s3://new2/path")
    assert "s3://new2/path" in compman_yml.read_text(encoding="utf-8")


def test_deploy_prefix_download(dummy_runtime, temp_dir: pathlib.Path):
    mock_s3 = MagicMock()
    mock_s3.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "my-prefix/file1.txt"}, {"Key": "my-prefix/sub/file2.txt"}]}
    ]
    def download(_bucket, key, destination):
        pathlib.Path(destination).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(destination).write_text(key, encoding="utf-8")

    mock_s3.download_file = MagicMock(side_effect=download)

    with patch("boto3.client", return_value=mock_s3), patch("compman.deploy.detect_runtime", return_value=dummy_runtime):
        deploy.deploy(s3_path="s3://my-bucket/my-prefix")
        assert (temp_dir / "project" / "file1.txt").exists()


def test_deploy_rejects_source_over_archive_limit(temp_dir: pathlib.Path, capsys):
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  limits:\n    max_archive_mb: 1\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    mock_s3 = MagicMock()
    mock_s3.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "my-prefix/big.bin"}]}
    ]

    def download(_bucket, _key, destination):
        pathlib.Path(destination).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(destination).write_bytes(b"x" * (1024 * 1024 + 1))

    mock_s3.download_file = MagicMock(side_effect=download)

    with patch("boto3.client", return_value=mock_s3), pytest.raises(SystemExit):
        deploy.deploy(s3_path="s3://my-bucket/my-prefix")

    error = capsys.readouterr().err
    assert "1 MB size limit" in error
    assert not (temp_dir / "project").exists()


def test_deploy_echoes_provenance_under_limit(dummy_runtime, temp_dir: pathlib.Path, capsys):
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  limits:\n    max_archive_mb: 10\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    mock_s3 = MagicMock()
    mock_s3.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "my-prefix/file1.txt"}]}
    ]

    def download(_bucket, _key, destination):
        pathlib.Path(destination).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(destination).write_text("hello", encoding="utf-8")

    mock_s3.download_file = MagicMock(side_effect=download)

    with patch("boto3.client", return_value=mock_s3):
        deploy.deploy(s3_path="s3://my-bucket/my-prefix")

    out = capsys.readouterr().out
    assert "Source: s3://my-bucket/my-prefix" in out
    assert "bytes" in out
    assert (temp_dir / "project" / "file1.txt").exists()


def test_deploy_without_limits_no_provenance(dummy_runtime, temp_dir: pathlib.Path, capsys):
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    mock_s3 = MagicMock()
    mock_s3.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "my-prefix/file1.txt"}]}
    ]

    def download(_bucket, _key, destination):
        pathlib.Path(destination).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(destination).write_text("hello", encoding="utf-8")

    mock_s3.download_file = MagicMock(side_effect=download)

    with patch("boto3.client", return_value=mock_s3):
        deploy.deploy(s3_path="s3://my-bucket/my-prefix")

    out = capsys.readouterr().out
    assert "Source:" in out
    assert (temp_dir / "project" / "file1.txt").exists()


def test_deploy_bucket_root_prefix(dummy_runtime, temp_dir: pathlib.Path):
    mock_s3 = MagicMock()
    mock_s3.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "Dockerfile"}]}
    ]
    mock_s3.download_file.side_effect = lambda _bucket, _key, destination: pathlib.Path(destination).write_text(
        "FROM busybox", encoding="utf-8"
    )

    with patch("boto3.client", return_value=mock_s3), patch("compman.deploy.detect_runtime", return_value=dummy_runtime):
        deploy.deploy(s3_path="s3://my-bucket")

    assert (temp_dir / "project" / "Dockerfile").exists()


def test_deploy_prefix_rejects_path_traversal(temp_dir: pathlib.Path):
    mock_s3 = MagicMock()
    mock_s3.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "my-prefix/../outside.txt"}]}
    ]
    with pytest.raises(ValueError, match="Unsafe S3 object path"):
        deploy._download_recursive(mock_s3, "bucket", "my-prefix", temp_dir / "project")


def test_deploy_swap_existing(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "project").mkdir(exist_ok=True)
    (temp_dir / "project" / "old_file.txt").write_text("old", encoding="utf-8")

    mock_s3 = MagicMock()
    src_dir = temp_dir / "_src_inner"
    src_dir.mkdir()
    (src_dir / "new_file.txt").write_text("new", encoding="utf-8")

    tar_path = temp_dir / "app.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(src_dir, arcname="_src_inner")

    mock_s3.download_file.side_effect = lambda b, k, dst: pathlib.Path(dst).write_bytes(tar_path.read_bytes())

    with patch("boto3.client", return_value=mock_s3), patch("compman.deploy.detect_runtime", return_value=dummy_runtime):
        deploy.deploy(s3_path="s3://my-bucket/app.tar.gz")
        assert (temp_dir / "project" / "new_file.txt").exists()


def test_generate_scaffold_sub_compose(dummy_runtime, temp_dir: pathlib.Path):
    project_dir = temp_dir / "project"
    project_dir.mkdir()
    sub_compose = project_dir / "docker-compose.yml"
    sub_compose.write_text("services:\n  app:\n    image: old\n", encoding="utf-8")

    deploy._generate_scaffold(temp_dir, "project", "s3://b/k", "my_image")
    assert not sub_compose.exists()
    root_compose = temp_dir / "docker-compose.yml"
    assert root_compose.exists()


def test_update_compman_deploy_fallback_insert(temp_dir: pathlib.Path):
    compman_yml = temp_dir / "compman.yml"
    compman_yml.write_text("compman:\n  name: app\n", encoding="utf-8")

    deploy._update_compman_deploy(compman_yml, "s3://new3/path")
    assert "s3://new3/path" in compman_yml.read_text(encoding="utf-8")


def test_handle_s3_errors():
    with pytest.raises(SystemExit):
        deploy._handle_s3_error(NoCredentialsError(), "s3://b/k")

    with pytest.raises(SystemExit):
        deploy._handle_s3_error(PartialCredentialsError(provider="env", cred_var="AWS_SECRET_ACCESS_KEY"), "s3://b/k")

    with pytest.raises(SystemExit):
        deploy._handle_s3_error(ClientError({"Error": {"Code": "403"}}, "GetObject"), "s3://b/k")

    with pytest.raises(SystemExit):
        deploy._handle_s3_error(ClientError({"Error": {"Code": "404"}}, "GetObject"), "s3://b/k")

    with pytest.raises(SystemExit):
        deploy._handle_s3_error(ClientError({"Error": {"Code": "500"}}, "GetObject"), "s3://b/k")

    with pytest.raises(SystemExit):
        deploy._handle_s3_error(EndpointConnectionError(endpoint_url="http://localhost"), "s3://b/k")

    with pytest.raises(SystemExit):
        deploy._handle_s3_error(RuntimeError("generic error"), "s3://b/k")


def test_deploy_reports_local_build_stage(dummy_runtime, temp_dir: pathlib.Path, capsys):
    mock_s3 = MagicMock()
    mock_s3.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "Dockerfile"}]}
    ]
    mock_s3.download_file.side_effect = lambda _bucket, _key, destination: pathlib.Path(destination).write_text(
        "FROM busybox", encoding="utf-8"
    )
    dummy_runtime.passthru_cli = MagicMock(side_effect=RuntimeError("build failed"))

    with patch("boto3.client", return_value=mock_s3), patch(
        "compman.deploy.detect_runtime", return_value=dummy_runtime
    ), pytest.raises(SystemExit):
        deploy.deploy(s3_path="s3://bucket", build=True)

    error = capsys.readouterr().err
    assert "building the container image" in error
    assert "Failed to download" not in error
    assert not (temp_dir / "project").exists()


def test_deploy_unknown_profile_via_config(temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  deploy:\n    dev: s3://b/dev.tar.gz\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    from compman.config import load_config as _load

    cfg = _load(str(temp_dir / "compman.yml"))
    with pytest.raises(SystemExit):
        deploy.deploy(s3_path=None, config=cfg, profile="prod")


def test_deploy_unknown_profile_via_load(temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  deploy:\n    dev: s3://b/dev.tar.gz\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        deploy.deploy(s3_path=None, profile="prod")


def test_deploy_local_bare_path(dummy_runtime, temp_dir: pathlib.Path):
    src = temp_dir / "local_src"
    src.mkdir()
    (src / "app.txt").write_text("local", encoding="utf-8")
    deploy.deploy(s3_path=str(src))
    assert (temp_dir / "project" / "app.txt").read_text(encoding="utf-8") == "local"


def test_deploy_local_file_scheme(dummy_runtime, temp_dir: pathlib.Path):
    src = temp_dir / "local_src2"
    src.mkdir()
    (src / "app2.txt").write_text("file", encoding="utf-8")
    deploy.deploy(s3_path=f"file://{src}")
    assert (temp_dir / "project" / "app2.txt").read_text(encoding="utf-8") == "file"


def test_deploy_checksum_ok(dummy_runtime, temp_dir: pathlib.Path, capsys):
    import hashlib

    src_file = temp_dir / "single.txt"
    src_file.write_text("hello checksum", encoding="utf-8")
    digest = hashlib.sha256(src_file.read_bytes()).hexdigest()
    checksum = f"sha256:{digest}"
    (temp_dir / "compman.yml").write_text(
        f"compman:\n  name: app\n  deploy:\n    default:\n      source: {src_file}\n      checksum: {checksum}\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    deploy.deploy(s3_path=None)
    out = capsys.readouterr().out
    assert "Checksum verified" in out
    assert (temp_dir / "project" / "single.txt").exists()


def test_deploy_checksum_mismatch(dummy_runtime, temp_dir: pathlib.Path):
    src_file = temp_dir / "single2.txt"
    src_file.write_text("hello", encoding="utf-8")
    bad = "sha256:" + "0" * 64
    (temp_dir / "compman.yml").write_text(
        f"compman:\n  name: app\n  deploy:\n    default:\n      source: {src_file}\n      checksum: {bad}\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        deploy.deploy(s3_path=None)
    assert not (temp_dir / "project" / "single2.txt").exists()


def test_deploy_checksum_archive_ok(dummy_runtime, temp_dir: pathlib.Path, capsys):
    import hashlib

    src_dir = temp_dir / "arch_src"
    src_dir.mkdir()
    (src_dir / "inner.txt").write_text("arch content", encoding="utf-8")
    archive = temp_dir / "app.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(src_dir, arcname="arch_src")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = f"sha256:{digest}"
    (temp_dir / "compman.yml").write_text(
        f"compman:\n  name: app\n  deploy:\n    default:\n      source: {archive}\n      checksum: {checksum}\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    deploy.deploy(s3_path=None)
    out = capsys.readouterr().out
    assert "Checksum verified" in out
    assert (temp_dir / "project" / "inner.txt").exists()


def test_deploy_checksum_skip_non_archive_dir(dummy_runtime, temp_dir: pathlib.Path):
    src = temp_dir / "plain_dir"
    src.mkdir()
    (src / "a.txt").write_text("data", encoding="utf-8")
    (temp_dir / "compman.yml").write_text(
        f"compman:\n  name: app\n  deploy:\n    default:\n      source: {src}\n      checksum: sha256:{'a'*64}\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    deploy.deploy(s3_path=None)
    assert (temp_dir / "project" / "a.txt").exists()


def test_deploy_dry_run_no_swap(dummy_runtime, temp_dir: pathlib.Path, capsys):
    project = temp_dir / "project"
    project.mkdir()
    (project / "old.txt").write_text("old", encoding="utf-8")
    mtime_before = (project / "old.txt").stat().st_mtime
    src = temp_dir / "new_src"
    src.mkdir()
    (src / "new.txt").write_text("new", encoding="utf-8")
    deploy.deploy(s3_path=str(src), dry_run=True)
    out = capsys.readouterr().out
    assert "Dry run" in out
    assert "Changes to be deployed" in out
    assert "+ new.txt" in out
    assert "- old.txt" in out
    assert (project / "old.txt").exists()
    assert not (project / "new.txt").exists()
    assert (project / "old.txt").stat().st_mtime == mtime_before


def test_deploy_dry_run_modified_and_no_changes(dummy_runtime, temp_dir: pathlib.Path, capsys):
    project = temp_dir / "project"
    project.mkdir()
    (project / "same.txt").write_text("same", encoding="utf-8")
    src = temp_dir / "src_same"
    src.mkdir()
    (src / "same.txt").write_text("same", encoding="utf-8")
    deploy.deploy(s3_path=str(src), dry_run=True)
    out = capsys.readouterr().out
    assert "(no changes)" in out
    capsys.readouterr()
    (src / "same.txt").write_text("changed", encoding="utf-8")
    deploy.deploy(s3_path=str(src), dry_run=True)
    out2 = capsys.readouterr().out
    assert "~ same.txt" in out2


def test_deploy_dry_run_no_target(dummy_runtime, temp_dir: pathlib.Path, capsys):
    src = temp_dir / "src_new"
    src.mkdir()
    (src / "a.txt").write_text("hi", encoding="utf-8")
    deploy.deploy(s3_path=str(src), dry_run=True)
    out = capsys.readouterr().out
    assert "Dry run" in out
    assert not (temp_dir / "project").exists()


def test_deploy_limits_provenance_always(dummy_runtime, temp_dir: pathlib.Path, capsys):
    mock_s3 = MagicMock()
    mock_s3.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "pref/file.txt"}]}
    ]

    def dl(_b, _k, dst):
        pathlib.Path(dst).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(dst).write_text("x", encoding="utf-8")

    mock_s3.download_file = MagicMock(side_effect=dl)
    with patch("boto3.client", return_value=mock_s3):
        deploy.deploy(s3_path="s3://b/pref")
    assert "Source:" in capsys.readouterr().out


def test_deploy_build_skip_pull_only(dummy_runtime, temp_dir: pathlib.Path):
    src = temp_dir / "src_build"
    src.mkdir()
    (src / "a.txt").write_text("data", encoding="utf-8")
    (temp_dir / "compman.yml").write_text(
        f"compman:\n  name: app\n  deploy:\n    default:\n      source: {src}\n      strategy: pull-only\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    dummy_runtime.passthru_cli = MagicMock()
    with patch("compman.deploy.detect_runtime", return_value=dummy_runtime):
        deploy.deploy(build=True, s3_path=None)
    dummy_runtime.passthru_cli.assert_not_called()
    assert (temp_dir / "project" / "a.txt").exists()


def test_deploy_build_skip_no_build(dummy_runtime, temp_dir: pathlib.Path):
    src = temp_dir / "src_nb"
    src.mkdir()
    (src / "a.txt").write_text("data", encoding="utf-8")
    dummy_runtime.passthru_cli = MagicMock()
    with patch("compman.deploy.detect_runtime", return_value=dummy_runtime):
        deploy.deploy(build=True, s3_path=str(src), no_build=True)
    dummy_runtime.passthru_cli.assert_not_called()


def test_deploy_build_skip_strategy_param(dummy_runtime, temp_dir: pathlib.Path):
    src = temp_dir / "src_strat"
    src.mkdir()
    (src / "a.txt").write_text("data", encoding="utf-8")
    dummy_runtime.passthru_cli = MagicMock()
    with patch("compman.deploy.detect_runtime", return_value=dummy_runtime):
        deploy.deploy(build=True, s3_path=str(src), strategy="pull-only")
    dummy_runtime.passthru_cli.assert_not_called()


def test_deploy_checksum_via_tmp_archive(dummy_runtime, temp_dir: pathlib.Path, capsys):
    import hashlib

    archive_content = temp_dir / "tmp_arch.tar.gz"
    inner = temp_dir / "inner_dir"
    inner.mkdir()
    (inner / "f.txt").write_text("content", encoding="utf-8")
    with tarfile.open(archive_content, "w:gz") as tar:
        tar.add(inner, arcname="inner_dir")
    digest = hashlib.sha256(archive_content.read_bytes()).hexdigest()
    checksum = f"sha256:{digest}"
    (temp_dir / "compman.yml").write_text(
        f"compman:\n  name: app\n  deploy:\n    default:\n      source: s3://b/tmp_arch.tar.gz\n      checksum: {checksum}\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    mock_s3 = MagicMock()
    mock_s3.download_file.side_effect = lambda b, k, dst: pathlib.Path(dst).write_bytes(archive_content.read_bytes())
    with patch("boto3.client", return_value=mock_s3):
        deploy.deploy(s3_path=None)
    assert "Checksum verified" in capsys.readouterr().out


def test_collect_files_file_branch(tmp_path: pathlib.Path):
    f = tmp_path / "solo.txt"
    f.write_text("hi", encoding="utf-8")
    assert deploy._collect_files(f) == {"solo.txt"}
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.txt").write_text("a", encoding="utf-8")
    assert deploy._collect_files(d) == {"a.txt"}


def test_verify_checksum_project_root_is_file(tmp_path: pathlib.Path, capsys):
    import hashlib

    f = tmp_path / "file.txt"
    f.write_text("data123", encoding="utf-8")
    digest = hashlib.sha256(f.read_bytes()).hexdigest()
    deploy._verify_checksum(str(f), f, tmp_path, f"sha256:{digest}")
    assert "Checksum verified" in capsys.readouterr().out
    deploy._verify_checksum(str(f), f, tmp_path, None)
    bad = "sha256:" + "0" * 64
    with pytest.raises(Exception, match="Checksum mismatch"):
        deploy._verify_checksum(str(f), f, tmp_path, bad)


def test_verify_checksum_project_root_archive_suffix(tmp_path: pathlib.Path, capsys):
    import hashlib

    f = tmp_path / "archive.tar.gz"
    f.write_bytes(b"archivebytes")
    digest = hashlib.sha256(f.read_bytes()).hexdigest()
    deploy._verify_checksum(str(f), f, tmp_path, f"sha256:{digest}")
    assert "Checksum verified" in capsys.readouterr().out


def test_verify_checksum_archive_no_candidate(tmp_path: pathlib.Path):
    src = "s3://b/missing.tar.gz"
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.txt").write_text("hi", encoding="utf-8")
    deploy._verify_checksum(src, proj, tmp_path, "sha256:" + "a" * 64)


def test_verify_checksum_single_file_multiple_files_skip(tmp_path: pathlib.Path):
    src_file = tmp_path / "orig.txt"
    src_file.write_text("orig", encoding="utf-8")
    proj = tmp_path / "proj2"
    proj.mkdir()
    (proj / "a.txt").write_text("a", encoding="utf-8")
    (proj / "b.txt").write_text("b", encoding="utf-8")
    deploy._verify_checksum(str(src_file), proj, tmp_path, "sha256:" + "a" * 64)


def test_verify_checksum_none_target(tmp_path: pathlib.Path):
    deploy._verify_checksum("s3://b/prefix", tmp_path / "nonexistent", tmp_path, "sha256:" + "a" * 64)


def test_verify_checksum_archive_suffix_dir(tmp_path: pathlib.Path):
    d = tmp_path / "archive.tar.gz"
    d.mkdir()
    deploy._verify_checksum("s3://b/archive.tar.gz", d, tmp_path, "sha256:" + "a" * 64)


def test_deploy_with_file_project_root(dummy_runtime, temp_dir: pathlib.Path, capsys):
    target_file = temp_dir / "single_file.txt"
    target_file.write_bytes(b"filecontent")
    with patch("compman.deploy._fetch_local", return_value=target_file):
        deploy.deploy(s3_path=str(target_file), dry_run=True)
    assert "Source:" in capsys.readouterr().out


def test_deploy_resolve_deploy_except_branch(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  deploy:\n    dev: s3://b/dev.tar.gz\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    from compman.config import load_config

    cfg = load_config(str(temp_dir / "compman.yml"))
    src = temp_dir / "src"
    src.mkdir()
    (src / "x.txt").write_text("x", encoding="utf-8")
    deploy.deploy(s3_path=str(src), config=cfg, profile="prod")
    assert (temp_dir / "project" / "x.txt").exists()


def test_deploy_dry_run_with_dir_in_common(dummy_runtime, temp_dir: pathlib.Path, capsys):
    project = temp_dir / "project"
    project.mkdir()
    (project / "common.txt").write_text("old", encoding="utf-8")
    src = temp_dir / "src_common"
    src.mkdir()
    (src / "common.txt").write_text("newcontent", encoding="utf-8")
    (src / "subdir").mkdir()
    (project / "subdir").mkdir()
    deploy.deploy(s3_path=str(src), dry_run=True)
    out = capsys.readouterr().out
    assert "Dry run" in out


def test_deploy_dry_run_same_size_diff_content(dummy_runtime, temp_dir: pathlib.Path, capsys):
    project = temp_dir / "project"
    project.mkdir()
    (project / "file.txt").write_text("abcd", encoding="utf-8")
    src = temp_dir / "src_diff"
    src.mkdir()
    (src / "file.txt").write_text("abce", encoding="utf-8")
    deploy.deploy(s3_path=str(src), dry_run=True)
    out = capsys.readouterr().out
    assert "~ file.txt" in out


def test_deploy_dry_run_read_exception(dummy_runtime, temp_dir: pathlib.Path, capsys):
    project = temp_dir / "project"
    project.mkdir()
    (project / "file.txt").write_text("old", encoding="utf-8")
    src = temp_dir / "src_exc"
    src.mkdir()
    (src / "file.txt").write_text("new", encoding="utf-8")
    with patch.object(pathlib.Path, "read_bytes", side_effect=OSError("fail")):
        deploy.deploy(s3_path=str(src), dry_run=True)
    out = capsys.readouterr().out
    assert "~ file.txt" in out


def test_prune_versions_no_prune(tmp_path: pathlib.Path):
    vs = tmp_path / "versions"
    vs.mkdir()
    (vs / "20200101_000000").mkdir()
    (vs / "20200102_000000").mkdir()
    deploy.prune_versions(vs, keep=3)
    assert len(list(vs.iterdir())) == 2


def test_prune_versions_prunes_oldest(tmp_path: pathlib.Path):
    vs = tmp_path / "versions"
    vs.mkdir()
    for name in ["20200101_000000", "20200102_000000", "20200103_000000"]:
        (vs / name).mkdir()
        time.sleep(0.01)
    deploy.prune_versions(vs, keep=2)
    remaining = sorted(p.name for p in vs.iterdir())
    assert remaining == ["20200102_000000", "20200103_000000"]


def test_rollback_invalid_timestamp(tmp_path: pathlib.Path):
    cfg_path = tmp_path / "compman.yml"
    cfg_path.write_text("compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n", encoding="utf-8")
    old = pathlib.Path.cwd()
    import os
    os.chdir(tmp_path)
    try:
        cfg = load_config(str(cfg_path))
        with pytest.raises(CommandError, match="Invalid timestamp"):
            deploy.rollback(cfg, "not-a-timestamp")
    finally:
        os.chdir(old)


def test_rollback_nonexistent(tmp_path: pathlib.Path):
    cfg_path = tmp_path / "compman.yml"
    cfg_path.write_text("compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n", encoding="utf-8")
    old = pathlib.Path.cwd()
    import os
    os.chdir(tmp_path)
    try:
        cfg = load_config(str(cfg_path))
        (cfg.backup_dir / ".versions").mkdir(parents=True, exist_ok=True)
        with pytest.raises(CommandError, match="not found"):
            deploy.rollback(cfg, "20200101_000000")
    finally:
        os.chdir(old)


def test_rollback_restores_previous(temp_dir: pathlib.Path):
    src1 = temp_dir / "src1"
    src1.mkdir()
    (src1 / "inner.txt").write_text("v1", encoding="utf-8")
    deploy.deploy(s3_path=str(src1))
    vdir = temp_dir / "backup" / ".versions"
    first = sorted(p.name for p in vdir.iterdir() if p.is_dir())[0]
    # ensure second deploy has different timestamp
    import time as _time
    _time.sleep(1)
    src2 = temp_dir / "src2"
    src2.mkdir()
    (src2 / "inner.txt").write_text("v2", encoding="utf-8")
    deploy.deploy(s3_path=str(src2))
    assert (temp_dir / "project" / "inner.txt").read_text(encoding="utf-8") == "v2"
    assert len(list(vdir.iterdir())) == 2
    cfg = load_config(str(temp_dir / "compman.yml"))
    deploy.rollback(cfg, first)
    assert (temp_dir / "project" / "inner.txt").read_text(encoding="utf-8") == "v1"


def test_versions_keep_prunes_old(temp_dir: pathlib.Path):
    for i in range(3):
        src = temp_dir / f"src_keep{i}"
        src.mkdir()
        (src / "f.txt").write_text(str(i), encoding="utf-8")
        deploy.deploy(s3_path=str(src), keep=2)
        import time as _time
        _time.sleep(1)
    vdir = temp_dir / "backup" / ".versions"
    assert len(list(vdir.iterdir())) == 2


def test_deploy_version_collision(temp_dir: pathlib.Path):
    src = temp_dir / "src_coll"
    src.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")
    # pre-create a version dir with current second to force collision
    import datetime as _dt
    now = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    vdir = temp_dir / "backup" / ".versions"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / now).mkdir()
    deploy.deploy(s3_path=str(src))
    # after deploy there should be 2 versions (pre-created + new with microsec)
    assert len(list(vdir.iterdir())) == 2
    # new version should contain a.txt
    found = False
    for p in vdir.iterdir():
        if (p / "a.txt").exists():
            found = True
    assert found


def test_cli_rollback_help(runner: CliRunner):
    res = runner.invoke(app, ["rollback", "--help"])
    assert res.exit_code == 0
    assert "rollback" in res.output.lower()


def test_cli_rollback_with_timestamp(temp_dir: pathlib.Path, runner: CliRunner):
    src = temp_dir / "src_cli"
    src.mkdir()
    (src / "x.txt").write_text("orig", encoding="utf-8")
    deploy.deploy(s3_path=str(src))
    vdir = temp_dir / "backup" / ".versions"
    ts = sorted(p.name for p in vdir.iterdir())[0]
    src2 = temp_dir / "src_cli2"
    src2.mkdir()
    (src2 / "x.txt").write_text("changed", encoding="utf-8")
    deploy.deploy(s3_path=str(src2))
    assert (temp_dir / "project" / "x.txt").read_text(encoding="utf-8") == "changed"
    res = runner.invoke(app, ["rollback", ts, "--yes"])
    assert res.exit_code == 0
    assert (temp_dir / "project" / "x.txt").read_text(encoding="utf-8") == "orig"


def test_cli_rollback_interactive_selection(temp_dir: pathlib.Path, runner: CliRunner):
    src = temp_dir / "src_inter"
    src.mkdir()
    (src / "a.txt").write_text("one", encoding="utf-8")
    deploy.deploy(s3_path=str(src))
    import time as _time
    _time.sleep(1)
    src2 = temp_dir / "src_inter2"
    src2.mkdir()
    (src2 / "a.txt").write_text("two", encoding="utf-8")
    deploy.deploy(s3_path=str(src2))
    vdir = temp_dir / "backup" / ".versions"
    assert len(list(vdir.iterdir())) == 2
    # interactive: choose first (oldest) via prompt_select mock
    with patch("compman.ops.common.prompt_select", return_value=0):
        res = runner.invoke(app, ["rollback"])
    assert res.exit_code == 0
    assert (temp_dir / "project" / "a.txt").read_text(encoding="utf-8") == "one"


def test_cli_rollback_fallback_select_backup(temp_dir: pathlib.Path, runner: CliRunner):
    # no versions dir -> fallback to select_backup_timestamp
    cfg = load_config(str(temp_dir / "compman.yml")) if (temp_dir / "compman.yml").exists() else None
    # ensure no versions
    vdir = temp_dir / "backup" / ".versions"
    if vdir.exists():
        import shutil
        shutil.rmtree(vdir)
    # create a dummy backup tar for select_backup_timestamp fallback
    (temp_dir / "compman.yml").write_text("compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n", encoding="utf-8")
    cfg = load_config(str(temp_dir / "compman.yml"))
    cfg.backup_dir.mkdir(parents=True, exist_ok=True)
    # no versions, so rollback without timestamp should use select_backup_timestamp which will fail with no backups
    res = runner.invoke(app, ["rollback"])
    assert res.exit_code != 0


def test_deploy_checksum_mismatch_before_dry_run(dummy_runtime, temp_dir: pathlib.Path, capsys):
    src_file = temp_dir / "single_mismatch.txt"
    src_file.write_text("hello mismatch", encoding="utf-8")
    bad = "sha256:" + "0" * 64
    (temp_dir / "compman.yml").write_text(
        f"compman:\n  name: app\n  deploy:\n    default:\n      source: {src_file}\n      checksum: {bad}\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        deploy.deploy(s3_path=None, dry_run=True)
    out = capsys.readouterr().out
    assert "Dry run" not in out
    assert not (temp_dir / "project" / "single_mismatch.txt").exists()


def test_deploy_directory_single_top_level_flatten(dummy_runtime, temp_dir: pathlib.Path):
    src_dir = temp_dir / "single_dir_src"
    src_dir.mkdir()
    (src_dir / "inner.txt").write_text("flattened", encoding="utf-8")
    archive = temp_dir / "single_dir.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(src_dir, arcname="single_dir_src")
    deploy.deploy(s3_path=str(archive))
    assert (temp_dir / "project" / "inner.txt").read_text(encoding="utf-8") == "flattened"
    assert not (temp_dir / "project" / "single_dir_src").exists()


@pytest.mark.parametrize(
    ("strategy", "should_build"),
    [
        ("recreate", True),
        ("pull-only", False),
    ],
)
def test_deploy_strategy_parametrized(dummy_runtime, temp_dir: pathlib.Path, strategy: str, should_build: bool):
    src = temp_dir / f"src_strategy_{strategy}"
    src.mkdir()
    (src / "a.txt").write_text("data", encoding="utf-8")
    dummy_runtime.passthru_cli = MagicMock()
    with patch("compman.deploy.detect_runtime", return_value=dummy_runtime):
        deploy.deploy(build=True, s3_path=str(src), strategy=strategy)
    if should_build:
        dummy_runtime.passthru_cli.assert_called_once()
    else:
        dummy_runtime.passthru_cli.assert_not_called()
