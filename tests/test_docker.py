from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import time
from unittest.mock import MagicMock, call, patch

import pytest

from compman._proc import PASSTHRU_UNBOUNDED, _env_timeout
from compman.config import Config, ConfigError, Profile, SecretRef
from compman.docker import (
    ContainerRuntime,
    _check_cmd,
    _die,
    _merged_env,
    _parse_service_status,
    _passthru,
    _run,
    detect_runtime,
    resolve_compose_context,
    resolve_compose_files,
)


def test_resolve_compose_files(temp_dir: pathlib.Path):
    base_file = temp_dir / "base.yml"
    base_file.touch()
    dev_file = temp_dir / "dev.yml"
    dev_file.touch()

    cfg = Config(
        name="test",
        compose_base="base.yml",
        profiles={"dev": Profile(file="dev.yml", env={"ENV": "DEV"})},
    )
    files, env = resolve_compose_files(cfg, "dev")
    assert len(files) == 2
    assert env == {"ENV": "DEV"}

    # Unknown profile
    with pytest.raises(ConfigError):
        resolve_compose_files(cfg, "nonexistent")

    # Missing compose file
    cfg_missing_file = Config(
        name="test",
        profiles={"dev": Profile(file="nonexistent.yml")},
    )
    with pytest.raises(ConfigError):
        resolve_compose_files(cfg_missing_file, "dev")

    # Missing base compose file
    cfg_missing_base = Config(
        name="test",
        compose_base="nonexistent_base.yml",
        profiles={"dev": Profile(file="dev.yml")},
    )
    with pytest.raises(ConfigError):
        resolve_compose_files(cfg_missing_base, "dev")


@patch("compman.docker._check_cmd")
def test_detect_runtime_docker(mock_check):
    mock_check.side_effect = [(True, "Docker version 20.10.0")]
    rt = detect_runtime()
    assert isinstance(rt, ContainerRuntime)
    assert rt.name == "docker"


@patch("compman.docker._check_cmd")
def test_detect_runtime_podman(mock_check):
    mock_check.side_effect = [(False, ""), (True, "podman version 4.0.0")]
    rt = detect_runtime()
    assert isinstance(rt, ContainerRuntime)
    assert rt.name == "podman"


@patch("compman.docker._check_cmd")
def test_detect_runtime_podman_compose(mock_check):
    mock_check.side_effect = [(False, ""), (False, ""), (True, "podman-compose 1.0.0")]
    rt = detect_runtime()
    assert isinstance(rt, ContainerRuntime)
    assert rt.name == "podman"


@patch("compman.docker._check_cmd")
def test_detect_runtime_docker_compose(mock_check):
    mock_check.side_effect = [(False, ""), (False, ""), (False, ""), (True, "docker-compose 1.29.2")]
    rt = detect_runtime()
    assert isinstance(rt, ContainerRuntime)
    assert rt.name == "docker"


@patch("compman.docker._check_cmd")
def test_detect_runtime_none_found(mock_check):
    mock_check.return_value = (False, "")
    with pytest.raises(RuntimeError):
        detect_runtime()


@patch.dict(os.environ, {"CONTAINER_RUNTIME": "podman"})
@patch("compman.docker._check_cmd")
def test_detect_runtime_override(mock_check):
    mock_check.return_value = (False, "")
    with pytest.raises(RuntimeError):
        detect_runtime()


def test_die_and_merged_env():
    cp = subprocess.CompletedProcess(args=["docker"], returncode=1, stdout="out", stderr="err")
    with pytest.raises(RuntimeError):
        _die(["docker"], cp)

    env = _merged_env({"FOO": "BAR"})
    assert env["FOO"] == "BAR"


@patch("subprocess.run")
def test_passthru_and_run(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="my_proj\n")

    res = _run(["docker", "ps"])
    assert res.returncode == 0

    code = _passthru(["docker", "ps"])
    assert code == 0
    assert mock_run.call_args_list[0].kwargs["encoding"] == "utf-8"
    assert mock_run.call_args_list[0].kwargs["errors"] == "replace"


def test_run_replaces_invalid_utf8_output():
    result = _run([sys.executable, "-c", "import os; os.write(1, b'\\xe2')"])
    assert result.stdout == "\ufffd"


def test_check_cmd_uses_replacement_safe_utf8_decoding():
    completed = subprocess.CompletedProcess(["docker"], 0, "ok", "")
    with patch("subprocess.run", return_value=completed) as run:
        assert _check_cmd(["docker", "version"]) == (True, "ok")
    run.assert_called_once_with(
        ["docker", "version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )


@patch("subprocess.run", side_effect=FileNotFoundError)
def test_run_file_not_found(mock_run):
    with pytest.raises(RuntimeError):
        _run(["nonexistent_cmd"])

    with pytest.raises(RuntimeError):
        _passthru(["nonexistent_cmd"])


@patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="", stderr="failed"))
def test_passthru_failure_is_raised(mock_run):
    with pytest.raises(RuntimeError, match="Command failed"):
        _passthru(["docker", "compose", "up"])


@patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["docker", "compose", "up"], 3600))
def test_passthru_timeout_is_raised(mock_run):
    with pytest.raises(RuntimeError, match="timed out"):
        _passthru(["docker", "compose", "up"])


@patch("subprocess.run")
def test_passthru_resolves_bounded_timeout_from_env(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    with patch.dict(os.environ, {"COMPMAN_TIMEOUT": "42"}):
        _passthru(["docker", "ps"])

    assert mock_run.call_args.kwargs["timeout"] == 42.0


@patch("subprocess.run")
def test_passthru_explicit_timeout_overrides_env(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    with patch.dict(os.environ, {"COMPMAN_TIMEOUT": "42"}):
        _passthru(["docker", "ps"], timeout=7.5)

    assert mock_run.call_args.kwargs["timeout"] == 7.5


@patch("subprocess.run")
def test_passthru_unbounded_omits_timeout_kwarg(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    _passthru(["docker", "logs", "-f"], timeout=PASSTHRU_UNBOUNDED)

    assert "timeout" not in mock_run.call_args.kwargs


@patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["docker", "logs", "-f"], 42))
def test_passthru_timeout_message_interpolates_resolved_value(mock_run):
    with patch.dict(os.environ, {"COMPMAN_TIMEOUT": "42"}):
        with pytest.raises(RuntimeError, match=r"timed out after 42 seconds: docker logs -f"):
            _passthru(["docker", "logs", "-f"])


def test_logs_and_exec_shell_classify_streaming_timeouts():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    with patch.object(runtime, "passthru_cli", return_value=0) as passthru:
        runtime.logs("cid", follow=True)
        runtime.logs("cid", follow=False)
        runtime.exec_shell("cid")

    assert passthru.call_args_list[0].kwargs["timeout"] == PASSTHRU_UNBOUNDED
    assert passthru.call_args_list[1].kwargs["timeout"] is None
    assert passthru.call_args_list[2].kwargs["timeout"] == PASSTHRU_UNBOUNDED


def test_logs_and_exec_shell_pass_verbatim_argv():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    with patch.object(runtime, "passthru_cli", return_value=0) as passthru:
        runtime.logs("cid", follow=True)
        runtime.logs("cid", follow=False, tail=7)
        runtime.exec_shell("cid")

    assert passthru.call_args_list[0].args[0] == ["logs", "-f", "-n", "50", "cid"]
    assert passthru.call_args_list[1].args[0] == ["logs", "-n", "7", "cid"]
    assert passthru.call_args_list[2].args[0] == [
        "exec",
        "-it",
        "cid",
        "sh",
        "-c",
        "if command -v bash >/dev/null 2>&1; then exec bash; else exec sh; fi",
    ]


def test_fix_permissions_handles_failure_and_parse_branches():
    runtime = ContainerRuntime(name="docker", cli=["docker"], compose=["docker", "compose"])
    failed = MagicMock(returncode=1, stdout="")
    single = MagicMock(returncode=0, stdout="onlyone")
    pair = MagicMock(returncode=0, stdout="1000 1000")

    with patch.object(runtime, "run_cli", side_effect=[failed]) as run:
        runtime.fix_permissions("c", "/data")
        assert run.call_count == 1
        assert run.call_args.args[0] == ["exec", "c", "stat", "-c", "%U %G", "/data"]

    with patch.object(runtime, "run_cli", side_effect=[single]) as run:
        runtime.fix_permissions("c", "/data")
        assert run.call_count == 1
        assert run.call_args.args[0] == ["exec", "c", "stat", "-c", "%U %G", "/data"]

    with patch.object(runtime, "run_cli", side_effect=[pair, None]) as run:
        runtime.fix_permissions("c", "/data")
        assert run.call_count == 2
        assert run.call_args.args[0] == ["exec", "-u", "root", "c", "chown", "-R", "1000:1000", "/data"]


def test_container_runtime_methods():
    rt = ContainerRuntime(name="docker", cli=["docker"], compose=["docker", "compose"])

    with (
        patch.object(rt, "run_compose") as mock_compose,
        patch.object(rt, "run_cli") as mock_cli,
        patch.object(rt, "passthru_cli") as mock_passthru_cli,
        patch.object(rt, "passthru_compose") as mock_passthru_compose,
    ):
        mock_compose.return_value = MagicMock(returncode=0, stdout="container1\n")
        mock_cli.side_effect = [
            MagicMock(returncode=0, stdout="container1\n"),
            MagicMock(returncode=0, stdout="vol1\n"),
            MagicMock(returncode=0, stdout="cid123\n"),
        ]

        assert rt.stack_exists("container1")
        assert rt.list_containers("my_proj") == ["container1"]
        assert rt.list_volumes("my_proj") == ["vol1"]
        assert rt.get_container_id("my_proj", "my_stack") == "cid123"

        rt.passthru_cli(["ps"])
        rt.passthru_compose(["ps"], project="my_proj")
        mock_passthru_cli.assert_called_once_with(["ps"])
        mock_passthru_compose.assert_called_once_with(["ps"], project="my_proj")


@pytest.mark.parametrize(
    ("runtime_name", "cli", "compose"),
    [
        ("docker", ["docker"], ["docker", "compose"]),
        ("podman", ["podman"], ["podman", "compose"]),
        ("podman", ["podman"], ["podman-compose"]),
    ],
)
def test_stack_exists_uses_provider_independent_engine_query(runtime_name, cli, compose):
    runtime = ContainerRuntime(runtime_name, cli, compose)
    result = subprocess.CompletedProcess(cli + ["ps"], 0, "app-web-1\n", "")

    with (
        patch.object(runtime, "run_cli", return_value=result) as run_cli,
        patch.object(runtime, "run_compose") as run_compose,
    ):
        assert runtime.stack_exists("app", [pathlib.Path("compose.yml")], {"MODE": "test"})

    run_compose.assert_not_called()
    run_cli.assert_called_once_with(
        [
            "ps",
            "-a",
            "--filter",
            "label=com.docker.compose.project=app",
            "--format",
            "{{.Names}}",
        ],
        check=False,
    )


def test_stack_exists_rejects_failed_engine_query():
    runtime = ContainerRuntime("podman", ["podman"], ["podman-compose"])
    result = subprocess.CompletedProcess(["podman", "ps"], 125, "", "offline")

    with patch.object(runtime, "run_cli", return_value=result):
        with pytest.raises(RuntimeError, match="Command failed"):
            runtime.stack_exists("app")


def test_service_status_reads_compose_json(monkeypatch):
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    payload = (
        '[{"Service":"web","Name":"app-web-1","State":"running",'
        '"Status":"Up 5 seconds","Health":"healthy"}]'
    )
    with patch.object(
        runtime, "run_compose", return_value=subprocess.CompletedProcess([], 0, payload, "")
    ) as run:
        rows = runtime.service_status("app", [pathlib.Path("compose.yml")], {})

    assert rows[0]["service"] == "web"
    run.assert_called_once_with(
        ["ps", "-a", "--format", "json"],
        project="app",
        compose_files=[pathlib.Path("compose.yml")],
        env={},
        check=False,
    )


def test_service_status_normalizes_real_docker_compose_schema():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    payload = (
        '[{"Command":"nginx","ExitCode":0,"Health":"healthy",'
        '"Name":"app-web-1","Service":"web","State":"running"}]'
    )
    with patch.object(
        runtime, "run_compose", return_value=subprocess.CompletedProcess([], 0, payload, "")
    ):
        rows = runtime.service_status("app", [], {})

    assert rows == [
        {
            "service": "web",
            "container": "app-web-1",
            "state": "running",
            "status": "running (exit 0)",
            "health": "healthy",
        }
    ]


def test_service_status_normalizes_real_podman_schema():
    runtime = ContainerRuntime("podman", ["podman"], ["podman-compose"])
    payload = (
        '[{"ExitCode":0,"Labels":{"com.docker.compose.project":"app",'
        '"com.docker.compose.service":"worker"},"Names":["app-worker-1"],'
        '"State":"running","Status":"Up 5 minutes"}]'
    )
    with patch.object(
        runtime, "run_compose", return_value=subprocess.CompletedProcess([], 0, payload, "")
    ):
        rows = runtime.service_status("app", [], {})

    assert rows == [
        {
            "service": "worker",
            "container": "app-worker-1",
            "state": "running",
            "status": "Up 5 minutes",
            "health": None,
        }
    ]


def test_service_status_uses_exit_code_when_state_is_missing():
    runtime = ContainerRuntime("podman", ["podman"], ["podman-compose"])
    payload = '[{"ExitCode":125,"Names":["app-worker-1"]}]'
    with patch.object(
        runtime, "run_compose", return_value=subprocess.CompletedProcess([], 0, payload, "")
    ):
        rows = runtime.service_status("app", [], {})

    assert rows[0]["status"] == "exit 125"


def test_service_status_reads_newline_delimited_json():
    runtime = ContainerRuntime("podman", ["podman"], ["podman", "compose"])
    payload = '{"Service":"web","Name":"app-web-1"}\n{"Service":"db","Name":"app-db-1"}'
    with patch.object(
        runtime, "run_compose", return_value=subprocess.CompletedProcess([], 0, payload, "")):
        rows = runtime.service_status("app", [], {})

    assert rows == [
        {"service": "web", "container": "app-web-1", "state": "", "status": "", "health": None},
        {"service": "db", "container": "app-db-1", "state": "", "status": "", "health": None},
    ]


def test_service_status_reads_single_json_object():
    runtime = ContainerRuntime("podman", ["podman"], ["podman", "compose"])
    with patch.object(
        runtime, "run_compose", return_value=subprocess.CompletedProcess([], 0, '{"Service":"web"}', "")
    ):
        rows = runtime.service_status("app", [], {})

    assert rows == [{"service": "web", "container": "", "state": "", "status": "", "health": None}]


def test_service_status_returns_empty_for_blank_output():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    with patch.object(runtime, "run_compose", return_value=subprocess.CompletedProcess([], 0, "\n", "")):
        rows = runtime.service_status("app", [], {})

    assert rows == []


def test_parse_service_status_returns_empty_for_missing_output():
    assert _parse_service_status(None) == []


def test_service_status_rejects_invalid_json():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    with patch.object(runtime, "run_compose", return_value=subprocess.CompletedProcess([], 0, "bad json", "")):
        with pytest.raises(RuntimeError, match="Invalid service status JSON"):
            runtime.service_status("app", [], {})


def test_service_status_rejects_json_without_object_rows():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    with patch.object(runtime, "run_compose", return_value=subprocess.CompletedProcess([], 0, "[1]", "")):
        with pytest.raises(RuntimeError, match="Invalid service status JSON"):
            runtime.service_status("app", [], {})


def test_service_status_raises_on_failed_probe():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    result = subprocess.CompletedProcess(["docker", "compose"], 1, "", "failed")
    with patch.object(runtime, "run_compose", return_value=result):
        with pytest.raises(RuntimeError, match="Command failed"):
            runtime.service_status("app", [], {})


def test_ensure_ready_for_start_returns_when_docker_is_ready(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    confirm_start = MagicMock()

    with patch.object(runtime, "run_cli", return_value=subprocess.CompletedProcess([], 0)) as run_cli:
        runtime.ensure_ready_for_start(confirm_start)

    run_cli.assert_called_once_with(["info"], capture=True, check=False, timeout=5.0)
    confirm_start.assert_not_called()


def test_ensure_ready_for_start_skips_podman(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    runtime = ContainerRuntime("podman", ["podman"], ["podman", "compose"])
    confirm_start = MagicMock()

    with patch.object(runtime, "run_cli") as run_cli:
        runtime.ensure_ready_for_start(confirm_start)

    run_cli.assert_not_called()
    confirm_start.assert_not_called()


def test_ensure_ready_for_start_skips_non_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    confirm_start = MagicMock()

    with patch.object(runtime, "run_cli") as run_cli:
        runtime.ensure_ready_for_start(confirm_start)

    run_cli.assert_not_called()
    confirm_start.assert_not_called()


def test_ensure_ready_for_start_rejects_noninteractive_start(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    confirm_start = MagicMock()

    with (
        patch.object(runtime, "run_cli", return_value=subprocess.CompletedProcess([], 1)),
        patch.object(subprocess, "Popen") as popen,
    ):
        with pytest.raises(RuntimeError) as exc_info:
            runtime.ensure_ready_for_start(confirm_start)

    assert str(exc_info.value) == (
        "Docker Desktop is not ready and cannot be started from a non-interactive session. "
        "Start Docker Desktop manually and retry."
    )
    confirm_start.assert_not_called()
    popen.assert_not_called()


def test_ensure_ready_for_start_rejects_declined_start(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    confirm_start = MagicMock(return_value=False)

    with (
        patch.object(runtime, "run_cli", return_value=subprocess.CompletedProcess([], 1)),
        patch.object(subprocess, "Popen") as popen,
    ):
        with pytest.raises(RuntimeError) as exc_info:
            runtime.ensure_ready_for_start(confirm_start)

    assert str(exc_info.value) == (
        "Docker Desktop startup was declined. Start Docker Desktop manually and retry."
    )
    confirm_start.assert_called_once_with()
    popen.assert_not_called()


def test_ensure_ready_for_start_launches_desktop_and_waits_for_ready(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    confirm_start = MagicMock(return_value=True)
    desktop = r"C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe"

    with (
        patch.object(
            runtime,
            "run_cli",
            side_effect=[subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0)],
        ) as run_cli,
        patch.object(shutil, "which", return_value=desktop),
        patch.object(subprocess, "Popen") as popen,
        patch.object(time, "monotonic", side_effect=[0.0, 0.0, 1.0]),
        patch.object(time, "sleep") as sleep,
    ):
        runtime.ensure_ready_for_start(confirm_start)

    confirm_start.assert_called_once_with()
    popen.assert_called_once_with([desktop], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    sleep.assert_called_once_with(1.0)
    assert run_cli.call_count == 2


def test_ensure_ready_for_start_uses_program_files_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    desktop = tmp_path / "Docker" / "Docker" / "Docker Desktop.exe"
    desktop.parent.mkdir(parents=True)
    desktop.touch()
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])

    with (
        patch.object(
            runtime,
            "run_cli",
            side_effect=[subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0)],
        ),
        patch.object(shutil, "which", return_value=None),
        patch.object(subprocess, "Popen") as popen,
        patch.object(time, "monotonic", side_effect=[0.0, 0.0, 1.0]),
        patch.object(time, "sleep"),
    ):
        runtime.ensure_ready_for_start(lambda: True)

    popen.assert_called_once_with([str(desktop)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def test_ensure_ready_for_start_reports_missing_desktop_executable(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("ProgramFiles", raising=False)
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])

    with (
        patch.object(runtime, "run_cli", return_value=subprocess.CompletedProcess([], 1)),
        patch.object(shutil, "which", return_value=None),
        patch.object(subprocess, "Popen") as popen,
        pytest.raises(RuntimeError, match="executable"),
    ):
        runtime.ensure_ready_for_start(lambda: True)

    popen.assert_not_called()


def test_ensure_ready_for_start_reports_missing_program_files_executable(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])

    with (
        patch.object(runtime, "run_cli", return_value=subprocess.CompletedProcess([], 1)),
        patch.object(shutil, "which", return_value=None),
        patch.object(subprocess, "Popen") as popen,
        pytest.raises(RuntimeError, match="executable"),
    ):
        runtime.ensure_ready_for_start(lambda: True)

    popen.assert_not_called()


def test_ensure_ready_for_start_reports_desktop_launch_error(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])

    with (
        patch.object(runtime, "run_cli", return_value=subprocess.CompletedProcess([], 1)),
        patch.object(shutil, "which", return_value="Docker Desktop.exe"),
        patch.object(subprocess, "Popen", side_effect=OSError("blocked")),
        pytest.raises(RuntimeError, match="start Docker Desktop"),
    ):
        runtime.ensure_ready_for_start(lambda: True)


def test_ensure_ready_for_start_times_out_after_default_sixty_seconds(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    times = [0.0]
    for second in range(60):
        times.extend([float(second), float(second + 1)])

    with (
        patch.object(runtime, "run_cli", return_value=subprocess.CompletedProcess([], 1)) as run_cli,
        patch.object(shutil, "which", return_value="Docker Desktop.exe"),
        patch.object(subprocess, "Popen"),
        patch.object(time, "monotonic", side_effect=times),
        patch.object(time, "sleep") as sleep,
        pytest.raises(RuntimeError, match="within 60 seconds"),
    ):
        runtime.ensure_ready_for_start(lambda: True)

    assert sleep.call_count == 60
    assert sleep.call_args_list == [call(1.0)] * 60
    assert run_cli.call_count == 60


def test_docker_is_ready_returns_false_when_info_command_fails():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])

    with patch.object(runtime, "run_cli", side_effect=RuntimeError("docker unavailable")) as run_cli:
        assert not runtime._docker_is_ready()

    run_cli.assert_called_once_with(["info"], capture=True, check=False, timeout=5.0)


def test_docker_is_ready_treats_probe_timeout_as_not_ready():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    expired = subprocess.TimeoutExpired(["docker", "info"], 2.5)

    with patch.object(runtime, "run_cli", side_effect=expired) as run_cli:
        assert not runtime._docker_is_ready(2.5)

    run_cli.assert_called_once_with(["info"], capture=True, check=False, timeout=2.5)


def test_run_cli_applies_requested_timeout():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])

    with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
        runtime.run_cli(["info"], timeout=2.5)

    assert run.call_args.kwargs["timeout"] == 2.5


def test_run_cli_uses_default_field_timeout_when_unset():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])

    with patch("compman.docker._run", return_value=MagicMock(returncode=0)) as run:
        runtime.run_cli(["info"])

    assert run.call_args.kwargs["timeout"] == 300.0


def test_run_cli_uses_runtime_default_timeout_when_unset():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"], timeout=45.0)

    with patch("compman.docker._run", return_value=MagicMock(returncode=0)) as run:
        runtime.run_cli(["info"])

    assert run.call_args.kwargs["timeout"] == 45.0


def test_run_cli_explicit_timeout_overrides_runtime_default():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"], timeout=45.0)

    with patch("compman.docker._run", return_value=MagicMock(returncode=0)) as run:
        runtime.run_cli(["info"], timeout=7.5)

    assert run.call_args.kwargs["timeout"] == 7.5


def test_run_compose_uses_runtime_default_timeout_when_unset():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"], timeout=45.0)

    with patch("compman.docker._run", return_value=MagicMock(returncode=0)) as run:
        runtime.run_compose(["ps"])

    assert run.call_args.kwargs["timeout"] == 45.0


def test_run_compose_explicit_timeout_overrides_runtime_default():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"], timeout=45.0)

    with patch("compman.docker._run", return_value=MagicMock(returncode=0)) as run:
        runtime.run_compose(["ps"], timeout=7.5)

    assert run.call_args.kwargs["timeout"] == 7.5


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        (None, 300.0),
        ("42", 42.0),
        ("not-a-number", 300.0),
        ("0", 300.0),
    ],
)
def test_env_timeout_parses_env_value(env_value, expected):
    env = {} if env_value is None else {"COMPMAN_TIMEOUT": env_value}
    with patch.dict(os.environ, env, clear=True):
        assert _env_timeout() == expected


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        ("42", 42.0),
        ("oops", 300.0),
    ],
)
@patch("compman.docker._check_cmd")
def test_detect_runtime_applies_env_timeout(mock_check, env_value, expected):
    mock_check.return_value = (True, "Docker version 20.10.0")
    with patch.dict(os.environ, {"COMPMAN_TIMEOUT": env_value}, clear=True):
        rt = detect_runtime()
    assert rt.timeout == expected


def test_ensure_ready_for_start_caps_probes_at_remaining_deadline(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])

    with (
        patch.object(runtime, "run_cli", return_value=subprocess.CompletedProcess([], 1)) as run_cli,
        patch.object(shutil, "which", return_value="Docker Desktop.exe"),
        patch.object(subprocess, "Popen"),
        patch.object(time, "monotonic", side_effect=[0.0, 0.0, 1.0, 1.0, 2.0, 2.0, 2.5]),
        patch.object(time, "sleep") as sleep,
        pytest.raises(RuntimeError, match="within 2.5 seconds"),
    ):
        runtime.ensure_ready_for_start(lambda: True, timeout=2.5)

    assert sleep.call_args_list == [call(1.0), call(1.0), call(0.5)]
    assert run_cli.call_args_list == [
        call(["info"], capture=True, check=False, timeout=5.0),
        call(["info"], capture=True, check=False, timeout=1.5),
        call(["info"], capture=True, check=False, timeout=0.5),
    ]


def test_ensure_ready_for_start_skips_probe_when_sleep_reaches_deadline(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])

    with (
        patch.object(runtime, "run_cli", return_value=subprocess.CompletedProcess([], 1)) as run_cli,
        patch.object(shutil, "which", return_value="Docker Desktop.exe"),
        patch.object(subprocess, "Popen"),
        patch.object(time, "monotonic", side_effect=[0.0, 0.0, 2.5]),
        patch.object(time, "sleep") as sleep,
        pytest.raises(RuntimeError, match="within 2.5 seconds"),
    ):
        runtime.ensure_ready_for_start(lambda: True, timeout=2.5)

    sleep.assert_called_once_with(1.0)
    run_cli.assert_called_once_with(["info"], capture=True, check=False, timeout=5.0)


def test_ensure_ready_for_start_times_out_before_poll_when_no_time_remains(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])

    with (
        patch.object(runtime, "run_cli", return_value=subprocess.CompletedProcess([], 1)) as run_cli,
        patch.object(shutil, "which", return_value="Docker Desktop.exe"),
        patch.object(subprocess, "Popen"),
        patch.object(time, "monotonic", return_value=0.0),
        patch.object(time, "sleep") as sleep,
        pytest.raises(RuntimeError, match="within 0 seconds"),
    ):
        runtime.ensure_ready_for_start(lambda: True, timeout=0.0)

    sleep.assert_not_called()
    run_cli.assert_called_once_with(["info"], capture=True, check=False, timeout=5.0)


@patch("compman.env_source.resolve_secrets")
def test_resolve_compose_context_secrets_not_injected_without_markers(
    mock_resolve, temp_dir: pathlib.Path
):
    (temp_dir / "docker-compose.dev.yml").touch()
    cfg = Config(
        name="test",
        root_dir=temp_dir,
        source_path=temp_dir / "compman.yml",
        compose_base="docker-compose.dev.yml",
        profiles={"dev": Profile(file="docker-compose.dev.yml", env={"SHARED": "prof"})},
        secrets={"DB_URL": SecretRef(arn="arn:app", key="url")},
    )
    context = resolve_compose_context(cfg, "dev")
    assert context.env == {"SHARED": "prof"}
    mock_resolve.assert_not_called()


@patch("compman.env_source.resolve_secrets", return_value={"DB_URL": "sec"})
def test_resolve_compose_context_default_profile(mock_resolve, temp_dir: pathlib.Path):
    (temp_dir / "docker-compose.yml").touch()
    cfg = Config(
        name="test",
        root_dir=temp_dir,
        source_path=temp_dir / "compman.yml",
        profiles={
            "default": Profile(file="docker-compose.yml", env={"DATABASE_URL": "${secrets:DB_URL}"})
        },
        secrets={"DB_URL": SecretRef(arn="arn:app", key="url")},
    )
    context = resolve_compose_context(cfg)
    assert context.env == {"DATABASE_URL": "sec"}
    mock_resolve.assert_called_once_with(cfg.secrets)


@patch("compman.env_source.resolve_secrets", return_value={"DB_USER": "admin", "DB_PASS": "s3cret"})
def test_resolve_compose_context_interpolates_secrets_in_profile_env(
    mock_resolve, temp_dir: pathlib.Path
):
    (temp_dir / "docker-compose.dev.yml").touch()
    cfg = Config(
        name="test",
        root_dir=temp_dir,
        source_path=temp_dir / "compman.yml",
        compose_base="docker-compose.dev.yml",
        profiles={
            "dev": Profile(
                file="docker-compose.dev.yml",
                env={"DATABASE_URL": "postgres://${secrets:DB_USER}:${secrets:DB_PASS}@host"},
            )
        },
        secrets={"DB_USER": SecretRef(arn="arn:app", key="user"), "DB_PASS": SecretRef(arn="arn:app", key="pass")},
    )
    context = resolve_compose_context(cfg, "dev")
    assert context.env == {"DATABASE_URL": "postgres://admin:s3cret@host"}
    mock_resolve.assert_called_once_with(cfg.secrets)


@patch(
    "compman.env_source.resolve_secrets",
    return_value={"DB_USER": "common", "DB_PASS": "profile-pass"},
)
def test_resolve_compose_context_profile_secrets_override_common(
    mock_resolve, temp_dir: pathlib.Path
):
    (temp_dir / "docker-compose.dev.yml").touch()
    cfg = Config(
        name="test",
        root_dir=temp_dir,
        source_path=temp_dir / "compman.yml",
        profiles={
            "dev": Profile(
                file="docker-compose.dev.yml",
                env={"DATABASE_URL": "postgres://${secrets:DB_USER}:${secrets:DB_PASS}@host"},
                secrets={"DB_PASS": SecretRef(arn="arn:prof", key="pass")},
            )
        },
        secrets={"DB_USER": SecretRef(arn="arn:common", key="user"), "DB_PASS": SecretRef(arn="arn:common", key="pass")},
    )
    context = resolve_compose_context(cfg, "dev")
    assert context.env == {"DATABASE_URL": "postgres://common:profile-pass@host"}
    merged = {
        "DB_USER": cfg.secrets["DB_USER"],
        "DB_PASS": cfg.profiles["dev"].secrets["DB_PASS"],
    }
    mock_resolve.assert_called_once_with(merged)


# ---- folded from the retired coverage-sweep files ----


def test_check_cmd_treats_unlaunchable_commands_as_absent():
    with patch("subprocess.run", side_effect=[FileNotFoundError, subprocess.TimeoutExpired(["x"], 1)]):
        assert _check_cmd(["x"]) == (False, "")
        assert _check_cmd(["x"]) == (False, "")


def test_run_raises_runtime_error_on_nonzero_exit():
    with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="bad", stdout="out")):
        with pytest.raises(RuntimeError, match="Command failed"):
            _run(["bad"])


def test_detect_runtime_env_override_docker_skips_podman_candidates():
    with patch.dict("os.environ", {"CONTAINER_RUNTIME": "docker"}), patch(
        "compman.docker._check_cmd", side_effect=[(False, ""), (True, "ok")]
    ):
        assert detect_runtime().compose == ["docker-compose"]


def test_get_container_id_omits_project_filter_when_project_is_none():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    with patch.object(runtime, "run_cli", return_value=MagicMock(stdout="cid\n")) as run_cli:
        assert runtime.get_container_id("web") == "cid"

    command = run_cli.call_args.args[0]
    assert "com.docker.compose.project" not in " ".join(command)


def test_resolve_compose_context_rejects_unknown_profile():
    with pytest.raises(ConfigError, match="Unknown profile"):
        resolve_compose_context(Config(name="app", profiles={}), "dev")


def test_container_runtime_passthru_helpers_delegate_to_module_passthru():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])

    with patch("compman.docker._passthru", return_value=0) as passthru:
        assert runtime.passthru_compose(["ps"]) == 0
        assert runtime.passthru_cli(["ps"]) == 0

    assert passthru.call_count == 2
    assert passthru.call_args_list[0].args[0] == ["docker", "compose", "ps"]
    assert passthru.call_args_list[1].args[0] == ["docker", "ps"]


def test_container_runtime_convenience_methods_wire_expected_run_cli_argv(tmp_path):
    runtime = ContainerRuntime(name="docker", cli=["docker"], compose=["docker", "compose"])
    dest = tmp_path / "payload.tar"

    with patch.object(runtime, "run_cli") as run_cli:
        runtime.inspect_container("c")
        runtime.copy_from_container("c", "/src", dest)
        runtime.copy_to_container("/src", "c", "/dst")
        runtime.inspect_value("c", "{{.Name}}")
        runtime.commit_container("c", "tag")
        runtime.save_image("img", dest)
        runtime.remove_image("img")
        runtime.load_image(dest)

    argvs = [call_args.args[0] for call_args in run_cli.call_args_list]
    assert argvs == [
        ["inspect", "c"],
        ["cp", "c:/src", str(dest)],
        ["cp", "/src", "c:/dst"],
        ["inspect", "--format", "{{.Name}}", "c"],
        ["commit", "c", "tag"],
        ["save", "-o", str(dest), "img"],
        ["rmi", "img"],
        ["load", "-i", str(dest)],
    ]


def test_run_without_capture_omits_capture_kwargs():
    with patch("subprocess.run", return_value=MagicMock(returncode=0)) as run_mock:
        _run(["x"], capture=False, check=False)

    kwargs = run_mock.call_args.kwargs
    assert "capture_output" not in kwargs
    assert "encoding" not in kwargs


def test_die_message_omits_empty_stream_sections():
    with pytest.raises(RuntimeError) as excinfo:
        _die(["x"], subprocess.CompletedProcess([], 3, "", ""))

    assert str(excinfo.value) == "Command failed: x (exit=3)"
