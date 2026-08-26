# compman — Docker Compose Stack Manager CLI

[ English | [한국어](README.ko.md) ]

`compman` manages Docker or Podman Compose stacks—including execution, service operations, volume and image backup, and S3 or HTTP archive deployment—from one CLI.

**Project homepage:** https://allbegray.github.io/compman/

## Who Is This For?

This tool is dedicated to the brave, slightly unfortunate souls working in environments where a web GUI is unavailable, the firewall blocks everything useful, heavyweight management software cannot be installed, and somehow only raw Docker commands remain.

If every convenient option has been answered with "not allowed," `compman` is for you.

## Key features

- Automatically detects Docker Compose and Podman Compose runtimes
- Uses a profile-based `compose` configuration with per-profile env vars and secrets
- Lists and monitors only the current project's containers with `ps` and `stats`
- Deploys from an S3 prefix/archive or an HTTP/HTTPS `.tar.gz`/`.tgz`/`.zip` archive, with optional HTTPS header authentication and SHA-256 integrity pinning
- Automatically creates `compman.yml` and `docker-compose.yml` when deploying into an empty directory
- Creates and restores timestamped backups of volumes and container images (gzip `.tar.gz` by default, optional Zstandard `.tar.zst` via `--zstd`)
- Stores backups in a local directory, an S3-compatible bucket (`s3://bucket/prefix`), or a remote host over SSH/SCP (`ssh://[user@]host[:port]/path`) via `dirs.backup`
- Korean and English help, plus shell completion
- Supports Windows, Linux, and macOS

## Requirements

- Python 3.12 or later (`--zstd` backups require Python 3.14+, which provides the stdlib `compression.zstd` module)
- Docker Compose or Podman Compose
- For S3 deployments and the S3 backup store: accessible S3-compatible storage and AWS credentials
- For HTTP deployments: a public archive URL, or an authenticated HTTPS URL via the `deploy.auth` configuration (token supplied through an environment variable)

CI verifies Python 3.12–3.14 on Ubuntu, macOS, and Windows. See the `Python version strategy` section of [BACKLOG.md](BACKLOG.md) for the Python 3.14 support plan and upgrade decision.

Successful CI for a push to `main` automatically creates an annotated tag from
the version in `pyproject.toml`. Every version bump must include the matching
dated section in `CHANGELOG.md`; existing tags are never moved. Published wheels
land on PyPI, so `uv tool install compman` (or `pipx install compman`) installs
from PyPI.

## Installation

### Automatic installation

```powershell
# Windows PowerShell
irm https://raw.githubusercontent.com/allbegray/compman/main/install.ps1 | iex
```

```cmd
:: Windows CMD
curl -fsSL https://raw.githubusercontent.com/allbegray/compman/main/install.cmd -o %TEMP%\install.cmd && call %TEMP%\install.cmd
```

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/allbegray/compman/main/install.sh | sh
```

Open a new terminal, then verify the installation.

```bash
compman -v       # --version also works
compman -h       # --help also works
```

### Install with uv

Let uv manage the Python interpreter for compman (it downloads a managed Python,
so even a system running an older Python like 3.9 works):

```bash
uv tool install --force --managed-python git+https://github.com/allbegray/compman.git
```

To install a development version from the repository, run:

```bash
uv tool install .
```

Update an installed CLI using uv's stored tool source with:

```bash
compman upgrade
```

This runs `uv tool upgrade compman --reinstall --managed-python --python <current major.minor>` (the Python version compman itself runs on). To install
upgrades from a different Git repository, pass `--repo URL` (used only for the pip fallback
when uv is unavailable):

```bash
compman upgrade --repo https://github.com/your-fork/compman.git
```

### Recover a damaged installation

If `compman upgrade` cannot run because the installation is damaged, reinstall from
the upstream Git source. Keeping that source unpinned lets future `uv tool upgrade`
commands continue moving to newer releases:

```bash
uv tool uninstall compman
uv tool install --force --managed-python git+https://github.com/allbegray/compman.git
compman --version
```

## Quick start

### Existing Compose project

```bash
cd my-project
compman init --scaffold
compman stack up
compman service status
compman stack down --yes
```

Running `compman init` without arguments displays an interactive menu with these three modes.

```bash
compman init --scaffold                         # Create compman.yml
compman init --s3 s3://bucket/app.tar.gz --build
compman init --seed -o project -p 18080         # Create a test project
compman init --seed -o project -a               # Create a test project and archive
```

Overwriting existing files requires an explicit `--force`.

### Deploy a new project from S3 or HTTP

Run this from an empty working directory.

```bash
mkdir my-app && cd my-app
compman deploy --path s3://my-bucket/releases/app.tar.gz --build --tag my-app
compman stack up
```

A successful deployment creates this file structure.

```text
my-app/
├── compman.yml
├── docker-compose.yml
└── project/              # Application source downloaded from S3
```

S3 paths support these two formats.

- Prefix: Recursively downloads objects beneath the path and preserves their directory structure.
- Archive: Safely extracts `.tar.gz`, `.tgz`, or `.zip`; a single top-level directory is flattened automatically.

Public HTTP and HTTPS URLs support archives only. Query strings are allowed, but the URL path must end in `.tar.gz`, `.tgz`, or `.zip`.

```bash
compman deploy --path https://example.com/releases/app.zip --build --tag my-app
```

Only the deployment target with the same name is replaced; other user files are retained. With `--build`, the image is built from the temporary source before the swap, so a build failure leaves the existing tree and configuration untouched. If the source-replacement step fails, the previous tree is restored; only a scaffold-generation failure after the swap can leave the new source tree in place.

The deployment source can be pinned to a known-good artifact with a SHA-256 digest. Pass `--sha256 HEX` for a single invocation, or set `deploy` as a mapping in `compman.yml` (`{ url: ..., sha256: ... }`). The downloaded source is verified before extraction, image build, and the managed-tree swap; a mismatch aborts the deploy with exit status 1 and changes nothing on disk. The pin applies whenever the deployed source URL equals the configured `deploy` URL, so `compman update` inherits it automatically.

HTTPS deploy sources can authenticate with an optional `auth` block in the mapping form of `deploy`: `{ url: https://..., sha256?: ..., auth?: { header, value_env } }`. At fetch time compman reads the header value from the environment variable named by `value_env`. The token is never stored in `compman.yml` or echoed in output, and error messages name only the variable. The header is sent exactly as `<env value>`, so for Bearer authentication set the variable to the full `Bearer <token>` string.

Authenticated sources require `https://`; combining plain `http://` with `auth` is a configuration error. On a cross-host redirect compman drops the auth header before following it, so the token never leaks to the redirect target, while same-host redirects keep it. If your CDN requires the header after redirecting, serve the archive from the same host. Authentication applies only when the deployed source URL equals the configured `deploy` URL; an explicit `--path` deploy is unauthenticated (a documented limitation). `compman doctor` warns when `deploy.auth` is configured but its environment variable is unset.

## Configuration file

Put all configuration under the `compman` key in `compman.yml`.

A JSON Schema is published at
[`docs/site/compman.schema.json`](docs/site/compman.schema.json), so IDEs like VS Code and IntelliJ can provide autocomplete, validation, and hover descriptions for every key. Add this line at the top of your `compman.yml` to enable it:

```yaml
# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
```

For case-by-case examples, see [`examples/compman-config/`](examples/compman-config/) (index in [`examples/README.md`](examples/README.md)).

### Profile-based Compose configuration

`compose` is required and must be a mapping of profiles. A single profile is
enough for one Compose file:

```yaml
compman:
  name: my-stack
  compose:
    default:
      file: docker-compose.yml
```

Multiple profiles select a Compose file and environment variables per
environment:

```yaml
compman:
  name: my-stack
  compose:
    base: docker-compose.yml
    local: docker-compose.local.yml
    dev:
      file: docker-compose.dev.yml
      env:
        DATABASE_URL: dev.db.example.com
        LOG_LEVEL: debug
    prod:
      file: docker-compose.prod.yml
      env:
        DATABASE_URL: prod.db.example.com
```

The profile `file` is optional. When omitted, `base` is used; if there is no `base`, `docker-compose.yml` is used. This lets one Compose file use different environment variables per environment.

```bash
compman stack up dev
compman service status --profile dev
compman stack down --profile dev --yes
```

### Deployment and managed directories

```yaml
compman:
  name: my-stack
  deploy: s3://my-bucket/releases/app.tar.gz
  folder: compose
  dirs:
    project: project
    backup: backup
    volume: volume
  compose:
    default:
      file: docker-compose.yml
```

- `folder`: Relative subdirectory containing Compose files
- `dirs.project`: Relative subdirectory for managed deployment source
- `dirs.backup`: Directory for backup archives
- `dirs.volume`: Directory for transferring volume data to and from the host
- `deploy`: Default S3 URI or public HTTP archive URL for `compman deploy` and `compman update`

Managed paths cannot escape the directory containing `compman.yml`. `--path` overrides the configured `deploy` value for one invocation only.

To cap the deployed source size, set an optional limit; when configured, the source and its byte size are echoed as provenance:

```yaml
compman:
  name: my-stack
  deploy: s3://my-bucket/releases/app.tar.gz
  limits:
    max_archive_mb: 50
  compose:
    default:
      file: docker-compose.yml
```

Long-running Docker/subprocess operations use a 300-second timeout by default; override it per process with `COMPMAN_TIMEOUT=<seconds>` (e.g. `COMPMAN_TIMEOUT=600`). Streaming commands (`service log -f`, `service connect`, `stats -f`) intentionally run without a timeout.

### Environment variables from AWS Secrets Manager

Use the top-level `secrets` key to provide shared secret values. Each entry maps
a name to `{ arn, key }`. Profile `env` values reference these names with
`${secrets:NAME}` markers; compman fetches the secret's JSON `SecretString` and
substitutes the value at `key` when a compose context is built.

```yaml
compman:
  name: my-stack
  compose:
    default:
      file: docker-compose.yml
  secrets:
    DB_URL:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/url
    DB_PASSWORD:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/password
```

- Secrets are injected only where a profile `env` value contains a
  `${secrets:NAME}` marker; they are never passed to compose as standalone
  variables. A profile `secrets` block merges over the top-level one (profile
  wins on a name clash).
- The `key` names the JSON key inside the secret (slash keys like `dtx/db/url`
  are supported).
- The same ARN is fetched once per command invocation, even when multiple env
  vars reference it.
- A missing secret, unresolvable region, or invalid secret body fails the command
  with a clear error. Use the standard AWS credential and region environment
  variables; `compman doctor` reports a warning when secrets are configured but
  credentials or region are missing.

**Referencing secrets from a profile `env`:** instead of declaring a
`DB_URL`/`DB_PASSWORD` pair in `secrets` and echoing it in `docker-compose.yml`,
you can build env values with `${secrets:NAME}` markers. `NAME` must be a name
declared in the `secrets` block. Partial interpolation is supported, and the
marker can sit next to system-variable references (which are left untouched for
docker compose to resolve):

```yaml
compman:
  name: my-stack
  compose:
    local: docker-compose.local.yml
    dev:
      file: docker-compose.dev.yml
      env:
        DATABASE_URL: postgres://${secrets:DB_USER}:${secrets:DB_PASSWORD}@db.example.com
        LOG_LEVEL: ${LOG_LEVEL:-info}          # system var, resolved by compose
  secrets:
    DB_USER:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/user
    DB_PASSWORD:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/password
```

A marker that references an undeclared name fails the command with a clear
error.

**Using the injected variables:** declaring them is not enough. compman passes
the interpolated profile `env` values into the `docker compose` process
environment, so `docker-compose.yml` must reference them with `${VAR}`
interpolation:

```yaml
# docker-compose.yml
services:
  app:
    image: my-app
    environment:
      - DB_URL=${DB_URL}                  # injected from secrets
      - LOG_LEVEL=${LOG_LEVEL:-info}      # with a default fallback
```

## Commands

```text
compman init [--scaffold | --s3 URI | --seed]
compman deploy [--path SOURCE_URI] [--sha256 HEX] [--build] [--tag TAG]
compman update [PROFILE] [-c|--config PATH] [--stack NAME]
compman doctor [--profile PROFILE] [-c|--config PATH] [--json] [--stack NAME]
compman status [--profile PROFILE] [-c|--config PATH] [--json] [--stack NAME]
compman ps [PROFILE] [-a|--all] [--json] [-c|--config PATH] [--stack NAME]
compman stats [PROFILE] [-f|--follow] [--json] [-c|--config PATH] [--stack NAME]
compman upgrade [--repo URL]
compman rollback
compman version
compman lang [ko|en]
compman completion [powershell|bash|zsh|fish] --install

compman stack up [PROFILE] [-c|--config PATH] [--stack NAME]
compman stack update [PROFILE] [-c|--config PATH] [--stack NAME]
compman stack down [--profile PROFILE] [-c|--config PATH] --yes [--stack NAME]
compman stack logs [SERVICE...] [-f] [--tail N] [--profile PROFILE] [-c|--config PATH] [--stack NAME]

compman service start [SERVICE...] [--profile PROFILE] [-c|--config PATH] [--stack NAME]
compman service stop [SERVICE...] [--profile PROFILE] [-c|--config PATH] [--stack NAME]
compman service restart [SERVICE...] [--profile PROFILE] [-c|--config PATH] [--stack NAME]
compman service status [--profile PROFILE] [-c|--config PATH] [--stack NAME]
compman service log [CONTAINER] [-f] [-n 50] [--profile PROFILE] [-c|--config PATH] [--stack NAME]
compman service connect [CONTAINER] [--profile PROFILE] [-c|--config PATH] [--stack NAME]

compman volume backup [-z LEVEL] [--zstd] [--no-stop] [--profile PROFILE] [-c|--config PATH] [--stack NAME]
compman volume restore [TIMESTAMP] [--no-stop] [--replace] [--profile PROFILE] [-c|--config PATH] [--stack NAME]
compman volume pull [--profile PROFILE] [-c|--config PATH] [--stack NAME]
compman volume push [--replace] [--profile PROFILE] [-c|--config PATH] [--stack NAME]

compman image backup [-z LEVEL] [--zstd] [--source-image] [--profile PROFILE] [-c|--config PATH] [--stack NAME]
compman image restore [TIMESTAMP] [--profile PROFILE] [-c|--config PATH] [--stack NAME]

compman schedule add [--every N | --daily HH:MM | --weekly DAY HH:MM | --monthly DD HH:MM] [--no-stop] [-z LEVEL] [--profile PROFILE] [--name TEXT] [--scheduler systemd|cron] [-c|--config PATH]
compman schedule list [--json]
compman schedule status NAME
compman schedule remove NAME

compman stacks list [--json]
compman stacks remove NAME
compman history [--limit N] [--json]

compman clear [--yes]
```

View all options for a command with `compman <command> --help`.

### Behavioral notes

- `update`: When `deploy` is configured, it downloads the S3 or HTTP source, builds images, and starts the stack. Otherwise, it updates the local Compose project with `up -d --build`.
- `stack down`: Shutting down a stack that does not exist is not an error; compman prints a notice and exits 0, so scripts can call it idempotently.
- `service log`: Displays the last 50 lines by default and streams output with `-f`. Accepts a Compose service name, resolved to its container via `compose ps -q`; scaled services with multiple instances ask for the exact container name.
- `ps`: Lists running containers in the selected compman project. Use `-a` to include stopped containers.
- `stats`: Prints one resource-usage snapshot for the selected project's running containers. Use `-f` to stream continuously.
- `service connect`: Falls back to `sh` if connecting with `bash` fails.
- Restoring while every container is stopped works as well: compman temporarily starts the stack, restores the volumes, then stops it again.
- `volume backup/restore`: By default, brings the stack down during the operation and restores it afterward. Use `--no-stop` only when you understand the consistency risk.
- `volume restore/push --replace`: Deletes files at the destination that are not in the source (byte-for-byte replace) instead of merging. The destination must be a validated absolute container path; this is destructive, so use it deliberately.
- `image backup`: By default, commits and saves the state of the running container. Use `--source-image` to save the original image.
- `volume backup` and `image backup`: gzip level defaults to 6. Use `-z 1` for faster backups or `-z 9` for smaller archives (`-z` applies to gzip only). Add `--zstd` to write a Zstandard `.tar.zst` archive instead; this requires Python 3.14+, and restoring a `.tar.zst` backup does too.
- `clear`: Runs `image prune -af` for the selected runtime, so it can delete unused images outside the current project. Requires `--yes` confirmation (or an interactive `y` answer).

## Diagnostics and status

```bash
compman doctor
compman doctor --json
compman doctor --config /path/to/compman.yml
compman doctor -c /path/to/compman.yml
compman status
compman status --profile PROFILE
compman status --json
compman status --config /path/to/compman.yml
compman status -c /path/to/compman.yml
```

`doctor` checks configuration, Compose files, container-runtime availability and connectivity, managed directories, and AWS credentials. `status` displays the service state of the running stack. `--json` outputs structured JSON suitable for automation.

`ps` and `stats` are deliberately project-scoped. Use `docker ps`, `docker stats`, or the Podman equivalents directly when you need runtime-wide results.

If a required `doctor` check fails, it returns exit code `1`. `status` returns exit code `1` when the target stack does not exist or status retrieval itself fails. If the stack exists and retrieval succeeds, it returns exit code `0` even if every service is stopped or exited. Missing AWS environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) are non-failing warnings, so `doctor` returns exit code `0` if all other required checks pass.

Backup files are stored in `dirs.backup`.

```text
<stack>.volume.<YYYYMMDD_HHMMSS>[_<microseconds>].tar.gz
<stack>.image.<YYYYMMDD_HHMMSS>[_<microseconds>].tar.gz
```

Backups are gzip `.tar.gz` by default. Restores resolve the stored suffix transparently, so `.tar.gz` and `.tar.zst` archives list and restore through the same `volume restore` / `image restore` commands.

Optional retention: set `limits.max_backups` to keep only the newest N archives per stack and kind. After each successful backup, older archives are pruned from the store (local files or S3 objects), and every removal is echoed; a failed deletion warns but never fails the backup.

```yaml
compman:
  limits:
    max_backups: 10
```

When restoring without a timestamp, choose an available backup interactively. Volume restore and `volume push` merge data into the target; they do not delete files that exist only at the target. Image restore loads the image into the runtime but does not automatically change the Compose `image` tag.

### Remote backup stores (S3 or SSH)

`dirs.backup` accepts either a local relative path or a remote URI. With an
S3 store, archives live in the bucket; compman stages them locally only while
a backup or restore runs and deletes the staged copy after a successful upload.
An `ssh://[user@]host[:port]/path` store behaves the same way, using `scp` and
`ssh` with pre-provisioned keys (BatchMode; no passwords are stored or prompted).

```yaml
compman:
  name: my-stack
  dirs:
    backup: s3://my-bucket/backups
  compose:
    default:
      file: docker-compose.yml
```

An SSH store keeps the same archive naming on the remote path:

```yaml
compman:
  name: my-stack
  dirs:
    backup: ssh://backup@nas.example:2222/srv/backups
  compose:
    default:
      file: docker-compose.yml
```

- Every `volume backup` and `image backup` uploads its archive to
  `<prefix>/<archive-filename>` with `Content-Type: application/gzip`
  (`application/zstd` for `.tar.zst` archives), then verifies the stored
  object size against the staged file.
- Restores list available timestamps from the bucket and download the selected
  archive automatically; there is no manual sync step.
- A failed upload exits non-zero, keeps the staged archive, and names its path;
  a successful upload removes it.
- The store works with any S3-compatible endpoint via `AWS_ENDPOINT_URL_S3` /
  `AWS_ENDPOINT_URL` (see [S3-compatible storage](#s3-compatible-storage)).
- When an S3 backup store is configured but AWS credentials or region are
  missing, `compman doctor` reports a warning.

Operator note: aborted multipart transfers can leave billed orphaned parts in the bucket. On flaky networks, add a bucket lifecycle rule that aborts incomplete multipart uploads (7 days works well).

### Scheduled backups

`compman schedule add` registers an unattended `volume backup` job with the platform's native scheduler, so backups run on a cadence without a shell loop. With an S3 backup store configured, scheduled backups replicate off-site automatically.

```bash
compman schedule add --daily 04:30 --no-stop      # every day at 04:30 local time
compman schedule add --every 30m                  # every 30 minutes
compman schedule add --weekly sun 03:00 -z 9     # Sundays at 03:00, gzip level 9
compman schedule add --monthly 1 05:00           # 1st of every month at 05:00
compman schedule list [--json]
compman schedule status my-stack.volume          # install state + last run outcome
compman schedule remove my-stack.volume           # default job name: <project>.volume
```

Exactly one cadence option is required: `--every Nm|Nh`, `--daily HH:MM`, `--weekly <day> HH:MM`, or `--monthly <day 1-31> HH:MM` (day names `sun`..`sat`, case-insensitive; all times are local). Pass-through flags mirror `volume backup`: `--no-stop`, `-z LEVEL`, and `--profile`. The job runs through a thin internal wrapper — `[compman, schedule _exec, <job>, volume backup, -c <config>, ...]` — which appends output to `schedule.log` next to the schedule registry (`%APPDATA%\compman\schedule.log` when the `APPDATA` environment variable is set — always the case on Windows — otherwise `~/.config/compman/schedule.log`). On Linux with systemd timers the output goes to journald instead (`journalctl --user -u compman-<name>.service`).

The scheduler mechanism is picked automatically: launchd on macOS, schtasks on Windows, and on Linux a systemd user timer when `systemctl --user show-environment` succeeds, otherwise crontab. Force the Linux mechanism with `--scheduler systemd|cron`. Cron cannot express every interval: `--every` values must divide 60 minutes (or be whole hours), otherwise registration fails and suggests `--scheduler systemd`.

The registry file `schedules.json` lives in that same directory (`%APPDATA%\compman` when `APPDATA` is set, otherwise `~/.config/compman`) and is the source of truth. `schedule list` probes each platform artifact and marks drifted entries `[missing]`; `schedule remove` still deletes the registry entry when the platform artifact is already gone.

`schedule status NAME` probes the platform artifact live (reporting it registered or `MISSING`) and prints the last recorded run — its finish time, exit code, and duration. Jobs added from this release on execute through the internal `schedule _exec` wrapper, which appends a start/finish record per run to `runs/<name>.jsonl` next to the registry. Jobs registered before this upgrade keep their original command line and have no run log yet; status says so and suggests removing and re-adding the job to enable tracking.

Platform limitations to know before relying on this:

- macOS LaunchAgents fire only while the user is logged in; headless servers should use the Linux mechanisms.
- Windows scheduled tasks run only while the user is logged on.
- A scheduled backup behaves like any non-interactive run: if Docker Desktop is required and not ready, the job fails concisely instead of hanging.

## Runtime selection

The automatic detection order is:

```text
docker compose → podman compose → podman-compose → docker-compose
```

To prefer Podman, set an environment variable.

```bash
export CONTAINER_RUNTIME=podman
# PowerShell: $env:CONTAINER_RUNTIME="podman"
```

### Windows Docker Desktop readiness

On Windows when Docker is the selected runtime, compman checks Docker Desktop before `compman stack up`, `compman update`, `compman stack update`, and a `compman deploy --build` image build. If Docker Desktop is not ready in an interactive terminal, it asks:

```text
Docker Desktop is not running. Start it now? [Y/n]
```

Press Enter (or answer `Y`) to start Docker Desktop. compman waits up to 60 seconds for it to become ready before continuing. Answering `N` exits with guidance to start Docker Desktop manually and retry.

In non-interactive execution, compman never starts Docker Desktop; it exits with a concise error instead. This check does not run for Podman, read-only commands, backup/restore, or stop/down paths.

Expected operational failures, including Docker Desktop readiness failures, are printed as concise messages without Python tracebacks.

## S3-compatible storage

Uses standard AWS SDK environment variables.

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=ap-northeast-2
export AWS_ENDPOINT_URL_S3=http://localhost:4566   # Default Ministack/LocalStack port
```

If `AWS_ENDPOINT_URL_S3` is absent, `AWS_ENDPOINT_URL` can also be used.

## Language and shell completion

```bash
compman lang ko                    # Set the default language for the current process
compman --lang en --help           # Use English for this invocation only
export COMPMAN_LANG=ko             # Set the default language in the shell environment

compman completion powershell --install
compman completion bash --install
compman completion zsh --install
compman completion fish --install
```

## Development and verification

```bash
uv sync --dev
uv run ruff check compman tests
uv run mypy compman
uv run pytest --cov=compman --cov-report=term-missing
```

CI verifies:

- Ubuntu, macOS, and Windows × Python 3.12–3.14 tests
- 100% statement and branch coverage
- Ruff and mypy
- Wheel build, isolated installation, and CLI execution
- Ministack S3 download, Docker image build, and Compose start/stop E2E

For current constraints and the improvement backlog, see [BACKLOG.md](BACKLOG.md). For development, testing, and debugging lessons learned, see [SOLUTION.md](SOLUTION.md).
