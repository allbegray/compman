# Critical Review and Improvement Backlog

Reviewed against the current implementation and 100% statement/branch test suite.
Root causes and reusable lessons live in [SOLUTION.md](SOLUTION.md).

Policy: completed items are **removed** once shipped — git history preserves
them. Retired IDs are never reused.

## Medium (M)

- [ ] [M1] Split large modules and coverage-only tests — `cli.py` and
  `i18n.py` remain past the module-split target; recommended design: store
  translations as validated resources rather than one dict module. Watch item:
  `tests/test_docker.py` (~900 lines) — split the `ensure_ready_for_start`
  cluster into a `test_docker_desktop.py` once it passes ~900 lines. Relocate
  grouped edge-test files beside the modules they specify while retaining the
  100% gate. Note: the coverage-sweep half of this item shipped in v1.10.1
  ([M16]); only the module splits remain.
- [ ] [M19] Unify the tar-writing seam — `ops/seed.py` writes its seed archive
  with a direct `tarfile.open` call while volume/image backups go through
  `archive.create_tar`; route seed through the shared helper (add an `arcname`
  option) so one seam owns tar creation and no writer can drift from
  `DEFAULT_GZIP_LEVEL`.
- [ ] [M20] Smoke-test the published wheel — `publish.yml` builds the wheel on
  3.13 and uploads it with only a tag check; install that wheel in a fresh venv
  and run the packaging job's smoke commands (`--help`, `version`,
  `init --scaffold`, `--lang ko --help`, `completion bash`) before publishing.
- [ ] [M21] Locale-decoding sweep for scheduling and completion subprocesses —
  `compman/scheduling/{crontab,schtasks,launchd,systemd,pick}.py` and
  `compman/completion.py` still call `subprocess.run(..., text=True)` without
  `encoding=`, so their parsed output follows the ambient locale; Python 3.15's
  UTF-8-by-default flips that on non-UTF-8 hosts. `backup_store._run_proc` and
  the docker path already pass `encoding="utf-8", errors="replace"`; apply the
  same here, ideally through one shared `_run_text` helper in `_proc.py`.

## Low (L)

- [ ] [L26] PATH-dependent schedule test —
  `test_add_schedule_rejects_non_divisible_interval_for_cron`
  (`tests/test_ops_schedule.py`) is the only test in its family that does not
  patch `resolve_executable`, so a bare `python -m pytest` outside `uv run`
  fails on PATH resolution; patch it like its siblings.
- [ ] [L27] Inert uv.lock resolution fork — the lock's `resolution-markers`
  split at `python_full_version >= '3.15'` produces identical graphs for 3.14
  and 3.15 (`uv export` diff is header-only); regenerate with `uv lock` and
  either collapse the fork or record why it exists, so the next lock diff is
  reviewable.
- [ ] [L28] Windows verification for the `q` quit key — `follow.py`'s stop path
  is POSIX-verified against real Docker 29.8 (`q`+Enter exits 0, Ctrl-C still
  exits 130, no stray child), but the Windows branch only claims `terminate()`
  where the log streams would need the same live check; also unverified there is
  whether Windows terminals echo the typed line into the streamed output.

## Release roadmap (theme per minor release)

Each minor release carries one theme; patch releases stay fix-only. Backlog IDs
above feed the sequence below; re-balance at each minor bump rather than
planning further ahead.

- **1.13 — Streaming ergonomics, concluded**: the `q`+Enter quit key for the
  follow commands (`compman/follow.py`) shipped in v1.13.0. A single-key raw-mode
  quit remains an open candidate, as do a `watch` mode and log filtering.
- **1.12 — Notifications & discoverability, concluded**: Slack stack-start
  notifications (`notify.slack`, `COMPMAN_SLACK_WEBHOOK_URL`, `doctor` check) in
  v1.12.0, plus the homepage SEO pass and documentation condensation in v1.12.1.
  Other providers (Discord, generic webhook) remain open candidates.
- **1.11 — Scheduling visibility & audit, concluded**: `schedule status`
  with per-job run tracking, `--monthly` cadence, `compman history` journal,
  and `stack logs` shipped in v1.11.0 (feature ideas adopted from the
  post-1.10 ideation; not prior backlog IDs).
- **1.10.1 — Test-seam & hygiene, concluded**: [M16] failure-injectable
  DummyRuntime with loud overrides plus coverage-sweep retirement, [L24]
  helper dedup batch, [L25] exit-code/CLI consolidation.
- **1.10 — Operational convenience, concluded**: [L12] rollback, [L13]
  SSH/SCP backup stores, [L14] multi-stack registry, plus the 2026-08-26
  analysis wave ([H5]–[H8], [M13]–[M18], [L15]–[L23]) all shipped in v1.10.0.
- **1.9 — Backup format & restore ergonomics, concluded**: `--zstd` archives
  and offline volume restore shipped in v1.9.0.
- **1.8 — Automation ergonomics, concluded**: [M9] `stack up --wait` and
  [M10] project-scoped `--json` shipped in v1.8.0.
- Ongoing between minors: [M1] module splits.

Feature gate for any new candidate: real value for restricted-environment
users, minimal dependency cost (boto3 lazy-import lesson), and a size the 100%
coverage gate can absorb.
