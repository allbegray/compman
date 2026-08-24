# Case 09 — Deploy size limit

Cap the size of the deployed source with `limits.max_archive_mb`. The cap is
enforced during download and on the extracted tree before any filesystem
change, so an oversized or malicious source cannot exhaust disk. Without a
configured limit, no cap applies.

## `compman.yml`

```yaml
compman:
  name: my-stack
  deploy: s3://my-bucket/releases/app.tar.gz
  limits:
    max_archive_mb: 50
  dirs:
    project: project
  compose:
    default:
      file: docker-compose.yml
```

- `limits.max_archive_mb` caps the fetched source in megabytes (S3 prefix,
  S3 archive, and HTTP archive downloads all honor it).
- When the limit is configured, a successful deploy echoes the source and its
  byte size as provenance.

## Oversized source

A source exceeding the cap aborts the deploy with a clear error before the
managed `project` directory is touched:

```text
Deploy source exceeds the 50 MB size limit (84999999 bytes).
```

## Commands that use it

```bash
compman deploy --path s3://my-bucket/releases/app.tar.gz --build --tag my-app
compman update
compman deploy --path https://example.com/releases/app.zip
```
