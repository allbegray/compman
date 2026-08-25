from __future__ import annotations

import pathlib

import pytest
from conftest import write_config

from compman.config import (
    Config,
    ConfigError,
    dump_default_config,
    load_config,
    sanitize_project_name,
)


def test_sanitize_project_name():
    assert sanitize_project_name("My Project!") == "my-project"
    assert sanitize_project_name("Desktop-App_123") == "desktop-app_123"
    assert sanitize_project_name("!!!") == "compman-app"
    assert sanitize_project_name("") == "compman-app"


def test_dump_default_config():
    content = dump_default_config("my-app")
    assert "name: my-app" in content
    assert "compose:" in content


def test_config_properties(temp_dir: pathlib.Path):
    cfg = Config(name="test", folder="sub", dirs={"backup": "bak", "volume": "vol", "project": "proj"})
    assert cfg.project_dir == temp_dir / "sub"
    assert cfg.backup_dir == temp_dir / "bak"
    assert cfg.volume_dir == temp_dir / "vol"
    assert cfg.deploy_dir == temp_dir / "proj"


def test_load_config_simple_list_rejected(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n"
        "  name: test-app\n"
        "  compose:\n"
        "    - docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="compose"):
        load_config(str(config_file))


def test_load_config_compose_omitted_rejected(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text("compman:\n  name: test-app\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="compose"):
        load_config(str(config_file))


def test_load_config_profiles(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n"
        "  name: test-app\n"
        "  compose:\n"
        "    base: docker-compose.base.yml\n"
        "    dev:\n"
        "      file: docker-compose.dev.yml\n"
        "      env:\n"
        "        FOO: BAR\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert "dev" in cfg.profiles
    assert cfg.profiles["dev"].file == "docker-compose.dev.yml"
    assert cfg.profiles["dev"].env == {"FOO": "BAR"}
    assert cfg.compose_base == "docker-compose.base.yml"


def test_load_config_single_compose_str(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n"
        "  name: test-app\n"
        "  compose: docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(str(config_file))


def test_load_config_profile_string_only(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n"
        "  name: test-app\n"
        "  compose:\n"
        "    dev: docker-compose.dev.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg.profiles["dev"].file == "docker-compose.dev.yml"


def test_load_config_missing_file(temp_dir: pathlib.Path):
    with pytest.raises(ConfigError):
        load_config(str(temp_dir / "nonexistent.yml"))


def test_load_config_invalid_yaml(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text("invalid: : [", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_config(str(config_file))


def test_load_config_missing_root_key(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text("other: foo", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config_file))


def test_load_config_default_name(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n  name: default-test\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg.name == "default-test"


def test_load_config_deploy_plain_string_unchanged(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n  name: app\n  deploy: s3://b/k.tar.gz\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg.deploy == "s3://b/k.tar.gz"
    assert cfg.deploy_sha256 is None


def test_load_config_deploy_mapping_with_sha256(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    digest = "a" * 64
    config_file.write_text(
        "compman:\n"
        "  name: app\n"
        "  deploy:\n"
        "    url: s3://b/k.tar.gz\n"
        f"    sha256: {digest}\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg.deploy == "s3://b/k.tar.gz"
    assert cfg.deploy_sha256 == digest


def test_load_config_deploy_mapping_uppercase_sha256_normalized(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n"
        "  name: app\n"
        "  deploy:\n"
        "    url: s3://b/k.tar.gz\n"
        f"    sha256: {'A' * 64}\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg.deploy_sha256 == "a" * 64


def test_load_config_deploy_mapping_without_sha256(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n"
        "  name: app\n"
        "  deploy:\n"
        "    url: s3://b/k.tar.gz\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg.deploy == "s3://b/k.tar.gz"
    assert cfg.deploy_sha256 is None


def test_load_config_deploy_mapping_missing_url(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n  name: app\n  deploy:\n    sha256: abc\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="deploy.url"):
        load_config(str(config_file))


@pytest.mark.parametrize("raw_url", ["123", ["s3://b/k.tar.gz"]])
def test_load_config_deploy_mapping_non_string_url(temp_dir: pathlib.Path, raw_url):
    config_file = temp_dir / "compman.yml"
    list_yaml = "\n      - s3://b/k.tar.gz" if isinstance(raw_url, list) else str(raw_url)
    config_file.write_text(
        "compman:\n"
        "  name: app\n"
        "  deploy:\n"
        f"    url: {list_yaml}\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="deploy.url"):
        load_config(str(config_file))


@pytest.mark.parametrize("digest", ["abc123", "z" * 64, 123])
def test_load_config_deploy_sha256_invalid(temp_dir: pathlib.Path, digest):
    config_file = temp_dir / "compman.yml"
    quoted = str(digest) if isinstance(digest, int) else digest
    config_file.write_text(
        "compman:\n"
        "  name: app\n"
        "  deploy:\n"
        "    url: s3://b/k.tar.gz\n"
        f"    sha256: {quoted}\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="deploy.sha256"):
        load_config(str(config_file))


@pytest.mark.parametrize("raw_deploy", [123, ["s3://b/k"]])
def test_load_config_deploy_not_string(temp_dir: pathlib.Path, raw_deploy):
    config_file = temp_dir / "compman.yml"
    list_yaml = "\n    - s3://b/k" if isinstance(raw_deploy, list) else str(raw_deploy)
    config_file.write_text(
        "compman:\n"
        "  name: app\n"
        f"  deploy: {list_yaml}\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="'deploy' must be"):
        load_config(str(config_file))


def test_load_config_limits_absent_ok(temp_dir: pathlib.Path):
    config_file = write_config(temp_dir / "compman.yml")
    cfg = load_config(str(config_file))
    assert cfg.limits == {}


def test_load_config_limits_valid(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n  name: app\n  limits:\n    max_archive_mb: 10\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg.limits == {"max_archive_mb": 10}


def test_load_config_limits_not_mapping(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n  name: app\n  limits: []\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="limits"):
        load_config(str(config_file))


def test_load_config_max_archive_mb_not_int(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n  name: app\n  limits:\n    max_archive_mb: '10'\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="max_archive_mb"):
        load_config(str(config_file))


def test_load_config_max_archive_mb_non_positive(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n  name: app\n  limits:\n    max_archive_mb: 0\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="max_archive_mb"):
        load_config(str(config_file))


def test_load_config_compose_invalid_type(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text("compman:\n  name: app\n  compose: 42\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config_file))


def test_load_config_compose_invalid_profile_value(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text("compman:\n  name: app\n  compose:\n    dev: 123\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config_file))


def test_load_config_invalid_nested_types(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text("compman:\n  dirs: []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="dirs"):
        load_config(str(config_file))

    config_file.write_text(
        "compman:\n  compose:\n    dev:\n      env: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="env"):
        load_config(str(config_file))

def test_load_config_no_name_uses_cwd(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg.name == sanitize_project_name(temp_dir.name)
    assert cfg.profiles["default"].file == "docker-compose.yml"


def test_load_config_secrets_valid(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n"
        "  name: app\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n"
        "  secrets:\n"
        "    DB_URL:\n"
        "      arn: arn:aws:secretsmanager:ap-northeast-2:123:secret:app\n"
        "      key: dtx/db/url\n"
        "    API_KEY:\n"
        "      arn: arn:aws:secretsmanager:ap-northeast-2:123:secret:app2\n"
        "      key: api-key\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg.secrets["DB_URL"].arn.endswith("secret:app")
    assert cfg.secrets["DB_URL"].key == "dtx/db/url"
    assert cfg.secrets["API_KEY"].key == "api-key"


def test_load_config_profile_secrets_valid(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n"
        "  name: app\n"
        "  compose:\n"
        "    dev:\n"
        "      file: docker-compose.dev.yml\n"
        "      secrets:\n"
        "        DB_PASS:\n"
        "          arn: arn:aws:secretsmanager:ap-northeast-2:123:secret:db\n"
        "          key: dtx/db/password\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg.profiles["dev"].secrets["DB_PASS"].arn.endswith("secret:db")
    assert cfg.profiles["dev"].secrets["DB_PASS"].key == "dtx/db/password"


def test_load_config_secrets_not_mapping(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n  secrets: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="secrets"):
        load_config(str(config_file))


def test_load_config_secrets_value_missing_arn_key(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n  secrets:\n    DB_URL: arn:foo\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="DB_URL"):
        load_config(str(config_file))

    config_file.write_text(
        "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n  secrets:\n    DB_URL:\n      arn: foo\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="key"):
        load_config(str(config_file))


def test_load_config_profile_secrets_not_mapping(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n  name: app\n  compose:\n    dev:\n      secrets: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="secrets"):
        load_config(str(config_file))


def test_load_config_resolves_paths_from_config_directory(tmp_path: pathlib.Path):
    project = tmp_path / "project"
    project.mkdir()
    config_file = project / "compman.yml"
    config_file.write_text(
        "compman:\n"
        "  name: app\n"
        "  folder: compose\n"
        "  dirs:\n"
        "    backup: backups\n"
        "    volume: volumes\n"
        "    project: source\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg.root_dir == project
    assert cfg.project_dir == project / "compose"
    assert cfg.backup_dir == project / "backups"
    assert cfg.volume_dir == project / "volumes"
    assert cfg.deploy_dir == project / "source"


@pytest.mark.parametrize(
    ("field", "yaml_value"),
    [
        ("folder", "folder: ../outside"),
        ("dirs.backup", "dirs:\n    backup: ../outside"),
        ("dirs.volume", "dirs:\n    volume: ../outside"),
        ("dirs.project", "dirs:\n    project: ../outside"),
        ("dirs.volume", "dirs:\n    volume: ."),
        ("dirs.project", "dirs:\n    project: ."),
    ],
)
def test_load_config_rejects_managed_paths_outside_project(
    tmp_path: pathlib.Path, field: str, yaml_value: str
):
    project = tmp_path / "project"
    project.mkdir()
    config_file = project / "compman.yml"
    config_file.write_text(
        f"compman:\n  name: app\n  {yaml_value}\n"
        "  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=field):
        load_config(str(config_file))
