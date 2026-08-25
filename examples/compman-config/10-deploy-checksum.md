# Case 10 — Deploy checksum pinning

Pin the deployed source to a known-good artifact with a SHA-256 digest. compman
verifies the fetched source against the digest after download and before
extraction, image build, or the managed-tree swap, so a tampered archive never
reaches your stack.

## `compman.yml`

```yaml
compman:
  name: my-stack
  deploy:
    url: s3://my-bucket/releases/app.tar.gz
    sha256: 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
  dirs:
    project: project
  compose:
    default:
      file: docker-compose.yml
```

- `deploy.url` is the S3 archive (or public HTTP archive) to deploy. The plain
  string form of `deploy:` keeps working unchanged.
- `deploy.sha256` is the expected digest: 64 hexadecimal characters,
  case-insensitive. A digest on an S3 prefix source fails before anything
  downloads; pinning works with archives only.

## Generating the digest

Compute it from the exact archive you upload:

```bash
shasum -a 256 app.tar.gz    # macOS
sha256sum app.tar.gz        # Linux
```

Publish the digest through a channel separate from the bucket (release notes,
for example). A `.sha256` file stored next to the archive proves nothing and is
not fetched by compman.

## One-off verification

Without editing `compman.yml`, pass the digest on the command line:

```bash
compman deploy --path s3://my-bucket/releases/app.tar.gz --sha256 <digest> --build --tag my-app
```

## Mismatch behavior

If the downloaded source does not match the digest, the deploy aborts with exit
status 1 before the image build and before the managed `project` directory is
touched:

```text
Deploy source failed SHA-256 verification (expected 9f86d081..., got e3b0c442...)
```

## `compman update`

`update` deploys the configured source URL, so it inherits the pin whenever it
deploys that same URL:

```bash
compman update
```
