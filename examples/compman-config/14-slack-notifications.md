# Case 14 — Slack notifications

Post a message to Slack when `stack up` or `stack update` brings the stack up,
so a long deploy finishing on a headless host is visible without watching the
terminal.

## What the message contains

```text
✅ Stack started

  *Stack* notify-demo  ·  *Profile* default
  *Runtime* docker     ·  *Host* build-host
  *Started at* 2026-10-02 20:06 KST  ·  *Duration* 681ms

  *Services* — 3 of 3 healthy

  ────────────────────────────────────────
  *Volumes* (2)
  🟢 notify-demo_web-data · web:/usr/share/nginx/html · 1.393kB
  🟢 notify-demo_pgdata · db:/var/lib/postgresql/data · 40.01MB

compman 1.12.0 · stack up
```

The metadata block writes two labelled items per line itself rather than using
Slack's `section.fields` grid: the docs only promise that fields "allow for 2
columns", and a client that stacks them would double the height.

Services are a healthy count plus **only the unhealthy ones**, each with state,
exit code, image tag, and published ports. One service not being ready turns
the headline into `⚠️ Stack started — N service(s) need attention` and marks
the volumes that failing service mounts, so the alarm names its own suspect.

## Fastest setup — no config file change

```bash
export COMPMAN_SLACK_WEBHOOK_URL='https://hooks.slack.com/services/T000/B000/XXXX'
# PowerShell: $env:COMPMAN_SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T000/B000/XXXX"

compman stack up            # Slack receives: stack, profile, services
compman stack update --wait
```

The environment variable alone is enough — every stack picks it up, and no
`compman.yml` edit is required.

Create the webhook under **Apps → Incoming Webhooks → Add New Webhook to
Workspace**, then pick the channel that receives the stack-start messages.

## Per-stack webhook (recommended)

Name the variable instead of the URL so the secret stays out of the config
file that gets committed:

```yaml
compman:
  name: my-stack
  compose:
    default:
      file: docker-compose.yml
  notify:
    slack:
      webhook_env: COMPMAN_SLACK_WEBHOOK_URL
```

```bash
export COMPMAN_SLACK_WEBHOOK_URL='https://hooks.slack.com/services/T000/B000/XXXX'
compman doctor            # warns if the variable is not set
```

A literal URL is also accepted, but it stores a write-capable credential in
`compman.yml`:

```yaml
  notify:
    slack:
      webhook: https://hooks.slack.com/services/T000/B000/XXXX   # must be https://
```

## Resolution order

1. `notify.slack.webhook` (literal URL)
2. the environment variable named by `notify.slack.webhook_env`
3. `COMPMAN_SLACK_WEBHOOK_URL`, **only** when the file has no `notify.slack`
   block

A stack that names its own variable never falls back to the global one, so a
per-stack setting cannot be silently replaced by an ambient value. A misspelled
key under `notify` (anything other than `slack`) is a configuration error
rather than a setting that quietly does nothing.

## Failure behavior

The containers are already running when the notification is sent, so delivery is
best-effort and never changes the exit status:

- Slack outage or unreachable host: warning on stderr, command still exits `0`.
- Revoked or mistyped webhook: warning on stderr, command still exits `0`.
- `webhook_env` variable not set: one warning per start, no HTTP request.

Slack answers `HTTP 200` even for revoked webhooks and reports the real verdict
in the body, so compman checks the body rather than the status line.

## What does not notify

Only `stack up`, `stack update`, and a deploy-driven `compman update` notify.
`stack down`, `volume backup`/`restore`, and `image backup`/`restore` do not —
in particular the temporary stop/start that a backup performs stays silent.

With no webhook configured, no extra `compose ps` query is made at all, so the
feature costs nothing on a stack that has not opted in.

## Cost and limits

- Volume **sizes** come from `docker system df -v`, the only Docker surface
  that reports them. It scans every image and volume on the host, so compman
  runs it only when the compose files declare a named volume *and*
  notifications are enabled. If it is unsupported (Podman) or fails, volumes
  are still listed with their mount paths — only the sizes are dropped.
- Service and volume rows are capped per block; anything beyond the cap is
  collapsed to "…and N more". Slack rejects an oversized block outright with
  `invalid_payload` rather than truncating it.