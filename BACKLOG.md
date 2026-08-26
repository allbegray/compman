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
- **1.10.1 — Test-seam & hygiene, concluded**: [M16] failure-injectable
  DummyRuntime with loud overrides plus coverage-sweep retirement, [L24]
  helper dedup batch, [L25] exit-code/CLI consolidation.
- Ongoing between minors: [M1] module splits.

Feature gate for any new candidate: real value for restricted-environment
users, minimal dependency cost (boto3 lazy-import lesson), and a size the 100%
coverage gate can absorb.
