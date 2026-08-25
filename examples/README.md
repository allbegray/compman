# compman configuration examples

Case-by-case `compman.yml` examples. Each case shows the declaration in
`compman.yml`, the matching `docker-compose.yml` usage, and the commands that
use it.

## How environment variables reach your containers

The single most common confusion: **declaring variables in `compman.yml` is not
enough**. Values come from a profile `env` (with optional `${secrets:NAME}`
markers) or the host environment. compman passes the interpolated profile `env`
to the `docker compose` process environment, and your `docker-compose.yml` must
reference them with `${VAR}` interpolation:

```yaml
# docker-compose.yml
services:
  app:
    image: my-app
    environment:
      - DB_URL=${DB_URL}          # interpolated from the compose process env
      - LOG_LEVEL=${LOG_LEVEL:-info}  # with a default fallback
```

Only `environment:` / Compose-file values that reference `${VAR}` receive the
injected value. A plain `environment:` entry without `${...}` stays literal.

## Index

| # | Case | Shows |
|---|------|-------|
| [01](compman-config/01-simple.md) | Single profile | One profile, one `docker-compose.yml` |
| [02](compman-config/02-folder-dirs.md) | Folder and managed dirs | `folder`, `dirs.project` / `backup` / `volume` |
| [03](compman-config/03-profile.md) | Profile mode basics | `base` + file-only profiles |
| [04](compman-config/04-profile-env.md) | Profile env injection | Per-profile `env` consumed via `${VAR}` |
| [05](compman-config/05-deploy.md) | Deploy sources | S3 prefix, S3 archive, HTTP archive |
| [06](compman-config/06-secrets.md) | AWS Secrets Manager | `${secrets:NAME}` markers in profile `env` |
| [07](compman-config/07-secrets-profile.md) | Secrets + profiles | Per-profile `secrets` override; `${secrets:NAME}` markers |
| [08](compman-config/08-full.md) | Full example | Everything combined |
| [09](compman-config/09-limits.md) | Deploy size limit | `limits.max_archive_mb` cap + provenance echo |
| [10](compman-config/10-deploy-checksum.md) | Deploy checksum pinning | `deploy: {url, sha256}` pin + `--sha256` flag |
| [11](compman-config/11-s3-backup-store.md) | S3 backup store | `dirs.backup` as an `s3://bucket/prefix` URI |
| [12](compman-config/12-authenticated-http-deploy.md) | Authenticated HTTP deploy | `deploy.auth` header sourced from `value_env` env var |
| [13](compman-config/13-scheduled-backup.md) | Scheduled backups | `schedule add/list/remove` cadences, mechanisms, and log locations |

Run any example from the directory that contains its `compman.yml`:

```bash
compman stack up
compman service status
compman stack down --yes
```

For profile-mode examples, pass the profile: `compman stack up dev`.
