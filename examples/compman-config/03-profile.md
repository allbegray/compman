# Case 03 — Profile mode basics

Profiles select different Compose files per environment. This case uses a
shared `base` file plus a per-profile file, with no environment variables.

## `compman.yml`

```yaml
# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
compman:
  name: my-stack
  compose:
    base: docker-compose.yml
    local: docker-compose.local.yml
    dev: docker-compose.dev.yml
    prod: docker-compose.prod.yml
```

- `base` is prepended as `-f` before every profile's own file.
- A plain string profile value (`dev: docker-compose.dev.yml`) sets the profile
  file only.
- With no profile argument, the first configured profile is used (`local`).

## `docker-compose.yml` (base)

```yaml
services:
  web:
    image: nginx:alpine
    ports:
      - "8080:80"
```

## Commands

```bash
compman stack up local
compman stack up dev
compman stack up prod
compman service status --profile prod
compman stack down --profile prod --yes
```

## When `base` is omitted

Each profile file is used on its own; the default `docker-compose.yml` is the
fallback for any profile whose file is missing.

```yaml
# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
compman:
  name: my-stack
  compose:
    dev: docker-compose.dev.yml
    prod: docker-compose.prod.yml
```
