from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from compman._proc import _env_timeout
from compman.archive_source import ensure_digest, extract_archive, has_archive_suffix, sha256_file
from compman.errors import CommandError
from compman.i18n import t


class _S3Client(Protocol):
    """Minimal structural type for the boto3 S3 client surface we use."""

    def download_file(self, bucket: str, key: str, destination: str) -> None: ...

    def delete_object(self, *, Bucket: str, Key: str) -> Any: ...

    def get_paginator(self, operation_name: str) -> Any: ...

    def head_object(self, *, Bucket: str, Key: str) -> Any: ...

    def upload_file(
        self, Filename: str, Bucket: str, Key: str, ExtraArgs: dict[str, str] | None = None
    ) -> None: ...


def create_client() -> Any:
    """Build a boto3 S3 client, honoring the endpoint override environment variables."""
    import boto3
    from botocore.config import Config

    endpoint = os.environ.get("AWS_ENDPOINT_URL_S3") or os.environ.get("AWS_ENDPOINT_URL")
    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        config=Config(
            connect_timeout=10,
            read_timeout=_env_timeout(),
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def fetch(
    s3: _S3Client,
    bucket: str,
    key: str,
    tmp: Path,
    max_bytes: int | None = None,
    sha256: str | None = None,
) -> Path:
    if sha256 is not None and not has_archive_suffix(key):
        raise CommandError(t("msg.deploy_checksum_requires_archive", path=f"s3://{bucket}/{key}"))
    if has_archive_suffix(key):
        if max_bytes is not None:
            _check_size(int(s3.head_object(Bucket=bucket, Key=key)["ContentLength"]), max_bytes)
        archive_path = tmp / key.rsplit("/", 1)[-1]
        download(s3, bucket, key, archive_path)
        if sha256 is not None:
            ensure_digest(sha256_file(archive_path), sha256)
        return extract_archive(archive_path, tmp / "extract", max_bytes=max_bytes)

    source_dir = tmp / "src"
    download_recursive(s3, bucket, key, source_dir, max_bytes=max_bytes)
    return source_dir


def download(s3: _S3Client, bucket: str, key: str, destination: Path) -> None:
    s3.download_file(bucket, key, str(destination))


def download_recursive(
    s3: _S3Client, bucket: str, key_prefix: str, destination: Path, max_bytes: int | None = None
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    paginator = s3.get_paginator("list_objects_v2")
    prefix = f"{key_prefix}/" if key_prefix else ""
    total = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            relative = key[len(key_prefix) :].lstrip("/")
            target = destination / relative
            if destination.resolve() not in target.resolve().parents:
                raise ValueError(f"Unsafe S3 object path: {key}")
            total += int(obj.get("Size", 0))
            _check_size(total, max_bytes)
            target.parent.mkdir(parents=True, exist_ok=True)
            download(s3, bucket, key, target)


def _check_size(size: int, max_bytes: int | None) -> None:
    if max_bytes is not None and size > max_bytes:
        limit_mb = (max_bytes + 1024 * 1024 - 1) // (1024 * 1024)
        raise CommandError(t("msg.deploy_limit_exceeded", limit=limit_mb, size=size))


def s3_error_hint(e: Exception, path: str | None = None) -> str | None:
    """Return a translated troubleshooting hint for a known S3 failure, else None."""
    from botocore.exceptions import (
        ClientError,
        EndpointConnectionError,
        NoCredentialsError,
        PartialCredentialsError,
    )

    if isinstance(e, (NoCredentialsError, PartialCredentialsError)):
        return t("msg.s3_no_creds")
    if isinstance(e, ClientError):
        err_code = str(e.response.get("Error", {}).get("Code", ""))
        if err_code in ("403", "AccessDenied", "Forbidden"):
            return t("msg.s3_403", path=path)
        if err_code in ("404", "NoSuchBucket", "NoSuchKey", "NotFound"):
            return t("msg.s3_404", path=path)
        err_msg = str(e.response.get("Error", {}).get("Message", e))
        return t("msg.s3_client_error", code=err_code, error=err_msg)
    if isinstance(e, EndpointConnectionError):
        return t("msg.s3_network")
    return None
