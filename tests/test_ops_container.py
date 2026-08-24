from __future__ import annotations

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
