from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from compman.backup_store import BackupStore, LocalBackupStore, parse_backup_store
from compman.errors import ConfigError

SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


def sanitize_project_name(name: str) -> str:
    """Normalize a string to a valid Docker Compose project name.

    Docker Compose project names must match [a-z0-9_-], start with [a-z0-9],
    and be entirely lowercase.
    """
    if not name:
        return "compman-app"
    s = str(name).lower()
    s = re.sub(r"[^a-z0-9_-]", "-", s)
    s = re.sub(r"^[^a-z0-9]+", "", s)
    s = s.strip("-_")
    return s or "compman-app"


@dataclass(frozen=True)
class Profile:
    file: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, SecretRef] = field(default_factory=dict)


@dataclass(frozen=True)
class SecretRef:
    arn: str
    key: str


@dataclass(frozen=True)
class DeployAuth:
    header: str
    value_env: str


@dataclass
class Config:
    name: str
    root_dir: Path = field(default_factory=Path.cwd)
    source_path: Path | None = None
    folder: str | None = None
    dirs: dict[str, str] = field(
        default_factory=lambda: {"backup": "backup", "volume": "volume", "project": "project"}
    )
    compose_base: str | None = None
    profiles: dict[str, Profile] = field(default_factory=dict)
    secrets: dict[str, SecretRef] = field(default_factory=dict)
    deploy: str | None = None
    deploy_sha256: str | None = None
    deploy_auth: DeployAuth | None = None
    max_archive_mb: int | None = None
    max_backups: int | None = None
    backup_store: BackupStore = field(
        default_factory=lambda: LocalBackupStore(Path.cwd() / "backup")
    )

    @property
    def limits(self) -> dict[str, int]:
        """Backward-compatible read view of the configured limits."""
        return {} if self.max_archive_mb is None else {"max_archive_mb": self.max_archive_mb}

    @property
    def project_dir(self) -> Path:
        return _managed_path(self.root_dir, self.folder, "folder", allow_root=True) if self.folder else self.root_dir.resolve()

    @property
    def volume_dir(self) -> Path:
        return _managed_path(self.root_dir, self.dirs.get("volume", "volume"), "dirs.volume")

    @property
    def deploy_dir(self) -> Path:
        return _managed_path(self.root_dir, self.dirs.get("project", "project"), "dirs.project")


def _managed_path(root: Path, value: str, field_name: str, allow_root: bool = False) -> Path:
    resolved_root = root.resolve()
    target = (resolved_root / value).resolve()
    if (target == resolved_root and not allow_root) or (
        target != resolved_root and resolved_root not in target.parents
    ):
        raise ConfigError(
            f"'{field_name}' must be a child directory inside the config directory: {value}"
        )
    return target


def _parse_secrets(raw: object, field_name: str) -> dict[str, SecretRef]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"'{field_name}' must be a mapping.")
    secrets: dict[str, SecretRef] = {}
    for env_name, raw_ref in raw.items():
        if not isinstance(raw_ref, dict) or not isinstance(raw_ref.get("arn"), str):
            raise ConfigError(
                f"'{field_name}.{env_name}' must be a mapping with an 'arn' string."
            )
        raw_key = raw_ref.get("key")
        if not isinstance(raw_key, str) or not raw_key:
            raise ConfigError(f"'{field_name}.{env_name}' is missing a 'key' string.")
        secrets[str(env_name)] = SecretRef(arn=str(raw_ref["arn"]), key=raw_key)
    return secrets


def load_config(config_path: str | None = None) -> Config:
    path = (Path(config_path) if config_path else Path.cwd() / "compman.yml").resolve()
    if not path.is_file():
        raise ConfigError(
            f"{path} not found. Run 'compman init' first."
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}") from e
    if not raw or not isinstance(raw, dict):
        raise ConfigError("Invalid config file: not a YAML mapping.")
    root = raw.get("compman")
    if not root or not isinstance(root, dict):
        raise ConfigError("'compman' key not found or not a mapping.")

    raw_name = root.get("name") or path.parent.name
    name = sanitize_project_name(str(raw_name))

    folder = root.get("folder")
    if folder is not None and not isinstance(folder, str):
        raise ConfigError("'folder' must be a string.")
    raw_dirs = root.get("dirs", {})
    if not isinstance(raw_dirs, dict):
        raise ConfigError("'dirs' must be a mapping.")
    dirs = {
        "backup": str(raw_dirs.get("backup", "backup")),
        "volume": str(raw_dirs.get("volume", "volume")),
        "project": str(raw_dirs.get("project", "project")),
    }

    compose_base: str | None = None
    profiles: dict[str, Profile] = {}

    raw_compose = root.get("compose")
    if raw_compose is None:
        raise ConfigError(
            "'compose' is required and must be a mapping of profiles."
        )
    if not isinstance(raw_compose, dict):
        raise ConfigError(
            "'compose' must be a mapping of profiles, e.g. "
            "'compose:\n  default:\n    file: docker-compose.yml'."
        )
    for key, val in raw_compose.items():
        if key == "base":
            compose_base = str(val)
        elif isinstance(val, str):
            profiles[key] = Profile(file=str(val))
        elif isinstance(val, dict):
            f = val.get("file")
            raw_env = val.get("env", {})
            if not isinstance(raw_env, dict):
                raise ConfigError(f"'compose.{key}.env' must be a mapping.")
            profiles[key] = Profile(
                file=str(f) if f else None,
                env={str(k): str(v) for k, v in raw_env.items()},
                secrets=_parse_secrets(val.get("secrets"), f"compose.{key}.secrets"),
            )
        else:
            raise ConfigError(
                f"Invalid value for 'compose.{key}': expected string or object."
            )

    raw_deploy = root.get("deploy")
    deploy_url: str | None = None
    deploy_sha256: str | None = None
    deploy_auth: DeployAuth | None = None
    if isinstance(raw_deploy, str):
        deploy_url = raw_deploy
    elif isinstance(raw_deploy, dict):
        url = raw_deploy.get("url")
        if not isinstance(url, str):
            raise ConfigError("'deploy.url' must be a string (e.g. 's3://bucket/app.tar.gz').")
        deploy_url = url
        raw_sha256 = raw_deploy.get("sha256")
        if raw_sha256 is not None:
            if not isinstance(raw_sha256, str) or not SHA256_PATTERN.fullmatch(raw_sha256):
                raise ConfigError(
                    "'deploy.sha256' must be a 64-character hexadecimal SHA-256 digest."
                )
            deploy_sha256 = raw_sha256.lower()
        raw_auth = raw_deploy.get("auth")
        if raw_auth is not None:
            if not isinstance(raw_auth, dict):
                raise ConfigError("'deploy.auth' requires 'header' and 'value_env' strings.")
            header = raw_auth.get("header")
            value_env = raw_auth.get("value_env")
            if (
                not isinstance(header, str)
                or not header
                or not isinstance(value_env, str)
                or not value_env
            ):
                raise ConfigError("'deploy.auth' requires 'header' and 'value_env' strings.")
            if not HEADER_NAME_PATTERN.fullmatch(header):
                raise ConfigError("'deploy.auth.header' is not a valid HTTP header name.")
            if not url.startswith("https://"):
                raise ConfigError("Authenticated HTTP deploy sources require an https:// URL.")
            deploy_auth = DeployAuth(header=header, value_env=value_env)
    elif raw_deploy is not None:
        raise ConfigError(
            "'deploy' must be a string (e.g. 's3://bucket/app') or a mapping with a 'url' key."
        )

    raw_secrets = root.get("secrets", {})
    if not isinstance(raw_secrets, dict):
        raise ConfigError("'secrets' must be a mapping.")
    secrets = _parse_secrets(raw_secrets, "secrets")

    raw_limits = root.get("limits", {})
    if not isinstance(raw_limits, dict):
        raise ConfigError("'limits' must be a mapping.")
    max_archive_mb = raw_limits.get("max_archive_mb")
    if max_archive_mb is not None:
        if not isinstance(max_archive_mb, int):
            raise ConfigError("'limits.max_archive_mb' must be an integer.")
        if max_archive_mb <= 0:
            raise ConfigError("'limits.max_archive_mb' must be greater than 0.")
    max_backups = raw_limits.get("max_backups")
    if max_backups is not None:
        if not isinstance(max_backups, int):
            raise ConfigError("'limits.max_backups' must be an integer.")
        if max_backups <= 0:
            raise ConfigError("'limits.max_backups' must be greater than 0.")

    raw_backup = str(raw_dirs.get("backup", "backup"))
    # Branch before _managed_path: an s3:// URI would otherwise fail the
    # child-of-config-root check with a confusing error.
    backup_store = parse_backup_store(raw_backup)
    if isinstance(backup_store, LocalBackupStore):
        backup_store = replace(
            backup_store, root=_managed_path(path.parent, raw_backup, "dirs.backup")
        )

    config = Config(
        name=name,
        root_dir=path.parent,
        source_path=path,
        folder=folder,
        dirs=dirs,
        compose_base=compose_base,
        profiles=profiles,
        secrets=secrets,
        deploy=deploy_url,
        deploy_sha256=deploy_sha256,
        deploy_auth=deploy_auth,
        max_archive_mb=max_archive_mb,
        max_backups=max_backups,
        backup_store=backup_store,
    )
    # Resolve all paths while loading so unsafe configuration fails before a
    # command can create, replace, or recursively delete anything.
    config.project_dir
    config.volume_dir
    config.deploy_dir
    return config


def dump_default_config(name: str) -> str:
    sanitized = sanitize_project_name(name)
    return f"""# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
compman:
  name: {sanitized}
  compose:
    default:
      file: docker-compose.yml
  # --- optional features ---
  # folder: my-project             # _project/ subdirectory
  # deploy: s3://bucket/app        # S3 or HTTP archive source (--path overrides)
  # deploy:                        # mapping form pins archive integrity:
  #   url: s3://bucket/app.tar.gz
  #   sha256: 64-hex-lowercase-digest-of-the-archive
  # dirs:
  #   backup: backup                  # or an S3 URI: s3://bucket/backups
  #   volume: volume
  # limits:
  #   max_backups: 10                # keep newest 10 archives per stack and kind
  # per-profile env (consumed via ${{VAR}} in compose files):
  #   dev:
  #     file: docker-compose.dev.yml
  #     env:
  #       DATABASE_URL: dev.example.com:5432
  #   prod:
  #     file: docker-compose.prod.yml
  #     env:
  #       DATABASE_URL: prod.example.com:5432
  # shared secrets (common to all profiles):
  # secrets:
  #   DB_URL:
  #     arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
  #     key: dtx/db/url
  # profile env can reference secrets: ${{secrets:DB_URL}}
"""
