# Critical Review and Improvement Backlog

Reviewed against the current implementation and 100% statement/branch test suite.
Root causes and reusable lessons live in [SOLUTION.md](SOLUTION.md).

Policy: completed items are **removed** once shipped — git history preserves
them. Retired IDs are never reused.

## High (H)

Correctness/security defects found by the 2026-08-26 full-repo analysis; ride
fix-only patch releases.

- [ ] [H5] Fix `image backup --zstd` end to end — the archive it creates can
  never be restored. `ops/image.py` calls `new_backup_paths` without
  `zstd_format`, so a zstd payload is written under a `.tar.gz` name, while
  `image restore` independently hardcodes `.tar.gz` when staging the archive.
  Mirror the volume path (`ops/volume.py`): pass the flag through to
  `new_backup_paths` and resolve stored suffixes via `find_archive`.

- [ ] [H6] Reject profile-less configs with `ConfigError` instead of a raw
  `StopIteration` traceback. `load_config` accepts `compose:` containing only
  `base:`; the first `resolve_compose_context` call then raises bare
  `StopIteration` (`next(iter(config.profiles))`) that escapes the CLI error
  boundary (which catches only CommandError/ConfigError/RuntimeError). One
  guard in `load_config`; the published JSON schema already requires a named
  default profile.

- [ ] [H7] Verify scheduler adapter success before recording a job. crontab,
  launchd, systemd, and schtasks adapters ignore their subprocess results, so a
  failed `crontab -` / `launchctl bootstrap` / `systemctl enable --now` /
  `schtasks /Create` still saves the JobRecord and prints "registered"; the
  file-presence `exists()` probes (launchd/systemd) then report such jobs as
  healthy in `schedule list`, unlike cron/schtasks which probe live state.
  Check returncodes before `save_registry` and align `exists()` with live state
  (`launchctl print`, `systemctl is-enabled`).

- [ ] [H8] Drop the deploy auth header on scheme-downgrade redirects. The
  auth-aware redirect handler strips the header only when the redirect leaves
  the host; a same-host https→http redirect resends the token in plaintext.
  Strip on any https→http move regardless of host.

## Medium (M)

- [ ] [M1] Split large modules and coverage-only tests — `cli.py` (~720 lines)
  and `i18n.py` (~1100 lines) remain past the module-split target; recommended
  design: store translations as validated resources rather than one dict
  module. Watch item: `tests/test_docker.py` (~900 lines) — split the
  `ensure_ready_for_start` cluster into a `test_docker_desktop.py` once it
  passes ~900 lines. Relocate grouped edge-test files beside the modules they
  specify while retaining the 100% gate.

- [ ] [M13] Serialize `schedules.json` writers. add/remove run an unlocked
  load→mutate→save cycle through one shared fixed `schedules.json.tmp`, so
  interleaved invocations can publish corrupt JSON whose quarantine-to-empty
  load silently discards every registered job. Advisory file lock plus unique
  temp names.

- [ ] [M14] Harden `stack_paused` failure edges: a failed `compose stop` leaves
  `stopped=False`, so the finally block never restarts an already partially
  stopped stack; and the blanket `compose start` resurrects services the
  operator had deliberately stopped before the backup. Track what compman
  stopped and restart exactly that set.

- [ ] [M15] Run the integration-marked suite in CI. `addopts` deselects
  `-m integration` and no workflow overrides it, so
  `tests/integration/test_real_runtime.py` never executes anywhere — while its
  docstring claims CI runs that selector — leaving the live-Docker net
  (the class that caught two past 100%-coverage-passing bugs) unguarded. Add
  `uv run pytest -m integration` to the ci.yml integration job and correct the
  docstring.

- [ ] [M16] Test-seam overhaul left open by SOLUTION.md §2: make DummyRuntime
  failure-injectable (scripted returncode/stdout sequences) instead of
  success-biased with ad-hoc per-test MagicMock patches, drop its unused
  `return_code` alias field, override the full base surface explicitly so
  missing overrides are loud; then retire the coverage-sweep files
  (`tests/test_missing_coverage.py`, `tests/test_coverage_completion.py`) by
  folding behavior-bearing cases into feature files under behavior-describing
  names.

- [ ] [M17] Config error-surface gaps: `limits.*` validation accepts YAML
  booleans as integers (`isinstance(True, int)`), so `max_backups: true`
  silently keeps 1 archive instead of failing like `'10'`/`-1` do; and
  `cli._load` catches only ConfigError, so an unreadable compman.yml surfaces
  as a raw OSError traceback from every stack command while `status` shows the
  clean localized message.

- [ ] [M18] Docs accuracy sweep: README and example 13 promise
  `%APPDATA%\compman\schedules.json` on Windows but `registry_path()` hardcodes
  `~/.config` everywhere; README shows `schedule remove daily-04-30`, a name
  the tool never generates (default `<stack>.volume`), omitting `--name`;
  SECURITY.md still states HTTP downloads have no authentication despite the
  shipped `deploy.auth`; the `--zstd` flag and `.tar.zst` names are documented
  nowhere (README archive-name patterns list `.tar.gz` only). Decide the
  Windows path question code-side or docs-side first.

## Lower (L)

- [ ] [L12] `compman rollback` — retain the previous managed-tree snapshot
  during the `dirs.project` swap and restore it (configuration included) on
  demand; extends the existing transactional deploy swap whose only remaining
  non-rolled-back failure mode is post-swap scaffold generation.

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

- [ ] [L15] Render `remediation`/`detail` in human doctor output; both are
  produced for every failing check and serialized under `--json`, but the
  default renderer prints only `marker id: message`, hiding the how-to-fix
  guidance behind the machine surface.

- [ ] [L16] Route `init` modes on explicit flags only: `port != 18080` doubles
  as a seed-mode sentinel, so `compman init -p 8080` (or bare `--archive`)
  silently generates the throwaway seed project instead of prompting.

- [ ] [L17] Derive the upgrade interpreter from the running interpreter instead
  of hardcoding `--python 3.13`, which force-reinstalls 3.12 users onto 3.13
  and ages independently of the declared >=3.12 floor.

- [ ] [L18] Unify the two compman.yml generators: scaffold output lacks the
  yaml-language-server schema header that dump_default_config writes, and
  update_deploy's last-resort fallback rewrites whole files via `safe_dump`,
  destroying user comments the surrounding line surgery preserved.

- [ ] [L19] Reconcile docs/site/compman.schema.json with the parser: remove the
  never-read `backup` property, widen `deploy.sha256` to the case-insensitive
  hex the parser actually accepts and normalizes, and align the
  required-profile wording once [H6] lands.

- [ ] [L20] Extend the i18n AST guard with en/ko placeholder-set parity
  (compare `string.Formatter().parse` sets per key); today a mismatched
  placeholder ships green and renders literally at runtime because `t()`
  swallows format errors.

- [ ] [L21] Subprocess/resource hygiene: honor COMPMAN_TIMEOUT beyond runtime
  CLIs (http_source pins 30 s sockets), build boto3 clients with explicit
  timeout/retry Config and reuse one client per invocation instead of one per
  call, and translate `subprocess.TimeoutExpired` at the CLI error boundary
  like other expected failures.

- [ ] [L22] Platform-safe quoting for scheduler payloads: systemd ExecStart
  uses POSIX shlex.join syntax that systemd does not parse (single quotes stay
  literal, spaced paths break the unit at fire time), and the schtasks /TR
  payload quotes only argv[0].

- [ ] [L23] Installer parity/hardening: install.sh pipes the floating astral.sh
  installer into sh where install.ps1 already pins uv and SHA256-verifies;
  install.ps1 should not force RemoteSigned execution policy as a silent side
  effect of completion registration.

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
  and offline volume restore shipped in v1.9.0; [H5] tracks the image-path
  defect that shipped with it.
- **1.10 — Operational convenience**: [L12] rollback plus [L14]
  multi-stack registry.
- Ongoing between minors: [M1] module splits, [M15]/[M16] gate repairs,
  remaining [L] hygiene items.

Patch track: [H5]–[H8] are correctness/security fixes landing as fix-only
patch releases as each is verified; [M13]–[M18] join whichever theme absorbs
them first.

Feature gate for any new candidate: real value for restricted-environment
users, minimal dependency cost (boto3 lazy-import lesson), and a size the 100%
coverage gate can absorb.
