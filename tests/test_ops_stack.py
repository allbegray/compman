from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest
from conftest import write_config
from typer.testing import CliRunner

from compman.cli import app
from compman.config import Config, Profile
from compman.ops import stack
from compman.ops.common import ensure_runtime_ready


def test_ensure_runtime_ready_prompts_to_start_docker_desktop(dummy_runtime):
    dummy_runtime.ensure_ready_for_start = MagicMock()

    with patch("compman.ops.common.typer.confirm", return_value=False) as confirm:
        ensure_runtime_ready(dummy_runtime)
        confirm_start = dummy_runtime.ensure_ready_for_start.call_args.args[0]
        assert confirm_start() is False

    dummy_runtime.ensure_ready_for_start.assert_called_once()
    confirm.assert_called_once_with(
        "Docker Desktop is not running. Start it now?", default=True, abort=False
    )


def test_stack_up_checks_readiness_immediately_before_compose(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "docker-compose.yml").touch()
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    calls: list[str] = []
    original_passthru = dummy_runtime.passthru_compose

    def passthru(*args, **kwargs):
        calls.append("compose")
        return original_passthru(*args, **kwargs)

    dummy_runtime.ensure_ready_for_start = MagicMock(side_effect=lambda callback: calls.append("ready"))
    dummy_runtime.passthru_compose = MagicMock(side_effect=passthru)

    stack.up(dummy_runtime, cfg)

    assert calls == ["ready", "compose"]
    dummy_runtime.ensure_ready_for_start.assert_called_once()
    dummy_runtime.passthru_compose.assert_called_once()
    assert len(dummy_runtime.compose_runs) == 1
    assert dummy_runtime.compose_runs[0]["args"] == ["up", "-d", "--force-recreate"]


def test_stack_update_checks_readiness_immediately_before_compose(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "docker-compose.yml").touch()
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    calls: list[str] = []
    original_passthru = dummy_runtime.passthru_compose

    def passthru(*args, **kwargs):
        calls.append("compose")
        return original_passthru(*args, **kwargs)

    dummy_runtime.ensure_ready_for_start = MagicMock(side_effect=lambda callback: calls.append("ready"))
    dummy_runtime.passthru_compose = MagicMock(side_effect=passthru)

    stack.update(dummy_runtime, cfg)

    assert calls == ["ready", "compose"]
    dummy_runtime.ensure_ready_for_start.assert_called_once()
    dummy_runtime.passthru_compose.assert_called_once()
    assert len(dummy_runtime.compose_runs) == 1
    assert dummy_runtime.compose_runs[0]["args"] == ["up", "-d", "--build", "--force-recreate"]


def test_stack_up_simple(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "docker-compose.yml").touch()
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    stack.up(dummy_runtime, cfg)
    assert len(dummy_runtime.compose_runs) == 1
    assert dummy_runtime.compose_runs[0]["args"] == ["up", "-d", "--force-recreate"]


def test_stack_up_profiles(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "docker-compose.dev.yml").touch()
    cfg = Config(
        name="my_stack",
        profiles={"dev": Profile(file="docker-compose.dev.yml")},
    )
    stack.up(dummy_runtime, cfg, profile="dev")
    assert len(dummy_runtime.compose_runs) == 1
    assert dummy_runtime.compose_runs[0]["args"] == ["up", "-d", "--force-recreate"]


def test_stack_profile_context(dummy_runtime, temp_dir: pathlib.Path):
    cfg = Config(
        name="my_stack",
        profiles={"dev": Profile(file="docker-compose.dev.yml", env={"MODE": "dev"})},
    )
    stack.up(dummy_runtime, cfg, profile="dev")
    run = dummy_runtime.compose_runs[0]
    assert run["compose_files"] == (temp_dir / "docker-compose.dev.yml",)
    assert run["env"] == {"MODE": "dev"}


def test_stack_up_profiles_default(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "docker-compose.dev.yml").touch()
    cfg = Config(
        name="my_stack",
        profiles={"dev": Profile(file="docker-compose.dev.yml")},
    )
    stack.up(dummy_runtime, cfg, profile=None)
    assert len(dummy_runtime.compose_runs) == 1


def test_stack_down(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "docker-compose.yml").touch()
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.ensure_ready_for_start = MagicMock()
    stack.down(dummy_runtime, cfg)
    assert len(dummy_runtime.compose_runs) == 1
    assert dummy_runtime.compose_runs[0]["args"] == ["down"]
    dummy_runtime.ensure_ready_for_start.assert_not_called()


def test_stack_down_not_running(dummy_runtime, temp_dir: pathlib.Path):
    dummy_runtime.ensure_ready_for_start = MagicMock()
    dummy_runtime.stack_exists = MagicMock(return_value=False)
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    stack.down(dummy_runtime, cfg)
    assert len(dummy_runtime.compose_runs) == 0
    dummy_runtime.ensure_ready_for_start.assert_not_called()


def test_stack_update_simple(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "docker-compose.yml").touch()
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    stack.update(dummy_runtime, cfg)
    assert len(dummy_runtime.compose_runs) == 1
    assert dummy_runtime.compose_runs[0]["args"] == ["up", "-d", "--build", "--force-recreate"]


def test_stack_update_profiles(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "docker-compose.dev.yml").touch()
    cfg = Config(
        name="my_stack",
        profiles={"dev": Profile(file="docker-compose.dev.yml")},
    )
    stack.update(dummy_runtime, cfg, profile="dev")
    assert len(dummy_runtime.compose_runs) == 1
    assert dummy_runtime.compose_runs[0]["args"] == ["up", "-d", "--build", "--force-recreate"]


def test_stack_update_profiles_default(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "docker-compose.dev.yml").touch()
    cfg = Config(
        name="my_stack",
        profiles={"dev": Profile(file="docker-compose.dev.yml")},
    )
    stack.update(dummy_runtime, cfg, profile=None)
    assert len(dummy_runtime.compose_runs) == 1


# ---- --wait readiness gate ----

import json  # noqa: E402

from compman.errors import CommandError  # noqa: E402


class _Proc:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def _ps_runner(pages: list[str]):
    pages_iter = iter(pages)

    def run_compose(args, **kwargs):
        if args[:2] == ["ps", "--format"]:
            return _Proc(next(pages_iter, "{}"))
        return MagicMock()

    return run_compose


def test_parse_compose_ps_handles_array_lines_and_garbage():
    from compman.ops.common import parse_compose_ps as _parse_compose_ps

    assert _parse_compose_ps("") == []
    arr = '[{"Service":"a","State":"running"},{"Service":"b"}]'
    assert len(_parse_compose_ps(arr)) == 2
    broken_array = '[{"Service":"a"}'
    assert _parse_compose_ps(broken_array) == []
    mixed = '\n{"Service":"a","State":"running"}\nnot-json\n\n{"Name":"c"}\n'
    parsed = _parse_compose_ps(mixed)
    assert len(parsed) == 2 and parsed[1]["Name"] == "c"


def test_service_readiness_casing_and_health_rules():
    from compman.ops.stack import _service_readiness

    assert _service_readiness({"Service": "web", "State": "running", "Health": ""}) == ("web", True)
    assert _service_readiness({"Service": "db", "State": "running", "Health": "healthy"}) == ("db", True)
    name, ok = _service_readiness({"service": "db", "state": "running", "health": "none"})
    assert ok is True and name == "?"
    name, ok = _service_readiness({"State": "exited", "Health": ""})
    assert ok is False and name == "?"
    _, ok2 = _service_readiness({"Service": "api", "state": "running", "Health": "starting"})
    assert ok2 is False


def test_unready_detail_lists_only_not_ready():
    from compman.ops.stack import _unready_detail

    entries = [
        {"Service": "ok", "State": "running", "Health": ""},
        {"Service": "bad", "State": "restarting", "Health": "unhealthy"},
    ]
    assert _unready_detail(entries) == "bad(restarting/unhealthy)"
    assert _unready_detail([]) == ""


def test_wait_until_ready_returns_when_all_ready(dummy_runtime, temp_dir, monkeypatch):
    (temp_dir / "docker-compose.yml").touch()
    cfg = Config(name="app", profiles={"default": Profile(file="docker-compose.yml")})
    ready = json.dumps([{"Service": "box", "State": "running", "Health": ""}])
    dummy_runtime.run_compose = MagicMock(return_value=_Proc(ready))
    monkeypatch.setattr(stack.time, "sleep", lambda s: None)
    context = stack.resolve_compose_context(cfg, None)
    stack._wait_until_ready(dummy_runtime, context)


def test_wait_until_ready_times_out_with_detail(dummy_runtime, temp_dir, monkeypatch):
    (temp_dir / "docker-compose.yml").touch()
    cfg = Config(name="app", profiles={"default": Profile(file="docker-compose.yml")})
    exited = json.dumps([{"Service": "box", "State": "exited", "Health": ""}])
    dummy_runtime.run_compose = MagicMock(return_value=_Proc(exited))
    clock = iter([0.0, 0.0, 10_000.0])
    monkeypatch.setattr(stack.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(stack.time, "sleep", lambda s: None)
    context = stack.resolve_compose_context(cfg, None)
    with pytest.raises(CommandError) as err:
        stack._wait_until_ready(dummy_runtime, context)
    assert "300s" in str(err.value) and "box(exited/-)" in str(err.value)


def test_stack_up_without_wait_never_polls_ps(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "docker-compose.yml").touch()
    cfg = Config(name="app", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.ensure_ready_for_start = MagicMock()
    stack.up(dummy_runtime, cfg)
    assert all(run["args"] != ["ps", "--format", "json"] for run in dummy_runtime.compose_runs)


def test_stack_update_with_wait_polls_until_ready(
    dummy_runtime, temp_dir: pathlib.Path, monkeypatch
):
    (temp_dir / "docker-compose.yml").touch()
    cfg = Config(name="app", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.ensure_ready_for_start = MagicMock()
    starting = json.dumps([{"Service": "box", "State": "created", "Health": ""}])
    ready = json.dumps([{"Service": "box", "State": "running", "Health": ""}])
    pages = iter([starting, ready])
    ps_calls: list[int] = []

    def run_compose(args, **kwargs):
        if args[:2] == ["ps", "--format"]:
            ps_calls.append(len(ps_calls))
            return _Proc(next(pages))
        return MagicMock()

    dummy_runtime.run_compose = run_compose
    sleeps: list[float] = []
    monkeypatch.setattr(stack.time, "sleep", lambda s: sleeps.append(s))
    stack.update(dummy_runtime, cfg, wait=True)
    assert sleeps == [1.0]
    assert len(ps_calls) == 2


def test_cli_stack_up_passes_wait_flag(runner: CliRunner, dummy_runtime, temp_dir: pathlib.Path):
    write_config(temp_dir / "compman.yml")
    with patch("compman.cli.detect_runtime", return_value=dummy_runtime), patch(
        "compman.cli._stack_ops"
    ) as ops:
        res = runner.invoke(app, ["stack", "up", "--wait"])
        assert res.exit_code == 0
    ops.return_value.up.assert_called_once()
    assert ops.return_value.up.call_args.kwargs["wait"] is True


def test_cli_stack_update_passes_wait_flag(runner: CliRunner, dummy_runtime, temp_dir: pathlib.Path):
    write_config(temp_dir / "compman.yml")
    with patch("compman.cli.detect_runtime", return_value=dummy_runtime), patch(
        "compman.cli._stack_ops"
    ) as ops:
        res = runner.invoke(app, ["stack", "update", "--wait"])
        assert res.exit_code == 0
    ops.return_value.update.assert_called_once()
    assert ops.return_value.update.call_args.kwargs["wait"] is True
