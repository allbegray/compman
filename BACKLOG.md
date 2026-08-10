# Critical Review and Improvement Backlog

Reviewed against the current implementation and 100% statement/branch test suite.
Root causes and reusable lessons for everything below live in [SOLUTION.md](SOLUTION.md).

## High (H)

- [ ] [H1] Deploy checksum/object-version pinning — `limits.max_archive_mb` is in
  place; the remaining integrity gap is that there is no user-configured SHA-256
  checksum or S3 object-version pin to detect a trusted-but-compromised bucket
  delivering an altered artifact.

## Medium (M)

- [ ] [M1] Split large modules and coverage-only tests — `completion_cmd` and
  `init_cmd` have been extracted to `compman/completion.py` and
  `compman/init_cmd.py`. `cli.py` (~553 lines) is now near the module-split
  target, but `i18n.py` (~850 lines) remains large, and
  `tests/test_missing_coverage.py` plus `test_coverage_completion.py` still group
  unrelated cases. Recommended design: store translations as validated resources,
  relocate edge tests beside the module they specify while retaining the 100%
  gate. Watch item: `tests/test_docker.py` (~800 lines) — split the
  `ensure_ready_for_start` cluster into a `test_docker_desktop.py` once it passes
  ~900 lines.

## Lower (L)

- [ ] [L1] Preserve underlying exception chains for support diagnostics
  (structured/debug logging itself is intentionally rejected — the project
  convention forbids stdlib `logging`; output flows through `typer.echo` + `t()`).
- [ ] [L2] Validate configuration against an explicit schema and publish a
  versioned config format.
- [ ] [L3] Add documentation checks for broken links and Markdown consistency
  (command-list validation against the typer tree already exists in
  `tests/test_cli.py`).

## Resolved (2026-08-07)

- [x] Stale PowerShell completion snippet: `seed` removed, `lang` added.
- [x] i18n violation in `ops/image.py`: invalid-timestamp `CommandError` now translated.
- [x] All hardcoded user-facing strings routed through `t()` (echo/confirm/prompt +
      option `help`), including a second round covering `cli.py`/`scaffold.py`/
      `deploy.py`/`ops/{service,common}.py`.
- [x] Test-suite hardening: i18n key-integrity tests, completion/README
      cross-validation against the typer tree, AST scan for untranslated literals;
      fixed a `_CURRENT_LANG` ContextVar leak with an autouse fixture.
- [x] `clear` now requires `--yes` (destructive global prune is guarded).
- [x] `scratch/` untracked and gitignored; `.omo/` gitignored.
- [x] Style: `typing.Optional` → PEP 604 in `cli.py`; vestigial
      `global _CURRENT_LANG` removed.
- [x] runpy warning removed (`runpy.run_path`); suite is warning-free.
- [x] `volume restore/push --replace` (byte-for-byte replace; validated destination).
- [x] `completion` and `init` extracted from `cli.py` (`compman/completion.py`,
      `compman/init_cmd.py`); cli.py ~553 lines.
- [x] Release engineering: dependency lower bounds, `checkout@v7` consistency,
      PyPI trusted publishing (`publish.yml`), expanded packaging smoke.
- [x] Deploy transactional through the build step (build before swap).
- [x] Python 3.14 in CI (test matrix + quality/packaging jobs).
- [x] `service log/connect` resolve service names via `compose ps -q`
      (scaled-instance guidance).
- [x] Deploy integrity: `limits.max_archive_mb` cap + provenance echo.
- [x] Configurable operation timeout via `COMPMAN_TIMEOUT`.
- [x] Dead code removed (`volume._fix_permissions`); `validate_timestamp`
      consolidated into `ops/common.py`.
- [x] Unsupported completion shell now errors instead of silently succeeding.

## Python version strategy

As of July 2026, Python 3.14 is the latest stable feature line and Python 3.10
reaches end of support in October 2026. The project metadata still supports
`>=3.10`, and CI now tests 3.10–3.14 with `quality`/`packaging` on 3.14.

Recommended sequence:

1. Keep 3.10 compatibility only if existing deployment hosts require it.
2. Before October 2026, raise the minimum to 3.11 or preferably 3.12 after
   checking target OS availability.
3. Do not enable the experimental JIT or adopt the free-threaded build merely
   for this CLI; its work is dominated by subprocess, filesystem, Docker, and
   network waits rather than CPU-bound Python threads.
4. Consider Python 3.14's standard-library Zstandard support only as a
   versioned, opt-in backup format. Retain `.tar.gz` read compatibility.
