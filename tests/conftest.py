from __future__ import annotations

import os
import pathlib
import subprocess
from collections import deque
from collections.abc import Sequence
from typing import Any, Generator

import pytest
from typer.testing import CliRunner

from compman import i18n
from compman.docker import ContainerRuntime

DEFAULT_CONFIG_YAML = "compman:\n  name: app\n  compose:\n    default:\n      file: docker-compose.yml\n"


def write_config(path: pathlib.Path, yaml_text: str = DEFAULT_CONFIG_YAML) -> pathlib.Path:
    """Write a compman.yml (Shape-A default) and return its path."""
    path.write_text(yaml_text, encoding="utf-8")
    return path


class Response(tuple[int, str, str]):
    """Scripted (returncode, stdout, stderr) for one runtime call."""


class DummyRuntime(ContainerRuntime):
    """In-memory ContainerRuntime double.

    Every public ContainerRuntime method is overridden explicitly; the
    ``dummy_runtime`` fixture fails loudly if a future base method is added
    without a matching override, so tests can never silently hit real
    subprocess code. Unscripted calls succeed deterministically; scripted
    responses are queued per channel with :meth:`queue` and consumed FIFO.
    Calls keep being recorded exactly as before: docker/compose argv in
    ``commands_run``, every compose invocation (run or passthru) as a dict
    in ``compose_runs``.
    """

    CLI_STDOUT = "my_stack_vol_1\nmy_stack-app-1\n"

    def __init__(self) -> None:
        super().__init__(name="docker", cli=["docker"], compose=["docker", "compose"])
        self.commands_run: list[list[str]] = []
        self.compose_runs: list[dict[str, Any]] = []
        self.compose_stdout = "my_stack_vol_1\nmy_stack-app-1\n"
        self._cli_script: deque[Response] = deque()
        self._compose_script: deque[Response] = deque()
        self._passthru_cli_script: deque[int] = deque()
        self._passthru_compose_script: deque[int] = deque()

    def queue(
        self,
        run_cli: Response | Sequence[Response] | None = None,
        compose: Response | Sequence[Response] | None = None,
        passthru_cli: int | Sequence[int] | None = None,
        passthru_compose: int | Sequence[int] | None = None,
    ) -> None:
        """Script FIFO responses for the given channels.

        ``run_cli``/``compose`` take ``(returncode, stdout, stderr)`` tuples;
        ``passthru_cli``/``passthru_compose`` take exit codes. A single tuple
        (or single int) is accepted as shorthand for one response. Channels
        not listed here keep their success defaults.
        """
        if run_cli is not None:
            self._cli_script.extend([run_cli] if isinstance(run_cli, Response) else run_cli)
        if compose is not None:
            self._compose_script.extend([compose] if isinstance(compose, Response) else compose)
        if passthru_cli is not None:
            self._passthru_cli_script.extend([passthru_cli] if isinstance(passthru_cli, int) else passthru_cli)
        if passthru_compose is not None:
            self._passthru_compose_script.extend(
                [passthru_compose] if isinstance(passthru_compose, int) else passthru_compose
            )

    def _result(self, cmd: list[str], spec: Response) -> subprocess.CompletedProcess[str]:
        returncode, stdout, stderr = spec
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    # ---- primitives: argv recording + scripted/success results ----

    def run_cli(
        self,
        args: Any,
        capture: bool = True,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.commands_run.append(list(args))
        cmd = [*self.cli, *args]
        if self._cli_script:
            return self._result(cmd, self._cli_script.popleft())
        return self._result(cmd, Response((0, self.CLI_STDOUT, "")))

    def run_compose(
        self,
        args: Any,
        project: str | None = None,
        compose_files: Any = None,
        env: Any = None,
        capture: bool = True,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.compose_runs.append(
            {
                "args": list(args),
                "project": project,
                "compose_files": compose_files,
                "env": env,
            }
        )
        cmd = [*self._compose_cmd(project, compose_files), *args]
        if self._compose_script:
            return self._result(cmd, self._compose_script.popleft())
        return self._result(cmd, Response((0, self.compose_stdout, "")))

    def passthru_cli(
        self,
        args: Any,
        cwd: pathlib.Path | str | None = None,
        timeout: float | None = None,
    ) -> int:
        self.commands_run.append(list(args))
        if self._passthru_cli_script:
            return self._passthru_cli_script.popleft()
        return 0

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
        if self._passthru_compose_script:
            return self._passthru_compose_script.popleft()
        return 0

    # ---- streaming helpers (fake argv keeps the historical placeholder) ----

    def logs(self, container: str, follow: bool = False, tail: int = 50) -> int:
        args = ["logs"]
        if follow:
            args.append("-f")
        args.extend(["-n", str(tail), container])
        return self.passthru_cli(args)

    def exec_shell(self, container: str) -> int:
        return self.passthru_cli(["exec", "-it", container, "sh", "-c", "shell"])

    # ---- convenience wrappers: same argv as production, via faked primitives ----

    def inspect_container(self, container: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.run_cli(["inspect", container], capture=True, check=check)

    def copy_from_container(self, container: str, source: str, destination: pathlib.Path) -> None:
        self.run_cli(["cp", f"{container}:{source}", str(destination)], capture=False)

    def copy_to_container(self, source: pathlib.Path | str, container: str, destination: str) -> None:
        self.run_cli(["cp", f"{source}", f"{container}:{destination}"], capture=False)

    def fix_permissions(self, container: str, destination: str) -> None:
        result = self.run_cli(
            ["exec", container, "stat", "-c", "%U %G", destination],
            capture=True,
            check=False,
        )
        if result.returncode != 0:
            return
        parts = result.stdout.strip().split()
        if len(parts) >= 2:
            self.run_cli(
                ["exec", "-u", "root", container, "chown", "-R", f"{parts[0]}:{parts[1]}", destination],
                capture=False,
                check=False,
            )

    def inspect_value(self, container: str, format_string: str) -> str:
        result = self.run_cli(["inspect", "--format", format_string, container], capture=True)
        return result.stdout.strip()

    def commit_container(self, container: str, tag: str) -> None:
        self.run_cli(["commit", container, tag], capture=False)

    def save_image(self, image: str, destination: pathlib.Path) -> None:
        self.run_cli(["save", "-o", str(destination), image], capture=False)

    def remove_image(self, image: str) -> None:
        self.run_cli(["rmi", image], capture=False, check=False)

    def load_image(self, source: pathlib.Path) -> None:
        self.run_cli(["load", "-i", str(source)], capture=False)

    def ensure_ready_for_start(self, confirm_start: Any, timeout: float = 60.0) -> None:
        return None

    # ---- state queries: canned success values, no subprocess surface ----

    def stack_exists(self, project: str, compose_files: Any = None, env: Any = None) -> bool:
        return True

    def list_volumes(self, project: str) -> list[str]:
        return ["vol1"]

    def list_containers(self, project: str, compose_files: Any = None, env: Any = None) -> list[str]:
        return ["container1"]

    def service_status(
        self,
        project: str,
        compose_files: Any = None,
        env: Any = None,
    ) -> list[dict[str, object]]:
        return [
            {
                "service": "app",
                "container": "my_stack-app-1",
                "state": "running",
                "status": "Up",
                "health": None,
            }
        ]

    def get_container_id(self, name: str, project: str | None = None) -> str:
        return "cid123"


_RUNTIME_PUBLIC_METHODS = {
    name: member
    for name, member in vars(ContainerRuntime).items()
    if not name.startswith("_") and callable(member)
}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def dummy_runtime() -> DummyRuntime:
    inherited = sorted(
        name
        for name, member in _RUNTIME_PUBLIC_METHODS.items()
        if getattr(DummyRuntime, name) is member
    )
    if inherited:
        pytest.fail(
            "DummyRuntime must explicitly override every public ContainerRuntime "
            f"method so tests never reach real subprocess code; missing overrides: {inherited}"
        )
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


@pytest.fixture(autouse=True)
def _isolate_history_journal(tmp_path, monkeypatch):
    """Keep ops-layer journal hooks out of the developer's real timeline."""
    from compman import history as _history

    monkeypatch.setattr(_history, "history_path", lambda: tmp_path / "history.jsonl")
    yield
