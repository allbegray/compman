# Critical Review and Improvement Backlog

Reviewed against the current implementation and 100% statement/branch test suite.
Root causes and reusable lessons for everything below live in [SOLUTION.md](SOLUTION.md).

## High (H)

- [x] [H1] Deploy checksum/object-version pinning — user-configured SHA-256 via
  `deploy: {url, sha256}` or `--sha256`, verified after download and before
  extraction/build/swap; S3 prefix sources reject pins before any download.
  Version-id pinning deferred (adds no detection power beyond the digest);
  tracked under the 1.6 theme follow-ups.

- [ ] [H4] Remote backup upload — `volume backup`/`image backup` archives land
  only in local `dirs.backup`; losing the host loses the backups too. Add an
  opt-in upload target (flag such as `--push s3://bucket/key` or a config
  `backup.upload` block) reusing the boto3 client setup from `s3_source.py`
  (endpoint override via `AWS_ENDPOINT_URL*`, standard AWS credentials), and
  echo the uploaded key and byte size as provenance like deploy does. Restore/
  pull-side remote support stays out of scope until upload is proven.

- [x] [H2] Enforce deploy size caps during download and extraction — the
  `limits.max_archive_mb` check runs only after `_fetch` has downloaded AND
  extracted the source into `.deploy_tmp_*` (`deploy.py:99-103`; unbounded
  streaming `http_source.py:22`; uncapped S3 pagination `s3_source.py:19-20,
  27-35`), so a malicious or misconfigured remote source can exhaust disk
  even when a limit is configured. SECURITY.md's "caps the size before any
  filesystem change" claim is false until this is fixed; correct it together
  with the code.

- [x] [H3] Validate volume-map.json contents before restore/push —
  `_load_mapping` checks key presence only (`ops/volume.py:238-241`); an
  attacker-controlled backup tarball can escape `restore_dir` via the
  `volume` field (`ops/volume.py:117`), copying arbitrary host directories
  into any container, with destinations unvalidated unless `--replace` is
  given (`ops/volume.py:110,122,183-195`).

## Medium (M)

- [ ] [M1] Split large modules and coverage-only tests — `completion_cmd` and
  `init_cmd` have been extracted to `compman/completion.py` and
  `compman/init_cmd.py`. `cli.py` (~650 lines) has grown back past the
  module-split target since the last review, and `i18n.py` (~900 lines)
  remains large; `tests/test_missing_coverage.py` plus
  `test_coverage_completion.py` still group unrelated cases. Recommended
  design: store translations as validated resources, relocate edge tests
  beside the module they specify while retaining the 100% gate. Watch item:
  `tests/test_docker.py` (851 lines) — split the `ensure_ready_for_start`
  cluster into a `test_docker_desktop.py` once it passes ~900 lines.

- [x] [M2] Unify subprocess timeout policy and the ops error contract —
  `_passthru` hardcodes timeout=3600 ignoring COMPMAN_TIMEOUT
  (`docker.py:384`, message text `docker.py:388`); `_run_upgrade_command`
  and the completion PowerShell probe run with no timeout (`cli.py:331-338`,
  `completion.py:25`); `deploy()` wraps everything in a broad
  `except Exception` -> SystemExit boundary that drops CommandError
  semantics and the chain (`deploy.py:118-122`); seed and completion
  `--install` print errors yet exit 0 (`ops/seed.py:27-32`,
  `completion.py:41-42`), against compman/ops/AGENTS.md conventions.

- [x] [M3] Lazy-import boto3/botocore off non-AWS command paths —
  `docker.py:14` eagerly pulls env_source (boto3/botocore) into every
  runtime-touching command (~300-600ms each), and `deploy.py:9-17` loads
  boto3 even for HTTP-only deploys; move imports into the secret-resolution
  and S3 branches.

- [x] [M4] Close test-contract gaps — the bash-to-sh connect fallback built
  in `docker.py:124-132` is never asserted (tests only check
  `passthru.call_count == 5`, `tests/test_coverage_completion.py:197-205`,
  with further count-only asserts in `tests/test_docker.py:183-191` and
  `tests/test_missing_coverage.py:190`);
  `tests/test_ops_service.py::test_service_log_multiple_containers` asserts
  nothing; the CI integration job covers only deploy/up/status/down
  (`.github/workflows/ci.yml:57-92`), leaving volume/image backup, ps/stats,
  doctor/status --json and service log/connect without real-runtime checks.

- [x] [M5] Route remaining hardcoded user-facing strings through t() — the
  interactive init menu (`init_cmd.py:36-41`) and the status header labels
  (`cli.py:249-256`) bypass translation because they reach echo/prompt via
  variables; extend the AST literal scan (tests/test_repository_urls.py) to
  cover prompt_select args and variable-built echoes.

- [ ] [M7] Authenticated HTTP(S) deploy sources — `http_source.py` accepts
  public archive URLs only (30s timeout, no auth options). Add opt-in
  header-based authentication (e.g. `deploy.auth: { header, value_env }`
  reading the token from an environment variable so no secret lands in
  `compman.yml`), preserving the existing redirect-target scheme/suffix
  re-validation.

- [ ] [M8] Backup retention policy — optional `limits.max_backups: N` pruning
  the oldest `<stack>.volume.*` / `<stack>.image.*` archives in `dirs.backup`
  after each successful backup, echoing exactly what was removed. Only files
  inside the managed backup directory may ever be deleted. Combined with cron,
  this completes the unattended-backup story alongside [H4].

- [ ] [M9] `stack up --wait` readiness gate — after up/update, poll service
  health (compose ps / health status) until running/healthy or COMPMAN_TIMEOUT
  elapses, exiting non-zero on failure so scripts and CI fail fast instead of
  racing the first request.

- [ ] [M10] Machine-readable output beyond diagnostics — extend the schema-
  versioned `--json` pattern (doctor/status) to `ps`, `stats`, and backup
  listings so automation consumes results without scraping human-readable text.

## Lower (L)

- [ ] [L1] Preserve underlying exception chains for support diagnostics
  (structured/debug logging itself is intentionally rejected — the project
  convention forbids stdlib `logging`; output flows through `typer.echo` + `t()`).
- [ ] [L2] Validate configuration against an explicit schema and publish a
  versioned config format.
- [ ] [L3] Add documentation checks for broken links and Markdown consistency
  (command-list validation against the typer tree already exists in
  `tests/test_cli.py`).

- [x] [L4] Deduplicate ops volume/image logic — backup vs pull repeat the
  guard sequence and mount-mapping loop verbatim (`ops/volume.py:29-64` vs
  `138-165`); restore vs push repeat unpack/warn/copy/fix-permissions
  (`:113-131` vs `:183-195`); the timestamp-collision retry block is
  duplicated between `ops/image.py:28-38` and `ops/volume.py:35-45`;
  extract shared helpers into ops/common.py.

- [x] [L5] Table-drive repetitive branch ladders — completion installs
  triplicate read-check-append-echo per shell (`completion.py:45-84`);
  detect_runtime repeats four near-identical probe blocks
  (`docker.py:280-318`); resolve_compose_context re-implements the fallback
  expression and profile lookup of resolve_compose_files
  (`docker.py:471-477` vs `502-512`).

- [x] [L6] Typing and dataclass-convention cleanup — untyped params
  `_load_mapping(path)` (`ops/volume.py:223`) and the s3 client args
  (`s3_source.py:8`); `limits: dict[str, Any]` instead of a typed field
  (`config.py:54`); SecretRef is a mutable value object contrary to the
  frozen-dataclass convention (`config.py:35-37`), and ContainerRuntime is
  likewise mutable (`docker.py:17`).
  Follow-up: freezing ContainerRuntime is deferred until the Wave-2
  timeout/lazy-import work has fully settled; Config intentionally stays
  mutable.

- [x] [L7] Move the seed HTML asset out of business logic — generate_seed
  embeds a 65-line HTML/CSS/JS string (`ops/seed.py:36-70`); hoist it to a
  module constant or template and dedupe the 18080 port default
  (`seed.py:16`, `scaffold.py:46`).
  Follow-up: `init_cmd.py:19,:32` and `scaffold.py:46` still carry their own
  18080 literals; they should reuse `ops.common.DEFAULT_SEED_PORT` when those
  CLI/scaffold surfaces are next touched.

- [x] [L8] Test-suite hygiene — extract a conftest helper for the 34
  identical compman.yml write_text blobs across five test files; add
  filterwarnings=["error"] and strict addopts/markers to
  [tool.pytest.ini_options]; parametrize the six near-duplicate
  COMPMAN_TIMEOUT tests (`tests/test_docker.py:651-704`).

- [x] [L9] Docs and automation ergonomics — document the `upgrade --repo`
  flag (`cli.py:343`) and its pinned `--python 3.13` that README's upgrade
  description omits (`cli.py:357-358`); reconcile the -c/--config listing
  inconsistency in README's Commands block; add remediation/error-code
  fields and provenance (generated_at, config path) to the doctor/status
  JSON schema v1 (`diagnostics.py:12-77`); add a limits.max_archive_mb
  example under examples/compman-config/.

- [x] [L10] Packaging and CI/release hardening — declare [build-system] and
  PyPI metadata (readme/urls/classifiers) in pyproject.toml; decide the
  requires-python floor before Python 3.10 EOL (October 2026); add
  concurrency cancel-in-progress to ci.yml, gate publish.yml on CI success,
  set timeout-minutes on the test job, pin gh-action-pypi-publish; switch
  install.ps1 to $ErrorActionPreference="Stop" and pin/hash the uv installer
  fetch; give install.sh a fish PATH story and fix its literal `\n` echo
  (`install.sh:40`); bound or replace the private `typer._click` import
  (`cli.py:14`) against the unbounded typer requirement.

- [x] [L11] Archive-extraction and disclosure leftovers — reject tar
  device/FIFO members on all supported Python versions (filter="data"
  parity exists only on 3.12+, `archive.py:16-19`); re-validate scheme and
  suffix after HTTP redirects (`http_source.py:15-16,21`); stop echoing the
  full compman.yml including the secrets ARN block during scaffold updates
  (`scaffold.py:115,125`).

- [ ] [L12] `compman rollback` — retain the previous managed-tree snapshot
  during the `dirs.project` swap and restore it (configuration included) on
  demand; extends the existing transactional deploy swap whose only remaining
  non-rolled-back failure mode is post-swap scaffold generation.

- [ ] [L13] Additional deploy/backup backends — GCS, Azure Blob, or SSH/SCP.
  Evaluate each against the three roadmap gates: real value for
  restricted-environment users, dependency cost (boto3 lazy-import lesson), and
  100% coverage burden. SSH/SCP likely fits the locked-down persona best.

- [ ] [L14] Multi-stack registry — optional global registry mapping stack names
  to directories so `compman --stack NAME status` works without cd-ing into
  each stack directory. Largest UX win but touches config bootstrap for every
  command (`cli.py` load_config); schedule only after the 1.6/1.7 themes ship.

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

DONE (2026-08-24): the floor decision landed — `requires-python = ">=3.12"` in
pyproject.toml, ruff/mypy target 3.12, and CI tests 3.12–3.14.

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

- [ ] [M6] Integration test infrastructure: fix timestamp derivation bug in
  tests/integration/test_real_runtime.py (.stem.split keeps .tar suffix ->
  validate_timestamp rejects) and redesign downed-stack volume restore path
  (compose down removes containers -> list_containers empty -> map validation
  fails; needs helper-container copy strategy).

## Release roadmap (theme per minor release)

Each minor release carries one theme; patch releases stay fix-only. Backlog IDs
above feed the sequence below; re-balance at each minor bump rather than
planning further ahead.

- **1.6 — Deploy/backup trust**: [H1] deploy checksum/object-version pinning,
  [H4] remote backup upload, [M7] authenticated HTTP deploys.
- **1.7 — Automation ergonomics**: [M9] `stack up --wait`, [M8] backup
  retention, [M10] project-scoped `--json` beyond doctor/status.
- **1.8 — Operational convenience**: [L12] rollback, plus one of [L14]
  multi-stack registry or [L2] config schema versioning.
- Ongoing between minors: [M1] module splits, [M6] integration-test fixes, and
  remaining [L] hygiene items.

Feature gate for any new candidate: real value for restricted-environment
users, minimal dependency cost (boto3 lazy-import lesson), and a size the 100%
coverage gate can absorb.
