# Case 11 — S3 backup store

Store volume and image backups in an S3-compatible bucket by pointing
`dirs.backup` at an `s3://` URI. Archives live in the bucket; compman stages
them locally only while a backup or restore runs and deletes the staged copy
after a successful upload, so losing the host does not lose the backups.

## `compman.yml`

```yaml
compman:
  name: my-stack
  dirs:
    backup: s3://my-bucket/backups
  compose:
    default:
      file: docker-compose.yml
```

- `dirs.backup` accepts a local relative path (the default `backup`) or an
  `s3://bucket/prefix` URI.
- Each `volume backup` or `image backup` uploads its archive to a flat key:
  `<prefix>/<stack>.<kind>.<timestamp>.tar.gz`.
- Restores list available timestamps from the bucket and download the selected
  archive automatically.

## Failure behavior

If an upload fails, compman exits non-zero and keeps the staged archive,
naming its path so nothing is lost. A successful upload removes the staged
copy together with its staging directory.

## Credentials

The store uses the standard AWS environment variables:

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=ap-northeast-2
export AWS_ENDPOINT_URL_S3=http://localhost:4566   # Ministack/LocalStack port
```

If `AWS_ENDPOINT_URL_S3` is absent, `AWS_ENDPOINT_URL` is honored too, so any
S3-compatible store works. Uploaded objects get
`Content-Type: application/gzip`, and compman verifies the uploaded size
against the staged file after upload. When an S3 backup store is set but
credentials or region are missing, `compman doctor` reports a warning.

## Commands that use it

```bash
compman volume backup --no-stop
compman image backup -z 9
compman volume restore                     # interactive listing from the bucket
compman doctor
```
