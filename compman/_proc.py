"""Shared subprocess timeout helpers.

Kept free of heavy imports so that lazily loaded command modules can use it
without pulling in AWS SDKs or the container-runtime layer.
"""

from __future__ import annotations

import os

# Sentinel for streaming passthru commands: omit the subprocess timeout kwarg
# entirely so `docker logs -f`, `exec -it`, and `stats` (follow) never expire.
PASSTHRU_UNBOUNDED = float("inf")


def _env_timeout() -> float:
    raw = os.environ.get("COMPMAN_TIMEOUT")
    if raw is None:
        return 300.0
    try:
        value = float(raw)
    except ValueError:
        return 300.0
    if value <= 0:
        return 300.0
    return value
