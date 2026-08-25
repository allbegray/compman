from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from compman.diagnostics import collect_doctor, collect_status


def write_simple_project(path: Path) -> None:
    (path / "compman.yml").write_text(
        "compman:\n"
        "  name: test-app\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    (path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")


def write_profile_project(path: Path) -> None:
    (path / "compman.yml").write_text(
        "compman:\n"
        "  name: test-app\n"
        "  compose:\n"
        "    dev: docker-compose.dev.yml\n"
        "    prod: docker-compose.prod.yml\n",
        encoding="utf-8",
    )
    (path / "docker-compose.dev.yml").write_text("services: {}\n", encoding="utf-8")
    (path / "docker-compose.prod.yml").write_text("services: {}\n", encoding="utf-8")


def test_collect_doctor_success(tmp_path, monkeypatch, dummy_runtime):
    write_simple_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    assert report.ok is True
    assert [check.id for check in report.checks[:3]] == ["config", "compose_files", "runtime"]
    assert report.to_dict()["schema_version"] == 1


def test_warning_does_not_fail_doctor(tmp_path, monkeypatch, dummy_runtime):
    write_simple_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    assert report.ok is True
    assert next(check for check in report.checks if check.id == "aws").severity == "warning"


def test_secrets_check_skipped_without_secrets(tmp_path, monkeypatch, dummy_runtime):
    write_simple_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    assert all(check.id != "secrets" for check in report.checks)


def test_secrets_check_reports_missing_credentials(tmp_path, monkeypatch, dummy_runtime):
    (tmp_path / "compman.yml").write_text(
        "compman:\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n"
        "  secrets:\n"
        "    DB_URL:\n"
        "      arn: arn:aws:secretsmanager:ap-northeast-2:123:secret:app\n"
        "      key: url\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    secrets = next(check for check in report.checks if check.id == "secrets")
    assert secrets.severity == "warning"
    assert secrets.ok is False


def test_secrets_check_ok_with_credentials_and_region(tmp_path, monkeypatch, dummy_runtime):
    (tmp_path / "compman.yml").write_text(
        "compman:\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n"
        "  secrets:\n"
        "    DB_URL:\n"
        "      arn: arn:aws:secretsmanager:ap-northeast-2:123:secret:app\n"
        "      key: url\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    secrets = next(check for check in report.checks if check.id == "secrets")
    assert secrets.ok is True


def test_backup_upload_check_skipped_when_unset(tmp_path, monkeypatch, dummy_runtime):
    write_simple_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    assert all(check.id != "backup_upload" for check in report.checks)


def _write_backup_upload_project(path: Path) -> None:
    (path / "compman.yml").write_text(
        "compman:\n"
        "  name: test-app\n"
        "  backup:\n"
        "    upload: s3://bucket/backups\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    (path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")


def test_backup_upload_check_ok_with_credentials_and_region(tmp_path, monkeypatch, dummy_runtime):
    _write_backup_upload_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    check = next(item for item in report.checks if item.id == "backup_upload")
    assert check.severity == "warning"
    assert check.ok is True
    assert "s3://bucket/backups" in check.message


def test_backup_upload_check_accepts_aws_region_fallback(tmp_path, monkeypatch, dummy_runtime):
    _write_backup_upload_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setenv("AWS_REGION", "ap-northeast-2")
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    check = next(item for item in report.checks if item.id == "backup_upload")
    assert check.ok is True


def test_backup_upload_check_reports_missing_credentials(tmp_path, monkeypatch, dummy_runtime):
    _write_backup_upload_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    check = next(item for item in report.checks if item.id == "backup_upload")
    assert check.ok is False


def test_backup_upload_check_reports_missing_region(tmp_path, monkeypatch, dummy_runtime):
    _write_backup_upload_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    check = next(item for item in report.checks if item.id == "backup_upload")
    assert check.ok is False
    json_checks = report.to_dict()["checks"]
    assert any(entry["id"] == "backup_upload" for entry in json_checks)


def test_doctor_warns_when_deploy_lacks_checksum(tmp_path, monkeypatch, dummy_runtime):
    (tmp_path / "compman.yml").write_text(
        "compman:\n"
        "  name: test-app\n"
        "  deploy: s3://bucket/app.tar.gz\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    check = next(item for item in report.checks if item.id == "deploy_checksum")
    assert check.severity == "warning"
    assert check.ok is False
    json_checks = report.to_dict()["checks"]
    assert any(entry["id"] == "deploy_checksum" for entry in json_checks)


def test_doctor_no_checksum_warning_when_pinned(tmp_path, monkeypatch, dummy_runtime):
    (tmp_path / "compman.yml").write_text(
        "compman:\n"
        "  name: test-app\n"
        "  deploy:\n"
        "    url: s3://bucket/app.tar.gz\n"
        f"    sha256: {'a' * 64}\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    assert all(check.id != "deploy_checksum" for check in report.checks)


def test_doctor_no_checksum_warning_without_deploy(tmp_path, monkeypatch, dummy_runtime):
    write_simple_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    assert all(check.id != "deploy_checksum" for check in report.checks)


def _write_auth_project(path) -> None:
    (path / "compman.yml").write_text(
        "compman:\n"
        "  name: test-app\n"
        "  deploy:\n"
        "    url: https://example.test/app.zip\n"
        "    auth:\n"
        "      header: Authorization\n"
        "      value_env: DEPLOY_TOKEN\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    (path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")





@pytest.mark.parametrize("config_contents", [None, "invalid: : ["])
def test_invalid_or_missing_config_is_a_failed_required_check(tmp_path, monkeypatch, dummy_runtime, config_contents):
    if config_contents is not None:
        (tmp_path / "compman.yml").write_text(config_contents, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    config = next(check for check in report.checks if check.id == "config")
    assert config.severity == "required"
    assert config.ok is False
    assert report.ok is False


def test_missing_compose_file_is_a_failed_required_check(tmp_path, monkeypatch, dummy_runtime):
    (tmp_path / "compman.yml").write_text(
        "compman:\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    compose = next(check for check in report.checks if check.id == "compose_files")
    assert compose.severity == "required"
    assert compose.ok is False
    assert report.ok is False


def test_runtime_detection_exception_is_a_failed_required_check(tmp_path, monkeypatch):
    write_simple_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: (_ for _ in ()).throw(RuntimeError("missing")))

    report = collect_doctor(None)

    runtime = next(check for check in report.checks if check.id == "runtime")
    assert runtime.severity == "required"
    assert runtime.ok is False
    assert report.ok is False


def test_nonzero_runtime_info_is_a_failed_required_check(tmp_path, monkeypatch, dummy_runtime):
    write_simple_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)
    monkeypatch.setattr(dummy_runtime, "run_cli", lambda *args, **kwargs: SimpleNamespace(returncode=1))

    report = collect_doctor(None)

    connection = next(check for check in report.checks if check.id == "runtime_connection")
    assert connection.severity == "required"
    assert connection.ok is False
    assert report.ok is False


def test_unwritable_managed_directory_parent_is_a_failed_required_check(tmp_path, monkeypatch, dummy_runtime):
    write_simple_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)
    monkeypatch.setattr("compman.diagnostics.os.access", lambda *args: False)

    report = collect_doctor(None)

    managed_dirs = next(check for check in report.checks if check.id == "managed_dirs")
    assert managed_dirs.severity == "required"
    assert managed_dirs.ok is False
    assert report.ok is False


def test_nested_missing_managed_directories_use_nearest_existing_ancestor(
    tmp_path, monkeypatch, dummy_runtime
):
    write_simple_project(tmp_path)
    existing = tmp_path / "writable"
    existing.mkdir()
    config_path = tmp_path / "compman.yml"
    config_path.write_text(
        "compman:\n"
        "  name: test-app\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n"
        "  dirs:\n"
        "    backup: writable/missing/backup\n"
        "    volume: writable/missing/volume\n"
        "    project: writable/missing/project\n",
        encoding="utf-8",
    )
    accessed = []

    def record_access(path, mode):
        accessed.append((Path(path), mode))
        return True

    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)
    monkeypatch.setattr("compman.diagnostics.os.access", record_access)

    report = collect_doctor(str(config_path))

    managed_dirs = next(check for check in report.checks if check.id == "managed_dirs")
    assert managed_dirs.ok is True
    assert accessed == [(existing, os.W_OK | os.X_OK)] * 3
    assert not (existing / "missing").exists()


def test_existing_managed_directory_checks_the_target_itself(tmp_path, monkeypatch, dummy_runtime):
    write_simple_project(tmp_path)
    backup = tmp_path / "backup"
    backup.mkdir()
    accessed = []

    def deny_backup(path, mode):
        candidate = Path(path)
        accessed.append((candidate, mode))
        return candidate != backup

    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)
    monkeypatch.setattr("compman.diagnostics.os.access", deny_backup)

    report = collect_doctor(str(tmp_path / "compman.yml"))

    managed_dirs = next(check for check in report.checks if check.id == "managed_dirs")
    assert managed_dirs.ok is False
    assert str(backup) in managed_dirs.message
    assert (backup, os.W_OK | os.X_OK) in accessed


def test_runtime_info_exception_is_a_failed_required_check(tmp_path, monkeypatch, dummy_runtime):
    write_simple_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)
    monkeypatch.setattr(dummy_runtime, "run_cli", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))

    report = collect_doctor(None)

    connection = next(check for check in report.checks if check.id == "runtime_connection")
    assert connection.ok is False
    assert report.ok is False


def test_managed_directory_access_exception_is_a_failed_required_check(tmp_path, monkeypatch, dummy_runtime):
    write_simple_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)
    monkeypatch.setattr("compman.diagnostics.os.access", lambda *args: (_ for _ in ()).throw(OSError("denied")))

    report = collect_doctor(None)

    managed_dirs = next(check for check in report.checks if check.id == "managed_dirs")
    assert managed_dirs.ok is False
    assert report.ok is False


@pytest.mark.parametrize(
    "stage",
    ["config", "compose_files", "runtime", "runtime_connection", "managed_dirs"],
)
def test_collect_doctor_propagates_programming_errors(stage, tmp_path, monkeypatch, dummy_runtime):
    write_simple_project(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    def programming_error(*args, **kwargs):
        raise AssertionError(stage)

    if stage == "config":
        monkeypatch.setattr("compman.diagnostics.load_config", programming_error)
    elif stage == "compose_files":
        monkeypatch.setattr("compman.diagnostics.resolve_compose_context", programming_error)
    elif stage == "runtime":
        monkeypatch.setattr("compman.diagnostics.detect_runtime", programming_error)
    elif stage == "runtime_connection":
        monkeypatch.setattr(dummy_runtime, "run_cli", programming_error)
    else:
        monkeypatch.setattr("compman.diagnostics.os.access", programming_error)

    with pytest.raises(AssertionError, match=stage):
        collect_doctor(str(tmp_path / "compman.yml"))


def test_aws_credentials_are_reported_as_available(tmp_path, monkeypatch, dummy_runtime):
    write_simple_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")

    report = collect_doctor(None)

    aws = next(check for check in report.checks if check.id == "aws")
    assert aws.severity == "warning"
    assert aws.ok is True


def test_collect_status_reports_profile_and_services(tmp_path, dummy_runtime, monkeypatch):
    write_profile_project(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)
    dummy_runtime.service_status = lambda *args: [
        {
            "service": "web",
            "container": "app-web-1",
            "state": "running",
            "status": "Up",
            "health": "healthy",
        }
    ]

    report = collect_status(str(tmp_path / "compman.yml"), "dev")

    assert report.ok is True
    assert report.profile == "dev"
    assert report.services[0].health == "healthy"
    assert report.to_dict()["services"] == [
        {
            "service": "web",
            "container": "app-web-1",
            "state": "running",
            "status": "Up",
            "health": "healthy",
        }
    ]


def test_collect_status_uses_first_profile_by_default(tmp_path, dummy_runtime, monkeypatch):
    write_profile_project(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)
    dummy_runtime.service_status = lambda *args: []

    report = collect_status(str(tmp_path / "compman.yml"))

    assert report.ok is True
    assert report.profile == "dev"
    assert report.compose_files == (str(tmp_path / "docker-compose.dev.yml"),)


def test_collect_status_rejects_unknown_profile(tmp_path, dummy_runtime, monkeypatch):
    write_simple_project(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_status(str(tmp_path / "compman.yml"), "dev")

    assert report.ok is False
    assert report.error is not None
    assert "Unknown profile" in report.error


def test_collect_status_reports_invalid_config(tmp_path):
    report = collect_status(str(tmp_path / "missing.yml"))

    assert report.ok is False
    assert report.runtime is None
    assert report.error is not None


def test_collect_status_reports_runtime_detection_failure(tmp_path, monkeypatch):
    write_simple_project(tmp_path)
    monkeypatch.setattr(
        "compman.diagnostics.detect_runtime", lambda: (_ for _ in ()).throw(RuntimeError("missing runtime"))
    )

    report = collect_status(str(tmp_path / "compman.yml"))

    assert report.ok is False
    assert report.runtime is None
    assert report.error == "missing runtime"


def test_collect_status_reports_absent_stack(tmp_path, dummy_runtime, monkeypatch):
    write_simple_project(tmp_path)
    dummy_runtime.stack_exists = lambda *args: False
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_status(str(tmp_path / "compman.yml"))

    assert report.ok is False
    assert report.services == ()
    assert report.error == "Stack 'test-app' is not running."


def test_collect_status_reports_failed_service_query(tmp_path, dummy_runtime, monkeypatch):
    write_simple_project(tmp_path)
    dummy_runtime.service_status = lambda *args: (_ for _ in ()).throw(RuntimeError("offline"))
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_status(str(tmp_path / "compman.yml"))

    assert report.ok is False
    assert report.error == "offline"


@pytest.mark.parametrize("stage", ["config", "compose_files", "runtime", "stack", "services"])
def test_collect_status_propagates_programming_errors(stage, tmp_path, dummy_runtime, monkeypatch):
    write_simple_project(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    def programming_error(*args, **kwargs):
        raise TypeError(stage)

    if stage == "config":
        monkeypatch.setattr("compman.diagnostics.load_config", programming_error)
    elif stage == "compose_files":
        monkeypatch.setattr("compman.diagnostics.resolve_compose_context", programming_error)
    elif stage == "runtime":
        monkeypatch.setattr("compman.diagnostics.detect_runtime", programming_error)
    elif stage == "stack":
        monkeypatch.setattr(dummy_runtime, "stack_exists", programming_error)
    else:
        monkeypatch.setattr(dummy_runtime, "service_status", programming_error)

    with pytest.raises(TypeError, match=stage):
        collect_status(str(tmp_path / "compman.yml"))


def test_collect_status_allows_empty_service_list(tmp_path, dummy_runtime, monkeypatch):
    write_simple_project(tmp_path)
    dummy_runtime.service_status = lambda *args: []
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_status(str(tmp_path / "compman.yml"))

    assert report.ok is True
    assert report.services == ()


def test_status_report_json_keys_are_stable(tmp_path, dummy_runtime, monkeypatch):
    write_simple_project(tmp_path)
    dummy_runtime.service_status = lambda *args: []
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_status(str(tmp_path / "compman.yml"))

    assert list(report.to_dict()) == [
        "schema_version",
        "ok",
        "runtime",
        "stack",
        "profile",
        "compose_files",
        "services",
        "error",
        "error_code",
        "generated_at",
        "config_path",
    ]
    assert report.to_dict()["schema_version"] == 1
    assert report.to_dict()["error_code"] is None
    assert report.to_dict()["config_path"] == str((tmp_path / "compman.yml").resolve())
    assert datetime.fromisoformat(report.to_dict()["generated_at"]).tzinfo is not None


def test_doctor_check_result_json_keys_include_remediation_and_detail(tmp_path, monkeypatch, dummy_runtime):
    write_simple_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    assert list(report.checks[0].to_dict()) == [
        "id",
        "severity",
        "ok",
        "message",
        "remediation",
        "detail",
    ]
    assert report.checks[0].remediation is None
    assert report.checks[0].detail is None
    assert report.to_dict()["schema_version"] == 1


@pytest.mark.parametrize(
    ("stage", "expected_error_code"),
    [
        ("config", "config-error"),
        ("compose_files", "compose-error"),
        ("runtime", "runtime-error"),
        ("stack", "stack-missing"),
        ("services", "runtime-error"),
    ],
)
def test_status_error_code_maps_each_failure_site(
    stage, expected_error_code, tmp_path, dummy_runtime, monkeypatch
):
    write_simple_project(tmp_path)

    if stage == "config":
        config_path = str(tmp_path / "missing.yml")
    elif stage == "compose_files":
        config_path = str(tmp_path / "compman.yml")
        (tmp_path / "compman.yml").write_text(
            "compman:\n  compose:\n    default:\n      file: missing-compose.yml\n",
            encoding="utf-8",
        )
    else:
        config_path = str(tmp_path / "compman.yml")
        if stage == "runtime":
            monkeypatch.setattr(
                "compman.diagnostics.detect_runtime",
                lambda: (_ for _ in ()).throw(RuntimeError("no runtime")),
            )
        else:
            monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)
            if stage == "stack":
                dummy_runtime.stack_exists = lambda *args: False
            else:
                dummy_runtime.service_status = lambda *args: (_ for _ in ()).throw(RuntimeError("boom"))

    report = collect_status(config_path)

    assert report.ok is False
    assert report.error_code == expected_error_code
    assert report.config_path == str(Path(config_path).resolve())
    assert datetime.fromisoformat(report.generated_at).tzinfo is not None
