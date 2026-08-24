from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from compman.archive_source import extract_archive, has_archive_suffix
from compman.errors import CommandError
from compman.i18n import t


class _S3Client(Protocol):
    """Minimal structural type for the boto3 S3 client surface we use."""

    def download_file(self, bucket: str, key: str, destination: str) -> None: ...

    def get_paginator(self, operation_name: str) -> Any: ...

    def head_object(self, bucket: str, key: str) -> Any: ...


def fetch(s3: _S3Client, bucket: str, key: str, tmp: Path, max_bytes: int | None = None) -> Path:
    if has_archive_suffix(key):
        if max_bytes is not None:
            _check_size(int(s3.head_object(bucket, key)["ContentLength"]), max_bytes)
        archive_path = tmp / key.rsplit("/", 1)[-1]
        download(s3, bucket, key, archive_path)
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
