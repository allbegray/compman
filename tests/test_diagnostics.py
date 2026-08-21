from __future__ import annotations

import os
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
    ]


def test_env_file_missing_is_warning(tmp_path, monkeypatch, dummy_runtime):
    (tmp_path / "compman.yml").write_text(
        "compman:\n"
        "  name: test-app\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n"
        "    prod:\n"
        "      file: docker-compose.yml\n"
        "      env_file: missing.env\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    env_checks = [c for c in report.checks if c.id == "env_file"]
    assert len(env_checks) == 1
    assert env_checks[0].severity == "warning"
    assert env_checks[0].ok is False
    assert "missing.env" in env_checks[0].message
    assert report.ok is True


def test_env_file_exists_no_warning(tmp_path, monkeypatch, dummy_runtime):
    (tmp_path / "compman.yml").write_text(
        "compman:\n"
        "  name: test-app\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n"
        "      env_file: existing.env\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "existing.env").write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    assert all(c.id != "env_file" for c in report.checks)
    assert report.ok is True


def test_env_file_missing_multiple_profiles(tmp_path, monkeypatch, dummy_runtime):
    (tmp_path / "compman.yml").write_text(
        "compman:\n"
        "  name: test-app\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n"
        "    dev:\n"
        "      file: docker-compose.yml\n"
        "      env_file: missing.env\n"
        "    prod:\n"
        "      file: docker-compose.yml\n"
        "      env_file: [existing.env, also-missing.env]\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "existing.env").write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    report = collect_doctor(None)

    env_checks = [c for c in report.checks if c.id == "env_file"]
    assert len(env_checks) == 2
    paths = [c.message for c in env_checks]
    assert any("missing.env" in m for m in paths)
    assert any("also-missing.env" in m for m in paths)
    assert report.ok is True


def test_env_file_missing_fallback_when_translation_missing(tmp_path, monkeypatch, dummy_runtime):
    from unittest.mock import patch

    from compman.diagnostics import collect_doctor

    (tmp_path / "compman.yml").write_text(
        "compman:\n"
        "  name: test-app\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n"
        "      env_file: missing.env\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)

    with patch("compman.diagnostics.t", return_value="check.env_file_missing"):
        report = collect_doctor(None)

    env_checks = [c for c in report.checks if c.id == "env_file"]
    assert len(env_checks) == 1
    assert "missing.env" in env_checks[0].message
    assert env_checks[0].message == "Env file not found: missing.env"


def test_doctor_warns_missing_checksum(tmp_path, monkeypatch, dummy_runtime):
    (tmp_path / "compman.yml").write_text(
        "compman:\n"
        "  name: test-app\n"
        "  deploy:\n"
        "    default: s3://bucket/app.tar.gz\n"
        "    dev:\n"
        "      source: s3://bucket/dev.tar.gz\n"
        "      checksum: sha256:" + "a" * 64 + "\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)
    report = collect_doctor(None)
    deploy_checks = [c for c in report.checks if c.id == "deploy_checksum"]
    assert len(deploy_checks) == 1
    assert deploy_checks[0].severity == "warning"
    assert deploy_checks[0].ok is False
    assert report.ok is True


def test_doctor_no_warning_when_checksum_present(tmp_path, monkeypatch, dummy_runtime):
    (tmp_path / "compman.yml").write_text(
        "compman:\n"
        "  name: test-app\n"
        "  deploy:\n"
        "    default:\n"
        "      source: s3://bucket/app.tar.gz\n"
        "      checksum: sha256:" + "b" * 64 + "\n"
        "  compose:\n"
        "    default:\n"
        "      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)
    report = collect_doctor(None)
    assert all(c.id != "deploy_checksum" for c in report.checks)
    assert report.ok is True


def test_doctor_no_deploy_no_checksum_check(tmp_path, monkeypatch, dummy_runtime):
    (tmp_path / "compman.yml").write_text(
        "compman:\n  name: test-app\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)
    report = collect_doctor(None)
    assert all(c.id != "deploy_checksum" for c in report.checks)


def test_collect_deploy_checksum_branches(tmp_path):
    from unittest.mock import patch

    from compman.config import Config
    from compman.diagnostics import _collect_deploy_checksum

    cfg_none = Config(name="app", deploy=None)
    checks: list = []
    _collect_deploy_checksum(cfg_none, checks)
    assert not checks

    class BadDeploy:
        def values(self):
            raise RuntimeError("boom")

    cfg_bad = Config(name="app", deploy=BadDeploy())  # type: ignore[arg-type]
    checks = []
    _collect_deploy_checksum(cfg_bad, checks)
    assert not checks

    class ExplodingSpec:
        @property
        def checksum(self):
            raise RuntimeError("exploding")

    class GoodDeploy:
        def values(self):
            return [ExplodingSpec(), ExplodingSpec()]  # type: ignore[return-value]

    cfg_exploding = Config(name="app", deploy=GoodDeploy())  # type: ignore[arg-type]
    checks = []
    _collect_deploy_checksum(cfg_exploding, checks)
    assert len(checks) == 1
    assert checks[0].id == "deploy_checksum"

    cfg_ok = Config(name="app", deploy={"default": __import__("compman.config", fromlist=["DeploySpec"]).DeploySpec(source="s3://b/a.tar.gz", checksum="sha256:" + "a" * 64)})
    checks = []
    _collect_deploy_checksum(cfg_ok, checks)
    assert not checks

    with patch("compman.diagnostics.t", return_value="check.deploy_checksum"):
        checks = []
        _collect_deploy_checksum(cfg_exploding, checks)
        assert checks[0].message == "2 deploy profile(s) without checksum"


@pytest.mark.parametrize("has_versions", [True, False])
def test_collect_versions_branches(tmp_path, monkeypatch, dummy_runtime, has_versions):
    (tmp_path / "compman.yml").write_text(
        "compman:\n  name: test-app\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    if has_versions:
        vdir = tmp_path / "backup" / ".versions"
        vdir.mkdir(parents=True)
        (vdir / "20200101_000000").mkdir()
        (vdir / "20200102_000000").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("compman.diagnostics.detect_runtime", lambda: dummy_runtime)
    report = collect_doctor(None)
    v_checks = [c for c in report.checks if c.id == "versions"]
    assert len(v_checks) == 1
    if has_versions:
        assert "2 versions" in v_checks[0].message
    else:
        assert v_checks[0].message == "no versions"


def test_collect_versions_oserror_branch(tmp_path):
    from pathlib import Path as _Path
    from unittest.mock import patch

    from compman.config import Config
    from compman.diagnostics import _collect_versions

    cfg = Config(name="app", root_dir=tmp_path)
    with patch.object(_Path, "is_dir", side_effect=OSError("denied")):
        checks: list = []
        _collect_versions(cfg, checks)
        assert len(checks) == 1
        assert checks[0].id == "versions"
        assert checks[0].message == "no versions"
