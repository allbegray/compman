# Changelog

Major user-visible changes to compman are recorded here, with the newest release
first.

## [1.5.0] - 2026-08-20

### 추가

- `compman.yml`의 `deploy`가 프로파일별 맵(`str | {source, checksum, strategy}`)을 지원하며 ` --profile`과 ` --path` 우선순위로 해석하고 기존 문자열은 `default`로 정규화한다.
- 로컬 배포 소스(`file://`와 베어 경로 `./dist/app.tar.gz`, `/abs/path`, 디렉터리)를 S3와 HTTP와 동일한 `fetch` 인터페이스로 지원한다.
- `compman deploy`에 ` --dry-run`(검증+diff 후 교체 없이 종료), ` --strategy recreate|pull-only`, ` --keep 1-10`, ` --no-build`를 추가하고 `source`+`size` provenance를 항시 출력한다.
- `backup/.versions/<YYYYMMDD_HHMMSS>`에 최대 3개(기본값) 버전을 보관하고 `compman rollback [TIMESTAMP]`로 복원하며 초과 시 LRU로 정리, `doctor`는 `checksum` 누락 시 경고와 보관 개수를 표시한다.

## [1.4.1] - 2026-08-20

### 추가

- `compose.<profile>.env_file`이 문자열 또는 리스트로 `.env` 파일을 지정할 수 있으며 빈 줄과 `#` 주석과 `export` 접두사, 따옴표 값을 처리하고 뒤 파일이 앞 파일을 덮은 뒤 `env`가 최종으로 덮고 `${secrets:NAME}`을 치환한다.

### 수정

- `deploy _swap`이 `src/.git`을 스킵해 배포 교체 시 기존 저장소 메타데이터를 보존한다.

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
