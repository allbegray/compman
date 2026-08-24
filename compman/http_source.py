from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from compman.archive_source import ARCHIVE_SUFFIXES, extract_archive, has_archive_suffix
from compman.errors import CommandError
from compman.i18n import t

_CHUNK_SIZE = 1024 * 1024


def fetch(url: str, tmp: Path, max_bytes: int | None = None) -> Path:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid HTTP source: {url}")
    if not has_archive_suffix(parsed.path):
        raise ValueError(f"HTTP source must be a .tar.gz, .tgz, or .zip archive: {url}")

    lower_path = parsed.path.lower()
    suffix = next(suffix for suffix in ARCHIVE_SUFFIXES if lower_path.endswith(suffix))
    archive_path = tmp / f"source{suffix}"
    with urlopen(url, timeout=30) as response:
        # Re-validate after redirects: the final target must still be a safe
        # public HTTP(S) archive URL.
        final_url = str(response.geturl())
        final = urlparse(final_url)
        if final.scheme not in ("http", "https") or not final.netloc:
            raise ValueError(f"Invalid HTTP source: {final_url}")
        if not has_archive_suffix(final.path):
            raise ValueError(f"HTTP source must be a .tar.gz, .tgz, or .zip archive: {final_url}")

        total = 0
        with archive_path.open("wb") as destination:
            while True:
                chunk = response.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    limit_mb = (max_bytes + 1024 * 1024 - 1) // (1024 * 1024)
                    raise CommandError(t("msg.deploy_limit_exceeded", limit=limit_mb, size=total))
                destination.write(chunk)

    return extract_archive(archive_path, tmp / "extract", max_bytes=max_bytes)
