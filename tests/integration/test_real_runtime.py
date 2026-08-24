"""Integration seam against a real container runtime.

These tests are marked ``integration`` and deselected by default through the
``-m 'not integration'`` addopt; run them explicitly with::

    uv run pytest -m integration

CI runs that same selector after its Docker-dependent services are up.
Skips (no docker CLI / unreachable daemon) are acceptable outcomes.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import uuid

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not available"),
]

STACK_TEMPLATE = """\
compman:
  name: {stack}
  compose:
    default:
      file: docker-compose.yml
"""

COMPOSE_TEMPLATE = """\
services:
  box:
    image: busybox:latest
    command: sleep infinity
    volumes:
      - data:/data
volumes:
  data:
"""


def _compman(args: list[str], cwd: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "compman", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=True,
    )


def _docker(args: list[str], cwd: pathlib.Path | None = None) -> str:
    result = subprocess.run(
        ["docker", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=True,
    )
    return result.stdout


@pytest.fixture(scope="module")
def docker_daemon() -> None:
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"docker daemon not reachable: {exc}")


def _write_project(tmp_path: pathlib.Path, stack: str) -> None:
    (tmp_path / "compman.yml").write_text(STACK_TEMPLATE.format(stack=stack), encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text(COMPOSE_TEMPLATE, encoding="utf-8")


def test_volume_backup_restore_roundtrip_with_busybox_named_volume(
    tmp_path: pathlib.Path, docker_daemon: None
):
    stack = f"compman-it-{uuid.uuid4().hex[:8]}"
    marker = f"roundtrip-{uuid.uuid4().hex[:12]}"
    _write_project(tmp_path, stack)

    try:
        _compman(["stack", "up"], tmp_path)
        _docker(["compose", "-p", stack, "exec", "-T", "box", "sh", "-c", f"echo {marker} > /data/marker.txt"], tmp_path)

        _compman(["volume", "backup"], tmp_path)
        backups = sorted(tmp_path.rglob("*.volume.*.tar.gz"))
        assert backups, "volume backup produced no archive"
        timestamp = backups[-1].stem.split(".", 2)[2]

        _compman(["stack", "down", "--yes"], tmp_path)
        _docker(["volume", "rm", "-f", f"{stack}_data"])

        _compman(["volume", "restore", timestamp], tmp_path)
        _compman(["stack", "up"], tmp_path)
        restored = _docker(
            ["compose", "-p", stack, "exec", "-T", "box", "cat", "/data/marker.txt"], tmp_path
        )
        assert restored.strip() == marker
    finally:
        subprocess.run(
            ["docker", "compose", "-p", stack, "down", "--volumes", "--timeout", "1"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )


def test_doctor_json_reports_runtime_ok(tmp_path: pathlib.Path, docker_daemon: None):
    _write_project(tmp_path, "compman-it-doctor")

    result = _compman(["doctor", "--json"], tmp_path)
    payload = json.loads(result.stdout)

    assert payload["schema_version"] == 1
    checks = {check["id"]: check for check in payload["checks"]}
    assert checks["runtime"]["ok"] is True
    assert checks["runtime_connection"]["ok"] is True
