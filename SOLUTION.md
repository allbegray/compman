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

- **`DummyRuntime` is success-biased.** Its `run_cli`/`run_compose` always return
  `returncode=0` with fixed stdout, so real runtime semantics are invisible to unit
  tests: `docker exec` fails on a *stopped* container, and `compose ps -q` returns
  *container IDs*, not names. Two real bugs (below) passed 100% branch coverage and
  were only caught by a real-Docker E2E. Any new runtime interaction needs a live
  Docker check, not just mock assertions.
- **100% line/branch coverage is not correctness.** Coverage-sweep tests
  (`test_missing_coverage.py`, `test_coverage_completion.py`) kept dead code alive
  (`volume._fix_permissions` was production-unused for a long time). Coverage means
  executed, not useful.
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
