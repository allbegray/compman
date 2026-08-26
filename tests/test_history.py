from __future__ import annotations

import json
import os
import pathlib
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from compman import history
from compman.scheduling.registry import registry_dir


@contextmanager
def isolated_home(tmp_path: pathlib.Path) -> Iterator[pathlib.Path]:
    """Pin Path.home and clear APPDATA so the journal resolves under tmp_path."""
    env = {key: value for key, value in os.environ.items() if key != "APPDATA"}
    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(pathlib.Path, "home", return_value=tmp_path),
    ):
        yield tmp_path


@contextmanager
def journal_home(tmp_path: pathlib.Path) -> Iterator[pathlib.Path]:
    """Point the journal at ``tmp_path`` via APPDATA (the Windows-style root)."""
    with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
        yield tmp_path


def test_history_path_lives_beside_the_schedule_registry(tmp_path: pathlib.Path) -> None:
    with journal_home(tmp_path):
        assert history.history_path() == registry_dir() / "history.jsonl"
        assert history.history_path() == tmp_path / "compman" / "history.jsonl"


@pytest.mark.parametrize("appdata", [None, ""])
def test_history_path_falls_back_to_home_config_without_usable_appdata(
    tmp_path: pathlib.Path, appdata: str | None
) -> None:
    env = {key: value for key, value in os.environ.items() if key != "APPDATA"}
    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(pathlib.Path, "home", return_value=tmp_path),
    ):
        if appdata is not None:
            os.environ["APPDATA"] = appdata
        assert history.history_path() == tmp_path / ".config" / "compman" / "history.jsonl"


def test_append_creates_parent_directories_and_roundtrips_fields(
    tmp_path: pathlib.Path,
) -> None:
    with isolated_home(tmp_path):
        assert history.append("deploy", stack="app", source="s3://b/k", built=True)
        assert history.append("backup", kind="volume", stack="app", archive="a.tar.gz")
        stored = json.loads(
            (tmp_path / ".config" / "compman" / "history.jsonl")
            .read_text("utf-8")
            .splitlines()[0]
        )
        assert stored["action"] == "deploy"
        assert stored["stack"] == "app"
        assert stored["source"] == "s3://b/k"
        assert stored["built"] is True
        assert "ts" in stored


def test_entries_are_newest_first(tmp_path: pathlib.Path) -> None:
    with isolated_home(tmp_path):
        for marker in ("first", "second", "third"):
            history.append("deploy", marker=marker)
        assert [entry["marker"] for entry in history.entries()] == [
            "third",
            "second",
            "first",
        ]


def test_entries_limit_keeps_only_the_newest(tmp_path: pathlib.Path) -> None:
    with isolated_home(tmp_path):
        for marker in ("first", "second", "third"):
            history.append("deploy", marker=marker)
        assert [entry["marker"] for entry in history.entries(2)] == ["third", "second"]


def test_entries_of_missing_journal_are_empty(tmp_path: pathlib.Path) -> None:
    with isolated_home(tmp_path):
        assert history.entries() == []


def test_entries_skip_blank_malformed_and_non_object_lines(
    tmp_path: pathlib.Path,
) -> None:
    good = {"ts": "2026-01-01T00:00:00+00:00", "action": "deploy", "stack": "app"}
    other = {"ts": "2026-01-02T00:00:00+00:00", "action": "backup", "kind": "volume"}
    lines = [
        "{",
        json.dumps(good),
        "",
        "   ",
        "not json at all",
        '"a bare string"',
        "[1, 2]",
        json.dumps(other),
    ]
    with isolated_home(tmp_path):
        path = tmp_path / ".config" / "compman" / "history.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert history.entries() == [other, good]


def test_append_failure_raises_oserror(tmp_path: pathlib.Path) -> None:
    with isolated_home(tmp_path):
        (tmp_path / ".config" / "compman").mkdir(parents=True)
        (tmp_path / ".config" / "compman" / "history.jsonl").mkdir()
        with pytest.raises(OSError):
            history.append("deploy", stack="app")


def test_envelope_matches_the_house_json_shape(tmp_path: pathlib.Path) -> None:
    with isolated_home(tmp_path):
        history.append("deploy", stack="app")
        history.append("backup", kind="image")
        payload = history.envelope()
        assert payload["schema_version"] == 1
        assert isinstance(payload["generated_at"], str)
        assert len(payload["entries"]) == 2
        limited = history.envelope(limit=1)
        assert [entry["action"] for entry in limited["entries"]] == ["backup"]


@pytest.fixture(autouse=True)
def _isolate_history_journal():
    """This module asserts real path resolution; skip the global tmp redirect."""
    yield
