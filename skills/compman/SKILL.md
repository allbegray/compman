---
name: compman
description: Use when editing compman.yml or operating a Docker Compose stack through compman (deploy, update, stack up/down, service ops, volume/image backup and restore, schedule, diagnose). Not for changing compman's own source.
---

# compman

Docker/Podman Compose stack manager driven by `compman.yml`. The command surface is authoritative only in `--help`: run `compman --help`, then `compman <group> --help`, before composing a command. Never guess a flag.

## Which command

| Intent | Commands |
|---|---|
| Start/stop/recreate the stack, follow logs | `stack up`, `stack down --yes`, `stack update`, `stack logs` |
| One service: start, stop, restart, status, log, exec | `service start/stop/restart/status/log/connect` |
| Fetch a release, roll back, deploy + rebuild | `deploy`, `rollback`, `update` |
| Diagnose, structured status | `doctor [--json]`, `status [--json]` |
| Volume / image backup and restore | `volume backup/restore/pull/push`, `image backup/restore` |
| Unattended recurring volume backups | `schedule add/list/status/remove` |
| Any of the above against another registered stack | add `--stack NAME` |

Commands resolve the `compman.yml` in the working directory; `-c PATH` overrides it and wins over `--stack`.

## compman.yml

- Field contract (JSON Schema): `https://allbegray.github.io/compman/compman.schema.json` — the URL every scaffolded config points at. Authoritative for keys, types, defaults.
- Worked cases: https://github.com/allbegray/compman/tree/main/examples/compman-config (index in `examples/README.md`).
- Keep the `# yaml-language-server: $schema=...` first line when writing the file.

Invariants that silently break stacks:

- `compose:` is required and maps profile names to files or `{file, env, secrets}`; the first profile is the default.
- Values reach containers only through a profile `env`; the Compose file must reference them as `${VAR}`. A plain `environment:` entry stays literal.
- Secrets only as `${secrets:NAME}` markers inside profile `env`, backed by a `secrets:` entry with `arn` + `key`. Substitute into the env; never pass a secret as a standalone variable.
- Credentials stay out of the file: `deploy.auth.value_env` and `notify.slack.webhook_env` name environment variables.
- `folder` and `dirs.*` are relative to the config directory and may not escape it.

## Verify, then report

1. After a config edit: `compman doctor --json` — exit 1 means a required check failed. Fix each failing check and rerun until it exits 0 (warnings may remain).
2. After stack changes: `compman status --json` (schema version 1) for service state.
3. Operational failures are one-line errors by design; quote the failing check in the report instead of retrying blind.

## Get confirmation first

`stack down --yes`, `deploy` (swaps the managed tree), `update` (rebuild + forced recreate, brief downtime), `volume backup` (stops services unless `--no-stop`), `volume restore`, `image restore`, `stacks remove`, `clear` (prunes unused images and build cache). `-f` streaming (`log -f`, `stack logs -f`, `stats -f`) needs a terminal for its `q`+Enter quit; skip it in automation.
