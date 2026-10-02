# SOLUTION.md — Development Knowledge Base

Lessons from developing, testing, and debugging compman. Read before changing
runtime interaction, CLI behavior, or tests. Companions: `AGENTS.md` (operating
rules), `BACKLOG.md` (open work).

## 1. Environment traps (Windows / WSL / Docker)

- **A "hung" WSL command is usually a zombie `wsl.exe` holding the pipe, not the program.** With no output, check `Get-Process wsl` for leftovers from aborted runs. Isolate by redirecting inside WSL and bounding with `timeout 20 <cmd> > /tmp/out 2>/tmp/err` — a healthy CLI returns instantly.
- **Never blanket-kill `wsl.exe` or `wsl --shutdown` while Docker Desktop runs.** It corrupts the `docker-desktop` distro bootstrap (`ExecError`, missing `componentsVersion.json`). Recover by restarting `Docker Desktop.exe` and polling `docker info` for up to ~90s. Orphaned `wsl.exe` processes are harmless; the OS reaps them.
- **PowerShell `\$` is not an escape; use a backtick.** Sending complex bash through PowerShell quoting invites silent corruption (`$HOME`/`$PATH` expand to Windows values and break the Linux PATH). Write a temp `.sh` and run `wsl -d Ubuntu -- bash /mnt/c/.../script.sh`.
- **WSL Ubuntu often lacks `python3-venv`/`pip`** (ensurepip absent). Use `uv tool install <wheel>`; if uv is missing, download `uv-x86_64-unknown-linux-gnu.tar.gz` on Windows and copy it into `~/.local/bin`.
- **`$env:TEMP` may be an 8.3 short path** (`C:\Users\AIMMED~1\...`); WSL reaches it as `/mnt/c/Users/AIMMED~1/...`.

## 2. Test traps

- **`DummyRuntime` is a scripted double, not a success stub.** Every public `ContainerRuntime` method is overridden explicitly and the fixture fails the test if a base method is added without one, so tests never fall through to real subprocess code. Failures are scriptable per channel and consumed FIFO: `dummy_runtime.queue(run_cli=(1, "", "boom"))`, `queue(compose=[(0, "cid", "")])`, `queue(passthru_cli=7)`. Results are real `CompletedProcess` objects (`.returncode`, never `.return_code`).
- **Assert on recorded argv, not on prose.** Docker/compose argv lands in `commands_run`, every compose invocation in `compose_runs`; keep asserting `dummy_runtime.compose_runs[*]["args"]`.
- **Success-biased mocks hid two real bugs** at 100% branch coverage: a `docker exec` against a stopped container swallowed by a mock that always succeeded, and `compose ps -q` returning IDs where names were expected. Any new runtime interaction needs a live-Docker check *and* a queued-failure test.
- **100% line/branch coverage is not correctness.** Executed is not useful. The retired sweep files (`test_missing_coverage.py`, `test_coverage_completion.py`) kept production-dead code alive (`volume._fix_permissions`). Behavioral cases live in feature files under behavior-describing names; do not reintroduce "remaining branches" grab-bags.
- **CLI invocations leak the language `ContextVar`.** `runner.invoke(app, ["lang", "ko"])` pollutes later tests; an autouse `conftest.py` fixture resets `i18n._CURRENT_LANG`.
- **`t()` keys fail silently.** A typo prints the key name. `tests/test_i18n.py` AST-checks that every key used in `compman/` exists, is bilingual, and is not unused.
- **Hardcoded user-facing strings recur.** `tests/test_repository_urls.py` AST-scans `typer.echo/confirm/prompt` first args *and* `typer.Option/Argument` `help=` for sentence-like literals.
- **Static command lists drift.** The PowerShell completion snippet and the README Commands block are cross-validated against the live typer tree (`tests/test_cli.py`).
- **Expected failures raise `CommandError("", code=N)` at the boundary.** `HelpOnUnknownCommandGroup.main` converts them to bare exits; stderr echoes happen where the error is detected, never via tracebacks.

## 3. Code pattern traps

- **`docker ps -q <service>` returns container IDs; the `name=^...$` filter matches names only.** Never re-resolve a `ps -q` result through `get_container_id` — use the resolved identifier directly (the `service log/connect` bug).
- **`docker exec` only works on a running container.** Inside `stack_paused` it fails silently when `|| true` / `2>/dev/null` swallow the error — the `volume restore --replace` bug: the delete never ran but the command "succeeded". Destructive operations must not suppress failures; clear the destination *before* stopping the stack.
- **Fail early, before filesystem mutation.** Deploy `--build` builds from the temporary source *before* the managed-tree swap, so a build failure leaves the existing tree untouched. Put fallible work ahead of irreversible work.
- **Every user-facing string goes through `t()`** — including `help=` text on options and arguments, not just `echo`/`confirm`/`prompt`. Exception messages stay English.
- **Duplicated helpers drift.** `ops/volume.py` and `ops/image.py` each had a `_validate_timestamp` with *different* messages; consolidated into one public `ops/common.validate_timestamp`.
- **A webhook that returns `HTTP 200` has not necessarily worked.** Slack answers `200` for revoked, expired, malformed, and *misspelled* webhooks — a bad path is even redirected to the HTML docs site — and puts the verdict in the body (`ok`, or `no_token` / `invalid_payload`). Verify the body, collapse whitespace, and truncate it.
- **Verify against the real tool before designing around its output.** Three assumptions about `compose ps` were wrong until a live Docker run: it **omits exited containers** without `--all` (a crashed service would vanish and the message would claim all healthy); its `Mounts` column is **truncated to an ellipsis** in `--format json`, so mount paths must come from the compose files; and `Publishers` lists each mapping **twice** (IPv4 + IPv6).
- **A best-effort side channel must be gated before it does any work.** The Slack hook needs extra `compose ps` and `system df` queries; guard on "is a webhook configured?" so an opted-out stack pays nothing. Same rule as the lazy boto3 import and lazily resolved secrets.
- **Secrets belong in environment variables, not in `compman.yml`.** Config names the variable, the value is read at use time, errors name only the variable. When a block opts into one variable, do not silently fall back to a global default of the same purpose — that hides a broken per-stack setting.
- **A summary plus exceptions beats a full dump.** An operator reads "3 of 3 healthy" and needs the names of the ones that are not — the failure case is where detail belongs. Slack rejecting an oversized block (`invalid_payload`, returned as 200-with-error-body) makes full dumps worse than noisy: they fail silently.
- **"Allows for 2 columns" is not "renders as 2 columns".** Slack documents `section.fields` as rendering "in a compact format that allows for 2 columns" — permissive language, and clients that stack them double the height. Anything that must look the same everywhere belongs in one `mrkdwn` block that packs its own columns.
- **SEO regressions are silent, so pin them with tests.** In a static site a renamed anchor, a `softwareVersion` that drifts from `pyproject.toml`, or a FAQ answer that no longer matches the visible page all ship unnoticed. `tests/test_site_seo.py` asserts length bands, one `<h1>`, resolvable anchors, JSON-LD validity, version agreement, and that every FAQPage question is visible.
- **Grid children default to `min-width: auto`, and check the real deployment path.** One long `<pre>` line widened a whole grid track past a 375px viewport, scrolling sideways even though the `<pre>` had `overflow-x: auto`. Absolute `/compman/...` asset hrefs, correct on GitHub Pages, silently 404 on a local `http.server` rooted at `docs/site` — which reads as broken CSS and hides the layout bug. Serve a copy under the `/compman/` prefix and measure there.

## 4. Recurring real-device E2E procedure

After any change touching runtime interaction, on a machine with Docker:

1. `uv build --wheel` → `uv tool install <wheel>` into an isolated `UV_TOOL_DIR`.
2. Smoke: `--version`, `-h`, `--lang ko --help`, `init --scaffold`, `doctor`, `status`, `completion bash`, `completion <unknown>` (expect exit 1).
3. Stack: `init --seed` → `stack up` (real build) → `service status` / `ps` / `stats` → `service log app` (service-name resolution) → HTTP 200 check.
4. Volumes: `volume backup` → mutate → `volume restore` (merge keeps new files) → `volume restore <ts> --replace` (destination-only files deleted) → `volume pull` / `volume push --replace`.
5. Images: `image backup` / `image restore`.
6. Guard rails: `clear` without `--yes` must abort; `stack down --yes` must clean up.
7. Repeat the smoke steps in WSL via a script file (see section 1).
