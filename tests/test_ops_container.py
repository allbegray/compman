from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from compman.config import Config, Profile
from compman.i18n import set_lang
from compman.ops import container


@pytest.fixture
def config(temp_dir):
    (temp_dir / "docker-compose.yml").touch()
    return Config(
        name="my_stack",
        root_dir=temp_dir,
        profiles={"default": Profile(file="docker-compose.yml")},
    )


def test_ps_uses_selected_compose_project(dummy_runtime, config):
    container.ps(dummy_runtime, config)

    run = dummy_runtime.compose_runs[-1]
    assert run["args"] == ["ps"]
    assert run["project"] == "my_stack"
    assert run["compose_files"] == (config.root_dir / "docker-compose.yml",)


def test_ps_all_includes_stopped_containers(dummy_runtime, config):
    container.ps(dummy_runtime, config, all_containers=True)

    assert dummy_runtime.compose_runs[-1]["args"] == ["ps", "--all"]


def test_stats_resolves_project_ids_then_prints_snapshot(dummy_runtime, config):
    dummy_runtime.compose_stdout = "cid-one\ncid-two\n"

    container.stats(dummy_runtime, config)

    assert dummy_runtime.compose_runs[-1]["args"] == ["ps", "--quiet"]
    assert dummy_runtime.commands_run[-1] == [
        "stats",
        "--no-stream",
        "cid-one",
        "cid-two",
    ]


def test_stats_follow_streams_continuously(dummy_runtime, config):
    dummy_runtime.compose_stdout = "cid-one\n"

    container.stats(dummy_runtime, config, follow=True)

    assert dummy_runtime.commands_run[-1] == ["stats", "cid-one"]


def test_stats_timeout_follows_streaming_classification(dummy_runtime, config):
    from compman._proc import PASSTHRU_UNBOUNDED

    dummy_runtime.compose_stdout = "cid-one\n"
    timeouts: list[float | None] = []
    original_passthru = dummy_runtime.passthru_cli

    def record_timeout(*args, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        return original_passthru(*args, **kwargs)

    with patch.object(dummy_runtime, "passthru_cli", side_effect=record_timeout):
        container.stats(dummy_runtime, config, follow=True)
        container.stats(dummy_runtime, config)

    assert timeouts == [PASSTHRU_UNBOUNDED, None]


def test_stats_empty_project_does_not_run_global_stats(dummy_runtime, config, capsys):
    set_lang("en")
    dummy_runtime.compose_stdout = "\n"
    before = list(dummy_runtime.commands_run)

    container.stats(dummy_runtime, config)

    assert dummy_runtime.commands_run == before
    assert "No running containers" in capsys.readouterr().out


# ---- --json output ----

class _Proc:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def _json_runtime(ps_stdout: str = "", stats_stdout: str | None = None, quiet_ids: str = "abc123\n"):
    from unittest.mock import MagicMock

    runtime = MagicMock()
    calls: list[list[str]] = []

    def run_compose(args, **kwargs):
        calls.append(list(args))
        if args[:2] == ["ps", "--quiet"]:
            return _Proc(quiet_ids)
        if args[:2] == ["ps", "--format"]:
            return _Proc(ps_stdout)
        if args[:2] == ["stats", "--format"]:
            return _Proc(stats_stdout or "[]")
        raise AssertionError(f"unexpected compose call {args}")

    runtime.run_compose = run_compose
    runtime.calls = calls
    return runtime


def test_ps_json_outputs_schema_payload(config, capsys):
    entries = [{"Service": "web", "State": "running", "Publishers": []}]
    runtime = _json_runtime(ps_stdout=json.dumps(entries))
    container.ps(runtime, config, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["generated_at"].endswith("+00:00")
    assert payload["stack"] == "my_stack"
    assert payload["containers"] == entries
    assert runtime.calls[0] == ["ps", "--format", "json"]


def test_ps_json_all_flag_appends_all(config, capsys):
    runtime = _json_runtime(ps_stdout="[]")
    container.ps(runtime, config, all_containers=True, json_output=True)
    assert runtime.calls[0] == ["ps", "--format", "json", "--all"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["containers"] == []


def test_ps_json_garbage_becomes_empty_containers(config, capsys):
    runtime = _json_runtime(ps_stdout="not-json")
    container.ps(runtime, config, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["containers"] == []


def test_stats_json_without_running_containers(config, capsys):
    runtime = _json_runtime(quiet_ids="")
    container.stats(runtime, config, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["stats"] == []
    assert payload["schema_version"] == 1


def test_stats_json_array_format(config, capsys):
    stats_entries = [{"Name": "web", "CPUPerc": "0.01%"}]
    runtime = _json_runtime(stats_stdout=json.dumps(stats_entries))
    container.stats(runtime, config, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["stats"] == stats_entries


def test_stats_json_lines_format_skips_garbage(config, capsys):
    lines = '{"Name":"web","CPUPerc":"1%"}\ngarbage\n'
    runtime = _json_runtime(stats_stdout=lines)
    container.stats(runtime, config, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["stats"]) == 1
    assert payload["stats"][0]["Name"] == "web"


def test_stats_follow_with_json_errors(config):
    runtime = _json_runtime(ps_stdout="", stats_stdout="[]")
    with pytest.raises(CommandError) as err:
        container.stats(runtime, config, follow=True, json_output=True)
    assert "--follow" in str(err.value)


from compman.errors import CommandError  # noqa: E402


def test_stats_json_broken_array_yields_empty_entries(config, capsys):
    runtime = _json_runtime(stats_stdout="[{'Name': 'web'}")
    container.stats(runtime, config, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["stats"] == []


def test_stats_json_lines_skips_blank_and_non_dict(config, capsys):
    runtime = _json_runtime(stats_stdout='{"Name":"web"}\n\n123\n')
    container.stats(runtime, config, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["stats"]) == 1
