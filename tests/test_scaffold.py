from __future__ import annotations

import pathlib

import yaml

import compman.scaffold as scaffold


def test_scaffold_update_deploy_dict_with_existing_compman(temp_dir: pathlib.Path):
    yml = temp_dir / "compman.yml"
    yml.write_text("compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n", encoding="utf-8")
    deploy_dict = {"default": "s3://bucket/app.tar.gz", "dev": {"source": "file://./dist/app.tar.gz"}}
    scaffold.update_deploy(yml, deploy_dict)
    data = yaml.safe_load(yml.read_text(encoding="utf-8"))
    assert data["compman"]["deploy"] == deploy_dict


def test_scaffold_update_deploy_dict_minimal_no_compman(temp_dir: pathlib.Path):
    yml = temp_dir / "compman.yml"
    yml.write_text("other: value\n", encoding="utf-8")
    deploy_dict = {"default": "s3://bucket/app.tar.gz"}
    scaffold.update_deploy(yml, deploy_dict)
    data = yaml.safe_load(yml.read_text(encoding="utf-8"))
    assert data["compman"]["deploy"] == deploy_dict


def test_scaffold_update_deploy_dict_idempotent(temp_dir: pathlib.Path):
    yml = temp_dir / "compman.yml"
    deploy_dict = {"default": "s3://bucket/app.tar.gz"}
    yml.write_text(yaml.safe_dump({"compman": {"name": "app", "deploy": deploy_dict}}), encoding="utf-8")
    before = yml.read_text(encoding="utf-8")
    scaffold.update_deploy(yml, deploy_dict)
    after = yml.read_text(encoding="utf-8")
    assert before == after


def test_scaffold_generate_string_deploy(temp_dir: pathlib.Path):
    root = temp_dir / "scaffold_root"
    root.mkdir()
    scaffold.generate(root, "project", "s3://bucket/app.tar.gz", "my-image")
    assert (root / "compman.yml").exists()
    assert (root / "docker-compose.yml").exists()
    content = (root / "compman.yml").read_text(encoding="utf-8")
    assert "s3://bucket/app.tar.gz" in content
