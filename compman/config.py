from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from compman.errors import ConfigError


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


@dataclass
class Profile:
    file: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, SecretRef] = field(default_factory=dict)
    env_file: list[str] = field(default_factory=list)


@dataclass
class SecretRef:
    arn: str
    key: str


@dataclass(frozen=True)
class DeploySpec:
    source: str
    checksum: str | None = None
    strategy: str | None = None


class _DeployMap(str):
    """Hybrid str/dict for backward-compatible deploy field.

    Behaves as str (default source) for legacy ``config.deploy`` usage
    (e.g. ``urlparse(config.deploy)``) while also supporting dict
    access ``config.deploy[profile]``.
    """

    _data: dict[str, DeploySpec]

    def __new__(cls, source: str, data: dict[str, DeploySpec]) -> _DeployMap:
        obj = super().__new__(cls, source)
        object.__setattr__(obj, "_data", data)
        return obj

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            return self._data[key]
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, dict):
            return self._data == other
        if isinstance(other, _DeployMap):
            return self._data == other._data and str(self) == str(other)
        return super().__eq__(other)

    def __hash__(self) -> int:
        return super().__hash__()

    def get(self, key: str, default: DeploySpec | None = None) -> DeploySpec | None:
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()

    def items(self):
        return self._data.items()

    def values(self):
        return self._data.values()


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
    deploy: Any = None
    limits: dict[str, Any] = field(default_factory=dict)

    @property
    def project_dir(self) -> Path:
        return self._managed_path(self.folder, "folder", allow_root=True) if self.folder else self.root_dir.resolve()

    @property
    def backup_dir(self) -> Path:
        return self._managed_path(self.dirs.get("backup", "backup"), "dirs.backup")

    @property
    def volume_dir(self) -> Path:
        return self._managed_path(self.dirs.get("volume", "volume"), "dirs.volume")

    @property
    def deploy_dir(self) -> Path:
        return self._managed_path(self.dirs.get("project", "project"), "dirs.project")

    # NOTE: _managed_path validates dirs.* / folder confinement.
    # Deploy source absolute paths (e.g. file:///abs/path, /abs/path) are
    # allowed for source resolution and must NOT be validated via _managed_path.
    def _managed_path(self, value: str, field_name: str, allow_root: bool = False) -> Path:
        root = self.root_dir.resolve()
        target = (root / value).resolve()
        if (target == root and not allow_root) or (target != root and root not in target.parents):
            raise ConfigError(
                f"'{field_name}' must be a child directory inside the config directory: {value}"
            )
        return target


_CHECKSUM_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ALLOWED_STRATEGIES = {"recreate", "pull-only"}


def _parse_deploy(raw: object) -> Any:
    if raw is None:
        return None
    if isinstance(raw, str):
        if not raw.strip():
            raise ConfigError("'deploy' must be a non-empty string.")
        data = {"default": DeploySpec(source=raw)}
        return _DeployMap(raw, data)
    if not isinstance(raw, dict):
        raise ConfigError("'deploy' must be a string or mapping of profiles.")
    if not raw:
        raise ConfigError("'deploy' must be a non-empty mapping.")
    result: dict[str, DeploySpec] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ConfigError("'deploy' keys must be non-empty strings.")
        if isinstance(value, str):
            if not value.strip():
                raise ConfigError(f"'deploy.{key}' must be a non-empty string.")
            result[str(key)] = DeploySpec(source=value)
        elif isinstance(value, dict):
            raw_source = value.get("source")
            if not isinstance(raw_source, str) or not raw_source.strip():
                raise ConfigError(f"'deploy.{key}.source' must be a string.")
            checksum = value.get("checksum")
            if checksum is not None:
                if not isinstance(checksum, str) or not _CHECKSUM_RE.fullmatch(checksum):
                    raise ConfigError(
                        f"'deploy.{key}.checksum' must match '^sha256:[0-9a-f]{{64}}$'."
                    )
            strategy = value.get("strategy")
            if strategy is not None:
                if not isinstance(strategy, str) or strategy not in _ALLOWED_STRATEGIES:
                    raise ConfigError(f"'deploy.{key}.strategy' must be 'recreate' or 'pull-only'.")
            allowed = {"source", "checksum", "strategy"}
            extra = set(value.keys()) - allowed
            if extra:
                raise ConfigError(f"'deploy.{key}' has unknown keys: {', '.join(sorted(extra))}")
            result[str(key)] = DeploySpec(
                source=raw_source, checksum=checksum, strategy=strategy
            )
        else:
            raise ConfigError(f"'deploy.{key}' must be a string or mapping.")
    default_source = result.get("default", next(iter(result.values()))).source if result else ""
    return _DeployMap(default_source, result)


def resolve_deploy(
    deploy: Any, profile: str | None
) -> DeploySpec:
    """Resolve deploy source with priority: cli --path > deploy[profile] > deploy[default].

    ``cli --path`` is expected to be handled by the caller before invoking.
    This helper implements ``deploy[profile]`` -> ``deploy["default"]`` ->
    ``ConfigError("Unknown deploy profile")``.
    """
    if deploy is None:
        raise ConfigError("Unknown deploy profile")
    if isinstance(deploy, _DeployMap):
        if profile is not None and profile in deploy:
            return deploy[profile]
        if "default" in deploy:
            return deploy["default"]
        raise ConfigError("Unknown deploy profile")
    if isinstance(deploy, str):
        return DeploySpec(source=deploy)
    if isinstance(deploy, dict):
        if profile is not None and profile in deploy:
            return deploy[profile]
        if "default" in deploy:
            return deploy["default"]
        raise ConfigError("Unknown deploy profile")
    raise ConfigError("Unknown deploy profile")


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
            raw_env_file = val.get("env_file")
            if raw_env_file is None:
                env_file: list[str] = []
            elif isinstance(raw_env_file, str):
                if not raw_env_file.strip():
                    raise ConfigError(f"'compose.{key}.env_file' must be a string or list of strings.")
                env_file = [raw_env_file]
            elif isinstance(raw_env_file, list):
                if not all(isinstance(item, str) for item in raw_env_file):
                    raise ConfigError(f"'compose.{key}.env_file' must be a string or list of strings.")
                if any(not item.strip() for item in raw_env_file):
                    raise ConfigError(f"'compose.{key}.env_file' must be a string or list of strings.")
                env_file = list(raw_env_file)
            else:
                raise ConfigError(f"'compose.{key}.env_file' must be a string or list of strings.")
            profiles[key] = Profile(
                file=str(f) if f else None,
                env={str(k): str(v) for k, v in raw_env.items()},
                secrets=_parse_secrets(val.get("secrets"), f"compose.{key}.secrets"),
                env_file=env_file,
            )
        else:
            raise ConfigError(
                f"Invalid value for 'compose.{key}': expected string or object."
            )

    deploy = _parse_deploy(root.get("deploy"))

    raw_secrets = root.get("secrets", {})
    if not isinstance(raw_secrets, dict):
        raise ConfigError("'secrets' must be a mapping.")
    secrets = _parse_secrets(raw_secrets, "secrets")

    raw_limits = root.get("limits", {})
    if not isinstance(raw_limits, dict):
        raise ConfigError("'limits' must be a mapping.")
    limits: dict[str, Any] = {}
    max_archive_mb = raw_limits.get("max_archive_mb")
    if max_archive_mb is not None:
        if not isinstance(max_archive_mb, int):
            raise ConfigError("'limits.max_archive_mb' must be an integer.")
        if max_archive_mb <= 0:
            raise ConfigError("'limits.max_archive_mb' must be greater than 0.")
        limits["max_archive_mb"] = max_archive_mb

    config = Config(
        name=name,
        root_dir=path.parent,
        source_path=path,
        folder=folder,
        dirs=dirs,
        compose_base=compose_base,
        profiles=profiles,
        secrets=secrets,
        deploy=deploy,
        limits=limits,
    )
    # Resolve all paths while loading so unsafe configuration fails before a
    # command can create, replace, or recursively delete anything.
    config.project_dir
    config.backup_dir
    config.volume_dir
    config.deploy_dir
    return config


def dump_default_config(name: str) -> str:
    sanitized = sanitize_project_name(name)
    return f"""compman:
  name: {sanitized}
  compose:
    default:
      file: docker-compose.yml
  # --- optional features ---
  # folder: my-project             # _project/ subdirectory
  # deploy: s3://bucket/app        # S3 or HTTP archive source (--path overrides)
  # dirs:
  #   backup: backup
  #   volume: volume
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
