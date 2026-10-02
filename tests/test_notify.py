from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from compman import notify
from compman.config import SlackNotify
from compman.notify import ServiceState, StackEvent, VolumeInfo

WEBHOOK = "https://hooks.slack.com/services/T000/B000/XXXX"


class _Response:
    """Minimal stand-in for the HTTPResponse urlopen returns."""

    def __init__(self, status: int = 200, body: bytes = b"ok") -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _event(**overrides) -> StackEvent:
    """A healthy two-service event; override via kwargs per test."""
    fields: dict = {
        "kind": "up",
        "stack": "my_stack",
        "profile": "default",
        "duration": 4.2,
        "runtime": "docker",
        "host": "build-host",
        "started_at": "2026-10-02 19:24:05 KST",
        "command": "stack up",
        "services": (
            ServiceState("web", "running"),
            ServiceState("db", "running", "healthy"),
        ),
    }
    fields.update(overrides)
    return StackEvent(**fields)


def _sent_payload(urlopen: MagicMock) -> dict:
    request = urlopen.call_args.args[0]
    return json.loads(request.data.decode("utf-8"))


# ---- resolve_webhook ----


def test_resolve_webhook_prefers_literal_value():
    settings = SlackNotify(webhook_env="COMPMAN_SLACK_WEBHOOK_URL", webhook=WEBHOOK)
    assert notify.resolve_webhook(settings) == WEBHOOK


def test_resolve_webhook_reads_configured_env_var(monkeypatch):
    monkeypatch.setenv("MY_SLACK_HOOK", WEBHOOK)
    assert notify.resolve_webhook(SlackNotify(webhook_env="MY_SLACK_HOOK")) == WEBHOOK


def test_resolve_webhook_falls_back_to_global_env_var(monkeypatch):
    monkeypatch.setenv(notify.WEBHOOK_ENV, WEBHOOK)
    assert notify.resolve_webhook(None) == WEBHOOK


def test_resolve_webhook_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv(notify.WEBHOOK_ENV, raising=False)
    monkeypatch.delenv("MY_SLACK_HOOK", raising=False)
    assert notify.resolve_webhook(None) is None
    assert notify.resolve_webhook(SlackNotify(webhook_env="MY_SLACK_HOOK")) is None
    assert notify.resolve_webhook(SlackNotify()) is None


def test_resolve_webhook_treats_empty_env_var_as_unset(monkeypatch):
    monkeypatch.setenv(notify.WEBHOOK_ENV, "")
    assert notify.resolve_webhook(None) is None


def test_config_block_stops_global_env_var_from_leaking_in(monkeypatch):
    monkeypatch.setenv(notify.WEBHOOK_ENV, WEBHOOK)
    monkeypatch.delenv("MY_SLACK_HOOK", raising=False)
    assert notify.resolve_webhook(SlackNotify(webhook_env="MY_SLACK_HOOK")) is None


# ---- missing_env_name ----


def test_missing_env_name_reports_unset_configured_variable(monkeypatch):
    monkeypatch.delenv("MY_SLACK_HOOK", raising=False)
    assert notify.missing_env_name(SlackNotify(webhook_env="MY_SLACK_HOOK")) == "MY_SLACK_HOOK"


def test_missing_env_name_is_none_when_not_a_misconfiguration(monkeypatch):
    monkeypatch.setenv("MY_SLACK_HOOK", WEBHOOK)
    assert notify.missing_env_name(None) is None
    assert notify.missing_env_name(SlackNotify(webhook=WEBHOOK)) is None
    assert notify.missing_env_name(SlackNotify(webhook_env="MY_SLACK_HOOK")) is None
    assert notify.missing_env_name(SlackNotify()) is None
    monkeypatch.delenv("MY_SLACK_HOOK")
    # A literal webhook always works, so the unset variable is not a problem.
    assert notify.missing_env_name(SlackNotify(webhook_env="MY_SLACK_HOOK", webhook=WEBHOOK)) is None


# ---- formatting helpers ----


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0.84, "840ms"), (4.24, "4.2s"), (59.9, "59.9s"), (63, "1m 03s"), (3600, "60m 00s")],
)
def test_format_duration_scales_to_the_magnitude(seconds, expected):
    assert notify.format_duration(seconds) == expected


def test_local_timestamp_renders_local_time():
    moment = datetime(2026, 10, 2, 19, 24, 5, tzinfo=timezone.utc)
    rendered = notify.local_timestamp(moment)
    assert rendered.startswith("2026-10-02 ") or rendered.startswith("2026-10-03 ")
    assert rendered.endswith(tuple("0123456789")) or " " in rendered


def test_host_name_is_the_machine_name():
    assert notify.host_name()


# ---- ServiceState ----


@pytest.mark.parametrize(
    ("service", "icon"),
    [
        (ServiceState("web", "running"), "\U0001f7e2"),
        (ServiceState("web", "running", "none"), "\U0001f7e2"),
        (ServiceState("web", "running", "healthy"), "\U0001f7e2"),
        (ServiceState("web", "running", "starting"), "\U0001f7e1"),
        (ServiceState("web", "running", "unhealthy"), "\U0001f7e1"),
        (ServiceState("web", "exited"), "\U0001f534"),
        (ServiceState("web", "created"), "\U0001f534"),
    ],
)
def test_service_state_icon_reflects_readiness(service, icon):
    assert service.icon == icon


def test_service_state_health_and_detail():
    assert ServiceState("web", "running").detail == "running"
    assert ServiceState("web", "running", "healthy").detail == "running · healthy"
    assert ServiceState("web", "exited").healthy is False


# ---- StackEvent ----


def test_stack_event_counts_healthy_and_problem_services():
    event = _event(
        services=(ServiceState("web", "running"), ServiceState("db", "exited"), ServiceState("cache", "running", "starting"))
    )
    assert event.healthy_count == 1
    assert [service.name for service in event.problems] == ["db", "cache"]
    assert event.icon == "⚠️"


def test_stack_event_is_clean_without_problems():
    assert _event().problems == ()
    assert _event().icon == "✅"


# ---- build_payload ----


def _block_types(payload: dict) -> list[str]:
    return [block["type"] for block in payload["blocks"]]


def _details_body(payload: dict) -> str:
    return payload["blocks"][1]["text"]["text"]


def _services_body(payload: dict) -> str:
    return payload["blocks"][2]["text"]["text"]


def _volumes_body(payload: dict) -> str:
    blocks = payload["blocks"]
    return blocks[blocks.index({"type": "divider"}) + 1]["text"]["text"]


def test_build_payload_renders_a_full_message():
    payload = notify.build_payload(_event())

    assert payload["text"] == (
        "✅ my_stack (default) — Stack started · 2 of 2 services healthy"
    )
    assert _block_types(payload) == ["header", "section", "section", "context"]
    assert payload["blocks"][0]["text"]["text"] == "✅ Stack started"

    # Two labelled items per line, three lines total, on every surface.
    assert _details_body(payload) == (
        "*Stack* `my_stack`  ·  *Profile* `default`\n"
        "*Runtime* `docker`  ·  *Host* `build-host`\n"
        "*Started at* 2026-10-02 19:24:05 KST  ·  *Duration* 4.2s"
    )
    assert len(_details_body(payload).splitlines()) == 3
    # A healthy stack costs exactly one service line.
    assert _services_body(payload) == "*Services* — 2 of 2 healthy"


def test_build_payload_stamps_the_compman_version_and_command():
    context = notify.build_payload(_event())["blocks"][-1]["elements"][0]["text"]
    assert context == f"compman {notify.package_version()} · `stack up`"


def test_build_payload_titles_an_update_event():
    payload = notify.build_payload(_event(kind="update", command="stack update"))
    assert payload["blocks"][0]["text"]["text"] == "✅ Stack updated"
    assert payload["text"].startswith("✅ my_stack (default) — Stack updated")


def test_build_payload_warns_in_the_title_and_lists_only_problem_services():
    payload = notify.build_payload(
        _event(
            services=(
                ServiceState("web", "running", image="nginx:alpine", ports=("18080→80",)),
                ServiceState("db", "exited", image="postgres:17", exit_code=3),
            )
        )
    )
    assert payload["blocks"][0]["text"]["text"] == "⚠️ Stack started — 1 service(s) need attention"
    assert payload["text"] == "⚠️ my_stack (default) — Stack started · 1 of 2 services healthy"
    # Only the unhealthy service is spelled out; the healthy one is just a count.
    assert _services_body(payload) == (
        "*Services* — 1 of 2 healthy\n\U0001f534 `db` · exited · exit 3 — postgres:17"
    )


def test_build_payload_shows_ports_and_health_for_a_running_problem_service():
    payload = notify.build_payload(
        _event(
            services=(
                ServiceState(
                    "web", "running", "unhealthy", "nginx:alpine", ("18080→80", "9000→9000/udp")
                ),
            )
        )
    )
    assert _services_body(payload) == (
        "*Services* — 0 of 1 healthy\n"
        "\U0001f7e1 `web` · running · unhealthy — nginx:alpine · 18080→80 · 9000→9000/udp"
    )


def test_build_payload_lists_volumes_with_mounts_and_size():
    payload = notify.build_payload(
        _event(
            volumes=(
                VolumeInfo("my_stack_pgdata", ("db:/var/lib/postgresql/data",), "1.39kB"),
                VolumeInfo("my_stack_uploads", ("web:/uploads",)),
            )
        )
    )
    assert _block_types(payload) == ["header", "section", "section", "divider", "section", "context"]
    assert _volumes_body(payload) == (
        "*Volumes* (2)\n"
        "\U0001f7e2 `my_stack_pgdata` · db:/var/lib/postgresql/data · 1.39kB\n"
        "\U0001f7e2 `my_stack_uploads` · web:/uploads"
    )


def test_build_payload_marks_volumes_mounted_by_a_failing_service():
    payload = notify.build_payload(
        _event(
            services=(ServiceState("db", "exited"), ServiceState("web", "running")),
            volumes=(
                VolumeInfo("my_stack_pgdata", ("db:/var/lib/postgresql/data",), "8.1GB"),
                VolumeInfo("my_stack_uploads", ("web:/uploads",), "412MB"),
            ),
        )
    )
    body = _volumes_body(payload)
    assert "\U0001f534 `my_stack_pgdata`" in body
    assert "\U0001f7e2 `my_stack_uploads`" in body


def test_build_payload_omits_sections_it_has_no_data_for():
    payload = notify.build_payload(_event(services=(), volumes=()))
    assert _block_types(payload) == ["header", "section", "context"]
    assert payload["text"] == "my_stack"


def test_build_payload_caps_problem_services_to_fit_slack_limits():
    many = tuple(ServiceState(f"svc-{index:02d}", "exited") for index in range(25))
    body = _services_body(notify.build_payload(_event(services=many)))
    assert body.count("\U0001f534") == notify.MAX_SECTION_LINES
    assert body.endswith("_…and 5 more_")
    assert len(body) < 3000


def test_build_payload_caps_volumes_to_fit_slack_limits():
    many = tuple(
        VolumeInfo(f"vol-{index:02d}", (f"svc:{index}",), "1kB") for index in range(25)
    )
    body = _volumes_body(notify.build_payload(_event(volumes=many)))
    assert body.count("\U0001f7e2") == notify.MAX_SECTION_LINES
    assert body.endswith("_…and 5 more_")
    assert len(body) < 3000


# ---- post ----


def test_post_sends_json_body_and_timeout():
    with patch.object(notify, "urlopen", return_value=_Response(200)) as urlopen:
        notify.post(WEBHOOK, {"text": "hi"}, timeout=5.0)
    request = urlopen.call_args.args[0]
    assert request.full_url == WEBHOOK
    assert request.get_method() == "POST"
    assert request.data == b'{"text": "hi"}'
    assert request.get_header("Content-type") == "application/json"
    assert urlopen.call_args.kwargs["timeout"] == 5.0


def test_post_raises_on_non_2xx_status():
    with patch.object(notify, "urlopen", return_value=_Response(500)):
        with pytest.raises(OSError, match="HTTP 500"):
            notify.post(WEBHOOK, {"text": "hi"})


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"invalid_payload", "rejected the message: invalid_payload"),
        (b"no_token", "rejected the message: no_token"),
        (b"  no_token\n", "rejected the message: no_token"),
        (b"", "empty response"),
        (b"   \n ", "empty response"),
        (b"  ok\n", None),
        (b"<html>" + b"x" * 500 + b"</html>", "rejected the message: <html>"),
    ],
)
def test_post_checks_the_body_because_slack_answers_200_on_failure(body, message):
    with patch.object(notify, "urlopen", return_value=_Response(200, body)):
        if message is None:
            notify.post(WEBHOOK, {"text": "hi"})
            return
        with pytest.raises(OSError, match=message) as raised:
            notify.post(WEBHOOK, {"text": "hi"})
    # A redirected HTML page must never flood the terminal.
    assert len(str(raised.value)) < 140


# ---- notify_stack_event ----


def test_notify_stack_event_posts_configured_webhook(monkeypatch):
    monkeypatch.setenv("MY_SLACK_HOOK", WEBHOOK)
    with patch.object(notify, "urlopen", return_value=_Response(200)) as urlopen:
        sent = notify.notify_stack_event(SlackNotify(webhook_env="MY_SLACK_HOOK"), _event())
    assert sent is True
    assert _sent_payload(urlopen)["text"].startswith("✅ my_stack")


def test_notify_stack_event_uses_default_timeout():
    with patch.object(notify, "urlopen", return_value=_Response(200)) as urlopen:
        notify.notify_stack_event(SlackNotify(webhook=WEBHOOK), _event())
    assert urlopen.call_args.kwargs["timeout"] == notify.NOTIFY_TIMEOUT


def test_notify_stack_event_warns_and_returns_false_when_unset(monkeypatch, capsys):
    monkeypatch.delenv("MY_SLACK_HOOK", raising=False)
    with patch.object(notify, "urlopen") as urlopen:
        sent = notify.notify_stack_event(SlackNotify(webhook_env="MY_SLACK_HOOK"), _event())
    assert sent is False
    urlopen.assert_not_called()
    assert "MY_SLACK_HOOK" in capsys.readouterr().err


def test_notify_stack_event_is_silent_when_not_configured(monkeypatch, capsys):
    monkeypatch.delenv(notify.WEBHOOK_ENV, raising=False)
    with patch.object(notify, "urlopen") as urlopen:
        assert notify.notify_stack_event(None, _event()) is False
    urlopen.assert_not_called()
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    "error",
    [OSError("connection refused"), ValueError("unknown url type: slack")],
)
def test_notify_stack_event_swallows_transport_errors(monkeypatch, capsys, error):
    monkeypatch.setenv(notify.WEBHOOK_ENV, WEBHOOK)
    with patch.object(notify, "urlopen", side_effect=error):
        assert notify.notify_stack_event(None, _event()) is False
    assert "ignored" in capsys.readouterr().err


def test_notify_stack_event_reports_http_rejection(monkeypatch, capsys):
    monkeypatch.setenv(notify.WEBHOOK_ENV, WEBHOOK)
    with patch.object(notify, "urlopen", return_value=_Response(404)):
        assert notify.notify_stack_event(None, _event()) is False
    assert "HTTP 404" in capsys.readouterr().err


def test_notify_stack_event_reports_revoked_webhook(monkeypatch, capsys):
    monkeypatch.setenv(notify.WEBHOOK_ENV, WEBHOOK)
    with patch.object(notify, "urlopen", return_value=_Response(200, b"no_token")):
        assert notify.notify_stack_event(None, _event()) is False
    assert "no_token" in capsys.readouterr().err