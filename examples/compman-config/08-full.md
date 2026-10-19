# Case 08 — Full example

All features combined: profiles with env injection, Secrets Manager, managed
directories, and a deploy source.

## Layout

```
my-stack/
├── compman.yml
├── compose/
│   ├── docker-compose.yml        # base
│   ├── docker-compose.dev.yml
│   └── docker-compose.prod.yml
├── project/                      # dirs.project — deploy source
├── backup/                       # dirs.backup  — backup archives
└── volume/                       # dirs.volume  — volume transfers
```

## `compman.yml`

```yaml
# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
compman:
  name: my-stack
  deploy: s3://my-bucket/releases/app
  folder: compose
  dirs:
    project: project
    backup: backup
    volume: volume
  compose:
    base: docker-compose.yml
    dev:
      file: docker-compose.dev.yml
      env:
        DATABASE_URL: postgres://${secrets:DB_USER}:${secrets:DB_PASSWORD}@db.example.com
        LOG_LEVEL: debug
    prod:
      file: docker-compose.prod.yml
      env:
        DATABASE_URL: postgres://${secrets:DB_USER}:${secrets:DB_PASSWORD}@db.example.com
        LOG_LEVEL: warn
  secrets:
    DB_USER:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/user
    DB_PASSWORD:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/password
```

## `compose/docker-compose.yml` (base)

```yaml
services:
  app:
    image: my-app
    ports:
      - "8080:80"
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - LOG_LEVEL=${LOG_LEVEL:-info}
```

## `compose/docker-compose.dev.yml`

```yaml
services:
  app:
    environment:
      - EXTRA_FEATURE=enabled
```

## Commands

```bash
compman stack up dev               # dev profile; secrets + dev env
compman service status --profile dev
compman volume backup              # archive into backup/
compman deploy                     # fetch source into project/ from S3
compman update                     # deploy + rebuild + recreate
compman stack down --profile dev --yes
```

## Effective environment for `dev`

| Variable | Source |
|----------|--------|
| `DATABASE_URL` | `dev` profile env (`postgres://...` built from Secrets Manager) |
| `LOG_LEVEL` | `dev` profile env (`debug`) |
| `EXTRA_FEATURE` | `docker-compose.dev.yml` |

Host environment variables are inherited by docker compose as usual and need no
configuration entry.
