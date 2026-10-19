# Case 06 — AWS Secrets Manager injection

Reference shared secrets from profile `env` values with `${secrets:NAME}`
markers. compman fetches each secret from AWS Secrets Manager once per command
invocation and substitutes the value at `key`.

## `compman.yml`

```yaml
# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
compman:
  name: my-stack
  compose:
    default:
      file: docker-compose.yml
      env:
        DATABASE_URL: postgres://${secrets:DB_USER}:${secrets:DB_PASSWORD}@db.example.com
  secrets:
    DB_USER:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/user
    DB_PASSWORD:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/password
```

- Each entry maps a marker name to `{ arn, key }`.
- `key` names a JSON key inside the secret's `SecretString`; slash keys like
  `dtx/db/user` are supported.
- The same ARN is fetched once per command invocation.
- A marker that references an undeclared name fails the command.
- Secrets are never passed to compose as standalone variables; only `env`
  values that reference them are injected.

## Secret shape

The `db` secret's `SecretString` is JSON:

```json
{
  "dtx/db/user": "admin",
  "dtx/db/password": "s3cret"
}
```

## `docker-compose.yml`

The interpolated `DATABASE_URL` reaches the compose process environment, so the
Compose file consumes it with `${VAR}` interpolation:

```yaml
services:
  app:
    image: my-app
    environment:
      - DATABASE_URL=${DATABASE_URL}
```

## Credentials

Use the standard AWS environment variables; `compman doctor` warns when secrets
are configured but credentials or region are missing.

```bash
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_DEFAULT_REGION="ap-northeast-2"
```

## Commands

```bash
compman stack up
```

A missing secret, unresolvable region, non-JSON body, or missing `key` fails
the command with a clear error before compose runs.
