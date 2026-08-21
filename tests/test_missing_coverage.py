from __future__ import annotations

import importlib
import json
import pathlib
import runpy
import shutil
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
import typer

import compman.cli as cli
import compman.completion as completion
import compman.deploy as deploy
from compman.config import Config, ConfigError, Profile, load_config
from compman.docker import ContainerRuntime, _run
from compman.errors import CommandError
from compman.ops import common, image, service, volume


def test_cli_internal_callbacks_and_load(runner, temp_dir):
    cli._lang_callback("ko")
    cli._lang_callback(None)
    ctx = MagicMock(invoked_subcommand=None)
    ctx.get_help.return_value = "help"
    cli.root(ctx)

    with patch("compman.cli.detect_runtime", side_effect=RuntimeError("missing")):
        (temp_dir / "compman.yml").write_text("compman:\n  name: app\n", encoding="utf-8")
        with pytest.raises(typer.Exit):
            cli._load()

    with patch("compman.ops.common.prompt_select", return_value=3):
        result = runner.invoke(cli.app, ["init"])
    assert result.exit_code == 0


def test_cli_lazy_wrappers_delegate_to_command_modules():
    doctor_report = MagicMock()
    status_report = MagicMock()
    with patch("compman.deploy.deploy") as deploy_command:
        cli._deploy(build=True, tag="tag", s3_path="s3://bucket/key")
    deploy_command.assert_called_once_with(
        build=True,
        tag="tag",
        s3_path="s3://bucket/key",
        config=None,
        runtime=None,
        profile=None,
        dry_run=False,
        strategy=None,
        keep=3,
        no_build=False,
    )

    with patch("compman.diagnostics.collect_doctor", return_value=doctor_report):
        assert cli.collect_doctor("compman.yml", "dev") is doctor_report
    with patch("compman.diagnostics.collect_status", return_value=status_report):
        assert cli.collect_status("compman.yml", "dev") is status_report


def test_cli_init_force_and_completion_existing(runner, temp_dir):
    profile = temp_dir / "profile.ps1"
    profile.write_text("# compman shell completion\nold _COMPMAN_COMPLETE\n", encoding="utf-8")
    with patch("subprocess.check_output", return_value=str(profile)):
        result = runner.invoke(cli.app, ["completion", "powershell", "--install"])
    assert result.exit_code == 0
    assert runner.invoke(cli.app, ["completion", "fish"]).exit_code == 0
    profile.write_text("existing", encoding="utf-8")
    with patch("subprocess.check_output", return_value=str(profile)):
        result = runner.invoke(cli.app, ["completion", "powershell", "--install"])
    assert result.exit_code == 0

    profile.write_text("Register-ArgumentCompleter -Native -CommandName compman", encoding="utf-8")
    with patch("subprocess.check_output", return_value=str(profile)):
        result = runner.invoke(cli.app, ["completion", "powershell", "--install"])
    assert result.exit_code == 0

    for shell, name, content in (
        ("bash", ".bashrc", "_COMPMAN_COMPLETE"),
        ("zsh", ".zshrc", "_COMPMAN_COMPLETE"),
    ):
        path = temp_dir / name
        path.write_text(content, encoding="utf-8")
        with patch("pathlib.Path.home", return_value=temp_dir):
            result = runner.invoke(cli.app, ["completion", shell, "--install"])
        assert result.exit_code == 0

    fish = temp_dir / ".config" / "fish" / "config.fish"
    fish.parent.mkdir(parents=True)
    fish.write_text("_COMPMAN_COMPLETE", encoding="utf-8")
    with patch("pathlib.Path.home", return_value=temp_dir):
        result = runner.invoke(cli.app, ["completion", "fish", "--install"])
    assert result.exit_code == 0


def test_cli_upgrade_and_uv_paths(runner):
    failed = MagicMock(returncode=1, stderr="failed", stdout="")
    with patch("shutil.which", return_value=None), patch(
        "subprocess.run", side_effect=[FileNotFoundError(), failed]
    ):
        result = runner.invoke(cli.app, ["upgrade"])
    assert result.exit_code != 0

    with patch("shutil.which", return_value=None), patch("subprocess.run", return_value=failed):
        result = runner.invoke(cli.app, ["upgrade"])
    assert result.exit_code != 0

    with patch("shutil.which", return_value=None), patch("subprocess.run", side_effect=[FileNotFoundError, failed]):
        result = runner.invoke(cli.app, ["upgrade"])
    assert result.exit_code != 0

    with patch("shutil.which", side_effect=[None] * 6), patch("pathlib.Path.is_file", return_value=False):
        assert cli._find_uv() == "uv"

    with patch("shutil.which", return_value=None), patch("pathlib.Path.is_file", return_value=True):
        assert cli._find_uv().endswith("uv.exe")
    with patch("shutil.which", return_value=None), patch("pathlib.Path.is_file", return_value=False):
        assert cli._find_uv() == "uv"


def test_find_uv_returns_path_from_shutil_which():
    with patch("shutil.which", return_value="C:/tools/uv.exe"):
        assert cli._find_uv() == "C:/tools/uv.exe"


def test_cli_version_callback_package_missing():
    with patch("compman.cli._pkg_version", side_effect=__import__("importlib").metadata.PackageNotFoundError):
        with pytest.raises(typer.Exit):
            cli._version_callback(True)
    with patch("compman.cli._pkg_version", side_effect=__import__("importlib").metadata.PackageNotFoundError):
        cli.version_cmd()


def test_cli_preparse_lang_reload():
    with patch("sys.argv", ["compman", "--lang", "ko"]):
        importlib.reload(cli)
    with patch("sys.argv", ["compman", "--lang=ko"]):
        importlib.reload(cli)
    with patch("sys.argv", ["compman", "-l= en"]):
        importlib.reload(cli)


def test_main_guard():
    with patch("compman.cli.app", side_effect=SystemExit(0)):
        with patch("sys.argv", ["compman"]):
            with pytest.raises(SystemExit):
                runpy.run_path(str(pathlib.Path(__file__).parents[1] / "compman" / "__main__.py"), run_name="__main__")


def test_config_remaining_branches(temp_dir):
    config = temp_dir / "empty.yml"
    config.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config))

    config.write_text("compman:\n  name: app\n  compose:\n    base: base.yml\n    dev: dev.yml\n", encoding="utf-8")
    cfg = load_config(str(config))
    assert cfg.compose_base == "base.yml"

    config = temp_dir / "compman.yml"
    config.write_text("compman:\n  name: app\n  compose:\n    dev: 3\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config))

    config.write_text("compman:\n  name: app\n  compose:\n    - base.yml\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config))


def test_cli_upgrade_fallback_failure_and_find_uv():
    failed = MagicMock(returncode=1, stderr="err", stdout="")
    with patch("shutil.which", return_value=None), patch("subprocess.run", side_effect=[FileNotFoundError(), failed]):
        with pytest.raises(SystemExit):
            cli.upgrade_cmd()
    with patch("shutil.which", return_value=None), patch("subprocess.run", side_effect=[FileNotFoundError(), MagicMock(returncode=0)]):
        cli.upgrade_cmd()
    with patch("shutil.which", return_value=None), patch("pathlib.Path.is_file", return_value=False):
        assert cli._find_uv() == "uv"
    with pytest.raises(CommandError, match="Unsupported shell"):
        completion.completion_cmd("unknown")
    with patch("sys.argv", ["compman", "version"]):
        with pytest.raises(SystemExit):
            runpy.run_path(str(pathlib.Path(__file__).parents[1] / "compman" / "cli.py"), run_name="__main__")


def test_runtime_command_branches():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    with patch("compman.docker._run", return_value=MagicMock(returncode=0)) as run:
        runtime.run_cli(["ps"], capture=False, check=False)
        runtime.run_compose(["ps"], project="p", compose_files=[pathlib.Path("a.yml")], env={"X": "1"}, capture=False, check=False)
        assert run.call_count == 2
    with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="bad", stdout="out")):
        with pytest.raises(RuntimeError):
            _run(["bad"])

    with patch("subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(RuntimeError):
            _run(["docker", "compose", "up"])

    runtime._compose_cmd(None, [pathlib.Path("a.yml"), pathlib.Path("b.yml")])
    with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="")):
        from compman.docker import _passthru
        _passthru(["true"])


def test_docker_remaining_branches():
    import compman.docker as docker
    with patch("subprocess.run", side_effect=[FileNotFoundError, subprocess.TimeoutExpired(["x"], 1)]):
        assert docker._check_cmd(["x"])[0] is False
        assert docker._check_cmd(["x"])[0] is False
    with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="", stdout="")):
        with pytest.raises(RuntimeError):
            docker._die(["x"], MagicMock(returncode=1, stderr="", stdout=""))
    with patch("compman.docker._check_cmd", side_effect=[(False, ""), (False, ""), (False, ""), (True, "ok")]):
        assert docker.detect_runtime().compose == ["docker-compose"]
    with patch("compman.docker._check_cmd", side_effect=[(False, ""), (True, "ok"), (False, ""), (True, "ok")]):
        assert docker.detect_runtime().name == "podman"
    with patch.dict("os.environ", {"CONTAINER_RUNTIME": "docker"}), patch("compman.docker._check_cmd", side_effect=[(False, ""), (True, "ok")]):
        assert docker.detect_runtime().compose == ["docker-compose"]
    with patch.dict("os.environ", {"CONTAINER_RUNTIME": "podman"}), patch("compman.docker._check_cmd", return_value=(False, "")):
        with pytest.raises(RuntimeError):
            docker.detect_runtime()
    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        docker._run(["x"], capture=False)


def test_runtime_stack_and_detection_branches():
    runtime = ContainerRuntime("docker", ["docker"], ["docker", "compose"])
    false = MagicMock(stdout="")
    with patch.object(runtime, "run_compose", return_value=false), patch.object(runtime, "run_cli", return_value=MagicMock(stdout="cid\n")):
        assert runtime.stack_exists("p")
    with patch.object(runtime, "run_compose", return_value=false), patch.object(runtime, "run_cli", return_value=MagicMock(stdout="")):
        assert not runtime.stack_exists("p")

    with patch("compman.docker._check_cmd", side_effect=[(False, ""), (False, ""), (False, ""), (False, "")]):
        with pytest.raises(RuntimeError):
            import compman.docker as docker
            docker.detect_runtime()


def test_deploy_error_and_scaffold_branches(temp_dir):
    bad_config = temp_dir / "compman.yml"
    bad_config.write_text("other: value", encoding="utf-8")
    with patch("boto3.client", return_value=MagicMock()), patch("compman.deploy._fetch", side_effect=RuntimeError("boom")):
        with pytest.raises(SystemExit):
            deploy.deploy(s3_path="s3://b/k")

    bad_config.write_text("compman:\n  name: app\n  compose:\n    - docker-compose.yml\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        deploy.deploy(s3_path=None)

    bad_config.write_text("compman:\n  name: app\n  deploy: s3://b/k\n", encoding="utf-8")
    with patch("boto3.client", return_value=MagicMock()), patch("compman.deploy._fetch", side_effect=RuntimeError("boom")):
        with pytest.raises(SystemExit):
            deploy.deploy(s3_path=None)

    deploy._update_compman_deploy(bad_config, "s3://new/path")
    bad_config.write_text("compman:\n  name: app\n  deploy: old\n", encoding="utf-8")
    with patch("yaml.safe_load", side_effect=ValueError("bad")):
        deploy._update_compman_deploy(bad_config, "s3://new/path")

    root = temp_dir / "scaffold"
    root.mkdir()
    deploy._generate_scaffold(root, "project", "s3://b/k", "img")
    assert (root / "docker-compose.yml").exists()

    src = temp_dir / "src"
    src.mkdir()
    (src / ".gitkeep").touch()
    (src / "old").mkdir()
    (src / "old" / "x").write_text("x", encoding="utf-8")
    target = temp_dir / "target"
    target.mkdir()
    (target / "delete.txt").write_text("x", encoding="utf-8")
    (target / ".git").mkdir()
    deploy._swap(src, target)
    assert not (target / "delete.txt").exists()


def test_deploy_update_fallback_and_recursive(temp_dir):
    path = temp_dir / "compman.yml"
    path.write_text("compman:\n  name: app\n", encoding="utf-8")
    with patch("yaml.safe_load", side_effect=[{}, ValueError("bad"), {}]):
        deploy._update_compman_deploy(path, "s3://b/k")

    s3 = MagicMock()
    s3.get_paginator.return_value.paginate.return_value = [{}, {"Contents": []}]
    deploy._download_recursive(s3, "b", "", temp_dir / "dst")
    assert s3.get_paginator.called


def test_deploy_update_line_branches(temp_dir):
    path = temp_dir / "compman.yml"
    path.write_text("compman:\n  name: app\n  deploy: old\nother: value\n", encoding="utf-8")
    deploy._update_compman_deploy(path, "s3://new")
    path.write_text("compman:\n", encoding="utf-8")
    deploy._update_compman_deploy(path, "s3://new")
    path.write_text("compman:\n  # comment\n", encoding="utf-8")
    with patch("yaml.safe_load", side_effect=[{"compman": {}}, {}]):
        deploy._update_compman_deploy(path, "s3://new")

    src = temp_dir / "src2"
    src.mkdir()
    dst = temp_dir / "dst2"
    dst.mkdir()
    (dst / "dir").mkdir()
    (dst / "file").write_text("x", encoding="utf-8")
    deploy._swap(src, dst)
    path.write_text("compman:\n  name: app\n# root\n", encoding="utf-8")
    deploy._update_compman_deploy(path, "s3://new")
    path.write_text("compman:\n  name: app\nother: value\n", encoding="utf-8")
    deploy._update_compman_deploy(path, "s3://new")
    path.write_text("root: value\ncompman:\n  name: app\n", encoding="utf-8")
    deploy._update_compman_deploy(path, "s3://new")
    new_target = temp_dir / "new-target"
    deploy._swap(src, new_target)
    try:
        (dst / "broken").symlink_to(dst / "does-not-exist")
    except OSError:
        pass
    else:
        deploy._swap(src, dst)


@pytest.mark.parametrize("new_item_is_dir", [False, True])
def test_deploy_swap_rolls_back_partially_moved_source(temp_dir, new_item_is_dir):
    src = temp_dir / "source"
    src.mkdir()
    new_item = src / "a-new"
    if new_item_is_dir:
        new_item.mkdir()
    else:
        new_item.write_text("new", encoding="utf-8")
    trigger = src / "b-trigger"
    trigger.write_text("trigger", encoding="utf-8")

    dst = temp_dir / "target"
    dst.mkdir()
    old_item = dst / "old"
    old_item.write_text("old", encoding="utf-8")

    real_move = shutil.move
    real_iterdir = pathlib.Path.iterdir

    def fail_on_trigger(source, destination):
        if pathlib.Path(source) == trigger:
            raise OSError("simulated move failure")
        return real_move(source, destination)

    def ordered_source(path):
        if path == src:
            return iter((new_item, trigger))
        return real_iterdir(path)

    with patch.object(type(src), "iterdir", autospec=True, side_effect=ordered_source), patch(
        "compman.deploy.shutil.move", side_effect=fail_on_trigger
    ):
        with pytest.raises(OSError, match="simulated move failure"):
            deploy._swap(src, dst)

    assert old_item.read_text(encoding="utf-8") == "old"
    assert not (dst / new_item.name).exists()


def test_service_empty_and_multiple(dummy_runtime, temp_dir):
    cfg = Config("app", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.list_containers = MagicMock(return_value=[])
    with pytest.raises(CommandError):
        service.log(dummy_runtime, cfg, None)
    with pytest.raises(CommandError):
        service.connect(dummy_runtime, cfg, None)
    dummy_runtime.list_containers = MagicMock(return_value=["a", "b"])
    service.connect(dummy_runtime, cfg, None)
    dummy_runtime.get_container_id = MagicMock(return_value="")
    with pytest.raises(CommandError):
        service.log(dummy_runtime, cfg, "a")
    with pytest.raises(CommandError):
        service.connect(dummy_runtime, cfg, "a")


def test_common_remaining_branches(temp_dir):
    with patch("sys.platform", "linux"), patch.dict("sys.modules", {"termios": MagicMock(), "tty": MagicMock(), "select": MagicMock()}):
        import compman.ops.common as ops_common
        with patch.object(ops_common.sys.stdin, "fileno", return_value=0), patch("os.read", return_value=b"x"):
            assert ops_common.get_key() == "other"

    with patch("sys.stdin.isatty", return_value=True), patch("compman.ops.common.get_key", return_value="other"):
        with patch("compman.ops.common.get_key", side_effect=["other", "enter"]):
            assert common.prompt_select("x", ["a"]) == 0

    mock_select3 = MagicMock()
    with patch("sys.platform", "linux"), patch.dict("sys.modules", {"termios": MagicMock(), "tty": MagicMock(), "select": mock_select3}):
        import compman.ops.common as ops_common
        mock_select3.select.side_effect = [([0], [], []), ([], [], [])]
        with patch.object(ops_common.sys.stdin, "fileno", return_value=0), patch("os.read", side_effect=[b"\x1b", b"x"]):
            assert ops_common.get_key() == "esc"
        mock_select3.select.side_effect = [([0], [], []), ([0], [], []), ([], [], [])]
        with patch.object(ops_common.sys.stdin, "fileno", return_value=0), patch("os.read", side_effect=[b"\x1b", b"[", b"x"]):
            assert ops_common.get_key() == "esc"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
def test_common_win32_branch():
    with patch("msvcrt.getch", return_value=b"x"):
        assert common.get_key() == "other"


def test_image_remaining_branches(dummy_runtime, temp_dir):
    cfg = Config("app", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.run_compose = MagicMock(return_value=MagicMock(stdout="cid1\n \nX"))
    dummy_runtime.run_cli = MagicMock(return_value=MagicMock(stdout="/name\n"))
    image.backup(dummy_runtime, cfg, source_mode=True)
    dummy_runtime.run_compose = MagicMock(return_value=MagicMock(stdout="cid1\n \n"))
    dummy_runtime.run_cli = MagicMock(return_value=MagicMock(stdout="/name\n"))
    image.backup(dummy_runtime, cfg, source_mode=True)

    cfg.backup_dir.mkdir(parents=True, exist_ok=True)
    with patch("compman.ops.image.select_backup_timestamp", return_value="20000101_0000"):
        with pytest.raises(CommandError):
            image.restore(dummy_runtime, cfg)

    (cfg.backup_dir / "app.image.20000101_0000.tar.gz").touch()
    image._list_backups(cfg)
    assert image._list_backups(cfg) is None


def test_volume_remaining_branches(dummy_runtime, temp_dir):
    cfg = Config("app", profiles={"default": Profile(file="docker-compose.yml")})
    bad = MagicMock(returncode=1, stdout="")
    empty = MagicMock(returncode=0, stdout="[]")
    with patch.object(dummy_runtime, "run_cli", return_value=bad):
        assert volume._inspect_mount(dummy_runtime, "c", "v") is None
    with patch.object(dummy_runtime, "run_cli", return_value=empty):
        assert volume._inspect_mount(dummy_runtime, "c", "v") is None
    data = MagicMock(returncode=0, stdout=json.dumps([{"Mounts": [{"Name": "other", "Destination": "/x"}]}]))
    with patch.object(dummy_runtime, "run_cli", return_value=data):
        assert volume._inspect_mount(dummy_runtime, "c", "v") is None

    volume._list_backups(cfg, "volume")


def test_volume_all_remaining_paths(dummy_runtime, temp_dir):
    cfg = Config("app", profiles={"default": Profile(file="docker-compose.yml")})
    dummy_runtime.list_volumes = MagicMock(return_value=["v"])
    dummy_runtime.list_containers = MagicMock(return_value=["c"])
    with patch("compman.ops.volume._inspect_mount", return_value=None):
        volume.backup(dummy_runtime, cfg, no_stop=True)
        volume.pull(dummy_runtime, cfg)

    backup = cfg.backup_dir / "app.volume.20260731_1200.tar.gz"
    backup.parent.mkdir(parents=True, exist_ok=True)
    empty = temp_dir / "empty"
    empty.mkdir()
    import tarfile
    map_file = temp_dir / "volume-map.json"
    map_file.write_text("{}", encoding="utf-8")
    with tarfile.open(backup, "w:gz") as tar:
        tar.add(empty, arcname=".")
        tar.add(map_file, arcname="volume-map.json")
    volume.restore(dummy_runtime, cfg, "20260731_1200", no_stop=True)

    with patch("compman.ops.volume.select_backup_timestamp", return_value="20260731_1200"):
        volume.restore(dummy_runtime, cfg, None, no_stop=True)

    cfg.volume_dir.mkdir(parents=True, exist_ok=True)
    (cfg.volume_dir / "volume-map.json").write_text(json.dumps({"c": {"volume": "missing", "destination": "/d"}}), encoding="utf-8")
    volume.push(dummy_runtime, cfg)
    dummy_runtime.stack_exists = MagicMock(return_value=False)
    with pytest.raises(CommandError):
        volume.push(dummy_runtime, cfg)

    dummy_runtime.stack_exists = MagicMock(return_value=True)
    with patch("compman.ops.volume._inspect_mount", return_value={"container": "c", "volume": "v", "destination": "/d"}):
        volume.pull(dummy_runtime, cfg)

    missing_map = cfg.backup_dir / "app.volume.20260101_0000.tar.gz"
    with tarfile.open(missing_map, "w:gz") as tar:
        tar.add(empty, arcname=".")
    with pytest.raises(CommandError):
        volume.restore(dummy_runtime, cfg, "20260101_0000", no_stop=True)

    data_dir = temp_dir / "vdata"
    data_dir.mkdir()
    map_file.write_text(json.dumps({"c": {"volume": "vdata", "destination": "/d"}}), encoding="utf-8")
    with tarfile.open(missing_map, "w:gz") as tar:
        tar.add(data_dir, arcname="vdata")
        tar.add(map_file, arcname="volume-map.json")
    volume.restore(dummy_runtime, cfg, "20260101_0000", no_stop=True)

    mount_result = MagicMock(returncode=0, stdout=json.dumps([{"Mounts": [{"Name": "v", "Destination": "/d"}]}]))
    with patch.object(dummy_runtime, "run_cli", return_value=mount_result):
        assert volume._inspect_mount(dummy_runtime, "c", "v")["destination"] == "/d"
    volume._list_backups(cfg, "volume")


def test_config_env_file_string_parses(temp_dir):
    cfg_path = temp_dir / "compman.yml"
    cfg_path.write_text(
        "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n      env_file: .env\n",
        encoding="utf-8",
    )
    cfg = load_config(str(cfg_path))
    assert cfg.profiles["default"].env_file == [".env"]


def test_config_env_file_list_parses(temp_dir):
    cfg_path = temp_dir / "compman.yml"
    cfg_path.write_text(
        "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n      env_file: [.env, other.env]\n",
        encoding="utf-8",
    )
    cfg = load_config(str(cfg_path))
    assert cfg.profiles["default"].env_file == [".env", "other.env"]


def test_config_env_file_absent_defaults_empty(temp_dir):
    cfg_path = temp_dir / "compman.yml"
    cfg_path.write_text(
        "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n",
        encoding="utf-8",
    )
    cfg = load_config(str(cfg_path))
    assert cfg.profiles["default"].env_file == []


@pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
def test_config_env_file_string_blank_raises(temp_dir, bad):
    cfg_path = temp_dir / "compman.yml"
    import yaml as _yaml

    data = {"compman": {"name": "app", "compose": {"default": {"file": "docker-compose.yml", "env_file": bad}}}}
    cfg_path.write_text(_yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="env_file"):
        load_config(str(cfg_path))


def test_config_env_file_list_with_blank_raises(temp_dir):
    cfg_path = temp_dir / "compman.yml"
    import yaml as _yaml

    data = {
        "compman": {"name": "app", "compose": {"default": {"file": "docker-compose.yml", "env_file": [".env", "   "]}}}
    }
    cfg_path.write_text(_yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="env_file"):
        load_config(str(cfg_path))


def test_config_env_file_list_with_empty_string_raises(temp_dir):
    cfg_path = temp_dir / "compman.yml"
    import yaml as _yaml

    data = {
        "compman": {"name": "app", "compose": {"default": {"file": "docker-compose.yml", "env_file": [""]}}}
    }
    cfg_path.write_text(_yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="env_file"):
        load_config(str(cfg_path))


def test_config_env_file_list_with_non_string_raises(temp_dir):
    cfg_path = temp_dir / "compman.yml"
    import yaml as _yaml

    data = {
        "compman": {"name": "app", "compose": {"default": {"file": "docker-compose.yml", "env_file": [".env", 123]}}}
    }
    cfg_path.write_text(_yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="env_file"):
        load_config(str(cfg_path))


def test_config_env_file_list_all_non_string_raises(temp_dir):
    cfg_path = temp_dir / "compman.yml"
    cfg_path.write_text(
        "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n      env_file: [123, 456]\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="env_file"):
        load_config(str(cfg_path))


@pytest.mark.parametrize("bad_val", ["123", "dict: {}", "float: 1.5"])
def test_config_env_file_invalid_type_raises(temp_dir, bad_val):
    cfg_path = temp_dir / "compman.yml"
    if bad_val.startswith("dict"):
        cfg_path.write_text(
            "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n      env_file: {a: b}\n",
            encoding="utf-8",
        )
    elif bad_val.startswith("float"):
        cfg_path.write_text(
            "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n      env_file: 1.5\n",
            encoding="utf-8",
        )
    else:
        cfg_path.write_text(
            "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n      env_file: 123\n",
            encoding="utf-8",
        )
    with pytest.raises(ConfigError, match="env_file"):
        load_config(str(cfg_path))


def test_load_env_file_empty(temp_dir):
    from compman.docker import _load_env_file

    f = temp_dir / ".env"
    f.write_text("", encoding="utf-8")
    assert _load_env_file(f) == {}


def test_load_env_file_comments_and_empty(temp_dir):
    from compman.docker import _load_env_file

    f = temp_dir / ".env"
    f.write_text("\n# comment\n   # indented\n\n   \n", encoding="utf-8")
    assert _load_env_file(f) == {}


def test_load_env_file_export_variants(temp_dir):
    from compman.docker import _load_env_file

    f = temp_dir / ".env"
    f.write_text(
        "export FOO=bar\n"
        "export   SPACED=val\n"
        "export \n"
        "export # comment after export\n"
        "export   # also comment\n",
        encoding="utf-8",
    )
    assert _load_env_file(f) == {"FOO": "bar", "SPACED": "val"}


def test_load_env_file_no_equals_ignored(temp_dir):
    from compman.docker import _load_env_file

    f = temp_dir / ".env"
    f.write_text("NOEQUALS\nFOO=bar\n", encoding="utf-8")
    assert _load_env_file(f) == {"FOO": "bar"}


def test_load_env_file_empty_key_ignored(temp_dir):
    from compman.docker import _load_env_file

    f = temp_dir / ".env"
    f.write_text("=value\n   =other\nFOO=ok\n", encoding="utf-8")
    assert _load_env_file(f) == {"FOO": "ok"}


def test_load_env_file_empty_value_and_quoted(temp_dir):
    from compman.docker import _load_env_file

    f = temp_dir / ".env"
    f.write_text(
        "EMPTY=\n"
        'QUOTED_D="hello"\n'
        "QUOTED_S='world'\n"
        'EMPTY_Q=""\n'
        "EMPTY_Q2=''\n"
        'SPACED_Q=" a b "\n'
        'MISMATCH="value\n'
        "MISMATCH2='value\n"
        "UNQUOTED=  spaced  \n",
        encoding="utf-8",
    )
    data = _load_env_file(f)
    assert data["EMPTY"] == ""
    assert data["QUOTED_D"] == "hello"
    assert data["QUOTED_S"] == "world"
    assert data["EMPTY_Q"] == ""
    assert data["EMPTY_Q2"] == ""
    assert data["SPACED_Q"] == " a b "
    assert data["MISMATCH"] == '"value'
    assert data["MISMATCH2"] == "'value"
    assert data["UNQUOTED"] == "spaced"


def test_load_env_file_key_trim_and_value_trim(temp_dir):
    from compman.docker import _load_env_file

    f = temp_dir / ".env"
    f.write_text("  KEY  =  value  \n", encoding="utf-8")
    assert _load_env_file(f) == {"KEY": "value"}


def test_load_env_file_export_quoted(temp_dir):
    from compman.docker import _load_env_file

    f = temp_dir / ".env"
    f.write_text('export KEY="quoted"\n', encoding="utf-8")
    assert _load_env_file(f) == {"KEY": "quoted"}


def test_resolve_profile_env_missing_file_raises(temp_dir):
    from compman.config import Config, Profile
    from compman.docker import _resolve_profile_env

    cfg = Config(name="app", root_dir=temp_dir, profiles={"default": Profile(file="docker-compose.yml", env_file=["missing.env"])})
    with pytest.raises(ConfigError, match="Env file not found"):
        _resolve_profile_env(cfg, cfg.profiles["default"])


def test_resolve_profile_env_relative_and_absolute(temp_dir, tmp_path):
    from compman.config import Config, Profile
    from compman.docker import _resolve_profile_env

    rel = temp_dir / "rel.env"
    rel.write_text("FOO=rel\n", encoding="utf-8")
    cfg = Config(name="app", root_dir=temp_dir, profiles={"default": Profile(file="docker-compose.yml", env_file=["rel.env"])})
    assert _resolve_profile_env(cfg, cfg.profiles["default"]) == {"FOO": "rel"}

    abs_file = tmp_path / "abs.env"
    abs_file.write_text("BAR=abs\n", encoding="utf-8")
    cfg2 = Config(
        name="app", root_dir=temp_dir, profiles={"default": Profile(file="docker-compose.yml", env_file=[str(abs_file)])}
    )
    assert _resolve_profile_env(cfg2, cfg2.profiles["default"]) == {"BAR": "abs"}


def test_resolve_profile_env_merge_order_and_explicit_override(temp_dir):
    from compman.config import Config, Profile
    from compman.docker import resolve_compose_context

    (temp_dir / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (temp_dir / "a.env").write_text("KEY=first\nSHARED=a\n", encoding="utf-8")
    (temp_dir / "b.env").write_text("KEY=second\nONLY_B=b\n", encoding="utf-8")
    cfg = Config(
        name="app",
        root_dir=temp_dir,
        source_path=temp_dir / "compman.yml",
        profiles={
            "default": Profile(file="docker-compose.yml", env={"KEY": "explicit", "ONLY_EXPLICIT": "e"}, env_file=["a.env", "b.env"])
        },
    )
    ctx = resolve_compose_context(cfg, "default")
    assert ctx.env["KEY"] == "explicit"
    assert ctx.env["SHARED"] == "a"
    assert ctx.env["ONLY_B"] == "b"
    assert ctx.env["ONLY_EXPLICIT"] == "e"


def test_resolve_profile_env_second_file_overrides_first(temp_dir):
    from compman.config import Config, Profile
    from compman.docker import _resolve_profile_env

    (temp_dir / "a.env").write_text("KEY=first\n", encoding="utf-8")
    (temp_dir / "b.env").write_text("KEY=second\n", encoding="utf-8")
    cfg = Config(
        name="app", root_dir=temp_dir, profiles={"default": Profile(file="docker-compose.yml", env_file=["a.env", "b.env"])}
    )
    assert _resolve_profile_env(cfg, cfg.profiles["default"])["KEY"] == "second"


def test_resolve_compose_context_with_env_file_and_secrets(temp_dir):
    from unittest.mock import patch

    from compman.config import Config, Profile, SecretRef
    from compman.docker import resolve_compose_context

    (temp_dir / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (temp_dir / ".env").write_text("PLAIN=fromfile\n", encoding="utf-8")
    cfg = Config(
        name="app",
        root_dir=temp_dir,
        source_path=temp_dir / "compman.yml",
        profiles={
            "default": Profile(
                file="docker-compose.yml",
                env={"COMBINED": "prefix-${secrets:MY_SEC}-suffix", "PLAIN": "explicit"},
                env_file=[".env"],
            )
        },
        secrets={"MY_SEC": SecretRef(arn="arn:aws:secretsmanager:ap-northeast-2:123:secret:app", key="k")},
    )
    with patch("compman.docker.resolve_secrets", return_value={"MY_SEC": "secretval"}):
        ctx = resolve_compose_context(cfg, "default")
    assert ctx.env["COMBINED"] == "prefix-secretval-suffix"
    assert ctx.env["PLAIN"] == "explicit"


def test_resolve_compose_files_with_env_file(temp_dir):
    from compman.config import Config, Profile
    from compman.docker import resolve_compose_files

    (temp_dir / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (temp_dir / ".env").write_text("FOO=bar\n", encoding="utf-8")
    cfg = Config(
        name="app", root_dir=temp_dir, profiles={"default": Profile(file="docker-compose.yml", env_file=[".env"])}
    )
    files, env = resolve_compose_files(cfg, "default")
    assert env == {"FOO": "bar"}
    assert files[0].name == "docker-compose.yml"


def test_resolve_compose_context_without_source_path_uses_env_file(temp_dir):
    from compman.config import Config, Profile
    from compman.docker import resolve_compose_context

    (temp_dir / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (temp_dir / ".env").write_text("FOO=bar\n", encoding="utf-8")
    cfg = Config(
        name="app",
        root_dir=temp_dir,
        source_path=None,
        profiles={"default": Profile(file="docker-compose.yml", env_file=[".env"])},
    )
    ctx = resolve_compose_context(cfg, "default")
    assert ctx.env == {"FOO": "bar"}


def test_deploy_swap_cleans_symlink_and_missing(tmp_path):
    import pathlib as _pl

    import compman.deploy as _deploy

    src = tmp_path / "src"
    src.mkdir()
    (src / "newfile").write_text("new", encoding="utf-8")
    dst = tmp_path / "dst"
    dst.mkdir()
    old = dst / "oldfile"
    old.write_text("old", encoding="utf-8")
    trigger = src / "trigger"
    trigger.write_text("trigger", encoding="utf-8")
    real_move = shutil.move

    def fail_on_trigger(s, d):
        if _pl.Path(s) == trigger:
            raise OSError("fail trigger")
        return real_move(s, d)

    def ordered(p):
        if p == src:
            return iter((src / "newfile", trigger))
        return _pl.Path.iterdir(p)

    with patch.object(type(src), "iterdir", autospec=True, side_effect=ordered), patch(
        "compman.deploy.shutil.move", side_effect=fail_on_trigger
    ):
        with pytest.raises(OSError):
            _deploy._swap(src, dst)
    assert (dst / "oldfile").read_text(encoding="utf-8") == "old"


def test_deploy_swap_missing_dest_branch(tmp_path):
    import pathlib as _pl

    import compman.deploy as _deploy

    src = tmp_path / "src2"
    src.mkdir()
    (src / "newfile").write_text("new", encoding="utf-8")
    dst = tmp_path / "dst2"
    dst.mkdir()
    (dst / "oldfile").write_text("old", encoding="utf-8")
    trigger = src / "trigger"
    trigger.write_text("trigger", encoding="utf-8")

    def fake_move(s, d):
        if _pl.Path(s) == trigger:
            raise OSError("fail trigger")
        return None

    def ordered2(p):
        if p == src:
            return iter((src / "newfile", trigger))
        return _pl.Path.iterdir(p)

    with patch.object(type(src), "iterdir", autospec=True, side_effect=ordered2), patch(
        "compman.deploy.shutil.move", side_effect=fake_move
    ):
        with pytest.raises(OSError):
            _deploy._swap(src, dst)
    assert (dst / "oldfile").read_text(encoding="utf-8") == "old"


def test_deploy_swap_symlink_branch(tmp_path):
    import pathlib as _pl

    import compman.deploy as _deploy

    src = tmp_path / "src3"
    src.mkdir()
    target = tmp_path / "targetdir"
    target.mkdir()
    link = src / "newlink"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink not supported")
    dst = tmp_path / "dst3"
    dst.mkdir()
    (dst / "oldfile").write_text("old", encoding="utf-8")
    trigger = src / "trigger"
    trigger.write_text("trigger", encoding="utf-8")
    real_move = shutil.move

    def fail_on_trigger3(s, d):
        if _pl.Path(s) == trigger:
            raise OSError("fail trigger")
        return real_move(s, d)

    def ordered3(p):
        if p == src:
            return iter((link, trigger))
        return _pl.Path.iterdir(p)

    with patch.object(type(src), "iterdir", autospec=True, side_effect=ordered3), patch(
        "compman.deploy.shutil.move", side_effect=fail_on_trigger3
    ):
        with pytest.raises(OSError):
            _deploy._swap(src, dst)
    assert not (dst / "newlink").exists()
    assert (dst / "oldfile").read_text(encoding="utf-8") == "old"


def test_get_key_win32_digit_branch():
    fake_msvcrt = MagicMock()
    fake_msvcrt.getch.side_effect = [b"5", b"\x00", b"H", b"\xe0", b"P", b"\r", b"\x1b", b"\x03"]
    with patch("sys.platform", "win32"), patch.dict("sys.modules", {"msvcrt": fake_msvcrt}):
        import compman.ops.common as _common

        assert _common.get_key() == "5"
        assert _common.get_key() == "up"
        assert _common.get_key() == "down"
        assert _common.get_key() == "enter"
        assert _common.get_key() == "esc"
        with pytest.raises(KeyboardInterrupt):
            _common.get_key()
    fake_msvcrt2 = MagicMock()
    fake_msvcrt2.getch.return_value = b"9"
    with patch("sys.platform", "win32"), patch.dict("sys.modules", {"msvcrt": fake_msvcrt2}):
        import compman.ops.common as _common2

        assert _common2.get_key() == "9"


def test_cli_deploy_strategy_validation():
    from typer.testing import CliRunner as _Runner

    from compman.cli import app as _app

    _runner = _Runner()
    res = _runner.invoke(_app, ["deploy", "--strategy", "invalid"])
    assert res.exit_code == 2
    res2 = _runner.invoke(_app, ["deploy", "--strategy", "RECREATE", "--help"])
    assert res2.exit_code == 0

