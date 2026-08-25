# Case 11 — Remote backup upload

Replicate volume and image backups to S3-compatible storage with the optional
`backup.upload` key. Once configured, every backup uploads its archive right
after the local copy is written, so losing the host does not lose the backups.
The local archive always remains; the upload is only a replica.

## `compman.yml`

```yaml
compman:
  name: my-stack
  backup:
    upload: s3://my-bucket/backups
  dirs:
    backup: backup
  compose:
    default:
      file: docker-compose.yml
```

- `backup.upload` is the destination prefix. Each successful `volume backup`
  or `image backup` uploads its archive to a flat key:
  `<prefix>/<stack>.<kind>.<timestamp>.tar.gz`.
- The upload happens automatically after each successful local backup, so a
  plain `compman volume backup` is enough; nothing extra to schedule.

## One-off upload

Without editing `compman.yml`, push a single backup to any S3 URI:

```bash
compman volume backup --no-stop --push s3://my-bucket/adhoc
```

`--push` overrides the configured target for that invocation only.

## Skipping the configured target

Run a purely local backup even though `backup.upload` is configured:

```bash
compman image backup --no-push
```

Passing `--push` and `--no-push` together in one invocation is an error.

If an upload fails, compman exits non-zero with a message naming the local
archive path, and the local backup stays intact.

## Credentials

Uploads use the standard AWS environment variables:

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=ap-northeast-2
export AWS_ENDPOINT_URL_S3=http://localhost:4566   # Ministack/LocalStack port
```

If `AWS_ENDPOINT_URL_S3` is absent, `AWS_ENDPOINT_URL` is honored too, so any
S3-compatible store works. Uploaded objects get
`Content-Type: application/gzip`, and compman verifies the uploaded size
against the local file after upload. When `backup.upload` is set but
credentials or region are missing, `compman doctor` reports a warning.

## Commands that use it

```bash
compman volume backup --no-stop
compman image backup -z 9
compman volume backup --no-stop --push s3://my-bucket/adhoc
compman image backup --no-push
compman doctor
```
