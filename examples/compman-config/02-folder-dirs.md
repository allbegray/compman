# Case 02 — Folder and managed directories

Keep Compose files in a subdirectory and relocate the managed backup, volume,
and project directories.

## `compman.yml`

```yaml
# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
compman:
  name: my-stack
  folder: compose
  dirs:
    project: project
    backup: backup
    volume: volume
  compose:
    default:
      file: docker-compose.yml
```

- `folder`: relative subdirectory that holds the Compose files. With
  `folder: compose`, the compose file is `compose/docker-compose.yml`.
- `dirs.project`: managed deployment source directory.
- `dirs.backup`: backup archive directory.
- `dirs.volume`: volume transfer directory.

All paths resolve relative to the directory containing `compman.yml` and may
not escape it. Destructive managed directories may not equal the config root.

## Layout

```
my-stack/
├── compman.yml
├── compose/
│   └── docker-compose.yml
├── project/       # dirs.project — deploy source
├── backup/        # dirs.backup  — backup archives
└── volume/        # dirs.volume  — volume transfers
```

## Commands

```bash
compman stack up
compman volume backup        # writes into backup/
compman deploy               # fetches source into project/
```
