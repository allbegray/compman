# Case 09 — env_file injection

Load environment variables from `.env` files per profile. `env_file` accepts a string or a list of strings; values are merged before `env` and Secrets interpolation.

## Layout

```
my-stack/
├── compman.yml
├── docker-compose.yml
├── .env
├── prod.env
└── /etc/compman/prod.env   # absolute path example
```

## Single file

Use one `.env` file for the profile:

```yaml
compman:
  name: my-stack
  compose:
    default:
      file: docker-compose.yml
      env_file: .env
```

## Multiple files with overwrite

Later files overwrite earlier ones:

```yaml
compman:
  name: my-stack
  compose:
    dev:
      file: docker-compose.yml
      env_file: [".env", "prod.env"]
      env:
        DATABASE_URL: prod.db.example.com  # explicit env wins over env_file
```

## Absolute path (outside project)

Absolute paths are allowed and are not constrained to `compman.yml`'s directory. Use this for operational secrets outside the repo:

```yaml
compman:
  name: my-stack
  compose:
    prod:
      file: docker-compose.yml
      env_file: /etc/compman/prod.env
```

## Combined with Secrets Manager

Values loaded from `env_file` are interpolated for `${secrets:NAME}` markers, just like `env` values:

```yaml
compman:
  name: my-stack
  compose:
    prod:
      file: docker-compose.yml
      env_file: prod.env
  secrets:
    DB_URL:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/url
```

`prod.env` may contain `DATABASE_URL=${secrets:DB_URL}` and it will be resolved at `resolve_compose_context` time. Explicit `env` still overwrites the file value after secret interpolation.

## `docker-compose.yml`

Reference the injected variables with `${VAR}`:

```yaml
services:
  app:
    image: my-app
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - LOG_LEVEL=${LOG_LEVEL:-info}
```

## Parsing rules

- Blank lines and lines starting with `#` are ignored.
- Leading `export ` is stripped.
- Lines without `=` are ignored; empty values (`EMPTY=`) are kept as `""`.
- Surrounding single or double quotes are removed: `"hello world"` → `hello world`.
- Precedence: `env_file` files in order → `env` → `${secrets:NAME}` interpolation.

## Commands

```bash
compman stack up prod
compman doctor   # warns if an env_file is missing, but does not fail the overall check
compman stack down --yes
```
