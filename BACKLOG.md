# Critical Review and Improvement Backlog

Reviewed against the current implementation and 100% statement/branch test suite.
Root causes and reusable lessons live in [SOLUTION.md](SOLUTION.md).

Policy: completed items are **removed** once shipped — git history preserves
them. Retired IDs are never reused.

## Medium (M)

- [ ] [M1] Split large modules and coverage-only tests — `cli.py` (~720 lines)
  and `i18n.py` (~1100 lines) remain past the module-split target; recommended
  design: store translations as validated resources rather than one dict
  module. Watch item: `tests/test_docker.py` (~900 lines) — split the
  `ensure_ready_for_start` cluster into a `test_docker_desktop.py` once it
  passes ~900 lines. Relocate grouped edge-test files beside the modules they
  specify while retaining the 100% gate.

- [ ] [M16] Test-seam overhaul left open by SOLUTION.md §2: make DummyRuntime
  failure-injectable (scripted returncode/stdout sequences) instead of
  success-biased with ad-hoc per-test MagicMock patches, drop its unused
  `return_code` alias field, override the full base surface explicitly so
  missing overrides are loud; then retire the coverage-sweep files
  (`tests/test_missing_coverage.py`, `tests/test_coverage_completion.py`) by
  folding behavior-bearing cases into feature files under behavior-describing
  names.

## Lower (L)

- [ ] [L24] Helper dedup batch: diagnostics._utc_now_iso duplicates
  ops.common.utc_now_iso; ops/schedule.py inlines datetime.now below its own
  utc_now_iso import; container.stats re-implements parse_compose_ps inline;
  launchd rebuilds StartInterval/StartCalendarInterval logic that the exported,
  tested cadence.launchd_start_spec seam exists for; image._list_backups
  duplicates volume's kind-aware version.

- [ ] [L25] Exit-code cleanup: standardize on CommandError(msg, code=…) at the
  single CLI boundary instead of the three current idioms (typer.Exit,
  SystemExit(code), raise SystemExit(1) inline); share Annotated
  ConfigOpt/ProfileOpt aliases across ~15 commands and attach
  HelpOnUnknownCommandGroup via one Typer-group factory.

## Release roadmap (theme per minor release)

Each minor release carries one theme; patch releases stay fix-only. Backlog IDs
above feed the sequence below; re-balance at each minor bump rather than
planning further ahead.

- **1.8 — Automation ergonomics, concluded**: [M9] `stack up --wait` and
  [M10] project-scoped `--json` shipped in v1.8.0.
- **1.9 — Backup format & restore ergonomics, concluded**: `--zstd` archives
  and offline volume restore shipped in v1.9.0.
- **1.10 — Operational convenience, concluded**: [L12] rollback, [L13]
  SSH/SCP backup stores, [L14] multi-stack registry, plus the 2026-08-26
  analysis wave ([H5]–[H8], [M13]–[M18], [L15]–[L23]) all shipped in v1.10.0.
- Ongoing between minors: [M1] module splits, [M16] test-seam overhaul,
  remaining [L] hygiene items ([L24], [L25]).

Feature gate for any new candidate: real value for restricted-environment
users, minimal dependency cost (boto3 lazy-import lesson), and a size the 100%
coverage gate can absorb.
