# compman - Docker Compose Stack Manager CLI

**Generated:** 2026-08-24 · **Commit:** 5eecd09 · **Branch:** main

## Quick start

```bash
uv tool install .      # install CLI
compman --help         # verify
```

## Structure

```
compman/               # Python package
  cli.py               # typer entrypoint: compman.cli:app; whole command tree (root + 4 groups)
  config.py            # compman.yml loader (Config dataclass)
  docker.py            # ContainerRuntime abstraction, compose file resolution, Docker Desktop readiness
  deploy.py            # source dispatch, managed-tree swap, optional image build
  diagnostics.py       # doctor/status report collection (schema v1)
  archive.py           # path-safe tar/zip extraction
  archive_source.py    # shared archive recognition/extraction
  http_source.py       # public HTTP/HTTPS archive download
  s3_source.py         # S3 prefix/archive download
  env_source.py        # AWS Secrets Manager resolution + ${secrets:NAME} interpolation
  scaffold.py          # deploy-time compman/compose generation
  errors.py            # CommandError / ConfigError exception hierarchy
  i18n.py              # en/ko TRANSLATIONS dict + t(); language via ContextVar/COMPMAN_LANG
  __main__.py          # python -m compman shim
  ops/                 # business logic per domain
    stack.py, service.py, container.py, volume.py, image.py, seed.py
    schedule.py        # schedule add/list/remove orchestration over scheduling/
    common.py          # shared: prompt_select, select_backup_timestamp, stack_paused, ensure_runtime_ready
  scheduling/          # platform-native backup scheduling (Phase A of [M11])
    cadence.py         # Cadence vocab: parse_cadence + cron/launchd/systemd/schtasks formatters
    registry.py        # schedules.json registry (JobRecord, atomic load/save), Runner alias
    resolve.py         # resolve_executable fallback chain
    launchd.py, systemd.py, crontab.py, schtasks.py  # pure builders + install/remove/exists adapters
    pick.py            # pick_scheduler platform/mechanism selection
tests/                 # pytest unit/regression suite (1:1 module mirror, 100% branch coverage)
test/                  # runnable examples and E2E guides (not pytest tests)
examples/compman-config/  # case-by-case compman.yml examples
docs/site/             # dependency-free GitHub Pages homepage
docs/superpowers/      # design specs + plans (implementation rationale)
docker-init/           # Ministack S3 seed bundle for integration/E2E
scratch/               # throwaway experiment projects (not production code)
.github/workflows/     # ci.yml, pages.yml, publish.yml, release-tag.yml
SOLUTION.md            # dev/test/debug lessons (read before touching runtime/CLI/tests)
```

- `compman init` provides an interactive 3-mode menu (1. Scaffold compman.yml, 2. S3 URL deploy, 3. Test seed project). Direct flags `--scaffold`, `--s3 <url>`, and `--seed` are also supported.
- Current package version: `1.5.0`.
- English is the default UI and documentation language. Korean remains supported through `--lang ko` or `COMPMAN_LANG=ko`; keep Korean text isolated to `i18n.py` TRANSLATIONS and their tests.
- Build/running is `uv`-based (`pyproject.toml` has `[tool.uv] package = true`).
- Python >=3.12; runtime deps: typer, PyYAML, boto3, botocore.
- Quality gates: full pytest suite under a hard 100% statement/branch coverage gate, Ruff, mypy.
- CI tests Python 3.12-3.14 on Linux/macOS/Windows and has packaging and Docker/Ministack integration jobs.

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Command tree / new CLI command | `compman/cli.py` (root + all 4 groups defined here) |
| Business logic for a command | `compman/ops/<domain>.py` |
| `compman.yml` parsing/validation | `compman/config.py` |
| Runtime detection / docker/podman calls | `compman/docker.py` |
| `doctor`/`status` JSON (schema v1) | `compman/diagnostics.py` |
| `${secrets:NAME}` resolution | `compman/env_source.py` |
| Deploy sources (S3/HTTP/archive) | `compman/deploy.py` + `{s3,http,archive,archive_source}_source.py` |
| All user-facing strings / language | `compman/i18n.py` (`t()`, `TRANSLATIONS`) |
| Exception types | `compman/errors.py` |
| Interactive selection / backup timestamps | `compman/ops/common.py` |

## CODE MAP

| Symbol | Location | Refs | Role |
|--------|----------|------|------|
| `ContainerRuntime` | `docker.py:18` | 48 | Runtime abstraction; every command path |
| `load_config` | `cli.py:32` | 32 | Config bootstrap |
| `deploy()` | `deploy.py:31` | 18 | Deploy/update core |
| `detect_runtime` | `cli.py:38` | 14 | Runtime selection |
| `ensure_runtime_ready` | `ops/common.py:14` | 7 | Docker Desktop gate |
| `stack_paused` | `ops/common.py:146` | 5 | Stop/start wrapper for backup consistency |
| `generate_seed` | `ops/seed.py:13` | 5 | `init --seed` |
| `t()` | `i18n.py:767` | all modules | Translation lookup |

## Config: `compman.yml`

Profile-based only; there is no simple (list) mode.

```yaml
compose:
  default:
    file: docker-compose.yml
  dev:
    file: docker-compose.dev.yml
    env:
      DATABASE_URL: dev.db.example.com
```

- `compose` is required and must be a mapping of profiles; omitting it or using a
  list/string raises `ConfigError`. Breaking change vs. pre-1.4.0 configs.
- Optional `folder` key -> compose files live under that relative subdirectory.
- `folder` and `dirs.*` are resolved relative to the config directory. Managed backup/volume/project paths may not escape it; destructive managed directories may not equal the config root.
- Optional `base` key -> prepended as `-f` before profile compose files.
- Profile `file` is optional: omitted -> fallback to `base` or `docker-compose.yml`.
  Useful when all profiles share one compose file with different env vars only.
- Top-level `secrets` maps a marker name to `{ arn, key }`. Secrets are injected
  only through `${secrets:NAME}` markers inside profile `env` values; they are
  never passed to compose as standalone variables. A profile `secrets` block
  merges over the top-level one (profile wins on a name clash). Each ARN is
  fetched once per command invocation, lazily when a compose context is built.
  Partial interpolation is supported; undeclared marker names fail. System
  environment variables are inherited by docker compose directly and need no
  config entry.
- Optional top-level `limits: { max_archive_mb: N }` caps the fetched deploy
  source size (enforced on the extracted tree; exceeding it aborts the deploy
  before any filesystem change). When configured, the deployed source and its
  byte size are echoed as provenance.
- `deploy` also accepts a mapping `{ url?, sha256?, auth?: { header, value_env } }`.
  `sha256` pins the artifact and is verified after download, before extraction/
  build/managed-tree swap; a mismatch aborts with exit 1 and nothing changes.
  Works for S3 archives and HTTP(S) too.
- `deploy.auth` authenticates HTTPS fetches: the header value is read at fetch
  time from the env var named by `value_env`; the token is never stored in
  compman.yml nor echoed, and error messages name only the variable. `https://`
  is required when auth is present (http+auth = config error). Cross-host
  redirects drop the auth header (same-host redirects keep it). Auth applies
  only when the deployed source URL equals the configured `deploy` URL; an
  explicit `--path` deploy is unauthenticated.
- `dirs.backup` accepts a relative local path or an `s3://bucket/prefix` URI
  (parsed into a frozen `BackupStore` union in `compman/backup_store.py`).
  Remote mode: archives live in the bucket; each backup stages locally, uploads
  (`Content-Type: application/gzip`, head_object size verify), then deletes the
  staged copy. Upload failure exits non-zero keeping and naming the staged
  archive; restores list/download from the store automatically.
- Long-running Docker/subprocess operations default to a 300s timeout, overridable
  per process with `COMPMAN_TIMEOUT=<seconds>` (invalid values fall back to 300).

## Runtime

- Auto-detects Docker then Podman. Override: `CONTAINER_RUNTIME=podman`.
- Detection order: `docker compose` -> `podman compose` -> `podman-compose` -> `docker-compose`.
- On Windows with Docker, `stack up`, `update`, and deploy image builds check whether Docker Desktop is ready. In an interactive terminal, an unavailable Desktop prompts `Docker Desktop is not running. Start it now? [Y/n]`; Enter accepts the default and compman starts it, then waits up to 60 seconds. Choosing `No` exits with guidance to start Docker Desktop manually and retry. Non-interactive commands never launch Docker Desktop. Podman, read-only commands, backup/restore, and stop/down paths do not use this startup check.

## CONVENTIONS

- **No stdlib `logging` anywhere.** All output via `typer.echo(..., err=True)` + `t()`; errors via exceptions, never logs.
- **Exceptions** (errors.py): `CommandError(message, code=1)` for user-facing ops failures, `ConfigError` for config, `RuntimeError` for runtime, `ValueError` for source-URL validation. Chain with `raise X from exc`. Exception messages stay English; only CLI presentation layer translates.
- **Dataclasses, not dicts**, for domain models (`Config`/`Profile`/`SecretRef`/`ContainerRuntime`); `@dataclass(frozen=True)` for value objects. Dicts only as raw YAML transport: parse -> validate (`ConfigError`) -> construct.
- **i18n**: all help/option/message text via `t("cmd.*" | "opt.*" | "msg.*")`; en default, ko optional. Exception messages exempt from translation.
- **Types**: `from __future__ import annotations` + PEP 604 `str | None` + builtin generics everywhere (cli.py `typing.Optional` is a tolerated outlier). mypy not `--strict` (`check_untyped_defs`, `warn_unused_ignores`). Ruff `select E,F,I`, `ignore E501`, line-length 120.
- **Tests**: `test_<unit>_<behavior>`; fixtures only in `tests/conftest.py` (`runner`, `dummy_runtime`, `temp_dir`); unittest.mock `patch`/`patch.object`/`patch.dict` dominant, `monkeypatch` for env/platform; no pytest-mock; assert on `dummy_runtime.compose_runs[*]["args"]`; `pytest.raises(..., match=...)` for errors; `@pytest.mark.parametrize` drives branch coverage.

## ANTI-PATTERNS (THIS PROJECT)

- `compose` must be a mapping of profiles — list/string mode is forbidden (`ConfigError`).
- Managed paths may not escape the config directory; destructive managed dirs may not equal config root.
- **Zero `type: ignore`, `# pragma: no cover`, TODO/FIXME/HACK markers** — codebase baseline is clean (only `noqa: F401` re-export shims in `deploy.py`). Keep it that way.
- Coverage is a hard gate: `fail_under = 100` with branch coverage (pyproject + CI "Enforce 100% coverage" step). New branches require new tests.
- Never pass secrets as standalone compose variables — only via `${secrets:NAME}` markers.
- Do not add production code to `scratch/` (throwaway) or `test/` (examples, not pytest).
- Korean text lives only in `i18n.py` TRANSLATIONS (enforced by `test_repository_urls.py` hangul policy).

## CLI quirks

- `doctor` checks configuration, compose files, container runtime, and deploy prerequisites. `--json` emits schema version `1`; failed required checks exit with status 1, while missing optional AWS environment variables (including secrets prerequisites) are warnings. It also warns when `deploy` is configured without a sha256 pin, when `deploy.auth.value_env` names an unset environment variable, and when an S3 `dirs.backup` store is configured but AWS credentials/region are missing.
- Top-level `status` reports normalized stack/service state across Docker and Podman. `--json` emits schema version `1`; a missing stack or runtime query error exits with status 1, while an existing stopped stack is successful.
- Top-level `ps` lists containers only in the selected compman project; `-a`/`--all` includes stopped containers.
- Top-level `stats` prints one resource snapshot for running containers in the selected project; `-f`/`--follow` streams continuously.
- `stack down` requires `--yes` confirmation (`typer.confirm`).
- The default profile is the first configured profile when none is supplied; an explicit name must be valid (unknown names fail).
- `image backup` defaults to committing runtime container state; `--source-image` flag saves the original image instead.
- `volume backup/restore` optional `--no-stop` flag skips stack teardown.
- `volume restore/push` optional `--replace` flag deletes destination-only files before copying (byte-for-byte replace instead of merge); the container destination is validated as an absolute, non-root path.
- `volume backup` and `image backup` accept `-z`/`--level` from 1 to 9; the default gzip compression level is 6.
- `service log` displays last 50 lines by default (`docker logs -n 50`), supports `-f`/`--follow` to stream and `-n`/`--tail N` for line count.
- `service connect` runs `docker exec -it` with bash fallback to sh.
- `service log`/`connect` accept Compose **service** names; the runtime container is resolved via `compose ps -q <service>`. Zero instances fail with a "no running containers" error; a scaled service with multiple instances fails with guidance to name the exact container.
- `deploy` sources come from `compman.yml: deploy` (single value, no per-profile) or `--path`. S3 uses boto3 (no AWS CLI needed); `AWS_ENDPOINT_URL_S3` or `AWS_ENDPOINT_URL` redirects the client (e.g. ministack at `http://localhost:4566`). Credentials use standard AWS environment variables.
- Deploy accepts an S3 **prefix** or `.tar.gz`/`.tgz`/`.zip` archive, plus public HTTP/HTTPS archives with those suffixes. HTTP uses standard TLS/redirect behavior and a 30-second timeout; authenticated fetches send a header sourced from an environment variable and require HTTPS. Archives reject absolute/traversal paths and links; a single top-level directory is flattened.
- `deploy` accepts `--sha256 HEX` (or `deploy.sha256` in config); the digest is verified after download, before extraction/build/swap, and a mismatch exits 1 with nothing changed. The pin applies whenever the deployed source URL equals the configured `deploy` URL, so `update` inherits it.
- `compman upgrade` refreshes the uv tool from its stored source with `uv tool upgrade compman --reinstall --managed-python --python 3.13`. To recover a damaged installation, run `uv tool uninstall compman`, then `uv tool install --managed-python --python 3.13 git+https://github.com/allbegray/compman.git`, and verify with `compman --version`. Keep the recovery source unpinned so future `uv tool upgrade` runs can move to newer releases.
- The fetched tree replaces the contents of the managed `dirs.project` directory, preserving `.git` and `.gitkeep`. Root `compman.yml` and `docker-compose.yml` are scaffolded or updated separately.
- Deploy with `--build` is transactional up to the managed-tree swap: the image builds from the temporary source first, so a build failure leaves the existing tree and configuration untouched. The swap itself rolls back on failure; only a scaffold-generation failure after the swap can leave the new source tree in place.
- `update` rebuilds and force-recreates containers; it is not a zero-downtime rolling deployment.
- `compman schedule add|list|remove` registers unattended `volume backup` jobs with the platform scheduler: launchd on macOS, schtasks on Windows, systemd user timer (probe `systemctl --user show-environment`) else crontab on Linux; `--scheduler systemd|cron` forces the Linux mechanism only. Exactly one cadence option (`--every Nm|Nh`, `--daily HH:MM`, `--weekly <day> HH:MM`) is required; cron targets additionally require 60-divisible minutes or whole-hour intervals. Jobs run `[exe, -c <config>, volume backup, ...baked flags]` with output appended to `<registry_dir>/schedule.log` (journald for systemd). The registry at `~/.config/compman/schedules.json` (`%APPDATA%\compman\schedules.json` on Windows) is the source of truth: `list` marks absent artifacts `[missing]`, `remove` tolerates already-missing artifacts and always deletes the entry.
- Expected operational failures, including Docker Desktop readiness failures, are shown as concise errors without Python tracebacks.
- Root version flags are `-v` and `--version`; help flags are `-h` and `--help` for the root and command groups.

## Backup naming

```
<stackname>.volume.<YYYYMMDD_HHMMSS>[_<microseconds>].tar.gz
<stackname>.image.<YYYYMMDD_HHMMSS>[_<microseconds>].tar.gz
```

## Verification

```bash
uv sync --dev
uv run ruff check compman tests
uv run mypy compman
uv run pytest --cov=compman --cov-report=term-missing
```

Before release completion, build a wheel and install it into an isolated uv tool
directory. Smoke-test the generated `compman.exe` itself, including `--version`,
English and Korean `--help`, `init`, `doctor`, and `status`; test `upgrade` when
the stored installation source supports it.

Every package version change must add a matching section to root `CHANGELOG.md`
summarizing user-visible changes. Keep the newest version first.
After a successful CI run for a push to `main`, `.github/workflows/release-tag.yml`
creates the missing annotated `v<project.version>` tag. Existing tags are never
moved; a version/tag collision fails the workflow.

## Documentation governance

Applied on 2026-08-10, modeled on the gorani project's `PROMPT.md` agent rules,
with one deliberate deviation: **all documentation and commit messages are in
English** (the gorani template defaults to Korean; the project owner overrode
that for compman). Rules:

- The six mandatory root documents must always exist: `AGENTS.md`, `BACKLOG.md`,
  `CHANGELOG.md`, `README.md`, `SECURITY.md`, `SOLUTION.md`. If any is missing,
  analyze the codebase and recreate it before starting work.
- The root directory holds only those six `.md` files; any other Markdown file
  lives under `docs/`.
- `BACKLOG.md` items use priority labels `[H1]`/`[M1]`/`[L1]` (High/Medium/Lower)
  with `- [ ]` checkboxes; completed items are marked `- [x]` and never deleted.
- `CHANGELOG.md` keeps dated, semantic-versioned sections (`## [x.y.z] - YYYY-MM-DD`)
  with `### Added` / `### Changed` / `### Fixed` / `### Removed` subsections.
- `SECURITY.md` documents authentication/authorization, secret management,
  vulnerability reporting, and code-writing security rules; never hardcode real
  credentials — use placeholders.
- `SOLUTION.md` records problems as topics with symptom/cause/solution/prevention;
  troubleshooting content from other documents is consolidated here.
- Codebase questions: if `graphify-out/` exists, query the knowledge graph first
  (`graphify query "<question>"`); after code changes, sync it with `graphify --update`.
- When packages are added, architecture changes, or bug-fix approaches are learned,
  record them immediately in the Execution Log below.
- Bilingual README: `README.md` (English) is authoritative and `README.ko.md` is
  its Korean mirror kept in sync by the command-block validation test
  (`test_readme_ko_command_list_matches_registered_command_tree`); prose changes to
  either file must be mirrored in the other.

## Execution Log

- **2026-08-10** — Applied the gorani governance rules in English: audited the six
  mandatory root documents (all present, already English), rewrote `SECURITY.md`
  from the GitHub template into a real policy, restructured `BACKLOG.md` into the
  labeled H/M/L checklist format, and confirmed the `graphify-out/` knowledge graph
  (graphifyy v0.9.38) is built and current.
