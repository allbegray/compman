# Case 10 — per-profile deploy, local source, checksum, strategy, dry-run, rollback

Use different release sources per profile, verify with checksum, preview with dry-run, and rollback to a kept version. Raw YAML is in [`per-profile-deploy.yml`](./per-profile-deploy.yml).

## Layout

```
my-stack/
├── compman.yml
├── docker-compose.yml
├── docker-compose.dev.yml
├── docker-compose.prod.yml
├── dist/app.tar.gz              # local source
├── project/                     # dirs.project — deploy target
└── backup/.versions/            # keep 3 by default (1-10 via --keep)
```

## `compman.yml` — per-profile deploy

```yaml
compman:
  name: per-profile-demo
  deploy:
    default: s3://my-bucket/releases/app.tar.gz
    dev:
      source: file://./dist/app.tar.gz
    staging:
      source: ./dist/app.tar.gz
      strategy: pull-only
    prod:
      source: s3://my-bucket/releases/app.tar.gz
      checksum: sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
      strategy: recreate
  compose:
    default:
      file: docker-compose.yml
    dev:
      file: docker-compose.dev.yml
    staging:
      file: docker-compose.staging.yml
    prod:
      file: docker-compose.prod.yml
```

- `deploy` may be a string (legacy, normalized to `default`) or a map of profile to `str | {source, checksum, strategy}`. Resolution order is ` --path > deploy[profile] > deploy["default"]`.
- Local sources accept `file://` and bare paths (`./dist/app.tar.gz`, `/abs/path/app.tar.gz`, or a directory). Archives (`.tar.gz`, `.tgz`, `.zip`) are extracted safely; a directory is copied.
- `checksum` is `sha256:<64 hex>`, verified only when set. Missing checksums trigger a `doctor` warning, not a failure.
- `strategy` is `recreate` (default, build may run) or `pull-only` (skip build). ` --strategy` on the CLI overrides `deploy.<profile>.strategy`; ` --no-build` also skips build.

## Local source vs S3/HTTP

```bash
# bare path — same as file://./dist/app.tar.gz
compman deploy --path ./dist/app.tar.gz --build

# explicit profile — picks deploy.dev
compman deploy --profile dev --build

# prod with checksum verification
compman deploy --profile prod --build
```

## Dry-run — preview without swapping

` --dry-run` runs fetch, checksum, limits, and optional build, then prints a diff and exits before `_swap`:

```bash
compman deploy --path ./dist/app.tar.gz --dry-run
compman deploy --profile prod --dry-run --strategy pull-only
```

Output includes `Dry run: no files were changed` and a `Diff:` section (`+` added, `-` removed, `~` modified, or `(no changes)`). On `dry-run` no files under `project/` change and no version is kept.

## Rollback and `--keep`

Each successful deploy copies the new `project/` into `backup/.versions/<YYYYMMDD_HHMMSS>` and prunes to ` --keep` (default 3, range 1-10):

```bash
compman deploy --keep 5 --profile prod
compman rollback 20260820_120000
compman rollback --profile prod       # pick from available timestamps interactively
compman rollback                      # choose interactively
```

`rollback <TIMESTAMP>` restores `backup/.versions/<TIMESTAMP>` via the same `_swap` used by deploy (`.git` / `.gitkeep` excluded, transactional rollback on failure). Without a timestamp, a prompt lists available versions.

## `compman update` — deprecated alias

If `deploy` is set, `compman update [PROFILE]` deploys then runs `stack up`; otherwise it just does `up -d --build`.

## Commands

```bash
compman deploy --help     # shows --profile --dry-run --strategy --keep --no-build
compman rollback --help
compman doctor            # warns when a deploy profile lacks checksum, shows kept versions
compman stack up prod
compman stack down --yes
```
