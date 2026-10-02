from __future__ import annotations

import json
import os
import pathlib
import socket
from unittest.mock import MagicMock, patch

import pytest
from conftest import write_config
from typer.testing import CliRunner

from compman.cli import app
from compman.config import Config, Profile, SlackNotify
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


def test_stack_up_with_wait_polls_until_ready(
    dummy_runtime, temp_dir: pathlib.Path, monkeypatch
):
    (temp_dir / "docker-compose.yml").touch()
    cfg = Config(name="app", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.ensure_ready_for_start = MagicMock()
    ready = json.dumps([{"Service": "box", "State": "running", "Health": ""}])
    ps_calls: list[int] = []

    def run_compose(args, **kwargs):
        if args[:2] == ["ps", "--format"]:
            ps_calls.append(len(ps_calls))
            return _Proc(ready)
        return MagicMock()

    dummy_runtime.run_compose = run_compose
    monkeypatch.setattr(stack.time, "sleep", lambda s: None)
    stack.up(dummy_runtime, cfg, wait=True)
    assert len(ps_calls) == 1


# ---- stack logs passthru argv matrix ----

def _stack_logs(dummy_runtime, temp_dir: pathlib.Path, **kwargs) -> dict:
    (temp_dir / "docker-compose.yml").touch()
    cfg = Config(name="my_stack", profiles={"default": Profile(file="docker-compose.yml")})
    stack.logs(dummy_runtime, cfg, **kwargs)
    return dummy_runtime.compose_runs[0]


def test_stack_logs_default_passthru(dummy_runtime, temp_dir: pathlib.Path):
    run = _stack_logs(dummy_runtime, temp_dir)
    assert run["args"] == ["logs"]
    assert run["project"] == "my_stack"
    assert run["compose_files"] == (temp_dir / "docker-compose.yml",)


def test_stack_logs_tail_flag(dummy_runtime, temp_dir: pathlib.Path):
    run = _stack_logs(dummy_runtime, temp_dir, tail=100)
    assert run["args"] == ["logs", "--tail", "100"]


def test_stack_logs_follow_flag(dummy_runtime, temp_dir: pathlib.Path):
    run = _stack_logs(dummy_runtime, temp_dir, follow=True)
    assert run["args"] == ["logs", "-f"]


def test_stack_logs_services_filter(dummy_runtime, temp_dir: pathlib.Path):
    run = _stack_logs(dummy_runtime, temp_dir, services=("web", "db"))
    assert run["args"] == ["logs", "web", "db"]


def test_stack_logs_all_flags_combined(dummy_runtime, temp_dir: pathlib.Path):
    run = _stack_logs(
        dummy_runtime, temp_dir, services=("web",), follow=True, tail=50
    )
    assert run["args"] == ["logs", "--tail", "50", "-f", "web"]


def test_stack_logs_profile_context(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "docker-compose.dev.yml").touch()
    cfg = Config(
        name="my_stack",
        profiles={"dev": Profile(file="docker-compose.dev.yml", env={"MODE": "dev"})},
    )
    stack.logs(dummy_runtime, cfg, profile="dev")
    run = dummy_runtime.compose_runs[0]
    assert run["env"] == {"MODE": "dev"}
    assert run["compose_files"] == (temp_dir / "docker-compose.dev.yml",)


# ---- Slack notifications on up / update ----

WEBHOOK = "https://hooks.slack.com/services/T000/B000/XXXX"
GREEN = "\U0001f7e2"
RED = "\U0001f534"


def _notified_stack(
    dummy_runtime,
    temp_dir,
    *,
    event,
    profile=None,
    notify_slack=None,
    wait=False,
    services=({"Service": "app", "State": "running"},),
):
    """Run up/update with a webhook configured and return the sent payloads."""
    if notify_slack is None:
        notify_slack = SlackNotify(webhook_env="MY_SLACK_HOOK")
    cfg = Config(
        name="my_stack",
        profiles={
            "default": Profile(file="docker-compose.yml"),
            "dev": Profile(file="docker-compose.yml"),
        },
        notify_slack=notify_slack,
    )
    dummy_runtime.ensure_ready_for_start = MagicMock()
    dummy_runtime.compose_stdout = json.dumps(list(services))
    sent: list[dict] = []

    def fake_post(url, payload, timeout=0.0):
        sent.append(payload)
        return None

    with patch.dict(os.environ, {"MY_SLACK_HOOK": WEBHOOK}), patch(
        "compman.notify.post", side_effect=fake_post
    ):
        if event == "up":
            stack.up(dummy_runtime, cfg, profile=profile, wait=wait)
        else:
            stack.update(dummy_runtime, cfg, profile=profile, wait=wait)
    return sent


def _header(payload: dict) -> str:
    return payload["blocks"][0]["text"]["text"]


def _details_body(payload: dict) -> str:
    return payload["blocks"][1]["text"]["text"]


def _block_types(payload: dict) -> list[str]:
    return [block["type"] for block in payload["blocks"]]


def _services_body(payload: dict) -> str:
    return payload["blocks"][2]["text"]["text"]


def _volumes_body(payload: dict) -> str:
    blocks = payload["blocks"]
    return blocks[blocks.index({"type": "divider"}) + 1]["text"]["text"]


def test_stack_up_notifies_slack_with_full_context(dummy_runtime, temp_dir: pathlib.Path):
    sent = _notified_stack(dummy_runtime, temp_dir, event="up")
    assert len(sent) == 1
    payload = sent[0]

    assert payload["text"] == "✅ my_stack (default) — Stack started · 1 of 1 services healthy"
    assert _header(payload) == "✅ Stack started"

    details = _details_body(payload)
    assert details.splitlines()[0] == "*Stack* `my_stack`  ·  *Profile* `default`"
    assert details.splitlines()[1] == f"*Runtime* `docker`  ·  *Host* `{socket.gethostname()}`"
    assert details.splitlines()[2].startswith("*Started at* ")
    assert details.splitlines()[2].endswith("  ·  *Duration* 0ms")

    # Service health comes from the post-start `compose ps --all` query, which
    # keeps an immediately-exited container visible instead of dropping it.
    assert _services_body(payload) == "*Services* — 1 of 1 healthy"
    assert dummy_runtime.compose_runs[-1]["args"] == ["ps", "--all", "--format", "json"]

    assert payload["blocks"][-1]["elements"][0]["text"].endswith("· `stack up`")


def test_stack_update_notifies_slack(dummy_runtime, temp_dir: pathlib.Path):
    sent = _notified_stack(dummy_runtime, temp_dir, event="update")
    assert _header(sent[0]) == "✅ Stack updated"
    assert sent[0]["blocks"][-1]["elements"][0]["text"].endswith("· `stack update`")


def test_notify_reports_the_explicit_profile(dummy_runtime, temp_dir: pathlib.Path):
    sent = _notified_stack(dummy_runtime, temp_dir, event="up", profile="dev")
    assert _details_body(sent[0]).startswith("*Stack* `my_stack`  ·  *Profile* `dev`")


def test_notify_uses_the_literal_webhook_without_environment_lookup(
    dummy_runtime, temp_dir: pathlib.Path
):
    sent = _notified_stack(
        dummy_runtime,
        temp_dir,
        event="up",
        notify_slack=SlackNotify(webhook=WEBHOOK),
    )
    assert len(sent) == 1


def test_notify_details_only_the_service_that_failed(
    dummy_runtime, temp_dir: pathlib.Path
):
    sent = _notified_stack(
        dummy_runtime,
        temp_dir,
        event="up",
        services=(
            {
                "Service": "web",
                "State": "running",
                "Image": "nginx:alpine",
                "Publishers": [
                    {"TargetPort": 80, "PublishedPort": 18080, "Protocol": "tcp"},
                    {"TargetPort": 80, "PublishedPort": 18080, "Protocol": "tcp"},
                ],
            },
            {"Service": "db", "State": "exited", "ExitCode": 3, "Image": "postgres:17"},
        ),
    )
    payload = sent[0]
    assert _header(payload) == "⚠️ Stack started — 1 service(s) need attention"
    assert _services_body(payload) == (
        "*Services* — 1 of 2 healthy\n"
        f"{RED} `db` · exited · exit 3 — postgres:17"
    )


def test_notify_deduplicates_ipv4_and_ipv6_publishers(
    dummy_runtime, temp_dir: pathlib.Path
):
    sent = _notified_stack(
        dummy_runtime,
        temp_dir,
        event="up",
        services=(
            {
                "Service": "web",
                "State": "running",
                "Health": "unhealthy",
                "Image": "nginx:alpine",
                "Publishers": [
                    {"URL": "0.0.0.0", "TargetPort": 80, "PublishedPort": 18080, "Protocol": "tcp"},
                    {"URL": "::", "TargetPort": 80, "PublishedPort": 18080, "Protocol": "tcp"},
                    {"TargetPort": 53, "PublishedPort": 0, "Protocol": "udp"},
                ],
            },
        ),
    )
    assert _services_body(sent[0]) == (
        "*Services* — 0 of 1 healthy\n"
        "\U0001f7e1 `web` · running · unhealthy — nginx:alpine · 18080→80"
    )


def test_notify_reports_volumes_with_mount_paths_and_sizes(
    dummy_runtime, temp_dir: pathlib.Path
):
    (temp_dir / "docker-compose.yml").write_text(
        "services:\n"
        "  web:\n"
        "    image: nginx:alpine\n"
        "    volumes:\n"
        "      - web-data:/usr/share/nginx/html\n"
        "volumes:\n"
        "  web-data:\n",
        encoding="utf-8",
    )
    dummy_runtime.commands_run.clear()
    dummy_runtime.CLI_STDOUT = json.dumps(
        {
            "Volumes": [
                {
                    "Name": "my_stack_web-data",
                    "Size": "12.5MB",
                    "Labels": "com.docker.compose.project=my_stack,"
                    "com.docker.compose.volume=web-data",
                },
                {
                    "Name": "other_project_cache",
                    "Size": "1GB",
                    "Labels": "com.docker.compose.project=other,com.docker.compose.volume=cache",
                },
            ]
        }
    )
    sent = _notified_stack(dummy_runtime, temp_dir, event="up")
    payload = sent[0]

    assert _block_types(payload) == ["header", "section", "section", "divider", "section", "context"]
    assert _volumes_body(payload) == (
        "*Volumes* (1)\n"
        f"{GREEN} `my_stack_web-data` · web:/usr/share/nginx/html · 12.5MB"
    )
    assert ["system", "df", "-v", "--format", "json"] in dummy_runtime.commands_run


def test_notify_lists_volumes_even_when_sizes_are_unavailable(
    dummy_runtime, temp_dir: pathlib.Path
):
    (temp_dir / "docker-compose.yml").write_text(
        "services:\n"
        "  db:\n"
        "    image: postgres:17\n"
        "    volumes:\n"
        "      - type: volume\n"
        "        source: pgdata\n"
        "        target: /var/lib/postgresql/data\n"
        "volumes:\n"
        "  pgdata:\n",
        encoding="utf-8",
    )
    dummy_runtime.CLI_STDOUT = json.dumps({"Volumes": []})
    sent = _notified_stack(dummy_runtime, temp_dir, event="up")
    assert _volumes_body(sent[0]) == (
        "*Volumes* (1)\n" f"{GREEN} `pgdata` · db:/var/lib/postgresql/data"
    )


def test_notify_skips_the_host_scan_when_no_volume_is_declared(
    dummy_runtime, temp_dir: pathlib.Path
):
    dummy_runtime.commands_run.clear()
    sent = _notified_stack(dummy_runtime, temp_dir, event="up")
    assert _block_types(sent[0]) == ["header", "section", "section", "context"]
    assert ["system", "df", "-v", "--format", "json"] not in dummy_runtime.commands_run


@pytest.mark.parametrize(
    "failure",
    [
        {"returncode": 1, "stdout": "", "stderr": "boom"},
        {"returncode": 0, "stdout": "not json", "stderr": ""},
        {"returncode": 0, "stdout": '["unexpected"]', "stderr": ""},
        {"returncode": 0, "stdout": json.dumps({"Volumes": "nope"}), "stderr": ""},
        {"raises": "OSError"},
    ],
)
def test_notify_degrades_gracefully_when_the_volume_scan_fails(
    dummy_runtime, temp_dir: pathlib.Path, failure
):
    (temp_dir / "docker-compose.yml").write_text(
        "services:\n"
        "  db:\n"
        "    volumes:\n"
        "      - pgdata:/data\n"
        "volumes:\n"
        "  pgdata:\n",
        encoding="utf-8",
    )
    if failure.get("raises"):
        dummy_runtime.run_cli = MagicMock(side_effect=OSError("docker not answering"))
    else:
        dummy_runtime.run_cli = MagicMock(
            return_value=_Proc(failure["stdout"], failure["returncode"])
        )
    sent = _notified_stack(dummy_runtime, temp_dir, event="up")
    # The volume is still reported; only its size is missing.
    assert _volumes_body(sent[0]).endswith("`pgdata` · db:/data")


def test_notify_ignores_unusable_volume_entries(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "docker-compose.yml").write_text(
        "services:\n"
        "  db:\n"
        "    volumes:\n"
        "      - pgdata:/data\n"
        "volumes:\n"
        "  pgdata:\n",
        encoding="utf-8",
    )
    dummy_runtime.CLI_STDOUT = json.dumps(
        {
            "Volumes": [
                "not-a-mapping",
                {"Name": "no-labels", "Size": "1kB"},
                {"Name": "foreign", "Size": "1kB", "Labels": "com.docker.compose.project=other"},
                {"Name": "unlabeled", "Size": "9kB", "Labels": "no.project.here"},
                {
                    "Name": "found",
                    "Size": "9kB",
                    "Labels": "com.docker.compose.project=my_stack,com.docker.compose.volume=pgdata",
                },
                {
                    "Name": "no-compose-key",
                    "Size": "5kB",
                    "Labels": "com.docker.compose.project=my_stack",
                },
            ]
        }
    )
    sent = _notified_stack(dummy_runtime, temp_dir, event="up")
    body = _volumes_body(sent[0])
    assert "9kB" in body
    assert "1kB" not in body
    assert "5kB" not in body


def test_notify_still_sends_when_service_query_fails(
    dummy_runtime, temp_dir: pathlib.Path
):
    dummy_runtime.run_compose = MagicMock(side_effect=OSError("docker not answering"))
    sent = _notified_stack(dummy_runtime, temp_dir, event="up")
    # No services block at all, but the notification itself still goes out.
    assert _block_types(sent[0]) == ["header", "section", "context"]
    assert sent[0]["text"] == "my_stack"


def test_notify_survives_a_runtime_error_from_the_service_query(
    dummy_runtime, temp_dir: pathlib.Path
):
    dummy_runtime.run_compose = MagicMock(side_effect=RuntimeError("compose ps blew up"))
    assert len(_notified_stack(dummy_runtime, temp_dir, event="up")) == 1


def test_notify_skips_the_service_section_when_ps_returns_nothing(
    dummy_runtime, temp_dir: pathlib.Path
):
    dummy_runtime.run_compose = MagicMock(return_value=_Proc(""))
    sent = _notified_stack(dummy_runtime, temp_dir, event="up")
    assert _block_types(sent[0]) == ["header", "section", "context"]


def test_notify_reads_podman_style_lowercase_ps_fields(
    dummy_runtime, temp_dir: pathlib.Path
):
    dummy_runtime.run_compose = MagicMock(
        return_value=_Proc(json.dumps([{"Name": "web", "state": "running", "health": "healthy"}]))
    )
    sent = _notified_stack(dummy_runtime, temp_dir, event="up")
    assert _services_body(sent[0]) == "*Services* — 1 of 1 healthy"


def test_notify_defaults_the_service_state_when_ps_omits_it(
    dummy_runtime, temp_dir: pathlib.Path
):
    dummy_runtime.run_compose = MagicMock(return_value=_Proc(json.dumps([{"Service": "db"}])))
    sent = _notified_stack(dummy_runtime, temp_dir, event="up")
    assert _services_body(sent[0]) == f"*Services* — 0 of 1 healthy\n{RED} `db` · unknown"


def test_notify_ignores_unusable_publisher_entries(
    dummy_runtime, temp_dir: pathlib.Path
):
    dummy_runtime.run_compose = MagicMock(
        return_value=_Proc(
            json.dumps(
                [
                    {
                        "Service": "web",
                        "State": "running",
                        "Health": "starting",
                        "Publishers": "not-a-list",
                    },
                    {
                        "Service": "db",
                        "State": "exited",
                        "Publishers": ["nope", {"TargetPort": 5432}],
                    },
                ]
            )
        )
    )
    sent = _notified_stack(dummy_runtime, temp_dir, event="up")
    body = _services_body(sent[0])
    assert f"{RED} `db` · exited" in body
    assert "nope" not in body


def test_stack_down_never_notifies(dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "docker-compose.yml").touch()
    cfg = Config(
        name="my_stack",
        profiles={"default": Profile(file="docker-compose.yml")},
        notify_slack=SlackNotify(webhook=WEBHOOK),
    )
    dummy_runtime.ensure_ready_for_start = MagicMock()
    with patch("compman.notify.post") as post:
        stack.down(dummy_runtime, cfg)
    post.assert_not_called()


def test_unset_notify_env_warns_once_per_start(dummy_runtime, temp_dir: pathlib.Path, capsys):
    (temp_dir / "docker-compose.yml").touch()
    cfg = Config(
        name="my_stack",
        profiles={"default": Profile(file="docker-compose.yml")},
        notify_slack=SlackNotify(webhook_env="MY_SLACK_HOOK"),
    )
    dummy_runtime.ensure_ready_for_start = MagicMock()
    with patch("compman.notify.post") as post:
        stack.up(dummy_runtime, cfg)
    post.assert_not_called()
    assert "MY_SLACK_HOOK" in capsys.readouterr().err
