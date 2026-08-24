from __future__ import annotations

import io
import pathlib
import tarfile
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
)

from compman import deploy, http_source
from compman.archive_source import extract_archive, has_archive_suffix
from compman.errors import CommandError


class _FakeResponse:
    """Minimal urlopen stand-in exposing read() and geturl()."""

    def __init__(self, data: bytes, url: str) -> None:
        self._data = io.BytesIO(data)
        self._url = url

    def read(self, size: int = -1) -> bytes:
        return self._data.read(size)

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


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
    response = _FakeResponse(archive.read_bytes(), url)
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


def test_http_source_aborts_download_over_limit(temp_dir: pathlib.Path):
    payload = b"x" * (2 * 1024 * 1024)
    response = _FakeResponse(payload, "https://example.test/big.zip")

    with patch("compman.http_source.urlopen", return_value=response):
        with pytest.raises(CommandError, match="1 MB size limit"):
            http_source.fetch("https://example.test/big.zip", temp_dir, max_bytes=1024 * 1024)


def test_http_source_downloads_under_limit(temp_dir: pathlib.Path):
    archive = temp_dir / "small.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("app.txt", "hello")
    response = _FakeResponse(archive.read_bytes(), "https://example.test/small.zip")

    with patch("compman.http_source.urlopen", return_value=response):
        extracted = http_source.fetch("https://example.test/small.zip", temp_dir, max_bytes=1024 * 1024)

    assert (extracted / "app.txt").read_text(encoding="utf-8") == "hello"


@pytest.mark.parametrize(
    ("final_url", "match"),
    [
        ("ftp://example.test/app.zip", "Invalid HTTP source"),
        ("http://example.test/app.tar", "must be a .tar.gz"),
    ],
)
def test_http_source_revalidates_redirect_target(final_url: str, match: str, temp_dir: pathlib.Path):
    response = _FakeResponse(b"data", final_url)

    with patch("compman.http_source.urlopen", return_value=response):
        with pytest.raises(ValueError, match=match):
            http_source.fetch("https://example.test/app.zip", temp_dir)

    assert not (temp_dir / "extract").exists()


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
    assert ".deploy_tmp_" in str(build_cwd) and temp_dir in build_cwd.parents
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
    assert "Source:" not in out
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


def test_deploy_fetch_aborts_archive_over_head_size(temp_dir: pathlib.Path):
    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {"ContentLength": 2 * 1024 * 1024}

    with pytest.raises(CommandError, match="1 MB size limit"):
        deploy._fetch(mock_s3, "bucket", "app.zip", temp_dir / "dl", max_bytes=1024 * 1024)

    mock_s3.download_file.assert_not_called()


def test_deploy_recursive_aborts_over_listed_size(temp_dir: pathlib.Path):
    mock_s3 = MagicMock()
    mock_s3.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "p/small.bin", "Size": 512}]},
        {"Contents": [{"Key": "p/big.bin", "Size": 2 * 1024 * 1024}]},
    ]
    downloaded: list[str] = []
    mock_s3.download_file.side_effect = lambda _b, key, _d: downloaded.append(key)

    with pytest.raises(CommandError, match="1 MB size limit"):
        deploy._download_recursive(mock_s3, "bucket", "p", temp_dir / "out", max_bytes=1024 * 1024)

    assert downloaded == ["p/small.bin"]


def test_deploy_aborts_extraction_over_member_total(temp_dir: pathlib.Path, capsys):
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  limits:\n    max_archive_mb: 1\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("huge.bin")
        info.size = 2 * 1024 * 1024
        tar.addfile(info, io.BytesIO(b"\0" * (2 * 1024 * 1024)))
    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {"ContentLength": len(tar_buffer.getvalue())}
    mock_s3.download_file.side_effect = lambda _b, _k, dst: pathlib.Path(dst).write_bytes(tar_buffer.getvalue())

    with patch("boto3.client", return_value=mock_s3), pytest.raises(SystemExit):
        deploy.deploy(s3_path="s3://my-bucket/huge.tar.gz")

    error = capsys.readouterr().err
    assert "size limit" in error
    assert not (temp_dir / "project").exists()


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
