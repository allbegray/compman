from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import typer

from compman.config import Config
from compman.errors import CommandError
from compman.i18n import t
from compman.s3_source import create_client, s3_error_hint


def resolve_upload_target(
    config: Config, push: str | None = None, no_push: bool = False
) -> str | None:
    if push is not None and no_push:
        raise CommandError(t("msg.backup_push_conflict"))
    if push is not None:
        return push
    if no_push:
        return None
    return config.backup_upload


def parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Invalid S3 URI (expected 's3://bucket/prefix'): {uri}")
    return parsed.netloc, parsed.path.strip("/")


def upload_backup(config: Config, archive_path: Path, kind: str, uri: str) -> None:
    local_size = archive_path.stat().st_size
    typer.echo(t("msg.backup_uploading", kind=kind, uri=uri))
    try:
        bucket, prefix = parse_s3_uri(uri)
        key = f"{prefix}/{archive_path.name}" if prefix else archive_path.name
        s3 = create_client()
        s3.upload_file(
            Filename=str(archive_path),
            Bucket=bucket,
            Key=key,
            ExtraArgs={"ContentType": "application/gzip"},
        )
        remote_size = int(s3.head_object(bucket, key)["ContentLength"])
    except Exception as e:
        raise CommandError(
            t("msg.backup_upload_failed", path=str(archive_path), detail=s3_error_hint(e, uri) or e)
        ) from e
    if remote_size != local_size:
        raise CommandError(t("msg.backup_upload_size_mismatch", remote=remote_size, local=local_size))
    typer.echo(t("msg.backup_uploaded", kind=kind, key=key, size=local_size))
