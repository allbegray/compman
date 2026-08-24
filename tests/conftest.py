from __future__ import annotations

import os
import pathlib
from typing import Any, Generator
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from compman import i18n
from compman.docker import ContainerRuntime

DEFAULT_CONFIG_YAML = "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n"


def write_config(path: pathlib.Path, yaml_text: str = DEFAULT_CONFIG_YAML) -> pathlib.Path:
    """Write a compman.yml (Shape-A default) and return its path."""
    path.write_text(yaml_text, encoding="utf-8")
    return path


class DummyRuntime(ContainerRuntime):
    def __init__(self) -> None:
        super().__init__(name="docker", cli=["docker"], compose=["docker", "compose"])
        self.commands_run: list[list[str]] = []
        self.compose_runs: list[dict[str, Any]] = []
        self.compose_stdout = "my_stack_vol_1\nmy_stack-app-1\n"

    def run_cli(
        self,
        args: Any,
        capture: bool = True,
        check: bool = True,
        timeout: float = 300.0,
    ) -> MagicMock:
        self.commands_run.append(list(args))
        m = MagicMock()
        m.return_code = 0
        m.returncode = 0
        m.stdout = "my_stack_vol_1\nmy_stack-app-1\n"
        return m

    def run_compose(
        self,
        args: Any,
        project: str | None = None,
        compose_files: Any = None,
        env: Any = None,
        capture: bool = True,
        check: bool = True,
    ) -> MagicMock:
        self.compose_runs.append(
            {
                "args": list(args),
                "project": project,
                "compose_files": compose_files,
                "env": env,
            }
        )
        m = MagicMock()
        m.return_code = 0
        m.returncode = 0
        m.stdout = self.compose_stdout
        return m

    def passthru_cli(
        self,
        args: Any,
        cwd: pathlib.Path | str | None = None,
        timeout: float | None = None,
    ) -> int:
        self.commands_run.append(list(args))
        return 0

    def logs(self, container: str, follow: bool = False, tail: int = 50) -> int:
        args = ["logs"]
        if follow:
            args.append("-f")
        args.extend(["-n", str(tail), container])
        return self.passthru_cli(args)

    def exec_shell(self, container: str) -> int:
        return self.passthru_cli(["exec", "-it", container, "sh", "-c", "shell"])

    def passthru_compose(
        self,
        args: Any,
        project: str | None = None,
        compose_files: Any = None,
        env: dict[str, str] | None = None,
    ) -> int:
        self.compose_runs.append(
            {
                "args": list(args),
                "project": project,
                "compose_files": compose_files,
                "env": env,
            }
        )
        return 0

    def stack_exists(self, project: str, compose_files: Any = None, env: Any = None) -> bool:
        return True

    def list_volumes(self, project: str) -> list[str]:
        return ["vol1"]

    def list_containers(self, project: str, compose_files: Any = None, env: Any = None) -> list[str]:
        return ["container1"]

    def get_container_id(self, name: str, project: str | None = None) -> str:
        return "cid123"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def dummy_runtime() -> DummyRuntime:
    return DummyRuntime()


@pytest.fixture
def temp_dir(tmp_path: pathlib.Path) -> Generator[pathlib.Path, None, None]:
    old_cwd = pathlib.Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


@pytest.fixture(autouse=True)
def _reset_language() -> Generator[None, None, None]:
    yield
    i18n._CURRENT_LANG.set(None)
