from __future__ import annotations

import pathlib

import pytest

from compman.config import (
    Config,
    ConfigError,
    DeploySpec,
    dump_default_config,
    load_config,
    resolve_deploy,
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


def test_load_config_deploy_not_string(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n  name: app\n  deploy: 123\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(str(config_file))


def test_load_config_limits_absent_ok(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
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


def test_load_config_deploy_string_normalized(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n  name: app\n  deploy: s3://bucket/app.tar.gz\n"
        "  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg.deploy is not None
    assert cfg.deploy["default"].source == "s3://bucket/app.tar.gz"
    assert cfg.deploy["default"].checksum is None
    assert cfg.deploy["default"].strategy is None


def test_load_config_deploy_per_profile_string_and_dict(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n"
        "  name: app\n"
        "  deploy:\n"
        "    default: s3://bucket/app.tar.gz\n"
        "    dev:\n"
        "      source: file://./dist/app.tar.gz\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg.deploy is not None
    assert cfg.deploy["default"].source == "s3://bucket/app.tar.gz"
    assert cfg.deploy["dev"].source == "file://./dist/app.tar.gz"


@pytest.mark.parametrize(
    ("deploy_yaml", "expected"),
    [
        (
            "deploy: s3://bucket/app.tar.gz",
            {"default": DeploySpec(source="s3://bucket/app.tar.gz")},
        ),
        (
            "deploy:\n    default: s3://bucket/app.tar.gz",
            {"default": DeploySpec(source="s3://bucket/app.tar.gz")},
        ),
        (
            "deploy:\n    default: s3://a.tar.gz\n    prod:\n      source: s3://b.tar.gz",
            {
                "default": DeploySpec(source="s3://a.tar.gz"),
                "prod": DeploySpec(source="s3://b.tar.gz"),
            },
        ),
        (
            "deploy:\n    default:\n      source: s3://a.tar.gz\n"
            "      checksum: sha256:" + "a" * 64 + "\n"
            "      strategy: recreate",
            {
                "default": DeploySpec(
                    source="s3://a.tar.gz", checksum="sha256:" + "a" * 64, strategy="recreate"
                )
            },
        ),
        (
            "deploy:\n    prod:\n      source: s3://b.tar.gz\n"
            "      strategy: pull-only",
            {"prod": DeploySpec(source="s3://b.tar.gz", strategy="pull-only")},
        ),
    ],
)
def test_load_config_deploy_per_profile_valid(
    temp_dir: pathlib.Path, deploy_yaml: str, expected: dict[str, DeploySpec]
):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        f"compman:\n  name: app\n  {deploy_yaml}\n"
        "  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    assert cfg.deploy == expected


@pytest.mark.parametrize(
    ("deploy_yaml", "match"),
    [
        ("deploy: 123", "deploy"),
        ("deploy: ''", "deploy"),
        ("deploy: {}", "deploy"),
        ("deploy:\n    default: 123", "deploy.default"),
        ("deploy:\n    default: ''", "deploy.default"),
        ("deploy:\n    default:\n      source: ''", "deploy.default.source"),
        ("deploy:\n    default:\n      checksum: bad", "deploy.default.source"),
        (
            "deploy:\n    dev:\n      source: s3://b/a.tar.gz\n      checksum: bad",
            "checksum",
        ),
        (
            "deploy:\n    dev:\n      source: s3://b/a.tar.gz\n      checksum: sha256:" + "z" * 64,
            "checksum",
        ),
        (
            "deploy:\n    dev:\n      source: s3://b/a.tar.gz\n      strategy: rolling",
            "strategy",
        ),
        ("deploy:\n    dev:\n      source: s3://b/a.tar.gz\n      extra: foo", "unknown keys"),
        ("deploy: []", "deploy"),
    ],
)
def test_load_config_deploy_invalid(temp_dir: pathlib.Path, deploy_yaml: str, match: str):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        f"compman:\n  name: app\n  {deploy_yaml}\n"
        "  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=match):
        load_config(str(config_file))


def test_resolve_deploy_profile_priority():
    deploy = {
        "default": DeploySpec(source="s3://bucket/default.tar.gz"),
        "dev": DeploySpec(source="s3://bucket/dev.tar.gz"),
    }
    assert resolve_deploy(deploy, "dev").source == "s3://bucket/dev.tar.gz"
    assert resolve_deploy(deploy, None).source == "s3://bucket/default.tar.gz"
    assert resolve_deploy(deploy, "unknown").source == "s3://bucket/default.tar.gz"


def test_resolve_deploy_fallback_and_errors():
    with pytest.raises(ConfigError, match="Unknown deploy profile"):
        resolve_deploy(None, None)
    with pytest.raises(ConfigError, match="Unknown deploy profile"):
        resolve_deploy(None, "dev")
    with pytest.raises(ConfigError, match="Unknown deploy profile"):
        resolve_deploy({"prod": DeploySpec(source="s3://b/a.tar.gz")}, "dev")
    with pytest.raises(ConfigError, match="Unknown deploy profile"):
        resolve_deploy({"prod": DeploySpec(source="s3://b/a.tar.gz")}, None)
    assert resolve_deploy("s3://bucket/app.tar.gz", "dev").source == "s3://bucket/app.tar.gz"
    assert resolve_deploy("s3://bucket/app.tar.gz", None).source == "s3://bucket/app.tar.gz"


@pytest.mark.parametrize(
    ("checksum", "valid"),
    [
        ("sha256:" + "a" * 64, True),
        ("sha256:" + "0" * 64, True),
        ("sha256:" + "f" * 64, True),
        ("sha256:" + "A" * 64, False),
        ("sha256:" + "a" * 63, False),
        ("sha256:" + "a" * 65, False),
        ("md5:" + "a" * 32, False),
        ("sha256:", False),
    ],
)
def test_load_config_deploy_checksum_validation(
    temp_dir: pathlib.Path, checksum: str, valid: bool
):
    config_file = temp_dir / "compman.yml"
    yaml_body = (
        "compman:\n  name: app\n  deploy:\n    default:\n"
        f"      source: s3://b/a.tar.gz\n      checksum: {checksum}\n"
        "  compose:\n    default:\n      file: docker-compose.yml\n"
    )
    config_file.write_text(yaml_body, encoding="utf-8")
    if valid:
        cfg = load_config(str(config_file))
        assert cfg.deploy is not None
        assert cfg.deploy["default"].checksum == checksum
    else:
        with pytest.raises(ConfigError, match="checksum"):
            load_config(str(config_file))


def test_deploy_map_methods(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n"
        "  name: app\n"
        "  deploy:\n"
        "    default: s3://bucket/default.tar.gz\n"
        "    dev: s3://bucket/dev.tar.gz\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    dm = cfg.deploy
    assert dm is not None
    assert len(dm) == 2
    assert "default" in dm
    assert "dev" in dm
    assert "prod" not in dm
    assert set(dm.keys()) == {"default", "dev"}
    assert {k for k, _ in dm.items()} == {"default", "dev"}
    assert len(list(dm.values())) == 2
    assert dm.get("default") is not None
    assert dm.get("default").source == "s3://bucket/default.tar.gz"
    assert dm.get("missing") is None
    assert dm.get("missing", None) is None
    assert list(dm) == ["default", "dev"]
    assert dm == {"default": DeploySpec(source="s3://bucket/default.tar.gz"), "dev": DeploySpec(source="s3://bucket/dev.tar.gz")}
    assert dm != {"default": DeploySpec(source="other")}
    assert dm == "s3://bucket/default.tar.gz"
    assert str(dm) == "s3://bucket/default.tar.gz"
    assert hash(dm) == hash("s3://bucket/default.tar.gz")
    assert dm["default"].source == "s3://bucket/default.tar.gz"
    assert dm[0] == "s"
    assert dm[0:2] == "s3"
    assert resolve_deploy(dm, "dev").source == "s3://bucket/dev.tar.gz"
    assert resolve_deploy(dm, None).source == "s3://bucket/default.tar.gz"
    assert resolve_deploy(dm, "unknown").source == "s3://bucket/default.tar.gz"


def test_resolve_deploy_with_deploymap_missing_default(temp_dir: pathlib.Path):
    config_file = temp_dir / "compman.yml"
    config_file.write_text(
        "compman:\n"
        "  name: app\n"
        "  deploy:\n"
        "    prod: s3://bucket/prod.tar.gz\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config_file))
    dm = cfg.deploy
    assert dm is not None
    with pytest.raises(ConfigError, match="Unknown deploy profile"):
        resolve_deploy(dm, "dev")
    with pytest.raises(ConfigError, match="Unknown deploy profile"):
        resolve_deploy(dm, None)


def test_parse_deploy_non_string_key():
    from compman.config import _parse_deploy

    with pytest.raises(ConfigError, match="keys must be non-empty"):
        _parse_deploy({123: "s3://bucket/app.tar.gz"})

    with pytest.raises(ConfigError, match="keys must be non-empty"):
        _parse_deploy({"": "s3://bucket/app.tar.gz"})


def test_deploymap_equality():
    from compman.config import _DeployMap

    a = _DeployMap("s3://a.tar.gz", {"default": DeploySpec(source="s3://a.tar.gz")})
    b = _DeployMap("s3://a.tar.gz", {"default": DeploySpec(source="s3://a.tar.gz")})
    c = _DeployMap("s3://b.tar.gz", {"default": DeploySpec(source="s3://b.tar.gz")})
    assert a == b
    assert a != c
    assert a == {"default": DeploySpec(source="s3://a.tar.gz")}
    assert hash(a) == hash("s3://a.tar.gz")


def test_resolve_deploy_invalid_type():
    with pytest.raises(ConfigError, match="Unknown deploy profile"):
        resolve_deploy(123, None)
    with pytest.raises(ConfigError, match="Unknown deploy profile"):
        resolve_deploy(123, "dev")
