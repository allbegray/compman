from __future__ import annotations

import json
import os
import pathlib
import subprocess
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
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
        "schedule",
        "_exec",
        "app-volume",
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


# ---------------------------------------------------------------------------
# monthly cadence end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("system", "force", "probe_rc", "expected_platform"),
    [
        ("Darwin", None, None, "launchd"),
        ("Linux", "systemd", None, "systemd"),
        ("Linux", "cron", None, "cron"),
        ("Win32", None, None, "schtasks"),
    ],
)
def test_add_schedule_bakes_monthly_job_per_adapter(
    tmp_path: pathlib.Path,
    system: str,
    force: str | None,
    probe_rc: int | None,
    expected_platform: str,
) -> None:
    adapter_patch, adapter = patch_adapters()
    patches: list[Any] = [
        patch.object(pathlib.Path, "home", return_value=tmp_path),
        patch("compman.ops.schedule.platform.system", return_value=system),
        patch("compman.ops.schedule.resolve_executable", return_value="/exe"),
        adapter_patch,
    ]
    if probe_rc is not None:
        patches.append(
            patch(
                "compman.scheduling.pick.subprocess.run",
                return_value=FakeProc(returncode=probe_rc),
            )
        )
    if system == "Linux":
        patches.append(
            patch("compman.ops.schedule.crontab_status", return_value=(True, ""))
        )
    with ExitStack() as stack:
        for entry in patches:
            stack.enter_context(entry)
        record = schedule_ops.add_schedule(
            make_config(tmp_path), monthly="15 03:00", scheduler=force
        )

    assert record.platform == expected_platform
    assert record.kind == "monthly"
    assert record.day == 15
    assert record.time == "03:00"
    assert record.weekday is None
    assert record.cadence().day == 15
    assert record.args == [
        "/exe",
        "schedule",
        "_exec",
        "app-volume",
        "volume",
        "backup",
        "-c",
        str(tmp_path / "compman.yml"),
    ]
    assert adapter.installed == [record]


def test_add_schedule_propagates_invalid_month_day_verbatim(tmp_path: pathlib.Path) -> None:
    with pytest.raises(CommandError, match=r"Invalid day for --monthly: '32'"):
        schedule_ops.add_schedule(make_config(tmp_path), monthly="32 03:00")


def test_add_schedule_rejects_monthly_combined_with_other_cadence(
    tmp_path: pathlib.Path,
) -> None:
    with pytest.raises(CommandError, match="--daily.*--monthly|--monthly.*--daily"):
        schedule_ops.add_schedule(
            make_config(tmp_path), daily="04:30", monthly="15 03:00"
        )


def test_runs_path_lives_under_the_registry_dir(tmp_path: pathlib.Path) -> None:
    with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
        assert schedule_ops.runs_path("job.one") == (
            tmp_path / "compman" / "runs" / "job.one.jsonl"
        )


def test_list_schedules_summarizes_monthly_cadence(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    seed_registry(
        tmp_path,
        {
            "job.one": {
                "platform": "launchd",
                "kind": "monthly",
                "day": 1,
                "time": "05:00",
                "config_path": "/cfg.yml",
            }
        },
    )
    adapter_patch, _adapter = patch_adapters(exists=True)
    with isolated_home(tmp_path), adapter_patch:
        schedule_ops.list_schedules()
    line = next(line for line in capsys.readouterr().out.splitlines() if "job.one" in line)
    assert "monthly on day 1 at 05:00" in line


# ---------------------------------------------------------------------------
# run_tracked_job
# ---------------------------------------------------------------------------


def _run_lines(tmp_path: pathlib.Path, name: str) -> list[dict[str, Any]]:
    path = tmp_path / ".config" / "compman" / "runs" / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_run_tracked_job_records_start_and_finish_then_exits_with_child_rc(
    tmp_path: pathlib.Path,
) -> None:
    completed = subprocess.CompletedProcess(["cmd"], 0)
    with (
        isolated_home(tmp_path),
        patch(
            "compman.ops.schedule.subprocess.run", return_value=completed
        ) as run_mock,
        pytest.raises(SystemExit) as exit_info,
    ):
        schedule_ops.run_tracked_job("app.volume", ["/bin/echo", "hi"])
    assert exit_info.value.code == 0
    run_mock.assert_called_once_with(["/bin/echo", "hi"], check=False)
    lines = _run_lines(tmp_path, "app.volume")
    assert list(lines[0]) == ["started_at"]
    assert lines[0]["started_at"].endswith("+00:00")
    assert lines[1]["exit_code"] == 0
    assert lines[1]["finished_at"].endswith("+00:00")
    assert isinstance(lines[1]["seconds"], float)


def test_run_tracked_job_records_failing_exit_code(tmp_path: pathlib.Path) -> None:
    completed = subprocess.CompletedProcess(["cmd"], 3)
    with (
        isolated_home(tmp_path),
        patch("compman.ops.schedule.subprocess.run", return_value=completed),
        pytest.raises(SystemExit) as exit_info,
    ):
        schedule_ops.run_tracked_job("app.volume", ["false"])
    assert exit_info.value.code == 3
    lines = _run_lines(tmp_path, "app.volume")
    assert lines[1]["exit_code"] == 3


def test_run_tracked_job_records_130_on_keyboard_interrupt(
    tmp_path: pathlib.Path,
) -> None:
    with (
        isolated_home(tmp_path),
        patch(
            "compman.ops.schedule.subprocess.run",
            side_effect=KeyboardInterrupt,
        ),
        pytest.raises(SystemExit),
    ):
        schedule_ops.run_tracked_job("app.volume", ["synthetic", "payload"])


def test_run_tracked_job_honors_injected_runner(tmp_path: pathlib.Path) -> None:
    calls: list[list[str]] = []

    def fake_runner(command: list[str], check: bool) -> FakeProc:
        calls.append(command)
        return FakeProc(returncode=9)

    with isolated_home(tmp_path), pytest.raises(SystemExit) as exit_info:
        schedule_ops.run_tracked_job("app.volume", ["cmd"], runner=fake_runner)
    assert exit_info.value.code == 9
    assert calls == [["cmd"]]
    lines = _run_lines(tmp_path, "app.volume")
    assert lines[1]["exit_code"] == 9



# ---------------------------------------------------------------------------
# show_status
# ---------------------------------------------------------------------------


def seed_runs(tmp_path: pathlib.Path, name: str, text: str) -> None:
    target = tmp_path / ".config" / "compman" / "runs" / f"{name}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


STATUS_JOB = {"platform": "launchd", "kind": "daily", "time": "04:30"}


def test_show_status_unknown_name_raises_not_found(tmp_path: pathlib.Path) -> None:
    with isolated_home(tmp_path):
        with pytest.raises(CommandError, match="No schedule named 'ghost'"):
            schedule_ops.show_status("ghost")


@pytest.mark.parametrize(
    ("exists_result", "fragment"),
    [(True, "registered"), (False, "MISSING")],
)
def test_show_status_reports_live_platform_state(
    tmp_path: pathlib.Path, capsys: Any, exists_result: bool, fragment: str
) -> None:
    seed_registry(tmp_path, {"app.volume": {**STATUS_JOB, "config_path": "/a.yml"}})
    adapter_patch, _adapter = patch_adapters(exists=exists_result)
    with isolated_home(tmp_path), adapter_patch:
        schedule_ops.show_status("app.volume")
    assert f"Platform entry: {fragment}" in capsys.readouterr().out


def test_show_status_without_runs_file_hints_migration(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    seed_registry(tmp_path, {"app.volume": {**STATUS_JOB, "config_path": "/a.yml"}})
    adapter_patch, _adapter = patch_adapters(exists=True)
    with isolated_home(tmp_path), adapter_patch:
        schedule_ops.show_status("app.volume")
    out = capsys.readouterr().out
    assert "Platform entry: registered" in out
    assert "No recorded runs yet." in out
    assert "remove and re-add this job" in out


def test_show_status_prints_last_complete_run(tmp_path: pathlib.Path, capsys: Any) -> None:
    seed_registry(tmp_path, {"app.volume": {**STATUS_JOB, "config_path": "/a.yml"}})
    seed_runs(
        tmp_path,
        "app.volume",
        '{"started_at": "2026-08-25T04:30:00+00:00"}\n'
        '{"finished_at": "2026-08-25T04:33:10+00:00", "exit_code": 0, "seconds": 190.5}\n',
    )
    adapter_patch, _adapter = patch_adapters(exists=True)
    with isolated_home(tmp_path), adapter_patch:
        schedule_ops.show_status("app.volume")
    out = capsys.readouterr().out
    assert "Last run: 2026-08-25T04:33:10+00:00" in out
    assert "exit 0" in out
    assert "190.5s" in out


def test_show_status_prefers_trailing_started_over_older_completes(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    seed_registry(tmp_path, {"app.volume": {**STATUS_JOB, "config_path": "/a.yml"}})
    seed_runs(
        tmp_path,
        "app.volume",
        '{"started_at": "2026-08-24T04:30:00+00:00"}\n'
        '{"finished_at": "2026-08-24T04:31:00+00:00", "exit_code": 0, "seconds": 60.0}\n'
        '{"started_at": "2026-08-25T04:30:00+00:00"}\n',
    )
    adapter_patch, _adapter = patch_adapters(exists=True)
    with isolated_home(tmp_path), adapter_patch:
        schedule_ops.show_status("app.volume")
    out = capsys.readouterr().out
    assert "Run in progress (started 2026-08-25T04:30:00+00:00)." in out
    assert "Last run:" not in out


def test_show_status_skips_corrupt_lines(tmp_path: pathlib.Path, capsys: Any) -> None:
    seed_registry(tmp_path, {"app.volume": {**STATUS_JOB, "config_path": "/a.yml"}})
    seed_runs(
        tmp_path,
        "app.volume",
        "{not json\n"
        "\n"
        '["not", "a", "dict"]\n'
        '{"started_at": "2026-08-25T09:00:00+00:00"}\n'
        '{"finished_at": "2026-08-25T09:01:00+00:00", "exit_code": 2, "seconds": 60.0}\n'
        "garbage\n",
    )
    adapter_patch, _adapter = patch_adapters(exists=True)
    with isolated_home(tmp_path), adapter_patch:
        schedule_ops.show_status("app.volume")
    out = capsys.readouterr().out
    assert "Last run: 2026-08-25T09:01:00+00:00" in out
    assert "exit 2" in out


def test_show_status_treats_empty_file_as_no_runs(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    seed_registry(tmp_path, {"app.volume": {**STATUS_JOB, "config_path": "/a.yml"}})
    seed_runs(tmp_path, "app.volume", "")
    adapter_patch, _adapter = patch_adapters(exists=True)
    with isolated_home(tmp_path), adapter_patch:
        schedule_ops.show_status("app.volume")
    out = capsys.readouterr().out
    assert "No recorded runs yet." in out
    assert "remove and re-add this job" in out


def test_show_status_treats_unparsable_file_as_no_runs(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    seed_registry(tmp_path, {"app.volume": {**STATUS_JOB, "config_path": "/a.yml"}})
    seed_runs(tmp_path, "app.volume", "{broken\n{also broken\n")
    adapter_patch, _adapter = patch_adapters(exists=True)
    with isolated_home(tmp_path), adapter_patch:
        schedule_ops.show_status("app.volume")
    out = capsys.readouterr().out
    assert "No recorded runs yet." in out
    assert "remove and re-add this job" in out


def test_show_status_treats_keyless_records_as_no_runs(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    seed_registry(tmp_path, {"app.volume": {**STATUS_JOB, "config_path": "/a.yml"}})
    seed_runs(tmp_path, "app.volume", '{"junk": true}\n{}\n')
    adapter_patch, _adapter = patch_adapters(exists=True)
    with isolated_home(tmp_path), adapter_patch:
        schedule_ops.show_status("app.volume")
    out = capsys.readouterr().out
    assert "No recorded runs yet." in out
    assert "remove and re-add this job" in out
