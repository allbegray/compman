from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import pytest

from compman.config import Config, Profile
from compman.errors import CommandError
from compman.ops import service


def test_service_ops(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})

    service.start(dummy_runtime, cfg, ("web",))
    assert dummy_runtime.compose_runs[-1]["args"] == ["start", "web"]

    service.stop(dummy_runtime, cfg, ("web",))
    assert dummy_runtime.compose_runs[-1]["args"] == ["stop", "web"]

    service.restart(dummy_runtime, cfg, ("web",))
    assert dummy_runtime.compose_runs[-1]["args"] == ["restart", "web"]

    dummy_runtime.compose_stdout = "web-1\n"
    service.log(dummy_runtime, cfg, "web", follow=True, tail=100)
    assert dummy_runtime.compose_runs[-1]["args"] == ["ps", "-q", "web"]
    assert dummy_runtime.commands_run[-1] == ["logs", "-f", "-n", "100", "web-1"]

    service.status(dummy_runtime, cfg)
    assert dummy_runtime.compose_runs[-1]["args"] == ["ps", "-a"]

    service.connect(dummy_runtime, cfg, "web")
    assert dummy_runtime.compose_runs[-1]["args"] == ["ps", "-q", "web"]
    assert dummy_runtime.commands_run[-1] == ["exec", "-it", "web-1", "sh", "-c", "shell"]


def test_service_log_auto_select(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.list_containers = MagicMock(return_value=["single_container"])
    service.log(dummy_runtime, cfg, service=None)
    assert dummy_runtime.commands_run[-1] == ["logs", "-n", "50", "single_container"]


def test_service_log_multiple_containers(dummy_runtime, temp_dir: pathlib.Path, capsys):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.list_containers = MagicMock(return_value=["c1", "c2"])
    service.log(dummy_runtime, cfg, service=None)

    assert dummy_runtime.commands_run == []
    out = capsys.readouterr().out
    assert "Available containers:" in out
    assert "  c1" in out
    assert "  c2" in out


def test_service_log_no_containers(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.list_containers = MagicMock(return_value=[])
    with pytest.raises(CommandError):
        service.log(dummy_runtime, cfg, service=None)


def test_service_connect_auto_select(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.list_containers = MagicMock(return_value=["single_container"])
    service.connect(dummy_runtime, cfg, service=None)
    assert dummy_runtime.commands_run[-1] == ["exec", "-it", "single_container", "sh", "-c", "shell"]


def test_service_connect_service_not_running(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.compose_stdout = ""
    with pytest.raises(CommandError, match="No running containers found"):
        service.connect(dummy_runtime, cfg, service="app")


def test_service_log_resolves_service_name(dummy_runtime, temp_dir: pathlib.Path, capsys):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.compose_stdout = "web-1\n"
    service.log(dummy_runtime, cfg, "web", tail=10)
    assert dummy_runtime.compose_runs[-1]["args"] == ["ps", "-q", "web"]
    assert dummy_runtime.compose_runs[-1]["project"] == "my_stack"
    assert "Using container web-1 for service web." in capsys.readouterr().out
    assert dummy_runtime.commands_run[-1] == ["logs", "-n", "10", "web-1"]


def test_service_log_service_not_running(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.compose_stdout = ""
    with pytest.raises(CommandError, match="No running containers found"):
        service.log(dummy_runtime, cfg, "web")
    assert dummy_runtime.compose_runs[-1]["args"] == ["ps", "-q", "web"]


def test_service_log_service_scaled(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.compose_stdout = "web-1\nweb-2\n"
    with pytest.raises(CommandError, match="Service web has 2 running instances"):
        service.log(dummy_runtime, cfg, "web")
    assert dummy_runtime.compose_runs[-1]["args"] == ["ps", "-q", "web"]


def test_service_start_stop_restart_no_resolution(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    service.start(dummy_runtime, cfg, ("web",))
    service.stop(dummy_runtime, cfg, ("web",))
    service.restart(dummy_runtime, cfg, ("web",))
    assert [run["args"] for run in dummy_runtime.compose_runs] == [
        ["start", "web"],
        ["stop", "web"],
        ["restart", "web"],
    ]


def test_service_connect_without_containers_raises_command_error(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.list_containers = MagicMock(return_value=[])

    with pytest.raises(CommandError):
        service.connect(dummy_runtime, cfg, service=None)


def test_service_connect_with_multiple_containers_lists_them_without_connecting(
    dummy_runtime, temp_dir: pathlib.Path, capsys
):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.list_containers = MagicMock(return_value=["a", "b"])

    service.connect(dummy_runtime, cfg, service=None)

    out = capsys.readouterr().out
    assert "Specify a container name:" in out
    assert "  a" in out and "  b" in out
    assert dummy_runtime.commands_run == []


def test_service_connect_scaled_service_raises_ambiguous_error(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.compose_stdout = "web-1\nweb-2\n"

    with pytest.raises(CommandError, match="Service web has 2 running instances"):
        service.connect(dummy_runtime, cfg, "web")
    assert dummy_runtime.compose_runs[-1]["args"] == ["ps", "-q", "web"]
