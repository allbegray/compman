# Case 12: Authenticated HTTP deploy

Deploy an HTTPS archive that sits behind token authentication. The token lives
in a host environment variable, never in `compman.yml`, and compman sends it as
a request header only while fetching the configured source.

## `compman.yml`

```yaml
compman:
  name: my-stack
  deploy:
    url: https://releases.example.com/app.tar.gz
    sha256: 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
    auth:
      header: Authorization
      value_env: RELEASE_TOKEN
  dirs:
    project: project
  compose:
    default:
      file: docker-compose.yml
```

- `deploy.auth.header` is the HTTP header name to set (`Authorization` here).
- `deploy.auth.value_env` names the environment variable holding the raw
  header value. compman reads it at fetch time, never stores or echoes it, and
  error messages name only the variable.
- The header is sent exactly as the environment value. For Bearer
  authentication, include the scheme yourself.

## Exporting the token

```bash
export RELEASE_TOKEN="Bearer ghp_xxx"
compman deploy --build --tag my-app
```

## Failure behavior

- Missing environment variable: the deploy fails before anything downloads,
  with a concise error naming `RELEASE_TOKEN` but not its value.
- Mismatched archive: with `sha256` set, a wrong artifact aborts the deploy
  before extraction and before the managed `project` directory is touched
  (see Case 10).

## Redirects and https

- Authenticated sources must use `https://`; combining plain `http://` with
  `auth` is a configuration error.
- A redirect to a different host drops the auth header, so the token never
  reaches the redirect target. Same-host redirects keep it. If your CDN
  requires the header after redirecting, serve the archive from the same host.
