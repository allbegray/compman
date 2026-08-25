from __future__ import annotations

import pathlib
import tarfile
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
)

from compman.config import Config, Profile
from compman.errors import CommandError
from compman.ops import upload


def _cfg(temp_dir: pathlib.Path, backup_upload: str | None = None) -> Config:
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    cfg.backup_upload = backup_upload
    return cfg


def _make_archive(temp_dir: pathlib.Path) -> pathlib.Path:
    archive = temp_dir / "my_stack.volume.20260825_120000.tar.gz"
    with tarfile.open(archive, "w:gz"):
        pass
    return archive


# ---- resolve_upload_target precedence ----


def test_resolve_upload_target_without_configuration_is_none(temp_dir: pathlib.Path):
    assert upload.resolve_upload_target(_cfg(temp_dir)) is None


def test_resolve_upload_target_uses_configured_target(temp_dir: pathlib.Path):
    assert upload.resolve_upload_target(_cfg(temp_dir, "s3://bucket/backups")) == "s3://bucket/backups"


def test_resolve_upload_target_push_only(temp_dir: pathlib.Path):
    assert upload.resolve_upload_target(_cfg(temp_dir), push="s3://other/x") == "s3://other/x"


def test_resolve_upload_target_push_overrides_config(temp_dir: pathlib.Path):
    target = upload.resolve_upload_target(_cfg(temp_dir, "s3://bucket/backups"), push="s3://other/x")
    assert target == "s3://other/x"


def test_resolve_upload_target_no_push_suppresses_config(temp_dir: pathlib.Path):
    assert upload.resolve_upload_target(_cfg(temp_dir, "s3://bucket/backups"), no_push=True) is None


def test_resolve_upload_target_rejects_push_and_no_push(temp_dir: pathlib.Path):
    with pytest.raises(CommandError, match="cannot be combined"):
        upload.resolve_upload_target(_cfg(temp_dir), push="s3://b/p", no_push=True)


# ---- parse_s3_uri ----


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("s3://bucket/backups/", ("bucket", "backups")),
        ("s3://bucket//a/b//", ("bucket", "a/b")),
        ("s3://bucket", ("bucket", "")),
        ("s3://bucket/", ("bucket", "")),
    ],
)
def test_parse_s3_uri_strips_slashes_and_allows_bucket_root(uri: str, expected: tuple[str, str]):
    assert upload.parse_s3_uri(uri) == expected


@pytest.mark.parametrize("uri", ["https://bucket/x", "ftp://bucket", "s3:///key"])
def test_parse_s3_uri_rejects_wrong_scheme_or_empty_bucket(uri: str):
    with pytest.raises(ValueError, match="Invalid S3 URI"):
        upload.parse_s3_uri(uri)


# ---- upload_backup ----


def test_upload_backup_happy_path_records_flat_key_and_content_type(temp_dir: pathlib.Path, capsys):
    archive = _make_archive(temp_dir)
    client = MagicMock()
    client.head_object.return_value = {"ContentLength": archive.stat().st_size}

    with patch("compman.ops.upload.create_client", return_value=client):
        upload.upload_backup(_cfg(temp_dir), archive, "Volume", "s3://bucket/backups")

    client.upload_file.assert_called_once_with(
        Filename=str(archive),
        Bucket="bucket",
        Key=f"backups/{archive.name}",
        ExtraArgs={"ContentType": "application/gzip"},
    )
    out = capsys.readouterr().out
    assert f"backups/{archive.name}" in out
    assert f"({archive.stat().st_size} bytes)" in out


def test_upload_backup_without_prefix_uses_bucket_root_key(temp_dir: pathlib.Path):
    archive = _make_archive(temp_dir)
    client = MagicMock()
    client.head_object.return_value = {"ContentLength": archive.stat().st_size}

    with patch("compman.ops.upload.create_client", return_value=client):
        upload.upload_backup(_cfg(temp_dir), archive, "Volume", "s3://bucket")

    assert client.upload_file.call_args.kwargs["Key"] == archive.name


def test_upload_backup_size_mismatch_raises(temp_dir: pathlib.Path):
    archive = _make_archive(temp_dir)
    client = MagicMock()
    client.head_object.return_value = {"ContentLength": archive.stat().st_size + 1}

    with patch("compman.ops.upload.create_client", return_value=client):
        with pytest.raises(CommandError, match="remote size") as excinfo:
            upload.upload_backup(_cfg(temp_dir), archive, "Volume", "s3://bucket/backups")

    assert str(archive) not in str(excinfo.value)
    assert str(archive.stat().st_size + 1) in str(excinfo.value)


@pytest.mark.parametrize(
    ("error", "detail_fragment"),
    [
        (NoCredentialsError(), "AWS credentials"),
        (PartialCredentialsError(provider="env", cred_var="AWS_SECRET_ACCESS_KEY"), "AWS credentials"),
        (ClientError({"Error": {"Code": "403"}}, "PutObject"), "403"),
        (ClientError({"Error": {"Code": "404"}}, "PutObject"), "404"),
        (ClientError({"Error": {"Code": "500", "Message": "boom"}}, "PutObject"), "boom"),
        (EndpointConnectionError(endpoint_url="http://localhost:4566"), "S3 endpoint"),
        (RuntimeError("socket exploded"), "socket exploded"),
    ],
)
def test_upload_backup_failure_keeps_local_path_in_message(
    error: Exception, detail_fragment: str, temp_dir: pathlib.Path
):
    archive = _make_archive(temp_dir)
    failing = MagicMock()
    failing.upload_file.side_effect = error

    with patch("compman.ops.upload.create_client", return_value=failing):
        with pytest.raises(CommandError) as excinfo:
            upload.upload_backup(_cfg(temp_dir), archive, "Volume", "s3://bucket/backups")

    message = str(excinfo.value)
    assert str(archive) in message
    assert detail_fragment in message


def test_upload_backup_failure_preserves_cause(temp_dir: pathlib.Path):
    archive = _make_archive(temp_dir)
    failing = MagicMock()
    failing.upload_file.side_effect = RuntimeError("socket exploded")

    with patch("compman.ops.upload.create_client", return_value=failing):
        with pytest.raises(CommandError) as excinfo:
            upload.upload_backup(_cfg(temp_dir), archive, "Volume", "s3://bucket/backups")

    assert isinstance(excinfo.value.__cause__, RuntimeError)
