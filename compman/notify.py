"""Slack notifications for stack start events.

The webhook URL is resolved from the ``notify.slack`` block in compman.yml
first -- the literal ``webhook`` value, else the environment variable named
by ``webhook_env`` -- and from :data:`WEBHOOK_ENV` when the config carries no
Slack block, so exporting a single environment variable is enough to turn
notifications on for every stack.

Delivery is best-effort. The containers are already running by the time a
notification is sent, so a Slack outage or an unreachable host must never turn
a successful command into a failure: transport problems are reported as a
warning on stderr and the exit status is left untouched.

Message layout is written rather than delegated to Slack's field grid. Block
Kit hard-fails rather than truncating -- a ``section`` text caps at 3000
characters and comes back as ``invalid_payload`` -- and ``section.fields`` is
documented only as rendering "in a compact format that allows for 2 columns",
which clients are free to stack vertically. Both would have made a large or
narrow-screen notification lose its content, so the metadata block packs
``DETAIL_COLUMNS`` labelled items per line itself, and per-block bodies are
capped at :data:`MAX_SECTION_LINES`.
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen

import typer

from compman.config import SlackNotify
from compman.i18n import t
from compman.version import package_version

WEBHOOK_ENV = "COMPMAN_SLACK_WEBHOOK_URL"
"""Global fallback webhook variable used when compman.yml has no notify block."""

NOTIFY_TIMEOUT = 10.0
"""Seconds to wait for Slack before giving up on a notification."""

MAX_SECTION_LINES = 20
"""Body lines per block before the remainder is collapsed to a count."""


@dataclass(frozen=True)
class ServiceState:
    """One service as reported by ``compose ps`` plus its compose metadata."""

    name: str
    state: str
    health: str = ""
    image: str = ""
    ports: tuple[str, ...] = ()
    exit_code: int | None = None

    @property
    def healthy(self) -> bool:
        return self.state == "running" and self.health in ("", "none", "healthy")

    @property
    def icon(self) -> str:
        if self.healthy:
            return "\U0001f7e2"  # green circle
        if self.state == "running":
            return "\U0001f7e1"  # yellow circle: up but starting or unhealthy
        return "\U0001f534"  # red circle: not running

    @property
    def detail(self) -> str:
        parts = [self.state]
        if self.health:
            parts.append(self.health)
        if self.exit_code:
            parts.append(f"exit {self.exit_code}")
        return " · ".join(parts)


@dataclass(frozen=True)
class VolumeInfo:
    """One named volume: what it is called, who mounts it, and how big it is."""

    name: str
    mounts: tuple[str, ...] = ()
    size: str = ""

    @property
    def detail(self) -> str:
        parts = list(self.mounts)
        if self.size:
            parts.append(self.size)
        return " · ".join(parts)


@dataclass(frozen=True)
class StackEvent:
    """Everything one notification reports about a completed stack start."""

    kind: str
    stack: str
    profile: str
    duration: float
    runtime: str
    host: str
    started_at: str
    command: str
    services: tuple[ServiceState, ...] = ()
    volumes: tuple[VolumeInfo, ...] = ()

    @property
    def healthy_count(self) -> int:
        return sum(1 for service in self.services if service.healthy)

    @property
    def problems(self) -> tuple[ServiceState, ...]:
        return tuple(service for service in self.services if not service.healthy)

    @property
    def icon(self) -> str:
        """Message-level status mark: warning when any service needs attention."""
        return "⚠️" if self.problems else "✅"


def resolve_webhook(notify: SlackNotify | None) -> str | None:
    """Return the webhook URL to post to, or None when none is configured."""
    if notify is None:
        return os.environ.get(WEBHOOK_ENV) or None
    if notify.webhook:
        return notify.webhook
    if not notify.webhook_env:
        return None
    return os.environ.get(notify.webhook_env) or None


def missing_env_name(notify: SlackNotify | None) -> str | None:
    """Return the unset environment variable name, when that is why delivery is off.

    Distinguishes "no webhook was ever configured" (nothing to report) from
    "compman.yml names an environment variable that is not set" (a
    misconfiguration worth a warning).
    """
    if notify is None or notify.webhook or not notify.webhook_env:
        return None
    if os.environ.get(notify.webhook_env):
        return None
    return notify.webhook_env


def local_timestamp(moment: datetime) -> str:
    """Render a moment in local time, e.g. ``2026-10-02 19:24:05 KST``."""
    return moment.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def host_name() -> str:
    return socket.gethostname()


def format_duration(seconds: float) -> str:
    """Render an elapsed time compactly: ``840ms``, ``4.2s``, or ``1m 03s``."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}m {rest:02d}s"


def _event_title(kind: str) -> str:
    if kind == "up":
        return t("msg.notify_stack_started")
    return t("msg.notify_stack_updated")


def _title(event: StackEvent) -> str:
    """Headline: a green check normally, a warning when a service needs attention."""
    title = _event_title(event.kind)
    if event.problems:
        return f"{event.icon} {title} — " + t("msg.notify_attention", count=len(event.problems))
    return f"{event.icon} {title}"


DETAIL_COLUMNS = 2
"""Labelled items per line in the metadata block."""

SEPARATOR = "  ·  "
"""Divider between two items on the same line."""


def _detail_pairs(event: StackEvent) -> list[tuple[str, str]]:
    return [
        (t("msg.notify_stack"), f"`{event.stack}`"),
        (t("msg.notify_profile"), f"`{event.profile}`"),
        (t("msg.notify_runtime"), f"`{event.runtime}`"),
        (t("msg.notify_host"), f"`{event.host}`"),
        (t("msg.notify_started_at"), event.started_at),
        (t("msg.notify_duration"), format_duration(event.duration)),
    ]


def _detail_rows(event: StackEvent) -> list[str]:
    """Lay the metadata out as several labelled items per line.

    Slack's `section.fields` is documented only as rendering "in a compact
    format that allows for 2 columns", and clients that stack those fields
    vertically turn a six-field block into twelve lines. Writing the pairs into
    a single mrkdwn block keeps ``DETAIL_COLUMNS`` items per row on every
    surface, and halves the height when the grid does render.
    """
    pairs = _detail_pairs(event)
    rows = [
        pairs[start : start + DETAIL_COLUMNS]
        for start in range(0, len(pairs), DETAIL_COLUMNS)
    ]
    return [
        SEPARATOR.join(f"*{label}* {value}" for label, value in row) for row in rows
    ]


def _summary(event: StackEvent) -> str:
    if not event.services:
        return event.stack
    return (
        f"{event.icon} {event.stack} ({event.profile}) — {_event_title(event.kind)} · "
        + t("msg.notify_healthy_count", healthy=event.healthy_count, total=len(event.services))
    )


def _detail_fields(event: StackEvent) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(_detail_rows(event))}}


def _capped(lines: list[str], limit: int = MAX_SECTION_LINES) -> list[str]:
    """Trim a block body to what Slack accepts, noting what was dropped."""
    hidden = len(lines) - limit
    if hidden <= 0:
        return lines
    return [*lines[:limit], t("msg.notify_more", count=hidden)]


def _service_section(event: StackEvent) -> list[dict[str, Any]]:
    """Compact service health: a summary line, then only what is not healthy.

    A large stack stays readable, and a healthy start costs one line.
    """
    if not event.services:
        return []
    lines = [
        t(
            "msg.notify_services_summary",
            healthy=event.healthy_count,
            total=len(event.services),
        )
    ]
    for service in _capped([_service_line(service) for service in event.problems]):
        lines.append(service)
    return [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}]


def _service_line(service: ServiceState) -> str:
    extras = [part for part in (service.image, *service.ports) if part]
    suffix = f" — {' · '.join(extras)}" if extras else ""
    return f"{service.icon} `{service.name}` · {service.detail}{suffix}"


def _volume_section(event: StackEvent) -> list[dict[str, Any]]:
    """One row per volume: name, mount points, and size."""
    if not event.volumes:
        return []
    lines = [f"{icon} `{volume.name}`{_volume_detail(volume)}" for icon, volume in zip(_volume_icons(event), event.volumes)]
    return [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(
                    [t("msg.notify_volumes_header", count=len(event.volumes)), *_capped(lines)]
                ),
            },
        },
    ]


def _volume_detail(volume: VolumeInfo) -> str:
    return f" · {volume.detail}" if volume.detail else ""


def _volume_icons(event: StackEvent) -> tuple[str, ...]:
    """Mark volumes mounted by a failing service so the cause is obvious."""
    failing = {service.name for service in event.problems}
    return tuple(
        "\U0001f534"
        if any(mount.split(":", 1)[0] in failing for mount in volume.mounts)
        else "\U0001f7e2"
        for volume in event.volumes
    )


def build_payload(event: StackEvent) -> dict[str, Any]:
    """Build the Slack incoming-webhook payload for one stack event.

    ``text`` is the notification fallback (and what a push preview shows);
    ``blocks`` renders the full message.
    """
    return {
        "text": _summary(event),
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": _title(event), "emoji": True}},
            _detail_fields(event),
            *_service_section(event),
            *_volume_section(event),
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"compman {package_version()} · `{event.command}`",
                    }
                ],
            },
        ],
    }


def post(webhook: str, payload: dict[str, Any], timeout: float = NOTIFY_TIMEOUT) -> None:
    """POST the payload to the webhook, raising OSError on any failure."""
    request = Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        if not 200 <= response.status < 300:
            raise OSError(f"Slack webhook returned HTTP {response.status}")
        verdict = response.read().decode("utf-8", "replace")
    # Slack answers 200 even for revoked, expired, or malformed webhooks and
    # reports the real verdict in the body ("ok" on success, "no_token" or
    # "invalid_payload" on failure), so the status line alone cannot confirm
    # that the notification was delivered.
    if verdict.strip() != "ok":
        raise OSError(f"Slack webhook rejected the message: {_verdict_summary(verdict)}")


def _verdict_summary(verdict: str, limit: int = 80) -> str:
    """One short line from a Slack response body.

    A mistyped webhook path is redirected to Slack's HTML documentation, so
    the raw body can be a whole web page; collapse it and cap the length so
    the warning stays readable on a terminal.
    """
    collapsed = " ".join(verdict.split())
    if not collapsed:
        return "empty response"
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[:limit]}..."


def notify_stack_event(notify: SlackNotify | None, event: StackEvent) -> bool:
    """Send one stack notification; returns True when Slack accepted it.

    Never raises: an unconfigured or failing webhook degrades to a warning.
    """
    webhook = resolve_webhook(notify)
    if webhook is None:
        unset = missing_env_name(notify)
        if unset is not None:
            typer.echo(t("msg.notify_env_missing", name=unset), err=True)
        return False
    try:
        post(webhook, build_payload(event))
    except (OSError, ValueError) as exc:
        typer.echo(t("msg.notify_failed", error=exc), err=True)
        return False
    return True