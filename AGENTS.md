# compman - agent operating manual

Not a user manual. `README.md` owns the feature and configuration reference; this
file owns the rules, seams, and traps you cannot infer from reading the code.

## Quick start

```bash
uv tool install . && compman --help
uv run pytest -q          # 1100+ tests, ~5s
```

## Facts

- Python >=3.12; runtime deps `typer`, `PyYAML`, `boto3`, `botocore`; `uv`-based build.
- English is the default and the only documentation language. Korean exists in the
  UI via `--lang ko` / `COMPMAN_LANG=ko` and must stay confined to `i18n.py`.
- Package version lives in `pyproject.toml`. Never hardcode it in a document.
- Gates: pytest at 100% statement **and** branch coverage, Ruff, mypy.
- CI: Python 3.12-3.14 on Linux/macOS/Windows, plus packaging and Docker/Ministack
  integration jobs.

## Module map

```
compman/
  cli.py            typer entrypoint; the whole command tree (root + 4 groups)
  config.py         compman.yml -> Config dataclass
  docker.py         ContainerRuntime, compose resolution, Docker Desktop gate
  deploy.py         source dispatch, managed-tree swap, optional image build
  diagnostics.py    doctor/status report collection (schema v1)
  notify.py         Slack webhook resolution + best-effort delivery
  compose_spec.py   compose introspection (named-volume mounts)
  backup_store.py   frozen union: local / S3 / SSH backup stores
  archive*.py       path-safe tar/zip extraction + source recognition
  s3_source.py      S3 prefix/archive download      http_source.py  HTTP(S) archive download
  env_source.py     AWS Secrets Manager -> ${secrets:NAME}
  scaffold.py       deploy-time compman/compose generation
  version.py        package version lookup           errors.py        exception hierarchy
  i18n.py           en/ko TRANSLATIONS + t()         _proc.py        subprocess timeout helpers
  ops/              business logic per domain (stack, service, container, volume,
                    image, seed, schedule, common)
  scheduling/       platform-native backup scheduling (cadence, registry, resolve,
                    launchd, systemd, crontab, schtasks, pick)
tests/              1:1 module mirror; examples/ config cases; docs/site/ Pages homepage
docker-init/        Ministack S3 seed bundle   scratch/  gitignored experiments
```

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Command tree / new CLI command | `compman/cli.py` |
| Business logic for a command | `compman/ops/<domain>.py` |
| `compman.yml` parsing/validation | `compman/config.py` |
| Runtime detection / docker/podman calls | `compman/docker.py` |
| `doctor`/`status` JSON (schema v1) | `compman/diagnostics.py` |
| `${secrets:NAME}` resolution | `compman/env_source.py` |
| Deploy sources | `compman/deploy.py` + `{s3,http,archive,archive_source}_source.py` |
| Slack webhook config + delivery | `compman/notify.py` + `notify:` block in `config.py` |
| Named-volume mounts | `compman/compose_spec.py` |
| All user-facing strings | `compman/i18n.py` (`t()`, `TRANSLATIONS`) |
| Interactive selection / backup timestamps | `compman/ops/common.py` |

Highest-traffic seams: `ContainerRuntime` (`docker.py`) on every command path,
`load_config` and `detect_runtime` (`cli.py`), `deploy()` (`deploy.py`),
`ensure_runtime_ready` and `stack_paused` (`ops/common.py`), `t()` (`i18n.py`).

## Configuration invariants

Field-by-field reference is `README.md` + `config.py`. Only the constraints that
will bite you:

- `compose` is required and must be a **mapping of profiles**; a list or string is a
  `ConfigError`. There is no simple mode (breaking change since 1.4.0).
- `folder` and `dirs.*` resolve relative to the config directory. Managed
  backup/volume/project paths may not escape it, and a destructive managed dir may
  not equal the config root. `load_config` resolves all of them eagerly so unsafe
  config fails before any command can mutate the filesystem.
- Secrets reach compose **only** through `${secrets:NAME}` markers inside profile
  `env`. Never pass them as standalone variables. A profile `secrets` block wins over
  the top-level one; each ARN is fetched lazily, once per invocation.
- `deploy.sha256` and `deploy.auth` are pinning/secret references, not values. Auth
  requires `https://`, drops the header on cross-host redirects, and applies only when
  the deployed URL equals the configured `deploy` URL.
- `notify.slack.webhook_env` names a variable; a literal `webhook` must be `https://`.
  Resolution is `webhook` -> `webhook_env` -> global `COMPMAN_SLACK_WEBHOOK_URL`, and a
  stack that names its own variable never falls back to the global one.
- Long-running subprocesses default to 300s, overridable with `COMPMAN_TIMEOUT`
  (invalid values fall back to 300).

## Conventions

- **No stdlib `logging`.** Output via `typer.echo(..., err=True)` + `t()`; failures
  via exceptions, never logs.
- **Exceptions** (`errors.py`): `CommandError(message, code=1)` for user-facing
  failures, `ConfigError` for config, `RuntimeError` for runtime, `ValueError` for
  source-URL validation. Chain with `raise X from exc`. Exception messages stay
  English; only the CLI presentation layer translates.
- **Dataclasses, not dicts**, for domain models (`Config`/`Profile`/`SecretRef`/
  `ContainerRuntime`); `@dataclass(frozen=True)` for value objects. Dicts are raw YAML
  transport only: parse -> validate (`ConfigError`) -> construct.
- **i18n**: every help/option/message string goes through `t("cmd.*"|"opt.*"|"msg.*")`.
- **Types**: `from __future__ import annotations`, PEP 604 unions, builtin generics
  (`cli.py` `typing.Optional` is a tolerated outlier). Ruff `select E,F,I`, line length
  120, `E501` ignored. mypy runs `check_untyped_defs` + `warn_unused_ignores`.
- **Tests**: `test_<unit>_<behavior>`. Fixtures live only in `tests/conftest.py`
  (`runner`, `dummy_runtime`, `temp_dir`). Prefer `unittest.mock`; `monkeypatch` for
  env/platform. Assert on `dummy_runtime.compose_runs[*]["args"]`. Use
  `@pytest.mark.parametrize` to drive branch coverage.

## Anti-patterns

- `compose` must be a mapping of profiles.
- Managed paths may not escape the config directory.
- **Zero `type: ignore`, `# pragma: no cover`, TODO/FIXME/HACK.** Only `noqa: F401`
  re-export shims in `deploy.py` are allowed.
- Coverage is a hard gate (`fail_under = 100`, branch coverage). Every new branch
  needs a new test.
- No production code in `scratch/`.
- Korean text lives only in `i18n.py` (hangul policy test).

## Command behavior invariants

Only the non-obvious; user-facing flags are in `README.md`.

- `doctor --json` / `status --json` emit schema version `1`. Failed *required*
  checks and a missing stack exit 1; a stopped-but-existing stack exits 0. Missing AWS
  credentials, an unpinned `deploy`, an unset `deploy.auth.value_env`, and an unset
  `notify.slack.webhook_env` are warnings, not failures.
- `ps` and `stats` are project-scoped by design, not whole-runtime.
- The default profile is the first configured one; an explicit unknown name fails.
- `stack down` requires `--yes`. `service log`/`connect` accept **service** names and
  resolve the container with `compose ps -q <service>`; zero instances and multi-instance
  services both fail with guidance.
- Deploy accepts an S3 prefix or a `.tar.gz`/`.tgz`/`.zip` archive, and public
  HTTP(S) archives with those suffixes. SHA-256 is verified after download, *before*
  extraction/build/swap. `AWS_ENDPOINT_URL_S3`/`AWS_ENDPOINT_URL` redirect boto3
  (Ministack at `http://localhost:4566`).
- The managed-tree swap preserves `.git` and `.gitkeep`. `deploy --build` builds from
  the temporary source first, so a build failure leaves the existing tree untouched;
  only a post-swap scaffold failure can leave the new tree in place.
- `rollback` restores the snapshot from the previous successful deploy. Snapshot
  capture problems warn but never fail a deploy.
- `stacks list/remove` manage `stacks.json` beside the schedule registry; `--stack NAME`
  runs any command against a registered stack from any directory (`-c` wins).
- **`update` is a rebuild plus force-recreate, not a zero-downtime rolling deploy.**
- `schedule` picks launchd (macOS), schtasks (Windows), and a systemd user timer or
  crontab (Linux). Cron cannot express every interval: `--every` must divide 60 minutes
  or be whole hours. Jobs run through `[exe, schedule, _exec, <name>, ...]` and append
  per-run records to `<registry>/runs/<name>.jsonl`, which `schedule status` reports.
  Registry and log live under `%APPDATA%\compman` when `APPDATA` is set, else
  `~/.config/compman`. Default job name is `<sanitized project>.volume`.
- `history` reads an append-only JSONL journal; write failures warn, never fail.
- Slack notifications fire only after a successful `stack up`/`stack update` or a
  deploy-driven `update`. Data comes from one `compose ps --all --format json`, plus
  one `docker system df -v --format json` **only** when the compose files declare a
  named volume. Mount paths come from `compose_spec.read_volume_mounts` because
  `compose ps` truncates its `Mounts` column. `stack down`, backup, and restore never
  notify. Delivery is warning-only and never changes the exit status.
- Operational failures, including Docker Desktop readiness, render as concise errors
  without tracebacks. Root version flags are `-v`/`--version`; help is `-h`/`--help`.

## Backup naming

```
<stackname>.volume.<YYYYMMDD_HHMMSS>[_<microseconds>].tar.gz
<stackname>.image.<YYYYMMDD_HHMMSS>[_<microseconds>].tar.gz
```

`--zstd` writes `.tar.zst` instead; restores resolve whichever suffix was stored.

## Verification

```bash
uv sync --dev
uv run ruff check compman tests
uv run mypy compman
uv run pytest --cov=compman --cov-report=term-missing
```

Before a release: build a wheel, install it into an isolated `UV_TOOL_DIR`, and
smoke-test the generated executable itself (`--version`, English and Korean
`--help`, `init`, `doctor`, `status`).

## Release

- Every version change adds a dated `## [x.y.z] - YYYY-MM-DD` section to
  `CHANGELOG.md`, newest first.
- `tests/test_repository_urls.py` asserts `pyproject.toml`, `uv.lock`, and
  `CHANGELOG.md` agree, and that the wheel version matches.
- A successful CI run on a push to `main` makes `release-tag.yml` create the missing
  annotated `v<version>` tag, then `publish.yml` uploads to PyPI. Tags are never
  moved; a collision fails the workflow.

## Documentation rules

- Six mandatory root documents: `AGENTS.md`, `BACKLOG.md`, `CHANGELOG.md`, `README.md`, `SECURITY.md`, `SOLUTION.md`. Recreate any that go missing. The root holds only these six; other Markdown lives under `docs/`, which is English-only and Hangul-free.
- **Each root document owns one thing and points at the others for the rest.** `README.md` is the user manual and the GitHub landing page; `AGENTS.md` is the agent operating manual (rules, seams, traps) and must not restate user-facing features; `SOLUTION.md` is the troubleshooting sink; `SECURITY.md` is policy; `BACKLOG.md` and `CHANGELOG.md` are state. When two documents start explaining the same thing, one of them is wrong.
- Keep documents at their current size. If a change makes one grow, cut something.
- `BACKLOG.md` uses `[H1]`/`[M1]`/`[L1]` with `- [ ]` checkboxes. Shipped items are deleted, not checked; retired IDs are never reused.
- `SECURITY.md` documents auth, secret handling, reporting, and code-writing rules, and every credential surface that exists. Use placeholder credentials, never real ones.
- `SOLUTION.md` records symptom/cause/solution/prevention per topic. **Read it before touching runtime, CLI, or tests.**
- `README.md` is authoritative; `README.ko.md` mirrors it structurally — same headings, same length, same code blocks. `test_readme_ko_command_list_matches_registered_command_tree` enforces the command blocks agree with the CLI, and the section extractor depends on the literal phrase "View all options".
- The Pages homepage stays dependency-free: no Korean, and the only permitted `<script>` is `type="application/ld+json"`. Assets use absolute `/compman/...` paths because GitHub serves `404.html` at the requested URL.
- When you add a package, change architecture, or learn a bug-fix approach, record it in the Execution Log below.

## Execution Log

- **2026-10-02** — Homepage SEO pass: keyword-led title/description, canonical, robots/OG/Twitter tags, a hand-encoded 1200x630 PNG share card, `SoftwareApplication` + `FAQPage` JSON-LD, `robots.txt`, `sitemap.xml`, `favicon.svg`, a real 404 page, task-oriented Use cases / Install sections, and `tests/test_site_seo.py`. Fixed a mobile horizontal-overflow bug (grid children default to `min-width: auto`) and the stale "Python 3.10+" claim.
- **2026-10-02** — Slack stack-start notifications (v1.12.0): `notify.py`, `compose_spec.py`, the `notify.slack` block, a `doctor` `notify_env` check, and a `stack up`/`stack update` hook. Three `compose ps` assumptions were wrong until a real Docker run — it needs `--all`, it truncates `Mounts`, and it duplicates `Publishers` per address family.
- **2026-10-02** — Documentation pass. `AGENTS.md` halved (25.4KB → 13.1KB) by dropping its restatement of `README.md` and its rot-prone `Generated / Commit / Branch` header; `README.md` 32.2KB → 16.5KB by replacing prose walls with guarantee lists and tables; `SECURITY.md` gained the Slack, SSH, and on-host registry credential surfaces. Recorded here as the rule it produced: each root document owns one thing, and a document that grows must lose something.
- **2026-08-10** — Applied the gorani documentation governance in English: audited the six root documents, rewrote `SECURITY.md` into a real policy, and restructured `BACKLOG.md` into the labeled H/M/L checklist format.
