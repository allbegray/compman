from __future__ import annotations

import json
import re
from typing import Any, Mapping

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    NoRegionError,
)

from compman._proc import _env_timeout
from compman.config import SecretRef
from compman.errors import ConfigError

_SECRET_MARKER = re.compile(r"\$\{secrets:([^}]+)\}")


def resolve_secrets(
    refs: Mapping[str, SecretRef],
    client: Any | None = None,
) -> dict[str, str]:
    """Resolve AWS Secrets Manager references to environment variables.

    Each unique ARN is fetched at most once; per-command cache lives in the
    caller. Values are taken from the secret's SecretString, parsed as JSON,
    then each referenced key is extracted.
    """
    if not refs:
        return {}

    secrets_client = client if client is not None else _client()
    arn_json: dict[str, dict] = {}
    resolved: dict[str, str] = {}
    for env_name, ref in refs.items():
        if ref.arn not in arn_json:
            arn_json[ref.arn] = _fetch_secret(secrets_client, ref.arn)
        try:
            resolved[env_name] = arn_json[ref.arn][ref.key]
        except KeyError:
            raise ConfigError(
                f"Secret {ref.arn} has no key '{ref.key}'."
            ) from None
    return resolved


def interpolate_secrets(
    values: Mapping[str, str],
    resolved: Mapping[str, str],
) -> dict[str, str]:
    """Replace ${secrets:NAME} markers in env values with resolved secret values.

    Partially-interpolated strings are supported, e.g.
    ``postgres://${secrets:DB_USER}:${secrets:DB_PASS}@host``. A referenced
    name that is not present in ``resolved`` raises ConfigError.
    """
    result: dict[str, str] = {}
    for name, value in values.items():
        if "${secrets:" not in value:
            result[name] = value
            continue

        def _replace(match: re.Match[str]) -> str:
            secret_name = match.group(1)
            try:
                return resolved[secret_name]
            except KeyError:
                raise ConfigError(
                    f"env '{name}' references '{secret_name}' which is not "
                    "declared under 'secrets'."
                ) from None

        result[name] = _SECRET_MARKER.sub(_replace, value)
    return result


def _client() -> Any:
    try:
        return boto3.client(
            "secretsmanager",
            config=Config(
                connect_timeout=10,
                read_timeout=_env_timeout(),
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
    except NoRegionError as exc:
        raise ConfigError(
            "AWS region is not configured. Set AWS_DEFAULT_REGION "
            "or configure a region in ~/.aws/config."
        ) from exc


def _fetch_secret(client: Any, arn: str) -> dict:
    try:
        response = client.get_secret_value(SecretId=arn)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ResourceNotFoundException":
            raise ConfigError(f"Secret not found: {arn}") from exc
        if code == "AccessDeniedException":
            raise ConfigError(
                f"Access denied reading secret {arn}. Check the IAM policy "
                "grants secretsmanager:GetSecretValue."
            ) from exc
        raise ConfigError(f"Failed to read secret {arn}: {exc}") from exc
    except Exception as exc:
        raise ConfigError(f"Failed to read secret {arn}: {exc}") from exc

    secret_string = response.get("SecretString")
    if not isinstance(secret_string, str):
        raise ConfigError(
            f"Secret {arn} has no SecretString. Only string secrets "
            "with a JSON body are supported."
        )
    try:
        parsed = json.loads(secret_string)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"Secret {arn} is not valid JSON. Store keys as a JSON "
            "SecretString and reference them with 'key'."
        ) from exc
    if not isinstance(parsed, dict):
        raise ConfigError(
            f"Secret {arn} JSON body is not an object. Use a mapping of "
            "keys to reference individual values."
        )
    return parsed
