from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import shutil
import tarfile
import zipfile
from http.client import HTTPMessage
from unittest.mock import MagicMock, patch
from urllib.request import Request

import pytest
import typer
import yaml
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
)
from conftest import write_config

from compman import backup_store, deploy, http_source, s3_source
from compman.archive_source import ensure_digest, extract_archive, has_archive_suffix, sha256_file
from compman.config import DeployAuth, load_config
from compman.errors import CommandError
from compman.i18n import t

_PIN_A = "a" * 64
_PIN_B = "b" * 64


@pytest.fixture(autouse=True)
def _isolate_stack_registry(tmp_path, monkeypatch):
    """Deploy tests must never touch the developer's real stacks.json."""

    from compman import stack_registry

    monkeypatch.setattr(stack_registry, "stacks_path", lambda: tmp_path / "stacks.json")
    yield


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


def test_deploy_empty_directory_prints_onboarding_hints_and_exits_one(
    temp_dir: pathlib.Path, capsys
):
    with pytest.raises(CommandError) as excinfo:
        deploy.deploy(s3_path=None)

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert t("msg.empty_dir_deploy") in err
    assert t("msg.empty_dir_start") in err
    assert "compman deploy --path s3://<your-bucket>/path/to/app.tar.gz" in err
    assert t("msg.config_hint") in err
    assert "     compman init" in err


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

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("compman.http_source.urlopen", return_value=response) as urlopen,
    ):
        extracted = http_source.fetch(url, download_dir)

    urlopen.assert_called_once_with(url, timeout=300.0)
    assert (extracted / "app.txt").read_text(encoding="utf-8") == "hello"


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [(None, 300.0), ("42", 42.0), ("not-a-number", 300.0), ("0", 300.0)],
)
def test_http_source_fetch_derives_timeout_from_env(
    env_value: str | None, expected: float, temp_dir: pathlib.Path
):
    archive = temp_dir / "app.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("app.txt", "hello")
    response = _FakeResponse(archive.read_bytes(), "https://example.test/app.zip")
    env = {} if env_value is None else {"COMPMAN_TIMEOUT": env_value}

    with (
        patch.dict(os.environ, env, clear=True),
        patch("compman.http_source.urlopen", return_value=response) as urlopen,
    ):
        http_source.fetch("https://example.test/app.zip", temp_dir)

    urlopen.assert_called_once_with("https://example.test/app.zip", timeout=expected)


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


def test_deploy_config_without_path_prints_hint_and_exits_one(temp_dir: pathlib.Path, capsys):
    write_config(temp_dir / "compman.yml")
    with pytest.raises(CommandError) as excinfo:
        deploy.deploy(s3_path=None)
    assert excinfo.value.code == 1
    assert "not configured" in capsys.readouterr().err


@pytest.mark.parametrize(
    "yaml_text",
    [
        "compman:\n  name: app\n  compose:\n    - docker-compose.yml\n",
        "compman:\n  name: app\n  deploy:\n    sha256: abc\n",
    ],
)
def test_deploy_unparsable_config_names_the_error_and_exits_one(
    yaml_text: str, temp_dir: pathlib.Path, capsys
):
    (temp_dir / "compman.yml").write_text(yaml_text, encoding="utf-8")

    with pytest.raises(typer.Exit) as excinfo:
        deploy.deploy(s3_path=None)

    assert excinfo.value.exit_code == 1
    assert "could not be parsed" in capsys.readouterr().err


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


def test_download_recursive_tolerates_pages_without_contents(temp_dir: pathlib.Path):
    mock_s3 = MagicMock()
    mock_s3.get_paginator.return_value.paginate.return_value = [{}, {"Contents": []}]

    target = temp_dir / "dst"
    deploy._download_recursive(mock_s3, "bucket", "", target)

    assert list(target.iterdir()) == []


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


def test_handle_s3_errors_exit_with_command_error_code_one():
    errors = [
        NoCredentialsError(),
        PartialCredentialsError(provider="env", cred_var="AWS_SECRET_ACCESS_KEY"),
        ClientError({"Error": {"Code": "403"}}, "GetObject"),
        ClientError({"Error": {"Code": "404"}}, "GetObject"),
        ClientError({"Error": {"Code": "500"}}, "GetObject"),
        EndpointConnectionError(endpoint_url="http://localhost"),
        RuntimeError("generic error"),
    ]
    for error in errors:
        with pytest.raises(CommandError) as excinfo:
            deploy._handle_s3_error(error, "s3://b/k")
        assert excinfo.value.code == 1


def test_deploy_routes_client_creation_failure_through_s3_error_handler(temp_dir: pathlib.Path):
    with patch("boto3.client", side_effect=NoCredentialsError()):
        with pytest.raises(CommandError) as excinfo:
            deploy.deploy(s3_path="s3://bucket/key")

    assert excinfo.value.code == 1
    assert not (temp_dir / "project").exists()


def test_handle_s3_error_output_routes_through_s3_error_hint(capsys):
    path = "s3://b/k"
    error = ClientError({"Error": {"Code": "403"}}, "GetObject")
    with pytest.raises(CommandError):
        deploy._handle_s3_error(error, path)

    assert capsys.readouterr().err == t("msg.s3_failed", path=path) + "\n" + t("msg.s3_403", path=path) + "\n"
    generic = RuntimeError("generic error")
    with pytest.raises(CommandError):
        deploy._handle_s3_error(generic, path)

    assert capsys.readouterr().err == t("msg.s3_failed", path=path) + "\n" + t("msg.download_error", error=generic) + "\n"


# ---- s3_source.create_client endpoint precedence ----


def test_create_client_prefers_aws_endpoint_url_s3(monkeypatch):
    client = MagicMock()
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "http://s3:4566")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://generic:4566")
    with patch("boto3.client", return_value=client) as boto_client:
        assert s3_source.create_client() is client

    boto_client.assert_called_once()
    assert boto_client.call_args.args == ("s3",)
    assert boto_client.call_args.kwargs["endpoint_url"] == "http://s3:4566"


def test_create_client_falls_back_to_aws_endpoint_url(monkeypatch):
    client = MagicMock()
    monkeypatch.delenv("AWS_ENDPOINT_URL_S3", raising=False)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://generic:4566")
    with patch("boto3.client", return_value=client) as boto_client:
        s3_source.create_client()

    boto_client.assert_called_once()
    assert boto_client.call_args.args == ("s3",)
    assert boto_client.call_args.kwargs["endpoint_url"] == "http://generic:4566"


def test_create_client_without_endpoint_env_passes_none(monkeypatch):
    client = MagicMock()
    monkeypatch.delenv("AWS_ENDPOINT_URL_S3", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with patch("boto3.client", return_value=client) as boto_client:
        s3_source.create_client()

    boto_client.assert_called_once()
    assert boto_client.call_args.args == ("s3",)
    assert boto_client.call_args.kwargs["endpoint_url"] is None

@pytest.mark.parametrize(
    ("env_value", "expected_read_timeout"),
    [(None, 300.0), ("42", 42.0), ("not-a-number", 300.0), ("0", 300.0)],
)
def test_create_client_config_derives_timeouts_from_env(
    env_value: str | None, expected_read_timeout: float, monkeypatch
):
    monkeypatch.delenv("COMPMAN_TIMEOUT", raising=False)
    if env_value is not None:
        monkeypatch.setenv("COMPMAN_TIMEOUT", env_value)
    client = MagicMock()
    with patch("boto3.client", return_value=client) as boto_client:
        s3_source.create_client()

    config = boto_client.call_args.kwargs["config"]
    assert config.connect_timeout == 10
    assert config.read_timeout == expected_read_timeout
    assert config.retries == {"max_attempts": 3, "mode": "standard"}


def test_backup_store_create_client_delegates_to_s3_source():
    assert backup_store.create_client is s3_source.create_client


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
        self.timeouts: list[float] = []

    def open(self, request: Request, timeout: float = 30) -> _FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
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
        patch.dict(os.environ, {"DEPLOY_TOKEN": "Bearer sekret"}, clear=True),
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
    assert opener.timeouts == [300.0]


def test_http_source_without_auth_keeps_bare_urlopen(temp_dir: pathlib.Path):
    response = _auth_zip_response(temp_dir)

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("compman.http_source.urlopen", return_value=response) as urlopen,
        patch("compman.http_source.build_opener") as build_opener,
    ):
        http_source.fetch("https://example.test/app.zip", temp_dir)

    urlopen.assert_called_once_with("https://example.test/app.zip", timeout=300.0)
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


def _redirect_request(
    handler: http_source._AuthAwareRedirectHandler,
    newurl: str,
    original_url: str = "https://example.test/app.zip",
):
    original = Request(
        original_url,
        headers={"Authorization": "Bearer sekret", "X-Custom": "keep-me"},
    )
    return handler.redirect_request(original, MagicMock(), 302, "Found", HTTPMessage(), newurl)


@pytest.mark.parametrize(
    ("original_url", "newurl", "keeps_auth"),
    [
        ("https://example.test/app.zip", "https://example.test/releases/app.zip", True),
        ("https://example.test/app.zip", "https://example.test:443/releases/app.zip", True),
        ("http://example.test/app.zip", "https://example.test/releases/app.zip", True),
        ("https://example.test/app.zip", "http://example.test/releases/app.zip", False),
        ("https://example.test/app.zip", "https://mirror.example.org/app.zip", False),
        ("https://example.test/app.zip", "file:///etc/passwd", False),
    ],
)
def test_redirect_request_applies_auth_header_policy(
    original_url: str, newurl: str, keeps_auth: bool
):
    new_request = _redirect_request(
        http_source._AuthAwareRedirectHandler("Authorization"), newurl, original_url
    )

    assert new_request is not None
    if keeps_auth:
        assert _header_value(new_request, "Authorization") == "Bearer sekret"
    else:
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


# ---- L12: rollback snapshot capture and restore ----


def _deploy_with_previous_tree(temp_dir: pathlib.Path) -> None:
    """Deploy over an existing managed tree with a previous compman.yml."""
    managed = temp_dir / "project"
    managed.mkdir()
    (managed / "old.txt").write_text("previous", encoding="utf-8")
    config_text = "compman:\n  name: app\n  deploy: old\n"
    (temp_dir / "compman.yml").write_text(config_text, encoding="utf-8")

    source = temp_dir / "fetched"
    source.mkdir()
    (source / "new.txt").write_text("current", encoding="utf-8")
    with patch("compman.deploy._fetch_http", return_value=source):
        deploy.deploy(s3_path="https://example.test/app.zip")


def test_deploy_captures_rollback_snapshot(temp_dir: pathlib.Path, capsys):
    _deploy_with_previous_tree(temp_dir)

    snap = temp_dir / ".compman" / "rollback"
    assert (snap / "tree" / "old.txt").read_text(encoding="utf-8") == "previous"
    assert (snap / "compman.yml").read_text(encoding="utf-8") == (
        "compman:\n  name: app\n  deploy: old\n"
    )
    meta = json.loads((snap / "meta.json").read_text(encoding="utf-8"))
    assert meta["timestamp"].endswith("+00:00")
    assert meta["target"] == "project"
    assert (temp_dir / "project" / "new.txt").exists()
    assert not (temp_dir / "project" / "old.txt").exists()
    assert str(snap) in capsys.readouterr().out


def test_deploy_replaces_previous_snapshot_atomically(temp_dir: pathlib.Path):
    _deploy_with_previous_tree(temp_dir)
    first_meta = json.loads(
        (temp_dir / ".compman" / "rollback" / "meta.json").read_text(encoding="utf-8")
    )

    second = temp_dir / "second-source"
    second.mkdir()
    (second / "v2.txt").write_text("v2", encoding="utf-8")
    with patch("compman.deploy._fetch_http", return_value=second):
        deploy.deploy(s3_path="https://example.test/v2.zip")

    snap = temp_dir / ".compman" / "rollback"
    assert (snap / "tree" / "new.txt").exists()
    assert not (snap / "tree" / "old.txt").exists()
    second_meta = json.loads((snap / "meta.json").read_text(encoding="utf-8"))
    assert second_meta["timestamp"] >= first_meta["timestamp"]
    leftovers = [p.name for p in snap.parent.iterdir() if p.name != "rollback"]
    assert leftovers == []


def test_deploy_snapshot_failure_warns_and_continues(temp_dir: pathlib.Path, capsys):
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  deploy: s3://b/k.tar.gz\n", encoding="utf-8"
    )
    zip_path = temp_dir / "app.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.txt", "hello")
    mock_s3 = MagicMock()
    mock_s3.download_file.side_effect = lambda b, k, dst: pathlib.Path(dst).write_bytes(
        zip_path.read_bytes()
    )

    with patch("boto3.client", return_value=mock_s3), patch(
        "compman.deploy._capture_rollback_snapshot",
        side_effect=RuntimeError("disk full"),
    ):
        deploy.deploy(build=False, tag=None, s3_path="s3://my-bucket/app.zip")

    err = capsys.readouterr().err
    assert "disk full" in err
    assert (temp_dir / "project" / "test.txt").exists()
    assert not (temp_dir / ".compman").exists() or not (
        temp_dir / ".compman" / "rollback"
    ).exists()


def test_deploy_scaffold_failure_after_swap_keeps_snapshot_recoverable(
    temp_dir: pathlib.Path,
):
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  deploy: s3://b/k.tar.gz\n", encoding="utf-8"
    )
    zip_path = temp_dir / "app.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.txt", "hello")
    mock_s3 = MagicMock()
    mock_s3.download_file.side_effect = lambda b, k, dst: pathlib.Path(dst).write_bytes(
        zip_path.read_bytes()
    )

    with patch("boto3.client", return_value=mock_s3), patch(
        "compman.deploy._generate_scaffold", side_effect=RuntimeError("template boom")
    ):
        with pytest.raises(SystemExit):
            deploy.deploy(build=False, tag=None, s3_path="s3://my-bucket/app.zip")

    snap = temp_dir / ".compman" / "rollback"
    assert (snap / "tree").is_dir()
    assert (temp_dir / "project" / "test.txt").exists()


def test_swap_old_dest_preserves_previous_tree(temp_dir: pathlib.Path):
    src = temp_dir / "source"
    src.mkdir()
    (src / "a-new").write_text("new", encoding="utf-8")
    target = temp_dir / "target"
    target.mkdir()
    (target / "a-old").write_text("old", encoding="utf-8")
    keep = temp_dir / "keep"

    deploy._swap(src, target, old_dest=keep)

    assert (keep / "a-old").read_text(encoding="utf-8") == "old"
    assert (target / "a-new").exists()


def test_swap_old_dest_restores_previous_tree_on_failure(temp_dir: pathlib.Path):
    src = temp_dir / "source"
    src.mkdir()
    (src / "a-new").write_text("new", encoding="utf-8")
    (src / "z-bomb").mkdir()
    target = temp_dir / "target"
    target.mkdir()
    (target / "a-old").write_text("old", encoding="utf-8")
    keep = temp_dir / "keep"

    real_move = shutil.move

    def failing_move(src_path, dst_path, *args, **kwargs):
        if "z-bomb" in str(src_path) or "z-bomb" in str(dst_path):
            raise OSError("cannot move bomb")
        return real_move(src_path, dst_path, *args, **kwargs)

    with patch("compman.deploy.shutil.move", side_effect=failing_move):
        with pytest.raises(OSError, match="bomb"):
            deploy._swap(src, target, old_dest=keep)

    assert (target / "a-old").read_text(encoding="utf-8") == "old"
    assert not (target / "a-new").exists()


@pytest.mark.parametrize("new_kind", ["file", "directory"])
def test_swap_rolls_back_new_entries_when_a_later_move_fails(temp_dir: pathlib.Path, new_kind: str):
    root = temp_dir / "target"
    src = temp_dir / "source"
    root.mkdir()
    src.mkdir()
    (root / "old.txt").write_text("old", encoding="utf-8")
    first = src / "a-new"
    if new_kind == "directory":
        first.mkdir()
        (first / "data.txt").write_text("new", encoding="utf-8")
    else:
        first.write_text("new", encoding="utf-8")
    (src / "b-new").write_text("new", encoding="utf-8")
    (src / "z-fail").write_text("fail", encoding="utf-8")

    real_move = shutil.move

    def move_then_fail(source, destination):
        if pathlib.Path(source).name == "z-fail":
            raise OSError("swap failed")
        return real_move(source, destination)

    with patch("compman.deploy.shutil.move", side_effect=move_then_fail):
        with pytest.raises(OSError, match="swap failed"):
            deploy._swap(src, root)

    assert (root / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (root / "a-new").exists()


def test_swap_preserves_repository_markers(temp_dir: pathlib.Path):
    root = temp_dir / "target"
    src = temp_dir / "source"
    root.mkdir()
    src.mkdir()
    (root / ".git").mkdir()
    (root / ".gitkeep").touch()
    (src / ".gitkeep").touch()
    (src / "app.txt").write_text("new", encoding="utf-8")

    deploy._swap(src, root)

    assert (root / ".git").is_dir()
    assert (root / ".gitkeep").is_file()
    assert (root / "app.txt").is_file()


def test_swap_rollback_tolerates_new_entry_already_missing(temp_dir: pathlib.Path):
    root = temp_dir / "target"
    src = temp_dir / "source"
    root.mkdir()
    src.mkdir()
    (src / "a-disappears").write_text("new", encoding="utf-8")
    (src / "z-fail").write_text("fail", encoding="utf-8")

    def disappear_then_fail(source, destination):
        source_path = pathlib.Path(source)
        if source_path.name == "a-disappears":
            source_path.unlink()
            return str(destination)
        raise OSError("swap failed")

    with patch("compman.deploy.shutil.move", side_effect=disappear_then_fail):
        with pytest.raises(OSError, match="swap failed"):
            deploy._swap(src, root)

    assert not (root / "a-disappears").exists()


def test_swap_rollback_tolerates_new_entry_vanishing_midway(temp_dir: pathlib.Path):
    src = temp_dir / "source"
    src.mkdir()
    new_item = src / "a-new"
    new_item.write_text("new", encoding="utf-8")
    trigger = src / "b-trigger"
    trigger.write_text("trigger", encoding="utf-8")

    dst = temp_dir / "target"
    dst.mkdir()

    real_move = shutil.move
    real_iterdir = pathlib.Path.iterdir

    def move_and_vanish(source, destination):
        if pathlib.Path(source) == trigger:
            (dst / new_item.name).unlink()
            raise OSError("simulated move failure")
        return real_move(source, destination)

    def ordered_source(path):
        if path == src:
            return iter((new_item, trigger))
        return real_iterdir(path)

    with patch.object(type(src), "iterdir", autospec=True, side_effect=ordered_source), patch(
        "compman.deploy.shutil.move", side_effect=move_and_vanish
    ):
        with pytest.raises(OSError, match="simulated move failure"):
            deploy._swap(src, dst)

    assert not (dst / new_item.name).exists()


@pytest.mark.parametrize("new_item_is_dir", [False, True])
def test_swap_rolls_back_partially_moved_source_entries(temp_dir: pathlib.Path, new_item_is_dir: bool):
    src = temp_dir / "source"
    src.mkdir()
    new_item = src / "a-new"
    if new_item_is_dir:
        new_item.mkdir()
    else:
        new_item.write_text("new", encoding="utf-8")
    trigger = src / "b-trigger"
    trigger.write_text("trigger", encoding="utf-8")

    dst = temp_dir / "target"
    dst.mkdir()
    old_item = dst / "old"
    old_item.write_text("old", encoding="utf-8")

    real_move = shutil.move
    real_iterdir = pathlib.Path.iterdir

    def fail_on_trigger(source, destination):
        if pathlib.Path(source) == trigger:
            raise OSError("simulated move failure")
        return real_move(source, destination)

    def ordered_source(path):
        if path == src:
            return iter((new_item, trigger))
        return real_iterdir(path)

    with patch.object(type(src), "iterdir", autospec=True, side_effect=ordered_source), patch(
        "compman.deploy.shutil.move", side_effect=fail_on_trigger
    ):
        with pytest.raises(OSError, match="simulated move failure"):
            deploy._swap(src, dst)

    assert old_item.read_text(encoding="utf-8") == "old"
    assert not (dst / new_item.name).exists()


def test_swap_rollback_cleanup_is_platform_independent(temp_dir: pathlib.Path):
    root = temp_dir / "target"
    src = temp_dir / "source"
    root.mkdir()
    src.mkdir()
    (src / "a-directory").mkdir()
    (src / "b-disappears").touch()
    (src / "z-fail").touch()

    def controlled_move(source, destination):
        name = pathlib.Path(source).name
        if name == "a-directory":
            pathlib.Path(destination).mkdir()
            return str(destination)
        if name == "b-disappears":
            pathlib.Path(source).unlink()
            return str(destination)
        raise OSError("swap failed")

    with patch("compman.deploy.shutil.move", side_effect=controlled_move):
        with pytest.raises(OSError, match="swap failed"):
            deploy._swap(src, root)

    assert not (root / "a-directory").exists()
    assert not (root / "b-disappears").exists()


def test_restore_rollback_swaps_and_restores_config(temp_dir: pathlib.Path):
    snap = temp_dir / ".compman" / "rollback"
    (snap / "tree").mkdir(parents=True)
    (snap / "tree" / "old.txt").write_text("previous", encoding="utf-8")
    (snap / "compman.yml").write_bytes(b"compman:\n  name: previous\n")
    (snap / "meta.json").write_text(
        json.dumps({"timestamp": "2026-01-02T03:04:05+00:00", "target": "project"}),
        encoding="utf-8",
    )
    managed = temp_dir / "project"
    managed.mkdir()
    (managed / "new.txt").write_text("current", encoding="utf-8")
    (temp_dir / "compman.yml").write_text("compman:\n  name: current\n", encoding="utf-8")

    timestamp = deploy.restore_rollback(temp_dir)

    assert timestamp == "2026-01-02T03:04:05+00:00"
    assert (managed / "old.txt").exists()
    assert not (managed / "new.txt").exists()
    assert (temp_dir / "compman.yml").read_bytes() == b"compman:\n  name: previous\n"
    assert not snap.exists()
    assert not (temp_dir / ".compman").exists()



def test_restore_rollback_keeps_compman_when_other_entries_exist(temp_dir: pathlib.Path):
    snap = temp_dir / ".compman" / "rollback"
    (snap / "tree").mkdir(parents=True)
    (snap / "meta.json").write_text(
        json.dumps({"timestamp": "2026-01-02T03:04:05+00:00", "target": "project"}),
        encoding="utf-8",
    )
    (temp_dir / ".compman" / "unrelated.txt").write_text("keep me", encoding="utf-8")
    managed = temp_dir / "project"
    managed.mkdir()

    timestamp = deploy.restore_rollback(temp_dir)

    assert timestamp == "2026-01-02T03:04:05+00:00"
    assert not snap.exists()
    assert (temp_dir / ".compman" / "unrelated.txt").exists()


def test_restore_rollback_without_snapshot_raises_command_error(temp_dir: pathlib.Path):
    with pytest.raises(CommandError, match="No rollback snapshot"):
        deploy.restore_rollback(temp_dir)


def test_restore_rollback_with_corrupt_meta_treated_as_missing(temp_dir: pathlib.Path):
    snap = temp_dir / ".compman" / "rollback"
    (snap / "tree").mkdir(parents=True)
    (snap / "meta.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CommandError, match="No rollback snapshot"):
        deploy.restore_rollback(temp_dir)


def test_deploy_snapshot_records_absolute_target_outside_cwd(
    temp_dir: pathlib.Path, tmp_path_factory
):
    cfg_dir = tmp_path_factory.mktemp("outer") / "cfg"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n  dirs:\n    project: managed\n",
        encoding="utf-8",
    )
    source = temp_dir / "fetched"
    source.mkdir()
    (source / "x.txt").write_text("x", encoding="utf-8")
    cfg = load_config(str(cfg_dir / "compman.yml"))

    with (
        patch("compman.deploy._fetch_http", return_value=source),
        patch("compman.deploy.record_stack") as record,
    ):
        deploy.deploy(s3_path="https://example.test/app.zip", config=cfg)
    record.assert_called_once_with("app", str(cfg_dir))

    meta = json.loads(
        (temp_dir / ".compman" / "rollback" / "meta.json").read_text(encoding="utf-8")
    )
    assert meta["target"] == str(cfg_dir / "managed")


def test_commit_replace_failure_restores_previous_snapshot(
    temp_dir: pathlib.Path, capsys
):
    _deploy_with_previous_tree(temp_dir)
    snap = temp_dir / ".compman" / "rollback"
    original_meta = (snap / "meta.json").read_text(encoding="utf-8")

    second = temp_dir / "second-source"
    second.mkdir()
    (second / "v2.txt").write_text("v2", encoding="utf-8")
    real_replace = os.replace

    def failing_replace(src, dst, *args, **kwargs):
        if "rollback_tmp_" in str(src):
            raise OSError("replace boom")
        return real_replace(src, dst, *args, **kwargs)

    with patch("compman.deploy._fetch_http", return_value=second), patch(
        "compman.deploy.os.replace", side_effect=failing_replace
    ):
        deploy.deploy(s3_path="https://example.test/v2.zip")

    assert "replace boom" in capsys.readouterr().err
    assert json.loads((snap / "meta.json").read_text(encoding="utf-8")) == json.loads(
        original_meta
    )
    assert (snap / "tree" / "old.txt").exists()
    leftovers = [p.name for p in snap.parent.iterdir() if p.name != "rollback"]
    assert leftovers == []


def test_deploy_swap_failure_inside_capture_falls_back_to_plain_swap(
    temp_dir: pathlib.Path, capsys
):
    managed = temp_dir / "project"
    managed.mkdir()
    (managed / "old.txt").write_text("previous", encoding="utf-8")
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  deploy: old\n", encoding="utf-8"
    )
    source = temp_dir / "fetched"
    source.mkdir()
    (source / "new.txt").write_text("current", encoding="utf-8")
    real_move = shutil.move

    def failing_staging_move(src, dst, *args, **kwargs):
        if ".compman" in str(dst):
            raise OSError("cannot move into staging")
        return real_move(src, dst, *args, **kwargs)

    with patch("compman.deploy._fetch_http", return_value=source), patch(
        "compman.deploy.shutil.move", side_effect=failing_staging_move
    ):
        deploy.deploy(s3_path="https://example.test/app.zip")

    assert "cannot move into staging" in capsys.readouterr().err
    assert (managed / "new.txt").exists()
    snap = temp_dir / ".compman" / "rollback"
    assert not snap.exists()
    leftovers = [p.name for p in snap.parent.iterdir()] if snap.parent.exists() else []
    assert not any(name.startswith(".rollback_tmp_") for name in leftovers)


def test_deploy_commit_failure_warns_but_keeps_deployment(temp_dir: pathlib.Path, capsys):
    source = temp_dir / "fetched"
    source.mkdir()
    (source / "new.txt").write_text("current", encoding="utf-8")
    with patch("compman.deploy._fetch_http", return_value=source), patch(
        "compman.deploy._commit_rollback_snapshot",
        side_effect=RuntimeError("meta boom"),
    ):
        deploy.deploy(s3_path="https://example.test/app.zip")

    assert "meta boom" in capsys.readouterr().err
    assert (temp_dir / "project" / "new.txt").exists()
    assert not (temp_dir / ".compman" / "rollback").exists()


def test_restore_rollback_absolute_target_without_saved_config(temp_dir: pathlib.Path):
    snap = temp_dir / ".compman" / "rollback"
    (snap / "tree").mkdir(parents=True)
    (snap / "tree" / "old.txt").write_text("previous", encoding="utf-8")
    (snap / "meta.json").write_text(
        json.dumps({"timestamp": "2026-01-02T03:04:05+00:00", "target": str(temp_dir / "project")}),
        encoding="utf-8",
    )
    managed = temp_dir / "project"
    managed.mkdir()
    (managed / "new.txt").write_text("current", encoding="utf-8")

    timestamp = deploy.restore_rollback(temp_dir)

    assert timestamp == "2026-01-02T03:04:05+00:00"
    assert (managed / "old.txt").exists()
    assert not (managed / "new.txt").exists()
    assert not (temp_dir / "compman.yml").exists()
    assert not snap.exists()


def test_commit_replace_failure_without_prior_snapshot_warns(temp_dir: pathlib.Path, capsys):
    source = temp_dir / "fetched"
    source.mkdir()
    (source / "new.txt").write_text("current", encoding="utf-8")
    real_replace = os.replace

    def failing_replace(src, dst, *args, **kwargs):
        if "rollback_tmp_" in str(src):
            raise OSError("fresh replace boom")
        return real_replace(src, dst, *args, **kwargs)

    with patch("compman.deploy._fetch_http", return_value=source), patch(
        "compman.deploy.os.replace", side_effect=failing_replace
    ):
        deploy.deploy(s3_path="https://example.test/app.zip")

    assert "fresh replace boom" in capsys.readouterr().err
    assert (temp_dir / "project" / "new.txt").exists()
    assert not (temp_dir / ".compman" / "rollback").exists()




# ---- L18: scaffold schema header and .bak fallback ----


def test_generate_scaffold_writes_schema_header_matching_default_config(
    dummy_runtime, temp_dir: pathlib.Path
):
    from compman.config import YAML_SCHEMA_HEADER, dump_default_config

    root = temp_dir / "proj"
    root.mkdir()
    deploy._generate_scaffold(root, "project", "s3://b/k.tar.gz", "img")

    content = (root / "compman.yml").read_text(encoding="utf-8")
    assert content.startswith(YAML_SCHEMA_HEADER + "\n")
    assert dump_default_config("x").startswith(YAML_SCHEMA_HEADER + "\n")


def test_update_deploy_fallback_writes_bak_before_safe_dump(temp_dir: pathlib.Path, capsys):
    compman_yml = temp_dir / "compman.yml"
    original = "compman:\n  # keep me\n  name: app\n  deploy: {a: 1}\n"
    compman_yml.write_text(original, encoding="utf-8")

    with patch("yaml.safe_load", side_effect=[{"compman": {"deploy": {"a": 1}}}, ValueError("bad")]):
        deploy._update_compman_deploy(compman_yml, "s3://new/path")

    bak = temp_dir / "compman.yml.bak"
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == original
    new_content = compman_yml.read_text(encoding="utf-8")
    parsed = yaml.safe_load(new_content)
    assert parsed["compman"]["deploy"] == "s3://new/path"
    out = capsys.readouterr().out
    assert str(bak) in out
    assert t("msg.updated_deploy", s3_path="s3://new/path") in out


def test_update_deploy_mapping_line_edit_preserves_comments(temp_dir: pathlib.Path, capsys):
    compman_yml = temp_dir / "compman.yml"
    original = (
        "# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json\n"
        "compman:\n"
        "  name: app\n"
        "  # deployment pin below\n"
        "  deploy:\n"
        "    url: s3://old/app.tar.gz\n"
        "    sha256: " + _PIN_A + "\n"
        "  dirs:\n"
        "    project: project\n"
        "# trailing comment\n"
    )
    compman_yml.write_text(original, encoding="utf-8")

    deploy._update_compman_deploy(compman_yml, "s3://new/app.tar.gz")

    new_content = compman_yml.read_text(encoding="utf-8")
    assert "# yaml-language-server:" in new_content
    assert "# deployment pin below" in new_content
    assert "# trailing comment" in new_content
    parsed = yaml.safe_load(new_content)
    assert parsed["compman"]["deploy"] == "s3://new/app.tar.gz"
    assert "compman.yml.bak" not in [p.name for p in temp_dir.iterdir()]


def test_update_deploy_tolerates_unparsable_yaml_by_inserting_after_compman(
    temp_dir: pathlib.Path,
):
    compman_yml = temp_dir / "compman.yml"
    compman_yml.write_text("compman:\n  name: app\n", encoding="utf-8")

    with patch(
        "yaml.safe_load",
        side_effect=[ValueError("bad"), {"compman": {"name": "app", "deploy": "s3://new"}}],
    ):
        deploy._update_compman_deploy(compman_yml, "s3://new")

    assert yaml.safe_load(compman_yml.read_text(encoding="utf-8"))["compman"]["deploy"] == "s3://new"


def test_update_deploy_skips_write_when_revalidation_loses_the_entry(temp_dir: pathlib.Path):
    compman_yml = temp_dir / "compman.yml"
    original = "compman:\n  name: app\n"
    compman_yml.write_text(original, encoding="utf-8")

    with patch("yaml.safe_load", side_effect=[ValueError("bad"), {"compman": {"name": "app"}}]):
        deploy._update_compman_deploy(compman_yml, "s3://new")

    assert compman_yml.read_text(encoding="utf-8") == original
    assert not list(temp_dir.glob("*.bak"))


def test_update_deploy_appends_entry_when_only_comments_follow_compman(temp_dir: pathlib.Path):
    compman_yml = temp_dir / "compman.yml"
    compman_yml.write_text("compman:\n  # nothing configurable yet\n", encoding="utf-8")

    deploy._update_compman_deploy(compman_yml, "s3://new")

    content = compman_yml.read_text(encoding="utf-8")
    assert "# nothing configurable yet" in content
    assert yaml.safe_load(content)["compman"]["deploy"] == "s3://new"


def test_update_deploy_stops_line_scan_at_dedented_sibling_key(temp_dir: pathlib.Path):
    compman_yml = temp_dir / "compman.yml"
    compman_yml.write_text("compman:\n  name: app\nother: value\n", encoding="utf-8")

    deploy._update_compman_deploy(compman_yml, "s3://new")

    parsed = yaml.safe_load(compman_yml.read_text(encoding="utf-8"))
    assert parsed["compman"]["deploy"] == "s3://new"
    assert parsed["other"] == "value"
