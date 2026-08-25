# Case 13 — Scheduled backups

Register an unattended `volume backup` job with the platform scheduler so
backups run on a cadence without a shell loop or cron-fu. Combine with the
S3 backup store (Case 11) and every scheduled backup also replicates off-site.

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

No scheduling-specific configuration exists; the registry lives at
`~/.config/compman/schedules.json` (`%APPDATA%\compman\schedules.json` on
Windows) and is managed entirely by the commands below.

## Register a schedule

```bash
compman schedule add --daily 04:30 --no-stop       # every day at 04:30 local time
compman schedule add --every 30m                   # every 30 minutes
compman schedule add --weekly sun 03:00 -z 9      # Sundays at 03:00, gzip level 9
```

- Exactly one cadence option is required: `--every Nm|Nh`, `--daily HH:MM`,
  or `--weekly <day> HH:MM` (`sun`..`sat`, case-insensitive).
- `--no-stop`, `-z LEVEL`, and `--profile` are baked into the registered
  command verbatim, exactly as you would pass them to `compman volume backup`.
- The job invokes `[compman, -c <abs config>, volume backup, ...]` directly —
  no wrapper scripts — and appends output to `schedule.log` next to the
  schedule registry (`~/.config/compman/schedule.log`).
- On Linux with systemd timers, output goes to journald instead:
  `journalctl --user -u compman-<name>.service`.

## Inspect and remove

```bash
compman schedule list             # shows name, mechanism, cadence, config path
compman schedule remove daily-04-30
```

`schedule list` probes each platform artifact and marks drifted entries
`[missing]`. `schedule remove` deletes the registry entry even when the
platform artifact is already gone, so cleanup never gets stuck.

## Mechanism selection

| Platform | Mechanism |
|----------|-----------|
| macOS | launchd (`~/Library/LaunchAgents/com.compman.volume.<name>.plist`) |
| Windows | schtasks (runs only while the user is logged on) |
| Linux | systemd user timer when `systemctl --user show-environment` succeeds, otherwise crontab |

Force the Linux mechanism with `--scheduler systemd` or `--scheduler cron`.
Cron cannot express every interval: `--every` values must divide 60 minutes
(or be whole hours), so `--every 45m` fails registration with a hint to force
systemd instead.

## Limitations

- macOS LaunchAgents fire only while the user is logged in.
- Windows tasks run only while the user is logged on.
- A scheduled backup behaves like any non-interactive run: if Docker Desktop
  is required and not ready, the job fails concisely instead of hanging.
