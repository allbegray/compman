# Security Policy

`compman` manages Docker/Podman Compose stacks. It is supply-chain-sensitive: it
downloads deploy artifacts, resolves secrets from AWS Secrets Manager, and runs
container commands as the user. This policy covers the credential model, secret
handling, and vulnerability reporting.

## Supported versions

Only the latest release line receives security fixes; there are no backports.

| Version | Supported |
| ------- | --------- |
| 1.x     | yes |
| < 1.0   | no |

## Authentication / authorization

`compman` has no accounts or API of its own. Authentication is delegated to the
services it talks to:

- **S3 / AWS Secrets Manager** — the boto3 credential chain:
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`,
  `AWS_DEFAULT_REGION`. `AWS_ENDPOINT_URL_S3` (or `AWS_ENDPOINT_URL`) redirects
  the client for S3-compatible endpoints (Ministack/LocalStack at
  `http://localhost:4566`). Never commit real credentials:

  ```bash
  export AWS_ACCESS_KEY_ID=<your-access-key-id>
  export AWS_SECRET_ACCESS_KEY=<your-secret-access-key>
  export AWS_DEFAULT_REGION=ap-northeast-2
  ```

  `compman doctor` warns (non-failing) when secrets are configured but credentials
  or region are missing.

- **Docker / Podman runtimes** — `compman` shells out as the invoking user.
  Authorization is whatever the runtime grants that user; `compman` adds and
  bypasses no permission layer.

- **SSH backup stores** (`ssh://[user@]host[:port]/path`) — transfer drives `scp`
  and `ssh` with `BatchMode=yes` and `StrictHostKeyChecking=accept-new`. Keys are
  assumed pre-provisioned in the agent's keyring; `compman` never reads, writes,
  or generates key material. Because host keys are accepted on first contact,
  provision them out of band first on hosts you care about.

- **Slack notifications** (`notify.slack`) — an Incoming Webhook URL is a
  write-capable credential for one channel. Prefer `webhook_env`, which names an
  environment variable read at send time so the URL never enters `compman.yml` or
  the repository; a literal `webhook` keeps the secret in a tracked file. The URL
  is never echoed and failures name only the variable. Treat it as a secret
  everywhere — shell history and CI logs included — and rotate it after exposure.

- **Authenticated HTTP deploys** (`deploy.auth: { header, value_env }`) — one
  caller-supplied header on configured HTTPS fetches. The value is read from
  `value_env` at fetch time, never stored, echoed, or logged; errors name only the
  variable. The loader rejects a non-`https://` URL and a value containing CR/LF.
  During redirects the header is dropped whenever the target leaves the original
  host (compared case-insensitively and port-agnostically; an unparsable host
  counts as cross-host) or downgrades to `http`, so a token never travels to
  another host or over plaintext. A `--path` deploy whose URL differs from the
  configured `deploy` URL runs unauthenticated.

There is no Basic, JWT, or API-key handling in `compman` itself. `${secrets:NAME}`
*injects* values into containers; it does not authenticate to compman.

## Secret management

- Secrets are declared in `compman.yml` under `secrets` as `{ arn, key }` pairs
  (an ARN plus the JSON key inside it).
- Values are injected **only** where a profile `env` contains a
  `${secrets:NAME}` marker — never as standalone compose variables, and markers
  are never expanded into `docker-compose.yml`.
- Each ARN is fetched once per invocation, lazily, when a compose context is
  built. A marker naming an undeclared secret fails clearly; other `${VAR}`
  markers are left for docker compose to resolve from the system environment.
- Never hardcode real tokens, keys, or ARNs in docs, tests, or examples — use
  placeholders (`<your-secret-access-key>`, `...:secret:example`). `compman.yml`
  belongs in version control; credentials do not.

## Deploy source integrity

Pin a source with a SHA-256 digest (`deploy: { url, sha256 }` or `--sha256`). It
is verified after download and before extraction, build, or tree replacement; a
mismatch aborts and leaves the managed tree untouched. This protects against
artifacts altered at a trusted-but-compromisable location — it does **not**
authenticate the publisher. Compute the digest yourself and publish it through a
channel independent of storage. `.sha256` sidecars are not auto-fetched, and
endpoints redirected via `AWS_ENDPOINT_URL_S3`/`AWS_ENDPOINT_URL` are out of
scope for this control.

## On-host state

`compman` writes a little state outside the project directory, under
`%APPDATA%\compman` when `APPDATA` is set (always on Windows), otherwise
`~/.config/compman`:

| File | Contents |
| ---- | -------- |
| `schedules.json` | registered backup jobs and their config paths |
| `history.jsonl` | append-only deploy/rollback/backup/restore log |
| `runs/<name>.jsonl` | per-run start/finish records |
| `schedule.log` | scheduled job output (journald under systemd) |
| `stacks.json` | multi-stack registry: name and directory per stack |

These hold **paths, stack names, timestamps, and exit codes — never secret
values**. They exist so an operator can audit a host nobody was watching; delete
them freely. Do not commit them if your directory layout is itself sensitive.

## Vulnerability reporting

Report privately, before public disclosure:

1. Open a **private** report at
   `https://github.com/allbegray/compman/security/advisories/new` (preferred),
   or email the maintainer with the subject prefix `[compman-security]`.
2. Include the affected version, a minimal reproduction with credentials
   redacted, and the impact you observed or suspect.
3. Expect acknowledgment within 5 business days and a status update with the fix
   plan. Accepted reports are fixed and published, then disclosed; declined
   reports come with the reason.

Please do not open public issues for active vulnerabilities before a fix ships.

## Security rules when writing code

- **Archive extraction safety** — reject absolute paths, `..` traversal, and
  links; flatten a single top-level directory. Extraction goes to a temporary
  tree, and when `limits.max_archive_mb` is set the cap is enforced during
  download and on uncompressed member totals before extraction begins; without a
  configured limit no cap applies.
- **Path containment** — managed backup/volume/project paths must never escape the
  config directory; a destructive managed directory may not equal the config root.
- **No secret leakage** — never echo, log, or embed secret values in errors or
  diagnostics. All output goes through `typer.echo(..., err=True)` (no stdlib
  `logging`), and exception messages stay free of credentials.
- **Fail before mutation** — fallible work (image builds, archive validation)
  runs before irreversible filesystem changes, so a failure leaves the previous
  state untouched.
- **No swallowing errors** — destructive operations must not suppress failures
  with `|| true` / `2>/dev/null`. A silent destructive step is both a correctness
  and a security bug.
- **No hardcoded credentials** anywhere, including tests, docs, and examples.
