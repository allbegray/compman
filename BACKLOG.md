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

## Lower (L)

- [ ] [L12] `compman rollback` — retain the previous managed-tree snapshot
  during the `dirs.project` swap and restore it (configuration included) on
  demand; extends the existing transactional deploy swap whose only remaining
  non-rolled-back failure mode is post-swap scaffold generation.

- [ ] [L2] Config schema versioning — publish `compman.schema.v1.json`
  (draft derived from config.py parse rules) so editors can validate and
  doctor can report schema drift; bump the schema version whenever a key's
  meaning changes. Implementation sketch: extract the validation logic from
  load_config into pure functions keyed by schema version, then generate the
  JSON Schema from those functions' rules to keep one source of truth.

- [ ] [L13] Additional deploy/backup backends — evaluated against the three
  roadmap gates: GCS/Azure rejected for now (new SDK dependencies collide with
  the boto3 lazy-import lesson), SSH/SCP accepted as the candidate that fits
  the locked-down persona best. Implementation shape when picked up:
  an SshBackupStore sibling of S3BackupStore driving `ssh`/`scp` subprocesses
  through the existing runner seam, no new dependencies, keys assumed
  pre-provisioned on the host.

- [ ] [L14] Multi-stack registry — optional global registry mapping stack names
  to directories so `compman --stack NAME status` works without cd-ing into
  each stack directory. Largest UX win but touches config bootstrap for every
  command (`cli.py` load_config); schedule after the automation themes ship.

## Release roadmap (theme per minor release)

Each minor release carries one theme; patch releases stay fix-only. Backlog IDs
above feed the sequence below; re-balance at each minor bump rather than
planning further ahead.

- **1.8 — Automation ergonomics, concluded**: [M9] `stack up --wait` and
  [M10] project-scoped `--json` shipped in v1.8.0.
- **1.9 — Operational convenience**: [L12] rollback plus one of [L14]
  multi-stack registry or [L2] config schema versioning.
- Ongoing between minors: [M1] module splits, remaining [L] hygiene items.

Feature gate for any new candidate: real value for restricted-environment
users, minimal dependency cost (boto3 lazy-import lesson), and a size the 100%
coverage gate can absorb.
