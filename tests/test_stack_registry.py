from __future__ import annotations

import json
import os
import pathlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest

from compman import stack_registry
from compman.scheduling.registry import registry_dir


@contextmanager
def isolated_home(tmp_path: pathlib.Path) -> Iterator[None]:
    """Pin Path.home and clear APPDATA so registry paths resolve under tmp_path."""
    env = {key: value for key, value in os.environ.items() if key != "APPDATA"}
    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(pathlib.Path, "home", return_value=tmp_path),
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_current_stack() -> Iterator[None]:
    yield
    stack_registry._CURRENT_STACK.set(None)


def test_stacks_path_lives_next_to_the_schedule_registry(tmp_path: pathlib.Path) -> None:
    with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
        assert stack_registry.stacks_path() == registry_dir() / "stacks.json"
        assert stack_registry.stacks_path() == tmp_path / "compman" / "stacks.json"


@pytest.mark.parametrize("appdata", [None, ""])
def test_stacks_path_falls_back_to_home_config_without_usable_appdata(
    appdata: str | None,
) -> None:
    env = {} if appdata is None else {"APPDATA": appdata}
    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(pathlib.Path, "home", return_value=pathlib.Path("/home/u")),
    ):
        assert stack_registry.stacks_path() == (
            pathlib.Path("/home/u/.config/compman/stacks.json")
        )


def test_missing_file_loads_as_empty(tmp_path: pathlib.Path) -> None:
    with isolated_home(tmp_path):
        assert stack_registry.entries() == {}


def test_record_and_resolve_roundtrip_sanitizes_names(
    tmp_path: pathlib.Path,
) -> None:
    project = tmp_path / "proj"
    with isolated_home(tmp_path):
        stack_registry.record("My App!", str(project))
        assert stack_registry.entries() == {"my-app": str(project)}
        assert stack_registry.resolve("my-app") == project
        # Lookup keys are sanitized exactly like recorded keys.
        assert stack_registry.resolve("MY-APP") == project


def test_record_overwrites_existing_entry(tmp_path: pathlib.Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    with isolated_home(tmp_path):
        stack_registry.record("app", str(first))
        stack_registry.record("app", str(second))
        assert stack_registry.entries() == {"app": str(second)}
        assert stack_registry.resolve("app") == second


def test_entries_are_sorted_by_name(tmp_path: pathlib.Path) -> None:
    with isolated_home(tmp_path):
        stack_registry.record("beta", "/b")
        stack_registry.record("alpha", "/a")
        assert list(stack_registry.entries()) == ["alpha", "beta"]


def test_resolve_unknown_name_returns_none(tmp_path: pathlib.Path) -> None:
    with isolated_home(tmp_path):
        assert stack_registry.resolve("ghost") is None


def test_remove_drops_entry_and_reports_presence(tmp_path: pathlib.Path) -> None:
    with isolated_home(tmp_path):
        stack_registry.record("app", str(tmp_path))
        assert stack_registry.remove("app") is True
        assert stack_registry.remove("app") is False
        assert stack_registry.entries() == {}
    stored = json.loads(
        (tmp_path / ".config" / "compman" / "stacks.json").read_text(encoding="utf-8")
    )
    assert stored == {"version": 1, "stacks": {}}


@pytest.mark.parametrize("payload", ['{"version": 1}', '{"stacks": "nope"}', '"str"'])
def test_corrupt_envelope_is_quarantined_and_starts_empty(
    tmp_path: pathlib.Path, payload: str, capsys: Any
) -> None:
    with isolated_home(tmp_path):
        path = tmp_path / ".config" / "compman" / "stacks.json"
        path.parent.mkdir(parents=True)
        path.write_text(payload, encoding="utf-8")
        assert stack_registry.entries() == {}
        assert not path.exists()
        assert path.with_name("stacks.json.bak").is_file()
    assert "Corrupt stack registry" in capsys.readouterr().err


def test_invalid_json_is_quarantined(tmp_path: pathlib.Path, capsys: Any) -> None:
    with isolated_home(tmp_path):
        path = tmp_path / ".config" / "compman" / "stacks.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        assert stack_registry.entries() == {}
    assert not (tmp_path / ".config" / "compman" / "stacks.json").exists()
    assert (tmp_path / ".config" / "compman" / "stacks.json.bak").is_file()
    assert "Corrupt stack registry" in capsys.readouterr().err


def test_non_string_values_are_treated_as_absent(tmp_path: pathlib.Path) -> None:
    with isolated_home(tmp_path):
        path = tmp_path / ".config" / "compman" / "stacks.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            '{"version": 1, "stacks": {"keep": "/k", "drop": 5}}',
            encoding="utf-8",
        )
        assert stack_registry.entries() == {"keep": "/k"}
    assert not list(path.parent.glob("*.bak"))


def test_save_failure_removes_the_staged_tmp_file(tmp_path: pathlib.Path) -> None:
    with isolated_home(tmp_path):
        target = stack_registry.stacks_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with patch(
            "compman.stack_registry.os.replace", side_effect=OSError("disk full")
        ):
            with pytest.raises(OSError, match="disk full"):
                stack_registry.record("app", "/a")
    assert not list(target.parent.glob("*.tmp"))


def test_each_write_stages_under_a_unique_tmp_name(tmp_path: pathlib.Path) -> None:
    staged: list[pathlib.Path] = []
    with (
        isolated_home(tmp_path),
        patch(
            "compman.stack_registry.os.replace",
            side_effect=lambda src, dst: staged.append(pathlib.Path(src)),
        ),
    ):
        stack_registry.record("app", "/a")
        stack_registry.record("app", "/b")
    names = [path.name for path in staged]
    assert len(set(names)) == 2
    assert all(name.startswith("stacks.json.") for name in names)
    assert all(name.endswith(".tmp") for name in names)
    assert all(str(os.getpid()) in name for name in names)


def test_current_stack_contextvar_roundtrip() -> None:
    assert stack_registry.current_stack() is None
    stack_registry.set_current_stack("app")
    assert stack_registry.current_stack() == "app"
