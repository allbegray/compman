from __future__ import annotations

import pathlib

import pytest

from compman.errors import CommandError
from compman.ops import seed


def test_generate_seed_normal(temp_dir: pathlib.Path):
    seed.generate_seed(output="my_project", archive=False, port=18080, force=False)
    proj_dir = temp_dir / "my_project"
    assert proj_dir.is_dir()
    assert (proj_dir / "index.html").exists()
    assert (proj_dir / "Dockerfile").exists()
    assert (temp_dir / "docker-compose.yml").exists()
    assert (temp_dir / "compman.yml").exists()

    content = (proj_dir / "Dockerfile").read_text(encoding="utf-8")
    assert "nginx:alpine" in content

    html = (proj_dir / "index.html").read_text(encoding="utf-8")
    assert '<html lang="en">' in html
    assert "<h1>compman Seed App</h1>" in html

    compose_content = (temp_dir / "docker-compose.yml").read_text(encoding="utf-8")
    assert "127.0.0.1:18080:80" in compose_content


def test_generate_seed_archive(temp_dir: pathlib.Path):
    seed.generate_seed(output="my_project", archive=True, port=18080, force=False)
    assert (temp_dir / "my_project.tar.gz").exists()


def test_generate_seed_existing(temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").touch()
    # Existing files without --force now fail with the command error contract
    with pytest.raises(CommandError, match="already exists"):
        seed.generate_seed(output="my_project", archive=False, port=18080, force=False)


@pytest.mark.parametrize("port", [0, 65536])
def test_generate_seed_rejects_out_of_range_ports(temp_dir: pathlib.Path, port: int):
    with pytest.raises(CommandError, match="port"):
        seed.generate_seed(output="seeded", archive=False, port=port, force=True)
