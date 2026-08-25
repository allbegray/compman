# Security Policy

`compman` is a CLI for managing Docker/Podman Compose stacks. It is a
supply-chain-sensitive tool: it downloads deployment artifacts (S3/HTTP),
resolves secrets from AWS Secrets Manager, and executes container commands on
behalf of the user. This policy covers supported versions, the authentication
and secret-handling model, vulnerability reporting, and security rules for code
changes.

## Supported Versions

Only the latest release line receives security fixes. Backports to older lines
are not provided; upgrade to the newest release instead.

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |
| < 1.0   | :x:                |

## Authentication / Authorization

`compman` has no user accounts or API of its own. All authentication is
delegated to the underlying services it talks to, using their standard
credential flows:

- **S3 / AWS Secrets Manager**: uses the AWS SDK (boto3) credential chain —
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` (for
  temporary credentials), and `AWS_DEFAULT_REGION` environment variables. For
  S3-compatible endpoints, `AWS_ENDPOINT_URL_S3` (or `AWS_ENDPOINT_URL`)
  redirects the client (e.g. Ministack/LocalStack at `http://localhost:4566`).
  Never commit real credentials; use placeholders:

  ```bash
  export AWS_ACCESS_KEY_ID=<your-access-key-id>
  export AWS_SECRET_ACCESS_KEY=<your-secret-access-key>
  export AWS_DEFAULT_REGION=ap-northeast-2
  ```

  When credentials or region are missing, `compman doctor` reports a warning
  (non-failing) when secrets are configured.

- **Docker / Podman runtimes**: `compman` shells out to the runtime as the
  invoking user. Authorization is whatever the runtime's own configuration
  grants that user — `compman` does not add or bypass any permission layer.

- **Public HTTP deployments**: HTTPS with standard TLS/redirect behavior only;
  no authentication options are offered for HTTP archive downloads.

There is no Basic, JWT, or API-key authentication in `compman` itself. The
`${secrets:NAME}` mechanism below is for *injecting* secret values into
containers, not for authenticating to compman.

## Secret Management

- Secret values are declared in `compman.yml` under a top-level `secrets`
  mapping: each marker name maps to `{ arn, key }` (an AWS Secrets Manager ARN
  plus the JSON key inside the secret).
- Values are injected **only** where a profile `env` value contains a
  `${secrets:NAME}` marker. They are never passed to compose as standalone
  environment variables, and markers are never expanded into `docker-compose.yml`.
- The same ARN is fetched once per command invocation, lazily, when a compose
  context is built.
- Marker names referencing an undeclared secret fail with a clear error; other
  `${VAR}` markers are left untouched for docker compose to resolve from the
  system environment.
- Never hardcode real tokens, keys, or ARN secrets in documentation, tests, or
  example configs — use placeholders (`<your-secret-access-key>`,
  `arn:aws:secretsmanager:...:secret:example`). `compman.yml` and the project
  tree belong in version control; credentials do not.
- System environment variables inherited by docker compose need no config entry
  and are not stored anywhere by `compman`.

## Deploy Source Integrity

Deploy sources can be pinned to a known-good artifact with a SHA-256 digest,
configured as `deploy: { url, sha256 }` in `compman.yml` or passed per
invocation with `--sha256` on `compman deploy`. The digest is verified after
download and before archive extraction, image build, or managed-tree
replacement; a mismatch aborts the deploy and leaves the managed tree
untouched. This protects against altered artifacts served from
trusted-but-compromisable locations (for example, a compromised bucket). It
does not authenticate the publisher: compute the digest yourself and publish it
through a channel independent of the storage location. `.sha256` sidecar files
are not auto-fetched, and redirected endpoints configured via
`AWS_ENDPOINT_URL_S3`/`AWS_ENDPOINT_URL` are outside this control's scope.

## Vulnerability Reporting

Please report suspected vulnerabilities privately so they can be fixed before
public disclosure:

1. Open a **private** report via GitHub Security Advisories at
   `https://github.com/allbegray/compman/security/advisories/new` (preferred),
   or email the maintainer with the subject prefix `[compman-security]`.
2. Include: the affected version, a minimal reproduction (commands and
   configuration with credentials redacted), and the impact you observed or
   suspect.
3. You can expect an acknowledgment within 5 business days and a status update
   with the fix plan. If the report is accepted, a patched release is published
   and the advisory is disclosed after the fix is available; if declined, the
   reason is explained.

Please do not open public issues for active vulnerabilities before a fix is
released.

## Security Rules When Writing Code

- **Archive extraction safety**: deploy archives (`.tar.gz`/`.tgz`/`.zip`) must
  reject absolute paths, `..` traversal, and links; a single top-level directory
  is flattened. Extraction happens into a temporary tree, and when
  `limits.max_archive_mb` is configured the cap is enforced during download and
  on uncompressed member totals before extraction begins; without a configured
  limit no cap applies.
- **Path containment**: managed backup/volume/project paths must never escape
  the config directory; destructive managed directories may not equal the
  config root.
- **No secret leakage**: never echo, log, or include secret values in error
  messages or diagnostics output. Use `typer.echo(..., err=True)` for all output
  (no stdlib `logging`), and keep exception messages free of credentials.
- **Fail before mutation**: fallible work (e.g. image builds, archive
  validation) runs before irreversible filesystem changes, so a failure leaves
  the previous state untouched.
- **No swallowing errors**: destructive operations must not suppress failures
  with `|| true`/`2>/dev/null` — a silent failure of a destructive step is a
  correctness and security bug.
- **No hardcoded credentials** in code, tests, docs, or example configs —
  always placeholders and environment variables.
