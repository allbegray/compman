# SOLUTION.md — Development Knowledge Base

Lessons learned while developing, testing, and debugging compman. Read this before
changing runtime interaction, CLI behavior, or tests. The goal: never repeat the
mistakes below. Companion files: `AGENTS.md` (operating rules for agents) and
`BACKLOG.md` (open/closed improvement items).

## 1. Environment traps (Windows / WSL / Docker)

- **A "hung" WSL command is usually a zombie `wsl.exe` blocking the pipe, not the
  program.** When a `wsl -d Ubuntu -- ...` call produces no output, check
  `Get-Process wsl` for lingering processes from aborted invocations. Isolate the
  real behavior by redirecting output to a file inside WSL and bounding with
  `timeout 20 <cmd> > /tmp/out 2>/tmp/err`; a healthy CLI returns instantly
  (compman `--version` did).
- **Never blanket-kill `wsl.exe` or `wsl --shutdown` while Docker Desktop is
  running.** It corrupts the `docker-desktop` distro bootstrap
  (`DockerDesktop/Wsl/ExecError`, missing `/opt/docker-desktop/componentsVersion.json`).
  Recovery: restart `Docker Desktop.exe`, poll `docker info` up to ~90s. Orphaned
  `wsl.exe` processes are harmless — the OS reaps them at the next natural WSL
  shutdown; leave them alone.
- **PowerShell `\$` is NOT an escape; use backtick `` `$ ``.** Sending complex bash
  through PowerShell quoting invites silent corruption (`$HOME`/`$PATH` expand to
  Windows values and break the Linux PATH). Instead write the script to a temp
  `.sh` file and run `wsl -d Ubuntu -- bash /mnt/c/.../script.sh`.
- **WSL Ubuntu often lacks `python3-venv`/`pip`** (ensurepip absent). Use `uv tool
  install <wheel>`; if uv is missing in WSL, download `uv-x86_64-unknown-linux-gnu.tar.gz`
  on Windows and copy the binary into `~/.local/bin`.
- **`$env:TEMP` may be an 8.3 short path** (`C:\Users\AIMMED~1\...`); WSL reaches it
  as `/mnt/c/Users/AIMMED~1/...`.

## 2. Test traps

- **`DummyRuntime` is a scripted double, not just a success stub.** Every public
  `ContainerRuntime` method is overridden explicitly; the `dummy_runtime`
  fixture fails the test if a future base method is added without an override,
  so tests can never silently fall through to real subprocess code. By default
  calls still succeed deterministically, but failures are scriptable per
  channel and consumed FIFO: `dummy_runtime.queue(run_cli=(1, "", "boom"))`,
  `queue(compose=[(0, "cid", ""), (1, "", "err")])`,
  `queue(passthru_cli=7)`, `queue(passthru_compose=2)`. Results are real
  `subprocess.CompletedProcess` objects (`.returncode`/`.stdout`/`.stderr` —
  there is no `.return_code` alias). Recording is unchanged: docker/compose
  argv lands in `commands_run`, every compose invocation in `compose_runs`,
  so keep asserting `dummy_runtime.compose_runs[*]["args"]`. Failure semantics
  matter: two real bugs (a stopped-container `docker exec` swallowed by
  success-biased mocks, and `compose ps -q` returning container IDs instead of
  names) passed 100% branch coverage before scripted failures existed — any new
  runtime interaction still needs a live-Docker check plus a queued-failure test.
- **100% line/branch coverage is not correctness.** Coverage means executed,
  not useful; the retired sweep files (`test_missing_coverage.py`,
  `test_coverage_completion.py`) once kept production-dead code alive
  (`volume._fix_permissions`). Behavioral cases live in feature files under
  behavior-describing names; do not reintroduce grab-bag "remaining branches"
  tests.
- **CLI invocations leak the language `ContextVar`.** `runner.invoke(app, ["lang", "ko"])`
  calls `set_lang("ko")` and pollutes later tests. Fix: autouse fixture in
  `conftest.py` resets `i18n._CURRENT_LANG` after every test.
- **`t()` keys are silently tolerant.** A mistyped key prints the key name instead of
  failing. Guard with AST contract tests (`tests/test_i18n.py`): every key used in
  `compman/` must exist, every entry must be `{en, ko}`, no unused keys.
- **Hardcoded user-facing strings recur.** `tests/test_repository_urls.py` AST-scans
  `typer.echo/confirm/prompt` first args AND `typer.Option/Argument` `help=` kwargs
  for sentence-like literals; only a tiny allowlist of shell examples is permitted.
- **Static command lists drift.** The PowerShell completion snippet and the README
  Commands block are cross-validated against the live typer tree
  (`tests/test_cli.py`).
- **Expected CLI failures raise `CommandError("", code=N)` at the boundary.**
  `HelpOnUnknownCommandGroup.main` converts them to bare exits — stderr echoes
  happen where the error is detected, never via tracebacks. `_load` config/
  runtime failures, deploy onboarding hints, and doctor/status short-circuits
  all follow this idiom; direct unit assertions pin `excinfo.value.code`.

## 3. Code pattern traps

- **`docker ps -q <service>` returns container IDs; the `name=^...$` filter matches
  names only.** Never re-resolve a `ps -q` result through `get_container_id` —
  use the resolved identifier directly (the `service log/connect` bug).
- **`docker exec` only works on a running container.** Running it inside
  `stack_paused` (container stopped) fails silently when `|| true` / `2>/dev/null`
  swallow the error — the `volume restore --replace` bug: the delete never ran but
  the command "succeeded". Destructive operations must not swallow errors; clear the
  destination *before* stopping the stack.
- **Fail early, before filesystem mutation.** Deploy `--build` builds from the
  temporary source *before* the managed-tree swap, so a build failure leaves the
  existing tree untouched. Put fallible work ahead of irreversible work.
- **Every user-facing string goes through `t()`** — including option/argument `help`
  text (`opt.*` keys), not just `echo`/`confirm`/`prompt`. Only exception messages
  stay English.
- **Duplicated helpers drift.** `ops/volume.py` and `ops/image.py` each had their own
  `_validate_timestamp` with *different* messages; consolidated into one public
  `ops/common.validate_timestamp`.
- **A webhook that returns `HTTP 200` has not necessarily worked.** Slack answers
  `200` for revoked, expired, and malformed webhooks too, and puts the real verdict
  in the body (`ok` on success, `no_token` / `invalid_payload` / `user_not_found`
  on failure). Checking only the status line makes a dead webhook look healthy;
  verify the body. A mistyped webhook path is redirected to Slack's HTML docs site,
  so collapse whitespace and truncate the verdict or one warning dumps a whole web
  page into the terminal.
- **A best-effort side channel must be gated before it does any work.** The Slack
  hook needs an extra `compose ps` query for service states; guard it on
  "is a webhook configured?" first so an opted-out stack pays nothing. Same rule as
  the lazy boto3 import and the lazily resolved secrets.
- **Secrets belong in environment variables, not in `compman.yml`.** Follow the
  existing `deploy.auth.value_env` pattern: config names the variable, the value is
  read at use time, and error messages name only the variable. A config block is
  committed far more often than a shell profile is rotated. When a config block
  *does* opt into one variable, do not silently fall back to a global default of the
  same purpose — that hides a broken per-stack setting.
- **Verify against the real tool before designing around its output.** Three
  assumptions were wrong on the first pass and only a live Docker run caught them:
  `compose ps` **omits exited containers** unless `--all` is passed (a crashed
  service would have vanished from the alert and the message would have claimed
  everything healthy); its `Mounts` column is **truncated to an ellipsis** in
  `--format json`, so mount paths must be read from the compose files instead; and
  `Publishers` lists every mapping **twice** (IPv4 and IPv6), which needs
  deduplicating. A mistyped webhook URL is also not a 404 — Slack serves its HTML
  docs with `HTTP 200`.
- **An oversized Slack block is rejected, not truncated.** `invalid_payload` comes
  back as a 200-with-error-body, so a 40-service stack would silently lose every
  notification until someone noticed. Cap block bodies and collapse the remainder.
- **"Allows for 2 columns" is not "renders as 2 columns".** Slack's Block Kit docs
  describe `section.fields` as rendering "in a compact format that allows for 2
  columns of side-by-side text" — permissive language, and clients that stack the
  fields vertically double the message height. Anything that must look the same
  on desktop web, mobile, and Connect belongs in one `mrkdwn` text block that
  packs its own columns, not in a grid the client controls.
- **A summary plus exceptions beats a full dump.** An operator does not read 40
  service lines; they read "3 of 3 healthy" and only need the names of the ones
  that are not. Same data, a fraction of the noise, and the failure case is where
  all the detail lands.
- **SEO regressions are silent, so pin them with tests.** A renamed anchor, a
  `softwareVersion` that drifts from `pyproject.toml`, a FAQ answer that no
  longer matches the visible page, or a truncated meta description all ship
  unnoticed in a static site. `tests/test_site_seo.py` asserts the title and
  description length bands, one `<h1>`, non-skipping heading levels, resolvable
  internal anchors, labelled sections, JSON-LD parseability, version agreement
  with the package, and — because Google's structured-data policy requires it —
  that every FAQPage question is actually visible on the page.
- **Grid children default to `min-width: auto`.** One long `<pre>` line in a
  grid cell widens the whole track past the viewport and the page starts
  scrolling sideways on a phone, even though the `<pre>` itself has
  `overflow-x: auto`. Set `min-width: 0` on any grid child that can hold code.
- **Verify rendering under the real deployment path.** Switching asset hrefs to
  absolute `/compman/...` is correct on GitHub Pages and silently 404s on a
  local `http.server` rooted at `docs/site` — which looks like broken CSS and
  hides real layout bugs. Serve a copy under the `/compman/` prefix and check
  there.

## 4. Recurring real-device E2E procedure

Run this on a machine with Docker after any change touching runtime interaction:

1. `uv build --wheel` → `uv tool install <wheel>` into an isolated `UV_TOOL_DIR`.
2. PowerShell smoke: `--version`, `-h`, `--lang ko --help`, `init --scaffold`,
   `doctor`, `status`, `completion bash`, `completion <unknown>` (expect exit 1).
3. Stack: `init --seed` → `stack up` (real build) → `service status` / `ps` /
   `stats` → `service log app` (service-name resolution) → HTTP 200 check.
4. Volumes: `volume backup` → mutate volume → `volume restore` (merge keeps new
   files) → `volume restore <ts> --replace` (destination-only files deleted) →
   `volume pull` / `volume push --replace`.
5. Images: `image backup` / `image restore`.
6. Guard rails: `clear` without `--yes` must abort; `stack down --yes` must clean up.
7. Repeat the smoke steps in WSL via a script file (see section 1).
