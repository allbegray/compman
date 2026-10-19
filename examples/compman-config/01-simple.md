# Case 01 — Single profile

One profile with one Compose file.

## `compman.yml`

```yaml
# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
compman:
  name: my-stack
  compose:
    default:
      file: docker-compose.yml
```

Multiple Compose files for the same profile use the `base` key plus the profile
`file`; both are passed as `-f` options in order:

```yaml
# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
compman:
  name: my-stack
  compose:
    default:
      file: docker-compose.yml
    base: docker-compose.base.yml
```

## `docker-compose.yml`

```yaml
services:
  web:
    image: nginx:alpine
    ports:
      - "8080:80"
```

## Commands

```bash
compman stack up
compman service status
compman stack down --yes
```

With a single configured profile, the profile argument is optional and the
profile is chosen automatically. Passing an unknown profile name fails.
