# Case 05 — Deploy sources

Configure a default release source for `compman deploy` and `compman update`.
Three source kinds are supported: an S3 prefix, an S3 archive, and a public
HTTP/HTTPS archive.

## `compman.yml`

```yaml
# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
compman:
  name: my-stack
  deploy: s3://my-bucket/releases/app
  dirs:
    project: project
  compose:
    default:
      file: docker-compose.yml
```

- `dirs.project` names the managed directory the source is swapped into
  (default `project`).
- `--path SOURCE_URI` overrides `deploy` for a single invocation.

## S3 prefix

Recursively downloads every object under the prefix and preserves the
directory structure.

```bash
compman deploy --path s3://my-bucket/releases/app
```

## S3 archive

Extracts a `.tar.gz`, `.tgz`, or `.zip`. A single top-level directory is
flattened.

```bash
compman deploy --path s3://my-bucket/releases/app.tar.gz --build --tag my-app
```

## HTTP / HTTPS archive

Public archives only, with a 30-second timeout. The URL path must end in
`.tar.gz`, `.tgz`, or `.zip`.

```bash
compman deploy --path https://example.com/releases/app.zip --build --tag my-app
```

## `compman update`

Rebuilds images and force-recreates containers (not zero-downtime):

```bash
compman update
```

## Resulting layout

```
my-stack/
├── compman.yml
├── docker-compose.yml
└── project/              # deployed source
```
