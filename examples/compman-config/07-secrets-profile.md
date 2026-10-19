# Case 07 — Secrets combined with profiles

Profile `env` values reference secrets with `${secrets:NAME}` markers. A
profile `secrets` block merges over the top-level `secrets` block (the profile
wins on a name clash). Secrets are never injected as standalone variables.

## `compman.yml`

```yaml
# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
compman:
  name: my-stack
  compose:
    base: docker-compose.yml
    dev:
      file: docker-compose.dev.yml
      env:
        DATABASE_URL: postgres://${secrets:DB_USER}:${secrets:DB_PASSWORD}@dev.db.example.com
        LOG_LEVEL: debug
    prod:
      file: docker-compose.prod.yml
      env:
        DATABASE_URL: postgres://${secrets:DB_USER}:${secrets:DB_PASSWORD}@prod.db.example.com
        LOG_LEVEL: warn
  secrets:
    DB_USER:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/user
    DB_PASSWORD:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/password
```

Both profiles reference the shared `DB_USER`/`DB_PASSWORD` secrets and supply
their own `DATABASE_URL` host and `LOG_LEVEL`.

## Per-profile secret override

A profile `secrets` block replaces an entry for that profile only. The profile
ARN wins when both define the same name:

```yaml
# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
compman:
  name: my-stack
  compose:
    dev:
      file: docker-compose.dev.yml
      env:
        DATABASE_URL: postgres://${secrets:DB_USER}:${secrets:DB_PASSWORD}@dev.db.example.com
      secrets:
        DB_PASSWORD:
          arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db-dev
          key: dtx/db/password
    prod:
      file: docker-compose.prod.yml
      env:
        DATABASE_URL: postgres://${secrets:DB_USER}:${secrets:DB_PASSWORD}@prod.db.example.com
  secrets:
    DB_USER:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/user
    DB_PASSWORD:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/password
```

The `dev` profile resolves `DB_PASSWORD` from `db-dev`; `prod` falls back to the
top-level `db` secret. Marker references are resolved against the merged
secrets, so an undeclared name in either block still fails the command.

## `docker-compose.yml`

The interpolated `DATABASE_URL` reaches the compose process environment, so the
Compose file consumes it with `${VAR}` interpolation:

```yaml
services:
  app:
    image: my-app
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - LOG_LEVEL=${LOG_LEVEL}
```

## Commands

```bash
compman stack up dev
compman stack up prod
```

## Resolution order

1. Secrets are merged: the profile `secrets` block overrides the top-level
   block on a name clash.
2. Each secret's ARN is fetched once per command invocation.
3. The profile `env` is interpolated: `${secrets:NAME}` markers are replaced
   with the resolved values; other markers (system variables) are left for
   docker compose to resolve.
4. Host environment variables pass through to docker compose as usual.
