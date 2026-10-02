# compman — Docker Compose Stack Manager CLI

[ English | [한국어](README.ko.md) ]

**Project homepage:** https://allbegray.github.io/compman/

`compman` manages Docker or Podman Compose stacks from one CLI: run and inspect
services, back up and restore volumes and images, schedule unattended backups,
deploy releases from S3 or HTTPS, and post a Slack notification when a stack
comes up.

No daemon, no web UI, no port opened — it calls the Docker or Podman CLI you
already have, which is why it fits locked-down hosts, jump boxes, and networks
where a management platform cannot be installed.

## Key features

- Auto-detects Docker Compose, Podman Compose, `podman-compose`, and `docker-compose`
- Profile-based `compose` config with per-profile env vars and AWS Secrets Manager injection
- Project-scoped `ps` and `stats`, plus `status`/`doctor` as text or JSON for CI
- Timestamped volume and image backups, gzip by default or Zstandard with `--zstd`
- Local, S3, or SSH/SCP backup storage, plus scheduled jobs via launchd/systemd/cron/schtasks
- Deploys from an S3 prefix or HTTP(S) archive with SHA-256 pinning and HTTPS header auth
- Slack notification on `stack up` / `stack update` with unhealthy-service and volume detail
- English and Korean help, shell completion, Windows/macOS/Linux

## Requirements

- Python 3.12+ (`--zstd` needs 3.14+, which ships the stdlib `compression.zstd`)
- Docker Compose or Podman Compose
- For S3: reachable S3-compatible storage and AWS credentials
- For authenticated HTTP deploys: an HTTPS archive URL and a token in an environment variable

CI runs Python 3.12–3.14 on Ubuntu, macOS, and Windows. Wheels publish to PyPI on
every tagged release.

## Install

```bash
uv tool install compman          # recommended, self-contained
pipx install compman             # equivalent
```

Or run the bundled installer, which puts the CLI on your `PATH`:

```bash
curl -fsSL https://raw.githubusercontent.com/allbegray/compman/main/install.sh | sh          # Linux / macOS
irm https://raw.githubusercontent.com/allbegray/compman/main/install.ps1 | iex               # Windows PowerShell
```

Then `compman --version`. Use `compman upgrade` to refresh an installed tool in
place. If the installation is damaged, uninstall and reinstall from the
**unpinned** upstream source so future upgrades keep working:

```bash
uv tool uninstall compman
uv tool install --managed-python git+https://github.com/allbegray/compman.git
```

For a development checkout, use `uv tool install .` and run the CLI from the repo.

## Quick start

```bash
cd my-project
compman init --scaffold     # or run `compman init` for an interactive menu
compman stack up
compman status
```

To deploy into an empty directory, `compman deploy` scaffolds the config for you:

```bash
mkdir my-app && cd my-app
compman deploy --path s3://my-bucket/releases/app.tar.gz --build --tag my-app
compman stack up
```

```
my-app/
├── compman.yml
├── docker-compose.yml
└── project/              # source fetched from S3/HTTP
```

## Configuration

Everything lives under the `compman` key in `compman.yml`. A JSON Schema is
published at [`docs/site/compman.schema.json`](docs/site/compman.schema.json) —
add this first line for IDE autocomplete and validation:

```yaml
# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
```

Worked examples: [`examples/compman-config/`](examples/compman-config/) (index in
[`examples/README.md`](examples/README.md)).

### Compose profiles

`compose` is required and must be a **mapping of profiles**. One profile is
enough; add more to switch environment per deployment.

```yaml
compman:
  name: my-stack
  compose:
    base: docker-compose.yml
    dev:
      file: docker-compose.dev.yml
      env:
        DATABASE_URL: dev.db.example.com
    prod:
      file: docker-compose.prod.yml
      env:
        DATABASE_URL: prod.db.example.com
```

```bash
compman stack up dev
```

A profile `file` is optional: omitted, it falls back to `base`, then
`docker-compose.yml`. That lets one Compose file vary only by environment.

### Keys

| Key | Purpose |
|-----|---------|
| `name` | Stack name; defaults to the config directory name |
| `folder` | Subdirectory holding the Compose files |
| `compose` | **Required.** Profile mapping; `base:` adds a shared Compose file |
| `dirs.project` | Managed deployment source tree |
| `dirs.backup` | Archive destination: local path, `s3://bucket/prefix`, or `ssh://[user@]host[:port]/path` |
| `dirs.volume` | Scratch directory for host↔container volume transfers |
| `deploy` | Default source for `deploy`/`update`: `s3://…`, an HTTPS archive URL, or a mapping (below) |
| `secrets` | AWS Secrets Manager entries, referenced by `${secrets:NAME}` |
| `notify.slack` | Slack webhook settings (see [Notifications](#notifications)) |
| `limits.max_archive_mb` | Cap on fetched deploy source size |
| `limits.max_backups` | Keep only the newest N archives per stack and kind |

Managed paths resolve relative to the config directory and may never escape it.
`--path` overrides `deploy` for a single invocation.

### Secrets

Declare `{ arn, key }` pairs under `secrets`, then reference them from a profile
`env` with `${secrets:NAME}`. compman substitutes the value at `key` when it
builds a compose context and passes the result to the `docker compose` process
environment, so the Compose file still uses `${VAR}`.

```yaml
compman:
  name: my-stack
  compose:
    default:
      file: docker-compose.yml
    dev:
      file: docker-compose.dev.yml
      env:
        DATABASE_URL: postgres://${secrets:DB_USER}@db.example.com
  secrets:
    DB_USER:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/user
```

- Injected **only** where a marker appears, never as standalone compose variables. An undeclared marker name fails the command.
- `key` may be a slash path. Partial interpolation works, and markers can sit beside system-variable references.
- A profile `secrets` block wins over the top-level one. Each ARN is fetched once per invocation.
- `compman doctor` warns when credentials or region are missing.

### Deploy sources and guarantees

S3 accepts a **prefix** (recursive, structure preserved) or a **archive**
(`.tar.gz`, `.tgz`, `.zip`, with a single top-level directory flattened).
Public HTTP/HTTPS accepts archives only, and the path must end in one of those
suffixes. Only the target with the same name is replaced; your own files are kept.

The mapping form adds pinning and auth:

```yaml
compman:
  deploy:
    url: s3://my-bucket/releases/app.tar.gz
    sha256: <64-hex-digest>
    auth: { header: Authorization, value_env: DEPLOY_TOKEN }   # HTTPS only
```

- **Transactional build.** `--build` compiles from the temporary source *before* the managed-tree swap, so a build failure leaves the existing tree and config untouched. A failed swap rolls back.
- **Integrity pinning.** `--sha256 HEX` or `deploy.sha256` is verified after download, before extraction, build, and swap. A mismatch aborts with exit 1 and changes nothing. It applies whenever the deployed URL equals the configured `deploy` URL, so `update` inherits it.
- **Token handling.** The header value is read at fetch time from `value_env` — never stored, never echoed, errors name only the variable. It is sent verbatim, so for Bearer auth store the full `Bearer <token>` string.
- **HTTPS required for auth**, and the header is dropped on a cross-host redirect so the token cannot leak. Serve from one host if your CDN needs it after redirecting.
- `compman rollback` restores the snapshot from the previous successful deploy.

## Commands

```text
compman init [--scaffold | --s3 URI | --seed]
compman deploy [--path SOURCE_URI] [--sha256 HEX] [--build] [--tag TAG]
compman update [PROFILE] [-c|--config PATH] [--stack NAME]
compman rollback
compman doctor [--profile PROFILE] [-c|--config PATH] [--json] [--stack NAME]
compman status [--profile PROFILE] [-c|--config PATH] [--json] [--stack NAME]
compman ps [PROFILE] [-a|--all] [--json] [-c|--config PATH] [--stack NAME]
compman stats [PROFILE] [-f|--follow] [--json] [-c|--config PATH] [--stack NAME]
compman history [--limit N] [--json]
compman stacks list [--json]
compman stacks remove NAME
compman clear [--yes]
compman upgrade [--repo URL]
compman lang [ko|en]
compman version
compman completion [powershell|bash|zsh|fish] --install

compman stack up [PROFILE] [--wait] [-c|--config PATH] [--stack NAME]
compman stack update [PROFILE] [--wait] [-c|--config PATH] [--stack NAME]
compman stack down [--profile PROFILE] -c|--config PATH --yes [--stack NAME]
compman stack logs [SERVICE...] [-f] [--tail N] [--profile PROFILE] [-c|--config PATH]

compman service start|stop|restart [SERVICE...] [--profile PROFILE] [-c|--config PATH]
compman service status [--profile PROFILE] [-c|--config PATH]
compman service log [SERVICE] [-f] [-n 50] [--profile PROFILE] [-c|--config PATH]
compman service connect [SERVICE] [--profile PROFILE] [-c|--config PATH]

compman volume backup [-z LEVEL] [--zstd] [--no-stop] [--profile PROFILE] [-c|--config PATH]
compman volume restore [TIMESTAMP] [--no-stop] [--replace] [--profile PROFILE] [-c|--config PATH]
compman volume pull [--profile PROFILE] [-c|--config PATH]
compman volume push [--replace] [--profile PROFILE] [-c|--config PATH]

compman image backup [-z LEVEL] [--zstd] [--source-image] [--profile PROFILE] [-c|--config PATH]
compman image restore [TIMESTAMP] [--profile PROFILE] [-c|--config PATH]

compman schedule add [--every N | --daily HH:MM | --weekly DAY HH:MM | --monthly DD HH:MM] [--no-stop] [-z LEVEL] [--name TEXT] [--scheduler systemd|cron]
compman schedule list [--json]
compman schedule status NAME
compman schedule remove NAME
```

`-c/--config` selects the config file, `--profile` the compose profile, and the
global `--stack NAME` runs any command against a registered stack from any
directory. View all options for any command with `compman <command> --help`.

### Behaviors worth knowing

- `update` is a rebuild plus force-recreate — **not** a zero-downtime rolling deploy. Without `deploy` it runs `up -d --build` locally.
- `stack down` on a missing stack is not an error: it exits 0, so scripts stay idempotent.
- `ps` and `stats` are project-scoped by design. `docker ps` / `podman ps` for runtime-wide results.
- `service log` and `connect` take **service** names, resolved via `compose ps -q`. Zero instances, or a scaled service with several, fails with guidance rather than guessing. `connect` falls back to `sh`.
- `volume backup`/`restore` stop the stack for consistency; `--no-stop` opts out. Restoring while everything is stopped also works — the stack is started temporarily and stopped again.
- `volume restore`/`push --replace` is a byte-for-byte replace that deletes destination-only files. Destructive by design; the destination must be an absolute container path.
- `image backup` commits container state unless `--source-image` is passed. gzip level defaults to 6 (`-z`); `--zstd` writes `.tar.zst` and needs Python 3.14+ for restore too.
- Archives are named `<stack>.{volume,image}.<YYYYMMDD_HHMMSS>[_<microseconds>].tar.gz`.
- `clear` runs `image prune -af`, which can remove unused images outside this project. Requires `--yes`.
- Long operations time out after 300s; override with `COMPMAN_TIMEOUT=<seconds>`. Streaming commands (`log -f`, `connect`, `stats -f`) never time out.

## Diagnostics

```bash
compman doctor
compman doctor --json
compman status --json
```

`--json` emits schema version `1`. `doctor` exits 1 only when a *required* check
fails; missing AWS credentials, an unpinned `deploy`, and unset
`deploy.auth`/`notify.slack` variables are warnings. `status` exits 1 when the
stack is missing, and 0 when it exists even if every service is stopped.

Operational failures, including Docker Desktop readiness on Windows, print as
concise messages without a Python traceback.

## Notifications

Set the webhook and every stack reports on `stack up` and `stack update`:

```bash
export COMPMAN_SLACK_WEBHOOK_URL='https://hooks.slack.com/services/T000/B000/XXXX'
```

Or scope it per stack so the secret stays out of the environment of the calling
shell:

```yaml
compman:
  notify:
    slack:
      webhook_env: COMPMAN_SLACK_WEBHOOK_URL   # recommended
      # webhook: https://hooks.slack.com/services/...   # literal URL, keeps the secret in this file
```

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

Resolution order is `webhook`, then the variable named by `webhook_env`, then
`COMPMAN_SLACK_WEBHOOK_URL` — the last only when the file has no `notify.slack`
block. A stack naming its own variable never falls back to the global one.

Services appear as a healthy count plus only the ones that are *not* healthy,
each with state, exit code, image tag, and published ports. The headline turns
into `⚠️ … N service(s) need attention` as soon as anything is off, and a volume
used by a failing service is marked 🔴 to point at the cause.

Delivery is best-effort and never changes the exit status — the containers are
already running, so an outage, a revoked webhook, or an unset variable warns on
stderr and still exits `0`. `stack down`, backup, and restore do not notify, so
the temporary restarts around a backup stay silent.

Volume **sizes** come from `docker system df -v`, the only Docker surface that
reports them. It scans the whole host, so compman runs it only when the compose
files declare a named volume and notifications are enabled; otherwise volumes
are still listed with their mount paths and only the sizes are dropped.

## Backups and scheduling

`dirs.backup` takes a local path, `s3://bucket/prefix`, or
`ssh://[user@]host[:port]/path`. Remote stores stage locally, upload, verify, then
remove the staged copy; SSH mode drives `scp`/`ssh` with `BatchMode=yes` and
assumes keys are already provisioned.

```bash
compman schedule add --daily 04:30 --no-stop
compman schedule add --every 30m
compman schedule add --monthly 1 05:00
compman schedule status my-stack.volume
compman schedule remove my-stack.volume
```

Exactly one cadence option is required. The platform mechanism is chosen
automatically: launchd on macOS, schtasks on Windows, and a systemd user timer or
crontab on Linux (`--scheduler systemd|cron` forces the Linux choice). Cron cannot
express every interval — `--every` must divide 60 minutes or be whole hours.
Output and per-run records land beside `schedules.json` under `%APPDATA%\compman`
when `APPDATA` is set, otherwise `~/.config/compman`; see
[`docs/site/`](docs/site/) for the registry layout.

## Runtime and environment

Detection order is `docker compose` → `podman compose` → `podman-compose` →
`docker-compose`. Force one with `CONTAINER_RUNTIME=podman`.

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=ap-northeast-2
export AWS_ENDPOINT_URL_S3=http://localhost:4566   # Ministack/LocalStack
export COMPMAN_TIMEOUT=600                         # seconds; default 300
export COMPMAN_LANG=ko                             # or --lang ko per invocation
```

On Windows with Docker, `stack up`, `stack update`, and deploy builds check
Docker Desktop readiness and offer to start it. Non-interactive runs never launch
it, and read-only, backup, and down paths skip the check entirely.

## Further reading

| Document | Contents |
|----------|----------|
| [examples/compman-config/](examples/compman-config/) | 14 case-by-case `compman.yml` files |
| [CHANGELOG.md](CHANGELOG.md) | Release history |
| [SECURITY.md](SECURITY.md) | Credential model, secret handling, reporting |
| [BACKLOG.md](BACKLOG.md) | Constraints and open work |
| [AGENTS.md](AGENTS.md) | Development, testing, and release rules |
| [SOLUTION.md](SOLUTION.md) | Debugging and design lessons |
| [Homepage](https://allbegray.github.io/compman/) | Search-optimized project site |

## License

MIT — see [LICENSE](LICENSE).
