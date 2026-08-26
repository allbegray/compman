from __future__ import annotations

import hashlib
import os
from http.client import HTTPMessage
from pathlib import Path
from typing import IO
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from compman._proc import _env_timeout
from compman.archive_source import ARCHIVE_SUFFIXES, ensure_digest, extract_archive, has_archive_suffix
from compman.config import DeployAuth
from compman.errors import CommandError
from compman.i18n import t

_CHUNK_SIZE = 1024 * 1024

class _AuthAwareRedirectHandler(HTTPRedirectHandler):
    """Redirect handler that drops the configured auth header off-host or on downgrade.

    Hosts are compared without ports so an explicit default port on the
    redirect target is not mistaken for a cross-host move; an unparsable
    target host counts as cross-host (fail-safe: the header is dropped).
    A same-host redirect that downgrades the scheme from https to http
    also drops the header so credentials never travel over plaintext.
    """

    def __init__(self, header: str) -> None:
        self._header = header

    def redirect_request(
        self, req: Request, fp: IO[bytes], code: int, msg: str, headers: HTTPMessage, newurl: str
    ) -> Request | None:
        new_request = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_request is None:
            return None
        target = urlparse(newurl)
        downgrade = urlparse(req.full_url).scheme == "https" and target.scheme == "http"
        if (
            downgrade
            or target.hostname is None
            or target.hostname.lower() != req.host.lower()
        ):
            new_request.headers = {
                key: value
                for key, value in new_request.headers.items()
                if key.lower() != self._header.lower()
            }
        return new_request


def fetch(
    url: str,
    tmp: Path,
    max_bytes: int | None = None,
    sha256: str | None = None,
    auth: DeployAuth | None = None,
) -> Path:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid HTTP source: {url}")
    if not has_archive_suffix(parsed.path):
        raise ValueError(f"HTTP source must be a .tar.gz, .tgz, or .zip archive: {url}")

    lower_path = parsed.path.lower()
    suffix = next(suffix for suffix in ARCHIVE_SUFFIXES if lower_path.endswith(suffix))
    archive_path = tmp / f"source{suffix}"
    timeout = _env_timeout()
    if auth is not None:
        value = os.environ.get(auth.value_env)
        if not value:
            raise CommandError(t("msg.deploy_auth_env_missing", name=auth.value_env))
        if "\r" in value or "\n" in value:
            raise CommandError(t("msg.deploy_auth_value_invalid", name=auth.value_env))
        opener = build_opener(_AuthAwareRedirectHandler(auth.header))
        response = opener.open(Request(url, headers={auth.header: value}), timeout=timeout)
    else:
        response = urlopen(url, timeout=timeout)
    with response as stream:
        # Re-validate after redirects: the final target must still be a safe
        # public HTTP(S) archive URL.
        final_url = str(stream.geturl())
        final = urlparse(final_url)
        if final.scheme not in ("http", "https") or not final.netloc:
            raise ValueError(f"Invalid HTTP source: {final_url}")
        if not has_archive_suffix(final.path):
            raise ValueError(f"HTTP source must be a .tar.gz, .tgz, or .zip archive: {final_url}")

        total = 0
        digest = hashlib.sha256()
        with archive_path.open("wb") as destination:
            while True:
                chunk = stream.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    limit_mb = (max_bytes + 1024 * 1024 - 1) // (1024 * 1024)
                    raise CommandError(t("msg.deploy_limit_exceeded", limit=limit_mb, size=total))
                destination.write(chunk)
                digest.update(chunk)

    if sha256 is not None:
        ensure_digest(digest.hexdigest(), sha256)
    return extract_archive(archive_path, tmp / "extract", max_bytes=max_bytes)
