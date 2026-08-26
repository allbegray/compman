from __future__ import annotations

import json
import os
import pathlib
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest

from compman.config import Config
from compman.errors import CommandError
from compman.ops import schedule as schedule_ops
from compman.scheduling import (
    CrontabAdapter,
    JobRecord,
    LaunchdAdapter,
    SchtasksAdapter,
    SystemdAdapter,
    load_registry,
)


@pytest.fixture(autouse=True)
def _strip_appdata(monkeypatch):
    """Windows runners set APPDATA; registry_dir() must not escape tmp homes."""

    monkeypatch.delenv("APPDATA", raising=False)


@dataclass
class FakeProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class FakeAdapter:
    def __init__(self, exists: bool = True, install_error: Exception | None = None) -> None:
        self.exists_result = exists
        self.install_error = install_error
        self.installed: list[JobRecord] = []
        self.removed: list[str] = []

    def install(self, record: JobRecord, runner: Any = None) -> None:
        if self.install_error is not None:
            raise self.install_error
        self.installed.append(record)

    def remove(self, name: str, runner: Any = None) -> None:
        self.removed.append(name)

    def exists(self, name: str, runner: Any = None) -> bool:
        return self.exists_result


def make_config(tmp_path: pathlib.Path) -> Config:
    return Config(name="app", root_dir=tmp_path)


def seed_registry(tmp_path: pathlib.Path, jobs: dict[str, Any]) -> None:
    target = tmp_path / ".config" / "compman" / "schedules.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"version": 1, "jobs": jobs}), encoding="utf-8")


def patch_adapters(
    exists: bool = True, install_error: Exception | None = None
) -> tuple[Any, FakeAdapter]:
    adapter = FakeAdapter(exists=exists, install_error=install_error)
    return (
        patch(schedule_ops.__name__ + "._adapter_for", return_value=adapter),
        adapter,
    )


@contextmanager
def isolated_home(tmp_path: pathlib.Path) -> Generator[None, None, None]:
    """Pin Path.home and clear APPDATA so registry paths resolve under tmp_path."""
    env = {key: value for key, value in os.environ.items() if key != "APPDATA"}
    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(pathlib.Path, "home", return_value=tmp_path),
    ):
        yield


# ---------------------------------------------------------------------------
# adapter mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform_name", "adapter_type"),
    [
        ("launchd", LaunchdAdapter),
        ("systemd", SystemdAdapter),
        ("cron", CrontabAdapter),
        ("schtasks", SchtasksAdapter),
    ],
)
def test_adapter_for_maps_platform_to_adapter(platform_name: str, adapter_type: type) -> None:
    assert isinstance(schedule_ops._adapter_for(platform_name), adapter_type)


# ---------------------------------------------------------------------------
# add_schedule
# ---------------------------------------------------------------------------


def test_add_schedule_registers_launchd_job_and_writes_registry(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    adapter_patch, adapter = patch_adapters()
    with (
        isolated_home(tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Darwin"),
        patch("compman.ops.schedule.resolve_executable", return_value="/opt/compman/bin/compman"),
        adapter_patch,
    ):
        record = schedule_ops.add_schedule(make_config(tmp_path), daily="04:30", no_stop=True)

    assert record.name == "app-volume"
    assert record.platform == "launchd"
    assert record.kind == "daily"
    assert record.time == "04:30"
    assert record.workdir == str(tmp_path)
    assert record.config_path == str(tmp_path / "compman.yml")
    assert record.log_path == str(tmp_path / ".config" / "compman" / "schedule.log")
    assert record.created.endswith("+00:00")
    assert record.args == [
        "/opt/compman/bin/compman",
        "volume",
        "backup",
        "-c",
        str(tmp_path / "compman.yml"),
        "--no-stop",
    ]
    assert adapter.installed == [record]
    with isolated_home(tmp_path):
        stored = load_registry()["jobs"]["app-volume"]
    assert stored["platform"] == "launchd"
    assert stored["args"] == record.args
    assert "registered (launchd)" in capsys.readouterr().out


def test_add_schedule_bakes_level_and_profile_flags(tmp_path: pathlib.Path) -> None:
    adapter_patch, adapter = patch_adapters()
    with (
        patch.object(pathlib.Path, "home", return_value=tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Darwin"),
        patch("compman.ops.schedule.resolve_executable", return_value="/exe"),
        adapter_patch,
    ):
        record = schedule_ops.add_schedule(
            make_config(tmp_path), every="6h", level=9, profile="dev"
        )

    assert record.args[-4:] == ["-z", "9", "--profile", "dev"]
    assert adapter.installed[0].minutes == 360


def test_add_schedule_omits_default_level_flag(tmp_path: pathlib.Path) -> None:
    adapter_patch, adapter = patch_adapters()
    with (
        patch.object(pathlib.Path, "home", return_value=tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Darwin"),
        patch("compman.ops.schedule.resolve_executable", return_value="/exe"),
        adapter_patch,
    ):
        record = schedule_ops.add_schedule(make_config(tmp_path), daily="04:30")

    assert "-z" not in record.args
    assert "--no-stop" not in record.args
    assert "--profile" not in record.args


def test_add_schedule_linux_force_systemd_skips_probe(tmp_path: pathlib.Path) -> None:
    adapter_patch, _adapter = patch_adapters()
    with (
        patch.object(pathlib.Path, "home", return_value=tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Linux"),
        patch("compman.ops.schedule.resolve_executable", return_value="/exe"),
        patch("compman.ops.schedule.crontab_status", return_value=(True, "")),
        adapter_patch,
    ):
        record = schedule_ops.add_schedule(
            make_config(tmp_path), daily="04:30", scheduler="systemd"
        )
    assert record.platform == "systemd"


def test_add_schedule_linux_probes_systemd_session(tmp_path: pathlib.Path) -> None:
    adapter_patch, _adapter = patch_adapters()
    with (
        patch.object(pathlib.Path, "home", return_value=tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Linux"),
        patch("compman.ops.schedule.resolve_executable", return_value="/exe"),
        patch("compman.scheduling.pick.subprocess.run", return_value=FakeProc(returncode=0)),
        adapter_patch,
    ):
        record = schedule_ops.add_schedule(make_config(tmp_path), daily="04:30")
    assert record.platform == "systemd"


def test_add_schedule_cron_fallback_when_no_systemd_session(tmp_path: pathlib.Path) -> None:
    adapter_patch, _adapter = patch_adapters()
    with (
        patch.object(pathlib.Path, "home", return_value=tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Linux"),
        patch("compman.ops.schedule.resolve_executable", return_value="/exe"),
        patch("compman.scheduling.pick.subprocess.run", return_value=FakeProc(returncode=1)),
        patch("compman.ops.schedule.crontab_status", return_value=(True, "")),
        adapter_patch,
    ):
        record = schedule_ops.add_schedule(make_config(tmp_path), every="30m")
    assert record.platform == "cron"


def test_add_schedule_rejects_non_divisible_interval_for_cron(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    adapter_patch, adapter = patch_adapters()
    with (
        isolated_home(tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Linux"),
        patch("compman.scheduling.pick.subprocess.run", return_value=FakeProc(returncode=1)),
        patch("compman.ops.schedule.crontab_status", return_value=(True, "")),
        adapter_patch,
    ):
        with pytest.raises(CommandError, match=r"--every 45m.*cannot be expressed in cron"):
            schedule_ops.add_schedule(make_config(tmp_path), every="45m")
    assert adapter.installed == []
    assert load_registry()["jobs"] == {}
    assert capsys.readouterr().out == ""


def test_add_schedule_rejects_unavailable_crontab(tmp_path: pathlib.Path) -> None:
    adapter_patch, adapter = patch_adapters()
    with (
        patch.object(pathlib.Path, "home", return_value=tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Linux"),
        patch("compman.ops.schedule.resolve_executable", return_value="/exe"),
        patch("compman.scheduling.pick.subprocess.run", return_value=FakeProc(returncode=1)),
        patch(
            "compman.ops.schedule.crontab_status",
            return_value=(False, "/bin/crontab: not found"),
        ),
        adapter_patch,
    ):
        with pytest.raises(CommandError, match="writable crontab.*not found"):
            schedule_ops.add_schedule(make_config(tmp_path), daily="04:30")
    assert adapter.installed == []


def test_add_schedule_does_not_persist_job_when_install_fails(
    tmp_path: pathlib.Path,
) -> None:
    adapter_patch, adapter = patch_adapters(install_error=CommandError("register blew up"))
    with (
        isolated_home(tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Darwin"),
        patch("compman.ops.schedule.resolve_executable", return_value="/exe"),
        adapter_patch,
    ):
        with pytest.raises(CommandError, match="register blew up"):
            schedule_ops.add_schedule(make_config(tmp_path), daily="04:30")
        assert load_registry()["jobs"] == {}
    assert adapter.installed == []


def test_add_schedule_rejects_duplicate_name(tmp_path: pathlib.Path) -> None:
    seed_registry(tmp_path, {"app-volume": {"config_path": "/other/compman.yml"}})
    adapter_patch, adapter = patch_adapters()
    with (
        isolated_home(tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Darwin"),
        patch("compman.ops.schedule.resolve_executable", return_value="/exe"),
        adapter_patch,
    ):
        with pytest.raises(CommandError, match="already registered.*other.compman.yml"):
            schedule_ops.add_schedule(make_config(tmp_path), daily="04:30")
    assert adapter.installed == []


def test_add_schedule_sanitizes_name_override(tmp_path: pathlib.Path) -> None:
    adapter_patch, _adapter = patch_adapters()
    with (
        patch.object(pathlib.Path, "home", return_value=tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Darwin"),
        patch("compman.ops.schedule.resolve_executable", return_value="/exe"),
        adapter_patch,
    ):
        record = schedule_ops.add_schedule(
            make_config(tmp_path), daily="04:30", name="My Stack!!"
        )
    assert record.name == "my-stack"


def test_add_schedule_holds_registry_lock_across_load_and_save(
    tmp_path: pathlib.Path,
) -> None:
    events: list[str] = []

    @contextmanager
    def fake_lock() -> Generator[None, None, None]:
        events.append("lock")
        try:
            yield
        finally:
            events.append("unlock")

    def fake_save(registry: dict[str, Any]) -> None:
        events.append("save")

    adapter_patch, _adapter = patch_adapters()
    with (
        isolated_home(tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Darwin"),
        patch("compman.ops.schedule.resolve_executable", return_value="/exe"),
        patch(schedule_ops.__name__ + ".registry_lock", fake_lock),
        patch(schedule_ops.__name__ + ".save_registry", fake_save),
        adapter_patch,
    ):
        schedule_ops.add_schedule(make_config(tmp_path), daily="04:30")
    assert events == ["lock", "save", "unlock"]


def test_remove_schedule_holds_registry_lock_across_load_and_save(
    tmp_path: pathlib.Path,
) -> None:
    events: list[str] = []

    @contextmanager
    def fake_lock() -> Generator[None, None, None]:
        events.append("lock")
        try:
            yield
        finally:
            events.append("unlock")

    def fake_save(registry: dict[str, Any]) -> None:
        events.append("save")

    seed_registry(tmp_path, {"app.volume": {"platform": "launchd", "kind": "daily"}})
    adapter_patch, adapter = patch_adapters()
    with (
        isolated_home(tmp_path),
        patch(schedule_ops.__name__ + ".registry_lock", fake_lock),
        patch(schedule_ops.__name__ + ".save_registry", fake_save),
        adapter_patch,
    ):
        schedule_ops.remove_schedule("app.volume")
    assert events == ["lock", "save", "unlock"]
    assert adapter.removed == ["app.volume"]


def test_add_schedule_derives_log_and_registry_under_appdata_when_set(
    tmp_path: pathlib.Path,
) -> None:
    appdata = tmp_path / "roaming"
    adapter_patch, _adapter = patch_adapters()
    with (
        patch.dict(os.environ, {"APPDATA": str(appdata)}),
        patch.object(pathlib.Path, "home", return_value=tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Darwin"),
        patch("compman.ops.schedule.resolve_executable", return_value="/exe"),
        adapter_patch,
    ):
        record = schedule_ops.add_schedule(make_config(tmp_path), daily="04:30")
        stored = load_registry()["jobs"]["app-volume"]
    assert record.log_path == str(appdata / "compman" / "schedule.log")
    assert stored["log_path"] == str(appdata / "compman" / "schedule.log")


def test_add_schedule_rejects_conflicting_cadence_options(tmp_path: pathlib.Path) -> None:
    with pytest.raises(CommandError, match="exactly one of --every"):
        schedule_ops.add_schedule(make_config(tmp_path), every="30m", daily="04:30")


def test_add_schedule_rejects_none_cadence_option(tmp_path: pathlib.Path) -> None:
    with pytest.raises(CommandError, match="exactly one of --every"):
        schedule_ops.add_schedule(make_config(tmp_path))


def test_add_schedule_wraps_invalid_cadence(tmp_path: pathlib.Path) -> None:
    with pytest.raises(CommandError, match="Invalid cadence '25:00'.*between 00:00 and 23:59"):
        schedule_ops.add_schedule(make_config(tmp_path), daily="25:00")


def test_add_schedule_wraps_unresolvable_executable(tmp_path: pathlib.Path) -> None:
    with (
        patch.object(pathlib.Path, "home", return_value=tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Darwin"),
        patch(
            "compman.ops.schedule.resolve_executable",
            side_effect=ValueError("Could not resolve"),
        ),
        pytest.raises(CommandError, match="uv tool install"),
    ):
        schedule_ops.add_schedule(make_config(tmp_path), daily="04:30")


def test_add_schedule_rejects_unsupported_platform(tmp_path: pathlib.Path) -> None:
    with (
        patch.object(pathlib.Path, "home", return_value=tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="FreeBSD"),
        patch("compman.ops.schedule.resolve_executable", return_value="/exe"),
        pytest.raises(CommandError, match="not supported on freebsd"),
    ):
        schedule_ops.add_schedule(make_config(tmp_path), daily="04:30")


def test_add_schedule_rejects_scheduler_force_off_linux(tmp_path: pathlib.Path) -> None:
    with (
        patch.object(pathlib.Path, "home", return_value=tmp_path),
        patch("compman.ops.schedule.platform.system", return_value="Darwin"),
        pytest.raises(CommandError, match="--scheduler can only be forced on Linux"),
    ):
        schedule_ops.add_schedule(make_config(tmp_path), daily="04:30", scheduler="cron")


# ---------------------------------------------------------------------------
# list_schedules
# ---------------------------------------------------------------------------


def test_list_schedules_prints_empty_notice(tmp_path: pathlib.Path, capsys: Any) -> None:
    with isolated_home(tmp_path):
        schedule_ops.list_schedules()
    assert "No backup schedules registered." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("job", "fragment"),
    [
        ({"platform": "launchd", "kind": "daily", "time": "04:30"}, "daily at 04:30"),
        ({"platform": "cron", "kind": "interval", "minutes": 45}, "every 45m"),
        ({"platform": "schtasks", "kind": "interval", "minutes": 120}, "every 2h"),
        ({"platform": "systemd", "kind": "weekly", "weekday": 0, "time": "03:00"}, "weekly on Sun at 03:00"),
    ],
)
def test_list_schedules_renders_cadence_summaries(
    tmp_path: pathlib.Path, capsys: Any, job: dict[str, Any], fragment: str
) -> None:
    seed_registry(tmp_path, {"job.one": {**job, "config_path": "/cfg.yml"}})
    adapter_patch, _adapter = patch_adapters(exists=True)
    with isolated_home(tmp_path), adapter_patch:
        schedule_ops.list_schedules()
    out = capsys.readouterr().out
    assert "Registered backup schedules:" in out
    line = next(line for line in out.splitlines() if "job.one" in line)
    assert fragment in line
    assert "/cfg.yml" in line
    assert "[missing]" not in line


def test_list_schedules_marks_missing_artifacts(tmp_path: pathlib.Path, capsys: Any) -> None:
    seed_registry(
        tmp_path,
        {
            "present.job": {
                "platform": "launchd",
                "kind": "daily",
                "time": "04:30",
                "config_path": "/a.yml",
            },
            "gone.job": {
                "platform": "schtasks",
                "kind": "interval",
                "minutes": 30,
                "config_path": "/b.yml",
            },
        },
    )

    adapters = {
        "launchd": FakeAdapter(exists=True),
        "schtasks": FakeAdapter(exists=False),
    }
    with (
        isolated_home(tmp_path),
        patch(schedule_ops.__name__ + "._adapter_for", side_effect=lambda p: adapters[p]),
    ):
        schedule_ops.list_schedules()
    out = capsys.readouterr().out
    present_line = next(line for line in out.splitlines() if "present.job" in line)
    gone_line = next(line for line in out.splitlines() if "gone.job" in line)
    assert "[missing]" not in present_line
    assert "[missing]" in gone_line


# ---------------------------------------------------------------------------
# remove_schedule
# ---------------------------------------------------------------------------


def test_remove_schedule_fails_when_name_unknown(tmp_path: pathlib.Path) -> None:
    with isolated_home(tmp_path):
        with pytest.raises(CommandError, match="No schedule named 'ghost'"):
            schedule_ops.remove_schedule("ghost")


def test_remove_schedule_removes_present_artifact(tmp_path: pathlib.Path, capsys: Any) -> None:
    seed_registry(
        tmp_path,
        {"app.volume": {"platform": "launchd", "kind": "daily", "config_path": "/a.yml"}},
    )
    adapter_patch, adapter = patch_adapters(exists=True)
    with isolated_home(tmp_path), adapter_patch:
        schedule_ops.remove_schedule("app.volume")
    assert adapter.removed == ["app.volume"]
    assert load_registry()["jobs"] == {}
    output = capsys.readouterr()
    assert "already missing" not in output.out
    assert "removed" in output.out


def test_remove_schedule_warns_when_artifact_already_gone(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    seed_registry(
        tmp_path,
        {"app.volume": {"platform": "launchd", "kind": "daily", "config_path": "/a.yml"}},
    )
    adapter_patch, adapter = patch_adapters(exists=False)
    with isolated_home(tmp_path), adapter_patch:
        schedule_ops.remove_schedule("app.volume")
        output = capsys.readouterr()
        assert "already missing" in output.out
        assert "removed" in output.out
        assert adapter.removed == ["app.volume"]
        assert load_registry()["jobs"] == {}


def test_list_schedules_json_payload(tmp_path: pathlib.Path, capsys: Any) -> None:
    seed_registry(
        tmp_path,
        {
            "app.volume": {
                "platform": "launchd",
                "kind": "daily",
                "minutes": None,
                "time": "04:30",
                "weekday": None,
                "config_path": "/a.yml",
            }
        },
    )
    adapter_patch, adapter = patch_adapters(exists=False)
    with isolated_home(tmp_path), adapter_patch:
        schedule_ops.list_schedules(json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["generated_at"].endswith("+00:00")
    job = payload["jobs"][0]
    assert job["name"] == "app.volume" and job["missing"] is True
