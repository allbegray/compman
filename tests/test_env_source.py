from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError, NoRegionError

from compman._proc import _env_timeout
from compman.config import SecretRef
from compman.env_source import interpolate_secrets, resolve_secrets
from compman.errors import ConfigError


def test_resolve_secrets_multiple_keys_shared_arn():
    client = Mock()
    client.get_secret_value.return_value = {
        "SecretString": json.dumps({"dtx/db/url": "db.example.com", "password": "s3cret"})
    }
    refs = {
        "DB_URL": SecretRef(arn="arn:app", key="dtx/db/url"),
        "DB_PASSWORD": SecretRef(arn="arn:app", key="password"),
    }
    resolved = resolve_secrets(refs, client=client)
    assert resolved == {"DB_URL": "db.example.com", "DB_PASSWORD": "s3cret"}
    assert client.get_secret_value.call_count == 1


def test_resolve_secrets_distinct_arns():
    client = Mock()
    client.get_secret_value.side_effect = [
        {"SecretString": json.dumps({"url": "a.example.com"})},
        {"SecretString": json.dumps({"key": "k123"})},
    ]
    refs = {
        "DB_URL": SecretRef(arn="arn:a", key="url"),
        "API_KEY": SecretRef(arn="arn:b", key="key"),
    }
    resolved = resolve_secrets(refs, client=client)
    assert resolved == {"DB_URL": "a.example.com", "API_KEY": "k123"}
    assert client.get_secret_value.call_count == 2


def test_resolve_secrets_empty():
    assert resolve_secrets({}, client=Mock()) == {}


def test_resolve_secrets_missing_key():
    client = Mock()
    client.get_secret_value.return_value = {"SecretString": json.dumps({"a": "1"})}
    refs = {"DB_URL": SecretRef(arn="arn:app", key="nope")}
    with pytest.raises(ConfigError, match="nope"):
        resolve_secrets(refs, client=client)


def test_resolve_secrets_non_json():
    client = Mock()
    client.get_secret_value.return_value = {"SecretString": "not-json"}
    refs = {"DB_URL": SecretRef(arn="arn:app", key="url")}
    with pytest.raises(ConfigError, match="JSON"):
        resolve_secrets(refs, client=client)


def test_resolve_secrets_non_object_json():
    client = Mock()
    client.get_secret_value.return_value = {"SecretString": "[1, 2, 3]"}
    refs = {"DB_URL": SecretRef(arn="arn:app", key="url")}
    with pytest.raises(ConfigError, match="object"):
        resolve_secrets(refs, client=client)


def test_resolve_secrets_missing_secret_string():
    client = Mock()
    client.get_secret_value.return_value = {"SecretBinary": b"x"}
    refs = {"DB_URL": SecretRef(arn="arn:app", key="url")}
    with pytest.raises(ConfigError, match="SecretString"):
        resolve_secrets(refs, client=client)


def test_resolve_secrets_not_found():
    client = Mock()
    client.get_secret_value.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "nope"}}, "GetSecretValue"
    )
    refs = {"DB_URL": SecretRef(arn="arn:missing", key="url")}
    with pytest.raises(ConfigError, match="not found"):
        resolve_secrets(refs, client=client)


def test_resolve_secrets_denied():
    client = Mock()
    client.get_secret_value.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "GetSecretValue"
    )
    refs = {"DB_URL": SecretRef(arn="arn:app", key="url")}
    with pytest.raises(ConfigError, match="denied"):
        resolve_secrets(refs, client=client)


def test_resolve_secrets_other_client_error():
    client = Mock()
    client.get_secret_value.side_effect = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "GetSecretValue"
    )
    refs = {"DB_URL": SecretRef(arn="arn:app", key="url")}
    with pytest.raises(ConfigError, match="slow down"):
        resolve_secrets(refs, client=client)


def test_resolve_secrets_unexpected_error():
    client = Mock()
    client.get_secret_value.side_effect = RuntimeError("boom")
    refs = {"DB_URL": SecretRef(arn="arn:app", key="url")}
    with pytest.raises(ConfigError, match="boom"):
        resolve_secrets(refs, client=client)


@patch("compman.env_source.boto3.client")
def test_resolve_secrets_no_region(mock_client):
    mock_client.side_effect = NoRegionError()
    refs = {"DB_URL": SecretRef(arn="arn:app", key="url")}
    with pytest.raises(ConfigError, match="region"):
        resolve_secrets(refs)


@patch("compman.env_source.boto3.client")
def test_resolve_secrets_default_client_used(mock_client):
    mock_client.return_value.get_secret_value.return_value = {
        "SecretString": json.dumps({"url": "db.example.com"})
    }
    refs = {"DB_URL": SecretRef(arn="arn:app", key="url")}
    resolved = resolve_secrets(refs)
    assert resolved == {"DB_URL": "db.example.com"}
    mock_client.assert_called_once_with("secretsmanager", config=mock_client.call_args.kwargs["config"])
    assert mock_client.call_args.args == ("secretsmanager",)



@patch("compman.env_source.boto3.client")
def test_secretsmanager_client_matches_s3_timeout_config(mock_client):
    mock_client.return_value.get_secret_value.return_value = {
        "SecretString": json.dumps({"url": "db.example.com"})
    }
    refs = {"DB_URL": SecretRef(arn="arn:app", key="url")}
    resolve_secrets(refs)
    cfg = mock_client.call_args.kwargs["config"]
    assert isinstance(cfg, BotoConfig)
    assert cfg.connect_timeout == 10
    assert cfg.read_timeout == _env_timeout()
    assert cfg.retries == {"max_attempts": 3, "mode": "standard"}

def test_interpolate_secrets_full_reference():
    resolved = {"DB_URL": "db.example.com"}
    values = {"DATABASE_URL": "${secrets:DB_URL}"}
    assert interpolate_secrets(values, resolved) == {"DATABASE_URL": "db.example.com"}


def test_interpolate_secrets_partial_reference():
    resolved = {"DB_USER": "admin", "DB_PASS": "s3cret"}
    values = {"DATABASE_URL": "postgres://${secrets:DB_USER}:${secrets:DB_PASS}@host"}
    assert interpolate_secrets(values, resolved) == {
        "DATABASE_URL": "postgres://admin:s3cret@host"
    }


def test_interpolate_secrets_plain_values_unchanged():
    resolved = {"DB_URL": "db.example.com"}
    values = {"LOG_LEVEL": "debug", "HOST": "localhost:5432"}
    assert interpolate_secrets(values, resolved) == values


def test_interpolate_secrets_unknown_name():
    resolved = {"DB_URL": "db.example.com"}
    values = {"DATABASE_URL": "${secrets:NOPE}"}
    with pytest.raises(ConfigError, match="NOPE"):
        interpolate_secrets(values, resolved)


def test_interpolate_secrets_empty():
    assert interpolate_secrets({}, {"DB_URL": "x"}) == {}
