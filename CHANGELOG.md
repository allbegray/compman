# Changelog

Major user-visible changes to compman are recorded here, with the newest release
first.

## [1.10.1] - 2026-08-26

### Changed

- Internal quality release with no user-visible behavior changes: unified the
  CLI error boundary on a single `CommandError` idiom, shared option
  annotations and one sub-group factory across the command tree, consolidated
  five duplicated helpers (diagnostics/schedule/container/launchd/backup
  listing) into their canonical seams, overhauled the test double to be
  failure-injectable with loud missing overrides, and retired the two
  coverage-sweep test files by folding behavioral cases into feature files.

## [1.10.0] - 2026-08-26

### Added

- Multi-stack registry: a successful deploy records the stack directory, so
  `compman --stack NAME <command>` works from any directory and
  `compman stacks list [--json]` / `compman stacks remove NAME` manage entries.
- `compman rollback`: every successful deploy keeps the previous managed tree
  and `compman.yml` as an automatic snapshot; rollback restores that snapshot
  transactionally (including the post-swap scaffold-failure case).
- SSH backup stores: `dirs.backup: ssh://[user@]host[:port]/path` stores
  volume/image backups on a remote host via ssh/scp — no new dependencies,
  keys assumed pre-provisioned.
- `doctor` human output now prints each failing/warning check's detail and
  remediation guidance (previously only visible through `--json`).

### Changed

- Scheduled backup installs are verified: crontab/launchd/systemd/schtasks
  installation failures now abort registration with a clear error instead of
  recording a job that never fires; `schedule list` probes live state on every
  platform.
- Schedule registry writes use an advisory lock and unique temp files;
  concurrent `schedule add`/`remove` can no longer corrupt `schedules.json`.
- Backups stop only the services that are running and restart exactly those;
  a failed stop no longer leaves the stack partially down, and services the
  operator stopped deliberately stay down.
- HTTP deploy socket timeouts follow `COMPMAN_TIMEOUT`; boto3 clients use
  explicit connect/read timeouts with standard retries.
- `compman upgrade` reinstalls under the running interpreter version instead
  of pinning Python 3.13.
- Windows keeps schedules under `%APPDATA%\compman` when APPDATA is set.
- `init` routes modes on explicit flags only: `init -p PORT` opens the
  interactive menu instead of silently generating the seed project.
- Scaffolded `compman.yml` carries the yaml-language-server schema header, and
  the update fallback preserves the original file as `.bak`.

### Fixed

- `image backup --zstd` wrote zstd data under a `.tar.gz` name and could never
  be restored; archive naming and restore resolution now follow `--zstd`
  end to end.
- A `compose:` mapping without any named profile fails with a clear config
  error instead of a `StopIteration` traceback.
- An unreadable `compman.yml` now exits with a concise message on every
  command, matching what `status` already showed.
- `limits` values reject YAML booleans (`max_backups: true`) instead of
  silently changing retention.
- Deploy auth headers are dropped on https→http redirect downgrades even when
  the redirect stays on the same host.
- systemd timer `ExecStart` and schtasks `/TR` payloads quote arguments safely
  for spaces and special characters.
- `install.sh` pins uv and verifies SHA256 checksums before installing;
  `install.ps1` no longer changes the execution policy as a side effect.

## [1.9.0] - 2026-08-26

### Added

- Zstandard backup format: `--zstd` on `volume backup` / `image backup` writes
  `.tar.zst` archives (smaller and faster than gzip at default levels).
  Requires the CLI to run on Python 3.14+; restores transparently detect and
  read `.tar.zst` from any store.
- Offline volume restore: when every container is stopped, restore temporarily
  starts the stack, restores the volumes, then stops it again — previously this
  failed mapping validation.
- Deploy surfaces `compman.yml` parse errors directly instead of showing the
  empty-directory onboarding hints.
- Command-not-found errors keep the original exception chain for diagnostics.

## [1.8.0] - 2026-08-25

### Added

- `stack up --wait` / `stack update --wait`: after starting the stack, compman
  polls service states until every service is running (or healthy) and exits
  non-zero with a per-service detail if the COMPMAN_TIMEOUT budget elapses.
- Machine-readable output: `--json` on `compman ps`, `compman stats`, and
  `compman schedule list` emits schema-version 1 payloads with generated_at.
  Empty states serialize as empty arrays.

### Fixed

- `update` now rebuilds exactly the image referenced by the existing compose
  configuration instead of a directory-derived default, so stacks deployed with
  `--tag` no longer keep running a stale image after an update. With multiple
  distinct service images the rebuild target is ambiguous: update skips it and
  warns, listing every image found.
- The real-runtime integration module passes again: restore-timestamp
  derivation keeps only the bare timestamp, and the downed-stack restore leg
  documents its clean-failure behavior.

## [1.7.1] - 2026-08-25

### Added

- Korean README (`README.ko.md`) mirroring the English documentation, with
  language-switcher links on both files and command-block sync validation so
  the mirror cannot drift from the CLI.

### Changed

- Backup listings are ordered most-recent-first, and interactive restore now
  preselects the newest backup.

## [1.7.0] - 2026-08-25

### Added

- Backup retention policy: optional `limits.max_backups: N` keeps only the
  newest N archives per stack and kind, pruning older ones from the configured
  store (local directory or S3 bucket) after each successful volume/image
  backup. Every removal is echoed; a failed deletion warns and continues.
- Backup listings are ordered most-recent-first, and interactive restore now
  preselects the newest backup.

## [1.6.2] - 2026-08-25

### Fixed

- Scheduled backups now run correctly: the registered job payload placed
  `--config` before the subcommand where the CLI does not accept it, so every
  launchd/cron/systemd/schtasks firing failed with "No such option: -c".
- Scheduled jobs embed the registering shell's `PATH` (launchd
  EnvironmentVariables, a PATH line inside the crontab marker block, an
  Environment directive in the systemd service) so the container runtime is
  found without a user shell environment.
- The corrupt-schedule-registry warning is translated like every other message.

## [1.6.1] - 2026-08-25

### Fixed

- S3 API calls now pass `Bucket`/`Key` as keyword arguments. Recent botocore
  releases reject positional arguments on API operations, which broke remote
  backup-store uploads at the post-upload size verification and the deploy
  source size-cap check when `limits.max_archive_mb` is configured.

## [1.6.0] - 2026-08-25

### Added

- Deploy integrity pinning: an optional `deploy.sha256` value (or `--sha256 HEX`
  on `compman deploy`) verifies the fetched source after download and before
  extraction, image build, or managed-tree swap; a mismatch aborts with exit
  status 1 and nothing changes. The pin applies whenever the deployed source URL
  equals the configured `deploy` URL, so `update` inherits it automatically.
  `compman doctor` warns when a deploy source is configured without a pin.
- Authenticated HTTPS deploy sources: an optional `deploy.auth { header,
  value_env }` block sends a request header whose value is read at fetch time
  from the named environment variable. The token is never stored in
  `compman.yml` nor echoed, authenticated sources require `https://`, and a
  redirect to a different host drops the auth header. `compman doctor` warns
  when the environment variable is unset.
- Scheduled volume backups: `compman schedule add|list|remove` registers
  platform-native jobs (launchd on macOS, systemd user timers with crontab
  fallback on Linux, Task Scheduler on Windows) that run `volume backup`
  unattended. Cadences are `--every Nm|Nh`, `--daily HH:MM`, or
  `--weekly DAY HH:MM`; jobs compose with the configured backup store, list
  marks absent platform artifacts `[missing]`, and remove tolerates them.
  Shell completion covers the new commands; help ships in English and Korean.
- S3 as a first-class backup store: `dirs.backup` accepts either a local path
  or `s3://bucket/prefix`. Backups stage locally, upload with content-type and
  remote size verification, and delete the staged copy after success (a failed
  upload preserves it and names its path); restores list, select, and download
  from the store automatically. Scheduled backups inherit the store from the
  configuration. `compman doctor` warns when a remote store is configured but
  AWS credentials or region are missing.

### Changed

- Scheduled-job output logs live next to `schedules.json` (the schedule
  registry) instead of inside the backup directory.

## [1.5.0] - 2026-08-24

### Added
- Deploy source size caps enforced during download (chunked HTTP, S3 object sizes) and extraction (uncompressed member totals)
- Volume-map validation on restore/push: path containment, container membership, destination checks
- Tar device/FIFO member rejection on all supported Python versions
- HTTP redirect target re-validation (scheme + archive suffix)
- Integration test module (`pytest -m integration`) with real-Docker volume roundtrip and doctor JSON cases
- `tests/conftest.py` config YAML builder (`DEFAULT_CONFIG_YAML` + `write_config`)
- `limits.max_archive_mb` example under `examples/compman-config/`
- Diagnostics JSON additive fields (schema version stays `1`): `status` reports an `error_code` (`config-error`, `compose-error`, `runtime-error`, or `stack-missing`) plus `generated_at` (ISO-UTC) and `config_path`; every doctor check reports `remediation` and `detail` keys (null for now)

### Changed
- Python support floor raised to >=3.12 (3.10 EOL October 2026)
- Long-running Docker/subprocess operations now all honor `COMPMAN_TIMEOUT` (default 300 seconds). Previously some operations used a hardcoded one-hour timeout that ignored the environment variable.
- Streaming commands (`service log -f`, `service connect`, `stats -f`) now run without any timeout so they can stream indefinitely.
- Deploy size-limit enforcement moved earlier: when `limits.max_archive_mb` is configured, oversized sources are aborted during download/extraction with the translated limit message instead of failing after extraction; other deploy failures now report the stage they failed in.
- boto3/botocore imports deferred to AWS-touching paths (faster startup for non-AWS commands)
- Scaffold update no longer echoes full `compman.yml` content (prevents ARN disclosure in terminal)
- `compman doctor --json` output no longer depends on typer internals for unknown-command handling

### Fixed
- `compman init --seed` into a directory that already contains `compman.yml`/`docker-compose.yml` now exits with status `1` instead of `0`
- A failed `compman completion --install` now exits with status `1` instead of `0`
- Unknown commands print the localized error and root help consistently and exit `2` without depending on typer internals
- Volume restore works after stack down (erroneous stack-existence gate removed)
- Archive extraction rejects FIFO/device members on Python < 3.12 (coverage gate restored)
- Interactive init menu and status header labels now route through i18n

### Security
- SECURITY.md size-cap claim corrected to reflect actual enforcement points

## [1.4.0] - 2026-08-03

### Breaking

- `compman.yml` is now profile-based only: `compose` is required and must be a
  mapping of profiles. Omitting it or using a list/string raises a `ConfigError`.
  A single profile (`default`) is the minimal valid config. Simple-mode configs
  must be converted (e.g. `compose: [docker-compose.yml]` becomes
  `compose:\n  default:\n    file: docker-compose.yml`).

### Added

- `compman.yml` supports an optional top-level `secrets` mapping providing
  shared secret values from AWS Secrets Manager. Each entry maps a marker name
  to `{ arn, key }`; the secret's JSON `SecretString` is fetched and the
  referenced key's value is used. Secrets are resolved lazily when a compose
  context is built. The same ARN is fetched only once per command invocation.
- A per-profile `secrets` block merges over the top-level one; the profile wins
  on a name clash.
- Secrets are injected only through `${secrets:NAME}` markers inside profile
  `env` values (partial interpolation supported); they are never passed to
  compose as standalone variables. Markers referencing an undeclared name fail
  with a clear error; other `${VAR}` markers are left untouched for docker
  compose to resolve.
- `compman doctor` reports a `secrets` warning check when secrets are
  configured but AWS credentials or region are missing.

## [1.3.3] - 2026-08-03

### Fixed

- Fixed Up/Down arrow selection still being cancelled over AWS Systems
  Manager Session Manager. Some terminals report application-mode cursor keys,
  which encode Up and Down as `ESC O A` / `ESC O B` instead of the standard
  `ESC [ A` / `ESC [ B`. Both forms are now recognized.

## [1.3.2] - 2026-08-03

### Fixed

- Fixed interactive Up/Down arrow selection being cancelled when the CLI is
  used through a high-latency remote session such as AWS Systems Manager
  Session Manager (`aws ssm start-session`). The strict 50ms escape-sequence
  window was too short for the tunneling round-trip, so the arrow started with
  ESC and was misread as cancel. Arrow keys are now read by accumulating bytes
  until the sequence completes, tolerating slow transports.

### Added

- Interactive menus now accept number keys (1-9) to select an option directly,
  as a fallback for terminals that cannot send arrow keys.

## [1.3.1] - 2026-08-03

### Fixed

- Fixed interactive Up/Down arrow selection being cancelled on POSIX
  terminals such as Amazon Linux. Terminal read buffering caused arrow-key
  escape sequences to be misinterpreted as an Esc/cancel.

## [1.3.0] - 2026-08-01

### Added

- Added project-scoped `compman ps` container listings with `-a`/`--all`.
- Added project-scoped `compman stats` resource snapshots with `-f`/`--follow`
  streaming.

## [1.2.0] - 2026-08-01

### Changed

- Replaced `compman init --skeleton` with `compman init --scaffold` and updated
  interactive and localized guidance to use scaffold terminology. The removed
  `--skeleton` option is no longer accepted.

### Added

- Added public HTTP and HTTPS `.tar.gz`, `.tgz`, and `.zip` deployment sources
  alongside existing S3 prefix and archive support.
- Added a dependency-free project homepage deployed through GitHub Pages at
  `https://allbegray.github.io/compman/`.
- Licensed compman under the MIT License.

## [1.1.6] - 2026-08-01

### Added

- Added a GitHub Actions workflow that creates an annotated version tag after a
  successful CI run for a push to `main`.
- Added release guards for CHANGELOG consistency, duplicate tags, and tag
  collisions, and prevented tag pushes from starting duplicate CI runs.

## [1.1.5] - 2026-08-01

### Added

- Added `-z`/`--level` (1-9) to volume and image backups for controlling gzip
  speed versus archive size. The default level is 6.

## [1.1.4] - 2026-08-01

### Added

- Added `compman -v` as a short alias for `compman --version`.
- Added `-h` as a short alias for `--help` on the root command and command groups.

## [1.1.3] - 2026-08-01

### Changed

- Reduced CLI help startup work by loading Docker, S3, diagnostics, YAML, and
  operation modules only when their commands need them.
- Removed duplicate configuration loading and container-runtime detection from
  the S3-backed `update` path.
- Made `compman upgrade` use an uv-managed Python 3.13 runtime so removing or
  replacing a system Python installation does not break the upgraded CLI.
- Clarified that the recommended audience works in environments where a web GUI
  is unavailable, rather than implying that users do not know how to use one.
- Added this changelog as the canonical source for release notes on every version
  update.

## [1.1.2] - 2026-08-01

### Fixed

- Made captured container output and localized console text safe on Windows
  code pages, including Korean help output.
- Prevented status and upgrade output from raising Unicode decoding tracebacks.
