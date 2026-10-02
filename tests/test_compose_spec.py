from __future__ import annotations

import pathlib

from compman.compose_spec import VolumeMount, read_volume_mounts


def _write(tmp_path: pathlib.Path, body: str, name: str = "docker-compose.yml") -> pathlib.Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_read_volume_mounts_parses_short_syntax(tmp_path: pathlib.Path):
    path = _write(
        tmp_path,
        "services:\n"
        "  db:\n"
        "    volumes:\n"
        "      - pgdata:/var/lib/postgresql/data\n"
        "      - logs:/var/log:ro\n"
        "volumes:\n"
        "  pgdata:\n"
        "  logs:\n",
    )
    assert read_volume_mounts([path]) == (
        VolumeMount("pgdata", "db", "/var/lib/postgresql/data"),
        VolumeMount("logs", "db", "/var/log"),
    )


def test_read_volume_mounts_parses_long_syntax(tmp_path: pathlib.Path):
    path = _write(
        tmp_path,
        "services:\n"
        "  app:\n"
        "    volumes:\n"
        "      - type: volume\n"
        "        source: uploads\n"
        "        target: /uploads\n"
        "volumes:\n"
        "  uploads:\n",
    )
    assert read_volume_mounts([path]) == (VolumeMount("uploads", "app", "/uploads"),)


def test_read_volume_mounts_ignores_bind_and_anonymous_mounts(tmp_path: pathlib.Path):
    path = _write(
        tmp_path,
        "services:\n"
        "  app:\n"
        "    volumes:\n"
        "      - ./src:/app/src\n"
        "      - /var/run/docker.sock:/var/run/docker.sock\n"
        "      - /anon\n"
        "      - type: bind\n"
        "        source: /host\n"
        "        target: /container\n"
        "      - type: volume\n"
        "        target: /no-source\n"
        "      - 42\n"
        "      - [nested]\n"
        "volumes:\n"
        "  declared:\n",
    )
    assert read_volume_mounts([path]) == ()


def test_read_volume_mounts_skips_undeclared_sources(tmp_path: pathlib.Path):
    path = _write(
        tmp_path,
        "services:\n"
        "  app:\n"
        "    volumes:\n"
        "      - mystery:/data\n"
        "volumes:\n"
        "  declared:\n",
    )
    assert read_volume_mounts([path]) == ()


def test_read_volume_mounts_deduplicates_repeated_mounts(tmp_path: pathlib.Path):
    path = _write(
        tmp_path,
        "services:\n"
        "  app:\n"
        "    volumes:\n"
        "      - shared:/one\n"
        "      - shared:/one\n"
        "      - shared:/two\n"
        "volumes:\n"
        "  shared:\n",
    )
    assert read_volume_mounts([path]) == (
        VolumeMount("shared", "app", "/one"),
        VolumeMount("shared", "app", "/two"),
    )


def test_read_volume_mounts_lets_a_later_file_override_a_service(tmp_path: pathlib.Path):
    base = _write(
        tmp_path,
        "services:\n"
        "  app:\n"
        "    volumes:\n"
        "      - old:/old\n"
        "volumes:\n"
        "  old:\n",
        "base.yml",
    )
    override = _write(
        tmp_path,
        "services:\n"
        "  app:\n"
        "    volumes:\n"
        "      - fresh:/fresh\n"
        "volumes:\n"
        "  fresh:\n",
        "override.yml",
    )
    assert read_volume_mounts([base, override]) == (VolumeMount("fresh", "app", "/fresh"),)


def test_read_volume_mounts_merges_volumes_declared_across_files(tmp_path: pathlib.Path):
    base = _write(
        tmp_path,
        "services:\n"
        "  app:\n"
        "    volumes:\n"
        "      - one:/one\n"
        "volumes:\n"
        "  one:\n",
        "base.yml",
    )
    override = _write(
        tmp_path,
        "services:\n"
        "  db:\n"
        "    volumes:\n"
        "      - two:/two\n"
        "volumes:\n"
        "  two:\n",
        "override.yml",
    )
    assert read_volume_mounts([base, override]) == (
        VolumeMount("one", "app", "/one"),
        VolumeMount("two", "db", "/two"),
    )


def test_read_volume_mounts_returns_nothing_without_a_volumes_block(tmp_path: pathlib.Path):
    path = _write(tmp_path, "services:\n  app:\n    image: nginx\n")
    assert read_volume_mounts([path]) == ()


def test_read_volume_mounts_tolerates_missing_or_broken_files(tmp_path: pathlib.Path):
    good = _write(
        tmp_path,
        "services:\n  app:\n    volumes:\n      - keep:/keep\nvolumes:\n  keep:\n",
    )
    broken = _write(tmp_path, "services: [unclosed\n", "broken.yml")
    assert read_volume_mounts([broken]) == ()
    assert read_volume_mounts([tmp_path / "missing.yml", good]) == (
        VolumeMount("keep", "app", "/keep"),
    )


def test_read_volume_mounts_tolerates_a_non_mapping_services_block(tmp_path: pathlib.Path):
    path = _write(tmp_path, "services:\n  - not-a-mapping\nvolumes:\n  keep:\n")
    assert read_volume_mounts([path]) == ()


def test_read_volume_mounts_tolerates_a_service_without_volumes(tmp_path: pathlib.Path):
    path = _write(
        tmp_path,
        "services:\n"
        "  app:\n    image: nginx\n"
        "  db:\n    volumes:\n      - pgdata:/data\n"
        "volumes:\n  pgdata:\n",
    )
    assert read_volume_mounts([path]) == (VolumeMount("pgdata", "db", "/data"),)


def test_read_volume_mounts_tolerates_a_non_list_volumes_entry(tmp_path: pathlib.Path):
    path = _write(
        tmp_path,
        "services:\n  app:\n    volumes: not-a-list\nvolumes:\n  keep:\n",
    )
    assert read_volume_mounts([path]) == ()


def test_volume_mount_label_names_the_service_and_path():
    assert VolumeMount("pgdata", "db", "/var/lib/postgresql").label == "db:/var/lib/postgresql"