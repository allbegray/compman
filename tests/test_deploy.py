from __future__ import annotations

import hashlib
import io
import os
import pathlib
import tarfile
import zipfile
from http.client import HTTPMessage
from unittest.mock import MagicMock, patch
from urllib.request import Request

import pytest
import yaml
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
)
from conftest import write_config

from compman import deploy, http_source, s3_source
from compman.archive_source import ensure_digest, extract_archive, has_archive_suffix, sha256_file
from compman.config import DeployAuth, load_config
from compman.errors import CommandError
from compman.i18n import t

_PIN_A = "a" * 64
_PIN_B = "b" * 64


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
    write_config(temp_dir / "compman.yml")
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


def test_deploy_rejects_source_over_archive_limit(temp_dir: pathlib.Path):
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

    with patch("boto3.client", return_value=mock_s3), pytest.raises(CommandError, match="1 MB size limit"):
        deploy.deploy(s3_path="s3://my-bucket/my-prefix")

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
    write_config(temp_dir / "compman.yml")
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


def test_deploy_aborts_extraction_over_member_total(temp_dir: pathlib.Path):
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

    with patch("boto3.client", return_value=mock_s3), pytest.raises(CommandError, match="size limit"):
        deploy.deploy(s3_path="s3://my-bucket/huge.tar.gz")

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


def test_handle_s3_error_output_routes_through_s3_error_hint(capsys):
    path = "s3://b/k"
    error = ClientError({"Error": {"Code": "403"}}, "GetObject")

    with pytest.raises(SystemExit):
        deploy._handle_s3_error(error, path)

    assert capsys.readouterr().err == t("msg.s3_failed", path=path) + "\n" + t("msg.s3_403", path=path) + "\n"

    generic = RuntimeError("generic error")
    with pytest.raises(SystemExit):
        deploy._handle_s3_error(generic, path)

    assert capsys.readouterr().err == t("msg.s3_failed", path=path) + "\n" + t("msg.download_error", error=generic) + "\n"


# ---- s3_source.create_client endpoint precedence ----


def test_create_client_prefers_aws_endpoint_url_s3(monkeypatch):
    client = MagicMock()
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "http://s3:4566")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://generic:4566")
    with patch("boto3.client", return_value=client) as boto_client:
        assert s3_source.create_client() is client

    boto_client.assert_called_once_with("s3", endpoint_url="http://s3:4566")


def test_create_client_falls_back_to_aws_endpoint_url(monkeypatch):
    client = MagicMock()
    monkeypatch.delenv("AWS_ENDPOINT_URL_S3", raising=False)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://generic:4566")
    with patch("boto3.client", return_value=client) as boto_client:
        s3_source.create_client()

    boto_client.assert_called_once_with("s3", endpoint_url="http://generic:4566")


def test_create_client_without_endpoint_env_passes_none(monkeypatch):
    client = MagicMock()
    monkeypatch.delenv("AWS_ENDPOINT_URL_S3", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with patch("boto3.client", return_value=client) as boto_client:
        s3_source.create_client()

    boto_client.assert_called_once_with("s3", endpoint_url=None)


# ---- s3_source.s3_error_hint ----


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (NoCredentialsError(), t("msg.s3_no_creds")),
        (PartialCredentialsError(provider="env", cred_var="X"), t("msg.s3_no_creds")),
        (ClientError({"Error": {"Code": "AccessDenied"}}, "PutObject"), t("msg.s3_403", path="s3://b/k")),
        (ClientError({"Error": {"Code": "NoSuchBucket"}}, "PutObject"), t("msg.s3_404", path="s3://b/k")),
        (
            ClientError({"Error": {"Code": "SlowDown", "Message": "slow"}}, "PutObject"),
            t("msg.s3_client_error", code="SlowDown", error="slow"),
        ),
        (EndpointConnectionError(endpoint_url="http://x"), t("msg.s3_network")),
    ],
)
def test_s3_error_hint_maps_known_failures(error: Exception, expected: str):
    assert s3_source.s3_error_hint(error, "s3://b/k") == expected


def test_s3_error_hint_returns_none_for_unknown_errors():
    assert s3_source.s3_error_hint(RuntimeError("boom")) is None
    assert s3_source.s3_error_hint(ClientError({"Error": {"Code": "404"}}, "PutObject")) == t(
        "msg.s3_404", path=None
    )


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


def _write_zip_bytes(path: pathlib.Path) -> bytes:
    with zipfile.ZipFile(path, "w") as zip_file:
        zip_file.writestr("test.txt", "hello")
    return path.read_bytes()


def _make_source_dir(temp_dir: pathlib.Path, name: str = "fetched-src") -> pathlib.Path:
    source = temp_dir / name
    source.mkdir()
    (source / "app.txt").write_text("new", encoding="utf-8")
    return source


def _write_mapping_deploy_config(temp_dir: pathlib.Path, url: str, digest: str | None) -> None:
    sha_line = f"    sha256: {digest}\n" if digest else ""
    (temp_dir / "compman.yml").write_text(
        "compman:\n"
        "  name: app\n"
        "  deploy:\n"
        f"    url: {url}\n"
        f"{sha_line}"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )


# ---- checksum plumbing ----


def test_deploy_passes_sha256_flag_to_fetch(temp_dir: pathlib.Path):
    with patch("compman.deploy._fetch", return_value=_make_source_dir(temp_dir)) as fetch:
        deploy.deploy(s3_path="s3://b/k.tar.gz", sha256=_PIN_A)

    assert fetch.call_args.kwargs["sha256"] == _PIN_A


def test_deploy_sha256_flag_wins_over_config_pin(temp_dir: pathlib.Path):
    _write_mapping_deploy_config(temp_dir, "s3://b/k.tar.gz", _PIN_B)
    cfg = load_config(str(temp_dir / "compman.yml"))
    with patch("compman.deploy._fetch", return_value=_make_source_dir(temp_dir)) as fetch:
        deploy.deploy(s3_path=cfg.deploy, config=cfg, sha256=_PIN_A)

    assert fetch.call_args.kwargs["sha256"] == _PIN_A


def test_deploy_config_pin_applied_when_path_matches(temp_dir: pathlib.Path):
    _write_mapping_deploy_config(temp_dir, "s3://b/k.tar.gz", _PIN_B)
    cfg = load_config(str(temp_dir / "compman.yml"))
    with patch("compman.deploy._fetch", return_value=_make_source_dir(temp_dir)) as fetch:
        deploy.deploy(s3_path=cfg.deploy, config=cfg)

    assert fetch.call_args.kwargs["sha256"] == _PIN_B


def test_deploy_config_pin_not_applied_to_different_path(temp_dir: pathlib.Path):
    _write_mapping_deploy_config(temp_dir, "s3://b/k.tar.gz", _PIN_B)
    cfg = load_config(str(temp_dir / "compman.yml"))
    with patch("compman.deploy._fetch", return_value=_make_source_dir(temp_dir)) as fetch:
        deploy.deploy(s3_path="s3://other/z.tar.gz", config=cfg)

    assert fetch.call_args.kwargs["sha256"] is None


def test_deploy_invalid_sha256_flag_fails_in_validation_stage(temp_dir: pathlib.Path, capsys):
    with patch("boto3.client") as boto_client, pytest.raises(SystemExit):
        deploy.deploy(s3_path="s3://b/k.tar.gz", sha256="nothex")

    assert "validating the deploy source" in capsys.readouterr().err
    boto_client.assert_not_called()


def test_deploy_uppercase_sha256_flag_is_normalized(temp_dir: pathlib.Path):
    with patch("compman.deploy._fetch", return_value=_make_source_dir(temp_dir)) as fetch:
        deploy.deploy(s3_path="s3://b/k.tar.gz", sha256=_PIN_A.upper())

    assert fetch.call_args.kwargs["sha256"] == _PIN_A


def test_cli_update_passes_configured_deploy_for_pin_inheritance(
    runner, dummy_runtime, temp_dir: pathlib.Path
):
    from compman.cli import app

    _write_mapping_deploy_config(temp_dir, "s3://b/k.tar.gz", _PIN_B)
    (temp_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    with patch("compman.cli.detect_runtime", return_value=dummy_runtime), patch(
        "compman.cli._deploy"
    ) as deploy_mock:
        res = runner.invoke(app, ["update"])

    assert res.exit_code == 0
    deploy_mock.assert_called_once()
    kwargs = deploy_mock.call_args.kwargs
    assert kwargs["s3_path"] == "s3://b/k.tar.gz"
    assert kwargs["config"].deploy_sha256 == _PIN_B
    assert "sha256" not in kwargs


# ---- s3_source checksum ----


def test_s3_source_archive_checksum_match(temp_dir: pathlib.Path):
    zip_bytes = _write_zip_bytes(temp_dir / "real.zip")
    mock_s3 = MagicMock()
    mock_s3.download_file.side_effect = lambda _b, _k, dst: pathlib.Path(dst).write_bytes(zip_bytes)

    result = s3_source.fetch(mock_s3, "bucket", "app.zip", temp_dir, sha256=hashlib.sha256(zip_bytes).hexdigest())

    assert (result / "test.txt").read_text(encoding="utf-8") == "hello"


def test_s3_source_archive_checksum_mismatch_skips_extraction(temp_dir: pathlib.Path):
    zip_bytes = _write_zip_bytes(temp_dir / "real.zip")
    mock_s3 = MagicMock()
    mock_s3.download_file.side_effect = lambda _b, _k, dst: pathlib.Path(dst).write_bytes(zip_bytes)

    with pytest.raises(CommandError, match="SHA-256 verification"):
        s3_source.fetch(mock_s3, "bucket", "app.zip", temp_dir, sha256=_PIN_B)

    assert not (temp_dir / "extract").exists()


def test_s3_source_archive_without_sha256_unchanged(temp_dir: pathlib.Path):
    zip_bytes = _write_zip_bytes(temp_dir / "real.zip")
    mock_s3 = MagicMock()
    mock_s3.download_file.side_effect = lambda _b, _k, dst: pathlib.Path(dst).write_bytes(zip_bytes)

    result = s3_source.fetch(mock_s3, "bucket", "app.zip", temp_dir, sha256=None)

    assert (result / "test.txt").exists()


def test_s3_source_prefix_with_sha256_fails_before_pagination(temp_dir: pathlib.Path):
    mock_s3 = MagicMock()

    with pytest.raises(CommandError, match="S3 prefix"):
        s3_source.fetch(mock_s3, "bucket", "my-prefix", temp_dir, sha256=_PIN_A)

    mock_s3.get_paginator.assert_not_called()
    mock_s3.download_file.assert_not_called()


def test_s3_source_prefix_without_sha256_downloads_recursively(temp_dir: pathlib.Path):
    mock_s3 = MagicMock()
    mock_s3.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "my-prefix/file1.txt"}]}
    ]
    mock_s3.download_file.side_effect = lambda _b, key, dst: pathlib.Path(dst).write_text(key, encoding="utf-8")

    result = s3_source.fetch(mock_s3, "bucket", "my-prefix", temp_dir)

    assert (result / "file1.txt").read_text(encoding="utf-8") == "my-prefix/file1.txt"


# ---- http_source checksum ----


def test_http_source_checksum_match(temp_dir: pathlib.Path):
    archive = temp_dir / "payload.zip"
    payload = _write_zip_bytes(archive)
    response = _FakeResponse(payload, "https://example.test/app.zip")

    with patch("compman.http_source.urlopen", return_value=response):
        extracted = http_source.fetch(
            "https://example.test/app.zip", temp_dir, sha256=hashlib.sha256(payload).hexdigest()
        )

    assert (extracted / "test.txt").read_text(encoding="utf-8") == "hello"


def test_http_source_checksum_mismatch_skips_extraction(temp_dir: pathlib.Path):
    archive = temp_dir / "payload.zip"
    payload = _write_zip_bytes(archive)
    response = _FakeResponse(payload, "https://example.test/app.zip")

    with patch("compman.http_source.urlopen", return_value=response):
        with pytest.raises(CommandError, match="SHA-256 verification"):
            http_source.fetch("https://example.test/app.zip", temp_dir, sha256=_PIN_B)

    assert not (temp_dir / "extract").exists()


# ---- archive_source helpers ----


def test_sha256_file_matches_hashlib_digest(temp_dir: pathlib.Path):
    payload = b"chunked-hash-payload" * 3000
    target = temp_dir / "blob.bin"
    target.write_bytes(payload)

    assert sha256_file(target) == hashlib.sha256(payload).hexdigest()


def test_ensure_digest_compare_is_case_insensitive():
    ensure_digest("ABC123", "abc123")


def test_ensure_digest_mismatch_raises():
    with pytest.raises(CommandError, match="expected abc"):
        ensure_digest("fff", "abc")


# ---- deploy() visibility and abort ordering ----


def test_deploy_echoes_verified_checksum_without_limits(temp_dir: pathlib.Path, capsys):
    zip_path = temp_dir / "real.zip"
    zip_bytes = _write_zip_bytes(zip_path)
    mock_s3 = MagicMock()
    mock_s3.download_file.side_effect = lambda _b, _k, dst: pathlib.Path(dst).write_bytes(zip_bytes)

    with patch("boto3.client", return_value=mock_s3):
        deploy.deploy(s3_path="s3://my-bucket/app.zip", sha256=hashlib.sha256(zip_bytes).hexdigest())

    out = capsys.readouterr().out
    assert f"Verified SHA-256: {hashlib.sha256(zip_bytes).hexdigest()}" in out
    assert "Source:" not in out


def test_deploy_checksum_mismatch_aborts_before_build_and_swap(temp_dir: pathlib.Path):
    zip_path = temp_dir / "real.zip"
    zip_bytes = _write_zip_bytes(zip_path)
    mock_s3 = MagicMock()
    mock_s3.download_file.side_effect = lambda _b, _k, dst: pathlib.Path(dst).write_bytes(zip_bytes)

    with patch("boto3.client", return_value=mock_s3), patch(
        "compman.deploy.detect_runtime"
    ) as detect, pytest.raises(CommandError) as excinfo:
        deploy.deploy(s3_path="s3://my-bucket/app.zip", build=True, sha256=_PIN_B)

    assert excinfo.value.code == 1
    detect.assert_not_called()
    assert not (temp_dir / "project").exists()


def test_deploy_provenance_precedes_checksum_line(dummy_runtime, temp_dir: pathlib.Path, capsys):
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  limits:\n    max_archive_mb: 10\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    zip_path = temp_dir / "real.zip"
    zip_bytes = _write_zip_bytes(zip_path)
    mock_s3 = MagicMock()
    mock_s3.download_file.side_effect = lambda _b, _k, dst: pathlib.Path(dst).write_bytes(zip_bytes)

    with patch("boto3.client", return_value=mock_s3):
        deploy.deploy(s3_path="s3://my-bucket/app.zip", sha256=hashlib.sha256(zip_bytes).hexdigest())

    out = capsys.readouterr().out
    assert out.index("Source:") < out.index("Verified SHA-256:")


# ---- scaffold.update_deploy mapping-form handling ----


def test_update_deploy_mapping_same_url_left_untouched(temp_dir: pathlib.Path):
    compman_yml = temp_dir / "compman.yml"
    content = (
        "compman:\n  name: app\n  deploy:\n    url: s3://old/path\n    sha256: abc\n"
    )
    compman_yml.write_text(content, encoding="utf-8")

    deploy._update_compman_deploy(compman_yml, "s3://old/path")

    assert compman_yml.read_text(encoding="utf-8") == content


def test_update_deploy_mapping_different_url_replaces_whole_block(temp_dir: pathlib.Path):
    compman_yml = temp_dir / "compman.yml"
    compman_yml.write_text(
        "compman:\n"
        "  name: app\n"
        "  deploy:\n"
        "    url: s3://old/path\n"
        "    sha256: aaaa\n"
        "\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )

    deploy._update_compman_deploy(compman_yml, "s3://new/path")

    new_content = compman_yml.read_text(encoding="utf-8")
    parsed = yaml.safe_load(new_content)
    assert parsed["compman"]["deploy"] == "s3://new/path"
    assert "url:" not in new_content
    assert "sha256:" not in new_content


# ---- authenticated HTTP deploy (M7) ----


class _FakeOpener:
    """Captures the request handed to open() and returns a canned response."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.requests: list[Request] = []

    def open(self, request: Request, timeout: float = 30) -> _FakeResponse:
        self.requests.append(request)
        return self._response


_AUTH = DeployAuth(header="Authorization", value_env="DEPLOY_TOKEN")


def _auth_zip_response(temp_dir: pathlib.Path, url: str = "https://example.test/app.zip") -> _FakeResponse:
    archive = temp_dir / "auth.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("app.txt", "hello")
    return _FakeResponse(archive.read_bytes(), url)


def _header_value(request: Request, name: str) -> str | None:
    return next((v for k, v in request.headers.items() if k.lower() == name.lower()), None)


def test_http_source_auth_sends_configured_header(temp_dir: pathlib.Path):
    opener = _FakeOpener(_auth_zip_response(temp_dir))

    with (
        patch.dict(os.environ, {"DEPLOY_TOKEN": "Bearer sekret"}),
        patch("compman.http_source.build_opener", return_value=opener) as build_opener,
    ):
        extracted = http_source.fetch("https://example.test/app.zip", temp_dir, auth=_AUTH)

    build_opener.assert_called_once()
    assert isinstance(build_opener.call_args.args[0], http_source._AuthAwareRedirectHandler)
    assert build_opener.call_args.args[0]._header == "Authorization"
    request = opener.requests[0]
    assert request.full_url == "https://example.test/app.zip"
    assert _header_value(request, "Authorization") == "Bearer sekret"
    assert (extracted / "app.txt").read_text(encoding="utf-8") == "hello"


def test_http_source_without_auth_keeps_bare_urlopen(temp_dir: pathlib.Path):
    response = _auth_zip_response(temp_dir)

    with (
        patch("compman.http_source.urlopen", return_value=response) as urlopen,
        patch("compman.http_source.build_opener") as build_opener,
    ):
        http_source.fetch("https://example.test/app.zip", temp_dir)

    urlopen.assert_called_once_with("https://example.test/app.zip", timeout=30)
    build_opener.assert_not_called()


def test_http_source_auth_missing_env_names_variable_only(temp_dir: pathlib.Path):
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("compman.http_source.build_opener") as build_opener,
    ):
        with pytest.raises(CommandError, match="DEPLOY_TOKEN") as excinfo:
            http_source.fetch("https://example.test/app.zip", temp_dir, auth=_AUTH)

    assert "Bearer" not in str(excinfo.value)
    build_opener.assert_not_called()


@pytest.mark.parametrize("bad_value", ["Bearer a\rb", "Bearer a\nb"])
def test_http_source_auth_rejects_line_breaks_in_env_value(temp_dir: pathlib.Path, bad_value: str):
    with (
        patch.dict(os.environ, {"DEPLOY_TOKEN": bad_value}),
        patch("compman.http_source.build_opener") as build_opener,
    ):
        with pytest.raises(CommandError, match="DEPLOY_TOKEN") as excinfo:
            http_source.fetch("https://example.test/app.zip", temp_dir, auth=_AUTH)

    message = str(excinfo.value)
    assert "\r" not in message
    assert "\n" not in message
    build_opener.assert_not_called()


def _redirect_request(handler: http_source._AuthAwareRedirectHandler, newurl: str):
    original = Request(
        "https://example.test/app.zip",
        headers={"Authorization": "Bearer sekret", "X-Custom": "keep-me"},
    )
    return handler.redirect_request(original, MagicMock(), 302, "Found", HTTPMessage(), newurl)


@pytest.mark.parametrize(
    "newurl",
    ["https://example.test/releases/app.zip", "https://example.test:443/releases/app.zip"],
)
def test_redirect_same_host_keeps_auth_header(newurl: str):
    new_request = _redirect_request(http_source._AuthAwareRedirectHandler("Authorization"), newurl)

    assert new_request is not None
    assert _header_value(new_request, "Authorization") == "Bearer sekret"
    assert _header_value(new_request, "X-Custom") == "keep-me"


@pytest.mark.parametrize("newurl", ["https://mirror.example.org/app.zip", "file:///etc/passwd"])
def test_redirect_cross_host_or_unparsable_drops_auth_header(newurl: str):
    new_request = _redirect_request(http_source._AuthAwareRedirectHandler("Authorization"), newurl)

    assert new_request is not None
    assert _header_value(new_request, "Authorization") is None
    assert _header_value(new_request, "X-Custom") == "keep-me"


def test_redirect_handler_propagates_none_from_base_handler():
    handler = http_source._AuthAwareRedirectHandler("Authorization")

    with patch.object(http_source.HTTPRedirectHandler, "redirect_request", return_value=None):
        result = handler.redirect_request(
            MagicMock(), MagicMock(), 302, "Found", HTTPMessage(), "https://example.test/app.zip"
        )

    assert result is None


def _write_auth_deploy_config(temp_dir: pathlib.Path) -> None:
    (temp_dir / "compman.yml").write_text(
        "compman:\n"
        "  name: app\n"
        "  deploy:\n"
        "    url: https://example.test/app.zip\n"
        "    auth:\n"
        "      header: Authorization\n"
        "      value_env: DEPLOY_TOKEN\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )


def test_deploy_forwards_config_auth_when_source_matches(temp_dir: pathlib.Path):
    _write_auth_deploy_config(temp_dir)
    cfg = load_config(str(temp_dir / "compman.yml"))

    with patch("compman.deploy._fetch_http", return_value=_make_source_dir(temp_dir)) as fetch_http:
        deploy.deploy(s3_path=cfg.deploy, config=cfg)

    assert fetch_http.call_args.kwargs["auth"] == cfg.deploy_auth


def test_deploy_omits_auth_for_different_path(temp_dir: pathlib.Path):
    _write_auth_deploy_config(temp_dir)
    cfg = load_config(str(temp_dir / "compman.yml"))

    with patch("compman.deploy._fetch_http", return_value=_make_source_dir(temp_dir)) as fetch_http:
        deploy.deploy(s3_path="https://other.test/app.zip", config=cfg)

    assert fetch_http.call_args.kwargs["auth"] is None


def test_deploy_string_config_has_no_auth_to_forward(temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  deploy: https://example.test/app.zip\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(temp_dir / "compman.yml"))

    with patch("compman.deploy._fetch_http", return_value=_make_source_dir(temp_dir)) as fetch_http:
        deploy.deploy(s3_path=cfg.deploy, config=cfg)

    assert fetch_http.call_args.kwargs["auth"] is None
