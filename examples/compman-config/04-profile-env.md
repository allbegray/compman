# Case 04 — Profile environment variable injection

Give each environment its own values, shared through a single Compose file.
This is the profile `env` feature: values are declared in `compman.yml`,
passed into the compose process environment, and consumed with `${VAR}` in the
Compose file.

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
        DATABASE_URL: dev.db.example.com
        LOG_LEVEL: debug
    prod:
      file: docker-compose.prod.yml
      env:
        DATABASE_URL: prod.db.example.com
        LOG_LEVEL: warn
```

## `docker-compose.yml` (shared)

The injected values must be referenced with `${VAR}` interpolation:

```yaml
services:
  app:
    image: my-app
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - LOG_LEVEL=${LOG_LEVEL:-info}
```

`${LOG_LEVEL:-info}` supplies `info` when the profile does not set a value.

## Commands

```bash
compman stack up dev
compman service status --profile dev
compman stack down --profile dev --yes
```

## Omitting `file`

When every profile shares one Compose file and only the env values differ, drop
`file`. The profile falls back to `base`, or to `docker-compose.yml` if `base`
is absent.

```yaml
# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
compman:
  name: my-stack
  compose:
    dev:
      env:
        DATABASE_URL: dev.db.example.com
    prod:
      env:
        DATABASE_URL: prod.db.example.com
```
