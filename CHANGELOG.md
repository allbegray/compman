# Changelog

Major user-visible changes to compman are recorded here, with the newest release
first.

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
