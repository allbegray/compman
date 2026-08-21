from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
from unittest.mock import MagicMock, patch

from typer._click.utils import strip_ansi
from typer.testing import CliRunner

from compman.cli import _run_upgrade_command, app
from compman.config import ConfigError
from compman.diagnostics import CheckResult, DoctorReport, ServiceStatus, StatusReport
from compman.errors import CommandError
from compman.i18n import set_lang, t


def test_importing_cli_does_not_load_command_only_modules():
    command_only = {
        "boto3",
        "botocore",
        "yaml",
        "compman.config",
        "compman.deploy",
        "compman.diagnostics",
        "compman.docker",
        "compman.ops.image",
        "compman.ops.container",
        "compman.ops.service",
        "compman.ops.stack",
        "compman.ops.volume",
    }
    script = (
        "import sys; import compman.cli; "
        f"print(sorted({command_only!r}.intersection(sys.modules)))"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )

    assert result.stdout.strip() == "[]"


def test_cli_version(runner: CliRunner):
    res = runner.invoke(app, ["version"])
    assert res.exit_code == 0
    assert "compman" in res.output

    short = runner.invoke(app, ["-v"])
    assert short.exit_code == 0
    assert "compman" in short.output


def test_cli_short_help_alias(runner: CliRunner):
    root_help = runner.invoke(app, ["-h"], color=True)
    assert root_help.exit_code == 0
    assert "Usage: compman" in strip_ansi(root_help.output)

    stack_help = runner.invoke(app, ["stack", "-h"], color=True)
    assert stack_help.exit_code == 0
    assert "Usage: compman stack" in strip_ansi(stack_help.output)


def test_cli_lang(runner: CliRunner):
    res = runner.invoke(app, ["lang"])
    assert res.exit_code == 0
    assert "Active Language" in res.output

    res_ko = runner.invoke(app, ["lang", "ko"])
    assert res_ko.exit_code == 0
    assert "ko" in res_ko.output

    res_inv = runner.invoke(app, ["lang", "invalid_lang"])
    assert res_inv.exit_code != 0


def test_cli_global_lang_flag(runner: CliRunner):
    res = runner.invoke(app, ["-l", "ko", "version"])
    assert res.exit_code == 0


def test_cli_init(runner: CliRunner, temp_dir: pathlib.Path):
    res_sk = runner.invoke(app, ["init", "--scaffold"])
    assert res_sk.exit_code == 0
    assert (temp_dir / "compman.yml").exists()

    res_sk_exists = runner.invoke(app, ["init", "--scaffold"])
    assert res_sk_exists.exit_code == 0

    removed_skeleton = runner.invoke(app, ["init", "--skeleton"])
    assert removed_skeleton.exit_code != 0
    assert "No such option" in strip_ansi(removed_skeleton.output)

    init_help = runner.invoke(app, ["init", "--help"], color=True)
    plain_help = strip_ansi(init_help.output)
    assert "--scaffold" in plain_help
    assert "--skeleton" not in plain_help

    res_sd = runner.invoke(app, ["init", "--seed", "-o", "my_seed", "--force"])
    assert res_sd.exit_code == 0
    assert (temp_dir / "my_seed").exists()

    with patch("compman.cli._deploy"):
        res_s3 = runner.invoke(app, ["init", "--s3", "s3://b/k"])
        assert res_s3.exit_code == 0


def test_cli_init_interactive(runner: CliRunner, temp_dir: pathlib.Path):
    with patch("compman.ops.common.prompt_select", return_value=0):
        res = runner.invoke(app, ["init", "--force"])
        assert res.exit_code == 0


def test_cli_clear(runner: CliRunner, dummy_runtime):
    with patch("compman.cli.detect_runtime", return_value=dummy_runtime):
        res = runner.invoke(app, ["clear", "--yes"])
        assert res.exit_code == 0
        assert dummy_runtime.commands_run[-1] == ["image", "prune", "-af"]


def test_cli_clear_requires_confirmation(runner: CliRunner, dummy_runtime):
    with patch("compman.cli.detect_runtime", return_value=dummy_runtime):
        res = runner.invoke(app, ["clear"], input="n\n")
        assert res.exit_code != 0
        assert dummy_runtime.commands_run == []

        res_yes = runner.invoke(app, ["clear"], input="y\n")
        assert res_yes.exit_code == 0
        assert dummy_runtime.commands_run[-1] == ["image", "prune", "-af"]


def test_cli_deploy(runner: CliRunner, dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text("compman:\n  name: app\n  deploy: s3://b/k.tar.gz\n", encoding="utf-8")
    with patch("compman.cli.detect_runtime", return_value=dummy_runtime), patch("compman.cli._deploy"):
        res = runner.invoke(app, ["deploy", "--path", "s3://b/k.tar.gz"])
        assert res.exit_code == 0


def test_cli_update(runner: CliRunner, dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text("compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n", encoding="utf-8")
    (temp_dir / "docker-compose.yml").touch()
    with patch("compman.cli.detect_runtime", return_value=dummy_runtime):
        res = runner.invoke(app, ["update"])
        assert res.exit_code == 0


def test_cli_project_ps_and_stats(runner: CliRunner, dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text(
        "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    (temp_dir / "docker-compose.yml").touch()
    dummy_runtime.compose_stdout = "cid123\n"

    with patch("compman.cli.detect_runtime", return_value=dummy_runtime):
        ps_result = runner.invoke(app, ["ps"])
        assert ps_result.exit_code == 0
        assert dummy_runtime.compose_runs[-1]["args"] == ["ps"]

        ps_all_result = runner.invoke(app, ["ps", "--all"])
        assert ps_all_result.exit_code == 0
        assert dummy_runtime.compose_runs[-1]["args"] == ["ps", "--all"]

        stats_result = runner.invoke(app, ["stats"])
        assert stats_result.exit_code == 0
        assert dummy_runtime.commands_run[-1] == ["stats", "--no-stream", "cid123"]

        follow_result = runner.invoke(app, ["stats", "--follow"])
        assert follow_result.exit_code == 0
        assert dummy_runtime.commands_run[-1] == ["stats", "cid123"]

        short_follow_result = runner.invoke(app, ["stats", "-f"])
        assert short_follow_result.exit_code == 0
        assert dummy_runtime.commands_run[-1] == ["stats", "cid123"]


def test_ps_stats_help_and_korean_translations(runner: CliRunner):
    set_lang("en")
    ps_help = strip_ansi(runner.invoke(app, ["ps", "--help"], color=True).output)
    stats_help = strip_ansi(runner.invoke(app, ["stats", "--help"], color=True).output)

    assert "List project containers" in ps_help
    assert "--all" in ps_help
    assert "Display project container resource usage" in stats_help
    assert "--follow" in stats_help
    assert "-f" in stats_help
    assert t("opt.follow", lang="en") == "Stream output continuously."
    assert "--no-stream" not in stats_help
    assert t("cmd.ps", lang="ko") == "프로젝트 컨테이너 목록 표시"
    assert t("cmd.stats", lang="ko") == "프로젝트 컨테이너 리소스 사용량 표시"


def test_cli_stack_commands(runner: CliRunner, dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text("compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n", encoding="utf-8")
    (temp_dir / "docker-compose.yml").touch()
    with patch("compman.cli.detect_runtime", return_value=dummy_runtime):
        res_up = runner.invoke(app, ["stack", "up"])
        assert res_up.exit_code == 0

        res_down = runner.invoke(app, ["stack", "down", "--yes"])
        assert res_down.exit_code == 0

        res_update = runner.invoke(app, ["stack", "update"])
        assert res_update.exit_code == 0


def test_cli_service_commands(runner: CliRunner, dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text("compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n", encoding="utf-8")
    (temp_dir / "docker-compose.yml").touch()
    with patch("compman.cli.detect_runtime", return_value=dummy_runtime):
        for cmd in ["start", "stop", "restart"]:
            res = runner.invoke(app, ["service", cmd, "web"])
            assert res.exit_code == 0

        res_st = runner.invoke(app, ["service", "status"])
        assert res_st.exit_code == 0

        dummy_runtime.compose_stdout = "web-1\n"
        res_log = runner.invoke(app, ["service", "log", "web"])
        assert res_log.exit_code == 0

        res_conn = runner.invoke(app, ["service", "connect", "web"])
        assert res_conn.exit_code == 0


def test_cli_volume_commands(runner: CliRunner, dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text("compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n", encoding="utf-8")
    (temp_dir / "docker-compose.yml").touch()
    with patch("compman.cli.detect_runtime", return_value=dummy_runtime), patch("compman.ops.volume.backup") as backup, patch("compman.ops.volume.restore"), patch("compman.ops.volume.pull"), patch("compman.ops.volume.push"):
        res_bak = runner.invoke(app, ["volume", "backup", "--no-stop", "-z", "2"])
        assert res_bak.exit_code == 0
        assert backup.call_args.kwargs["compression_level"] == 2

        res_res = runner.invoke(app, ["volume", "restore", "20260731_1200", "--no-stop"])
        assert res_res.exit_code == 0

        res_pull = runner.invoke(app, ["volume", "pull"])
        assert res_pull.exit_code == 0

        res_push = runner.invoke(app, ["volume", "push"])
        assert res_push.exit_code == 0

        invalid = runner.invoke(app, ["volume", "backup", "--level", "10"])
        assert invalid.exit_code == 2


def test_cli_image_commands(runner: CliRunner, dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text("compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n", encoding="utf-8")
    (temp_dir / "docker-compose.yml").touch()
    with patch("compman.cli.detect_runtime", return_value=dummy_runtime), patch("compman.ops.image.backup") as backup, patch("compman.ops.image.restore"):
        res_bak = runner.invoke(app, ["image", "backup", "--source-image", "--level", "4"])
        assert res_bak.exit_code == 0
        assert backup.call_args.kwargs["compression_level"] == 4

        res_res = runner.invoke(app, ["image", "restore", "20260731_1200"])
        assert res_res.exit_code == 0


def test_cli_load_error(runner: CliRunner, temp_dir: pathlib.Path):
    res = runner.invoke(app, ["stack", "up"])
    assert res.exit_code != 0


def test_cli_runtime_error_is_formatted(runner: CliRunner, temp_dir: pathlib.Path):
    set_lang("en")
    (temp_dir / "compman.yml").write_text(
        "compman:\n  compose:\n    dev: missing.yml\n", encoding="utf-8"
    )
    with patch("compman.cli.detect_runtime", return_value=MagicMock()):
        res = runner.invoke(app, ["stack", "up", "dev"])
    assert res.exit_code == 1
    assert "Error:" in res.output
    assert "Compose file not found" in res.output


def test_cli_unknown_command_shows_root_help(runner: CliRunner):
    set_lang("en")
    res = runner.invoke(app, ["unknown"])
    output = re.sub(r"\x1b\[[0-9;]*m", "", res.output)
    assert res.exit_code == 2
    assert "Usage: compman" in output
    assert "Commands" in output
    assert "Error: Unknown command 'unknown'." in output
    assert output.count("Usage: compman") == 1


def test_cli_unknown_subcommand_shows_group_help(runner: CliRunner):
    set_lang("en")
    res = runner.invoke(app, ["service", "down"])
    output = re.sub(r"\x1b\[[0-9;]*m", "", res.output)
    assert res.exit_code == 2
    assert "Usage: compman service" in output
    assert "status" in output
    assert "Error: Unknown command 'down'." in output
    assert output.count("Usage: compman service") == 1

    set_lang("ko")
    res_ko = runner.invoke(app, ["service", "down"])
    assert res_ko.exit_code == 2
    assert "오류: 알 수 없는 명령어입니다: 'down'" in res_ko.output
    set_lang("en")


def test_cli_upgrade_uses_uv_tool_upgrade_with_utf8_decoding(runner: CliRunner):
    result = MagicMock(returncode=0, stdout="", stderr="")
    repo = "https://example.test/custom/compman.git"
    with patch("compman.cli._find_uv", return_value="/fake/uv"), patch(
        "subprocess.run", return_value=result
    ) as run:
        res = runner.invoke(app, ["upgrade", "--repo", repo])
    assert res.exit_code == 0
    assert "Upgrading compman CLI..." in res.output
    assert repo not in res.output
    assert "compman CLI upgraded successfully!" in res.output
    run.assert_called_once_with(
        [
            "/fake/uv",
            "tool",
            "upgrade",
            "compman",
            "--reinstall",
            "--managed-python",
            "--python",
            "3.13",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_cli_completion(runner: CliRunner, temp_dir: pathlib.Path):
    res = runner.invoke(app, ["completion", "powershell"])
    assert res.exit_code == 0
    assert "Register-ArgumentCompleter" in res.output
    assert "'doctor'" in res.output
    assert "'status'" in res.output
    assert "'ps'" in res.output
    assert "'stats'" in res.output

    profile = temp_dir / "Microsoft.PowerShell_profile.ps1"
    with patch("compman.cli.subprocess.check_output", return_value=str(profile)) as profile_lookup:
        res_install = runner.invoke(app, ["completion", "powershell", "--install"])
        assert res_install.exit_code == 0
        assert "Registered PowerShell" in res_install.output
        installed = profile.read_text(encoding="utf-8")
        assert "Register-ArgumentCompleter -Native -CommandName compman" in installed
        assert "'doctor'" in installed
        assert "'status'" in installed

        res_reinstall = runner.invoke(app, ["completion", "powershell", "--install"])
        assert res_reinstall.exit_code == 0
        assert "already has auto-completion registered" in res_reinstall.output
        assert profile.read_text(encoding="utf-8") == installed
        assert profile_lookup.call_count == 2


def test_completion_snippet_matches_registered_command_tree(runner: CliRunner):
    res = runner.invoke(app, ["completion", "powershell"])
    assert res.exit_code == 0
    lines = res.output.splitlines()

    root_line = next(line for line in lines if "subcommands = @" in line)
    snippet_root = set(re.findall(r"'([^']+)'", root_line))
    actual_root = {c.name or c.callback.__name__ for c in app.registered_commands}
    actual_groups = {g.name for g in app.registered_groups}
    assert snippet_root == actual_root | actual_groups

    for group in app.registered_groups:
        for i, line in enumerate(lines):
            if f"$words[1] -eq '{group.name}'" in line:
                snippet_group = set(re.findall(r"'([^']+)'", lines[i + 1]))
                actual_group = {
                    c.name or c.callback.__name__ for c in group.typer_instance.registered_commands
                }
                assert snippet_group == actual_group, f"group {group.name}"
                break
        else:
            raise AssertionError(f"no completion branch for group {group.name}")


def test_readme_command_list_matches_registered_command_tree():
    root = pathlib.Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    if "## Commands" in readme:
        section = readme.split("## Commands", 1)[1].split("View all options", 1)[0]
    else:
        section = readme.split("### 전체 명령어", 1)[1].split("View all options", 1)[0] if "### 전체 명령어" in readme else readme
        if "View all options" not in section:
            section = section.split("### 동작 특성", 1)[0] if "### 동작 특성" in section else section

    actual_root = {c.name or c.callback.__name__ for c in app.registered_commands}
    actual_groups = {
        g.name: {c.name or c.callback.__name__ for c in g.typer_instance.registered_commands}
        for g in app.registered_groups
    }

    for line in section.splitlines():
        match = re.match(r"\s*compman (\w+)(?:\s+(\w+))?", line)
        if not match:
            continue
        command, subcommand = match.group(1), match.group(2)
        assert command in actual_root or command in actual_groups, f"unknown command {command!r} in README: {line.strip()}"
        if command in actual_groups and subcommand:
            assert subcommand in actual_groups[command], f"unknown {command} subcommand {subcommand!r} in README: {line.strip()}"


def test_cli_completion_bash(runner: CliRunner):
    res = runner.invoke(app, ["completion", "bash"])
    assert res.exit_code == 0
    assert "_COMPMAN_COMPLETE" in res.output


def test_cli_completion_zsh(runner: CliRunner):
    res = runner.invoke(app, ["completion", "zsh"])
    assert res.exit_code == 0
    assert "_COMPMAN_COMPLETE" in res.output


def test_cli_completion_fish(runner: CliRunner):
    res = runner.invoke(app, ["completion", "fish"])
    assert res.exit_code == 0
    assert "_COMPMAN_COMPLETE" in res.output


def test_cli_completion_install_bash(runner: CliRunner, temp_dir: pathlib.Path):
    rc = temp_dir / ".bashrc"
    with patch("pathlib.Path.home", return_value=temp_dir), patch("pathlib.Path.read_text", side_effect=FileNotFoundError if not rc.exists() else None):
        try:
            res = runner.invoke(app, ["completion", "bash", "--install"])
        except FileNotFoundError:
            res = runner.invoke(app, ["completion", "bash", "--install"])
        assert res.exit_code == 0


def test_cli_completion_install_zsh(runner: CliRunner, temp_dir: pathlib.Path):
    with patch("pathlib.Path.home", return_value=temp_dir):
        res = runner.invoke(app, ["completion", "zsh", "--install"])
        assert res.exit_code == 0


def test_cli_completion_install_fish(runner: CliRunner, temp_dir: pathlib.Path):
    with patch("pathlib.Path.home", return_value=temp_dir):
        res = runner.invoke(app, ["completion", "fish", "--install"])
        assert res.exit_code == 0


def test_cli_completion_install_ps_error(runner: CliRunner):
    with patch("subprocess.check_output", side_effect=Exception("mock fail")):
        res = runner.invoke(app, ["completion", "powershell", "--install"])
        assert res.exit_code == 0


def test_doctor_json_is_single_document(runner: CliRunner, monkeypatch):
    report = DoctorReport((CheckResult("config", "required", True, "valid"),))
    monkeypatch.setattr("compman.cli.collect_doctor", lambda *_: report)

    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["ok"] is True
    assert result.stdout.startswith("{")


def test_doctor_failure_exits_one_after_text_report(runner: CliRunner, monkeypatch):
    report = DoctorReport((CheckResult("config", "required", False, "missing"),))
    monkeypatch.setattr("compman.cli.collect_doctor", lambda *_: report)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "X" in result.stdout
    assert "missing" in result.stdout


def test_doctor_forwards_config_and_profile(runner: CliRunner, monkeypatch):
    report = DoctorReport(())
    calls: list[tuple[str | None, str | None]] = []
    monkeypatch.setattr(
        "compman.cli.collect_doctor",
        lambda config, profile: calls.append((config, profile)) or report,
    )

    result = runner.invoke(app, ["doctor", "--config", "custom.yml", "--profile", "dev"])

    assert result.exit_code == 0
    assert calls == [("custom.yml", "dev")]


def test_top_level_status_json_is_single_document_and_forwards_options(runner: CliRunner, monkeypatch):
    report = StatusReport(
        True,
        "docker",
        "app",
        "dev",
        ("compose.yml",),
        (ServiceStatus("web", "app-web-1", "running", "Up", "healthy"),),
    )
    calls: list[tuple[str | None, str | None]] = []
    monkeypatch.setattr(
        "compman.cli.collect_status",
        lambda config, profile: calls.append((config, profile)) or report,
    )

    result = runner.invoke(app, ["status", "--json", "--config", "custom.yml", "--profile", "dev"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["services"][0]["service"] == "web"
    assert result.stdout.startswith("{")
    assert calls == [("custom.yml", "dev")]


def test_top_level_status_text_report_lists_each_service(runner: CliRunner, monkeypatch):
    report = StatusReport(
        True,
        "docker",
        "app",
        None,
        ("compose.yml",),
        (
            ServiceStatus("web", "app-web-1", "running", "Up", "healthy"),
            ServiceStatus("worker", "app-worker-1", "running", "Up", None),
        ),
    )
    monkeypatch.setattr("compman.cli.collect_status", lambda *_: report)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Status: app" in result.stdout
    assert "web" in result.stdout
    assert "worker" in result.stdout


def test_top_level_status_text_report_includes_profile(runner: CliRunner, monkeypatch):
    report = StatusReport(True, "docker", "app", "dev", ("compose.yml",), ())
    monkeypatch.setattr("compman.cli.collect_status", lambda *_: report)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "(profile: dev)" in result.stdout


def test_top_level_status_failure_exits_one_after_text_report(runner: CliRunner, monkeypatch):
    report = StatusReport(False, None, "app", None, (), (), "Stack is not running.")
    monkeypatch.setattr("compman.cli.collect_status", lambda *_: report)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "Stack is not running." in result.stdout


def test_cli_init_s3_interactive(runner: CliRunner, temp_dir: pathlib.Path):
    with patch("compman.ops.common.prompt_select", return_value=1), patch("typer.prompt", return_value="s3://b/k"), patch("compman.cli._deploy"):
        res = runner.invoke(app, ["init"])
        assert res.exit_code == 0


def test_cli_update_deploy_path(runner: CliRunner, dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text("compman:\n  name: app\n  deploy: s3://b/k.tar.gz\n  compose:\n    default:\n      file: docker-compose.yml\n", encoding="utf-8")
    (temp_dir / "docker-compose.yml").touch()
    with patch("compman.cli.detect_runtime", return_value=dummy_runtime), patch("compman.cli._deploy") as deploy:
        res = runner.invoke(app, ["update"])
        assert res.exit_code == 0
    deploy.assert_called_once()
    assert deploy.call_args.kwargs["config"].name == "app"
    assert deploy.call_args.kwargs["runtime"] is dummy_runtime


def test_cli_stack_down_no_yes_abort(runner: CliRunner, dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text("compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n", encoding="utf-8")
    (temp_dir / "docker-compose.yml").touch()
    with patch("compman.cli.detect_runtime", return_value=dummy_runtime):
        res = runner.invoke(app, ["stack", "down"], input="y\n")
        assert res.exit_code == 0


def test_cli_root_no_subcommand(runner: CliRunner):
    res = runner.invoke(app, [])
    assert res.exit_code == 2


def test_cli_upgrade_uv_failure_reports_diagnostics_without_fallback(runner: CliRunner):
    mock_uv = MagicMock(returncode=1, stderr="uv fail", stdout="")
    with patch("compman.cli._find_uv", return_value="/fake/uv"), patch(
        "subprocess.run", return_value=mock_uv
    ) as run:
        res = runner.invoke(app, ["upgrade"])
    assert res.exit_code == 1
    assert "uv fail" in res.output
    assert "Traceback" not in res.output
    run.assert_called_once()


def test_cli_upgrade_missing_uv_falls_back_to_pip_with_custom_repo(runner: CliRunner):
    pip_result = MagicMock(returncode=0, stdout="", stderr="")
    repo = "https://example.test/custom/compman.git"
    with patch("compman.cli._find_uv", return_value="uv"), patch(
        "subprocess.run", side_effect=[FileNotFoundError(), pip_result]
    ) as run:
        res = runner.invoke(app, ["upgrade", "--repo", repo])
    assert res.exit_code == 0
    assert "compman CLI upgraded successfully!" in res.output
    assert run.call_args_list[1].args[0] == [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        f"git+{repo}",
    ]
    assert run.call_args_list[1].kwargs == {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }


def test_cli_upgrade_missing_uv_pip_failure_handles_replacement_text(runner: CliRunner):
    failed = MagicMock(returncode=1, stderr="download failed \ufffd", stdout="")
    with patch("compman.cli._find_uv", return_value="uv"), patch(
        "subprocess.run", side_effect=[FileNotFoundError(), failed]
    ):
        res = runner.invoke(app, ["upgrade"])
    assert res.exit_code == 1
    assert "download failed \ufffd" in res.output
    assert "Traceback" not in res.output


def test_cli_version_pkg_not_found(runner: CliRunner):
    with patch("compman.cli._pkg_version", side_effect=Exception):
        res = runner.invoke(app, ["version"])
        assert res.exit_code == 1


def test_cli_lang_callback_set(runner: CliRunner):
    res = runner.invoke(app, ["-l", "en", "version"])
    assert res.exit_code == 0


def test_cli_load_runtime_error(runner: CliRunner, temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text("compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n", encoding="utf-8")
    with patch("compman.docker.detect_runtime", side_effect=RuntimeError("no runtime")):
        res = runner.invoke(app, ["stack", "up"])
        assert res.exit_code != 0


def test_cli_expected_errors_exit_cleanly(runner: CliRunner):
    with patch("compman.cli._deploy", side_effect=CommandError("operation failed", code=7)):
        command_error = runner.invoke(app, ["deploy"])
    assert command_error.exit_code == 7
    assert isinstance(command_error.exception, SystemExit)
    assert command_error.output == "operation failed\n"
    assert "Traceback" not in command_error.output

    with patch("compman.cli._deploy", side_effect=ConfigError("invalid config")):
        config_error = runner.invoke(app, ["deploy"])
    assert config_error.exit_code == 1
    assert isinstance(config_error.exception, SystemExit)
    assert config_error.output == "Error: invalid config\n"
    assert "Traceback" not in config_error.output

    with patch("compman.cli.detect_runtime", side_effect=RuntimeError("missing runtime")):
        runtime_error = runner.invoke(app, ["clear", "--yes"])
    assert runtime_error.exit_code == 1
    assert isinstance(runtime_error.exception, SystemExit)
    assert runtime_error.output == "Pruning unused Docker images...\nError: missing runtime\n"
    assert "Traceback" not in runtime_error.output


def test_run_upgrade_command_replaces_invalid_utf8_from_real_subprocess():
    result = _run_upgrade_command(
        [sys.executable, "-c", "import os; os.write(1, b'invalid: \\xff')"]
    )
    assert result.returncode == 0
    assert result.stdout == "invalid: \ufffd"
    assert result.stderr == ""


def test_cli_service_no_services(runner: CliRunner, dummy_runtime, temp_dir: pathlib.Path):
    (temp_dir / "compman.yml").write_text("compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n", encoding="utf-8")
    (temp_dir / "docker-compose.yml").touch()
    with patch("compman.cli.detect_runtime", return_value=dummy_runtime):
        for cmd in ["start", "stop", "restart"]:
            res = runner.invoke(app, ["service", cmd])
            assert res.exit_code == 0
