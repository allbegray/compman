from __future__ import annotations

import json
import pathlib
import shlex
import sys
import xml.etree.ElementTree as ET
from dataclasses import FrozenInstanceError
from typing import Any
from unittest.mock import patch

import pytest

from compman.scheduling import (
    Cadence,
    CrontabAdapter,
    JobRecord,
    LaunchdAdapter,
    SchtasksAdapter,
    SystemdAdapter,
    build_crontab_block,
    build_plist_xml,
    build_schtasks_command,
    build_systemd_units,
    cron_expr,
    launchd_start_spec,
    load_registry,
    parse_cadence,
    pick_scheduler,
    registry_path,
    resolve_executable,
    save_registry,
    schtasks_cadence_args,
    systemd_oncalendar,
)
from compman.scheduling.cadence import parse_time_value
from compman.scheduling.crontab import begin_marker, end_marker, without_block
from compman.scheduling.launchd import label_for, plist_path
from compman.scheduling.systemd import unit_dir, unit_names


class FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RecordingRunner:
    def __init__(self, results: list[FakeProc] | None = None) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self._results = list(results or [])

    def __call__(self, args: Any, **kwargs: Any) -> FakeProc:
        self.calls.append((list(args), kwargs))
        return self._results.pop(0) if self._results else FakeProc()

    def argv_lists(self) -> list[list[str]]:
        return [args for args, _kwargs in self.calls]


def make_record(**overrides: Any) -> JobRecord:
    values: dict[str, Any] = {
        "name": "app.volume",
        "platform": "darwin",
        "kind": "daily",
        "minutes": None,
        "time": "04:30",
        "weekday": None,
        "workdir": "/work/app",
        "config_path": "/work/app/compman.yml",
        "args": ["/opt/compman", "-c", "/work/app/compman.yml", "volume", "backup", "--no-stop"],
        "log_path": "/work/app/backup/schedule.log",
        "path_env": "/usr/bin:/bin",
        "created": "2026-08-25T10:00:00",
    }
    values.update(overrides)
    return JobRecord(**values)


def plist_entries(text: str) -> dict[str, Any]:
    root = ET.fromstring(text)
    top = root.find("dict")
    assert top is not None
    children = list(top)
    entries: dict[str, Any] = {}
    index = 0
    while index < len(children):
        key = children[index]
        value = children[index + 1]
        if value.tag == "array":
            entries[key.text or ""] = [child.text or "" for child in value]
        elif value.tag == "dict":
            nested: dict[str, str] = {}
            nested_children = list(value)
            nested_index = 0
            while nested_index < len(nested_children):
                nested_key = nested_children[nested_index]
                nested_value = nested_children[nested_index + 1]
                nested[nested_key.text or ""] = nested_value.text or ""
                nested_index += 2
            entries[key.text or ""] = nested
        else:
            entries[key.text or ""] = value.text or ""
        index += 2
    return entries


# ---------------------------------------------------------------------------
# cadence parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("every", "daily", "weekly"),
    [
        (None, None, None),
        ("30m", "04:30", None),
        ("30m", None, "sun 03:00"),
        (None, "04:30", "sun 03:00"),
        ("30m", "04:30", "sun 03:00"),
    ],
)
def test_parse_cadence_rejects_when_not_exactly_one_option(
    every: str | None, daily: str | None, weekly: str | None
) -> None:
    with pytest.raises(ValueError, match="Specify exactly one"):
        parse_cadence(every, daily, weekly)


@pytest.mark.parametrize(
    ("value", "expected_minutes"),
    [("30m", 30), ("6h", 360), ("45m", 45), ("1m", 1), ("24h", 1440)],
)
def test_parse_cadence_parses_every(value: str, expected_minutes: int) -> None:
    assert parse_cadence(value, None, None) == Cadence(kind="interval", minutes=expected_minutes)


@pytest.mark.parametrize("value", ["", "30", "30x", "m", "h", "-5m", "0m", "0h", "1.5h"])
def test_parse_cadence_rejects_invalid_every(value: str) -> None:
    with pytest.raises(ValueError, match="Invalid --every"):
        parse_cadence(value, None, None)


@pytest.mark.parametrize("value", ["04:30", "4:05"])
def test_parse_cadence_parses_daily(value: str) -> None:
    assert parse_cadence(None, value, None) == Cadence(kind="daily", time=value)


@pytest.mark.parametrize("value", ["24:00", "23:60", "4:30pm", "0430", "", "ab:cd"])
def test_parse_cadence_rejects_invalid_daily(value: str) -> None:
    with pytest.raises(ValueError, match="Invalid time"):
        parse_cadence(None, value, None)


@pytest.mark.parametrize(
    ("value", "expected_weekday"),
    [
        ("sun 03:00", 0),
        ("MON 04:00", 1),
        ("Tue 05:00", 2),
        ("WED 06:00", 3),
        ("thu 07:00", 4),
        ("Fri 08:00", 5),
        ("sat 09:00", 6),
    ],
)
def test_parse_cadence_parses_weekly_day_names_case_insensitive(
    value: str, expected_weekday: int
) -> None:
    cadence = parse_cadence(None, None, value)
    assert cadence.kind == "weekly"
    assert cadence.weekday == expected_weekday


@pytest.mark.parametrize(
    "value", ["mon", "funday 03:00", "mon 03:00 extra", ""]
)
def test_parse_cadence_rejects_invalid_weekly(value: str) -> None:
    with pytest.raises(ValueError, match="Invalid --weekly"):
        parse_cadence(None, None, value)


@pytest.mark.parametrize("value", ["mon 24:00", "mon 4:30pm"])
def test_parse_cadence_rejects_weekly_with_invalid_time(value: str) -> None:
    with pytest.raises(ValueError, match="Invalid time"):
        parse_cadence(None, None, value)


def test_parse_time_value_requires_time() -> None:
    with pytest.raises(ValueError, match="required"):
        parse_time_value(None)


def test_parse_time_value_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="between 00:00 and 23:59"):
        parse_time_value("99:99")


def test_cadence_is_frozen() -> None:
    cadence = parse_cadence("30m", None, None)
    with pytest.raises(FrozenInstanceError):
        cadence.minutes = 5


# ---------------------------------------------------------------------------
# formatters
# ---------------------------------------------------------------------------


def test_cron_expr_interval_whole_hours() -> None:
    assert cron_expr(Cadence(kind="interval", minutes=120)) == "0 */2 * * *"


def test_cron_expr_interval_single_hour() -> None:
    assert cron_expr(Cadence(kind="interval", minutes=60)) == "0 */1 * * *"


def test_cron_expr_interval_minute_divisor() -> None:
    assert cron_expr(Cadence(kind="interval", minutes=30)) == "*/30 * * * *"


def test_cron_expr_interval_not_expressible_raises_with_systemd_hint() -> None:
    with pytest.raises(ValueError, match="cannot be expressed in cron.*systemd"):
        cron_expr(Cadence(kind="interval", minutes=45))


def test_cron_expr_daily() -> None:
    assert cron_expr(parse_cadence(None, "04:30", None)) == "30 4 * * *"


def test_cron_expr_weekly_uses_zero_based_sunday() -> None:
    assert cron_expr(parse_cadence(None, None, "sun 04:30")) == "30 4 * * 0"


def test_cron_expr_interval_requires_minutes() -> None:
    with pytest.raises(ValueError, match="requires a minute count"):
        cron_expr(Cadence(kind="interval"))


def test_cron_expr_weekly_requires_weekday() -> None:
    with pytest.raises(ValueError, match="requires a weekday"):
        cron_expr(Cadence(kind="weekly", time="04:30"))


def test_launchd_start_spec_interval_returns_seconds() -> None:
    assert launchd_start_spec(Cadence(kind="interval", minutes=30)) == 1800


def test_launchd_start_spec_daily_returns_calendar_dict() -> None:
    assert launchd_start_spec(parse_cadence(None, "04:30", None)) == {"Hour": 4, "Minute": 30}


def test_launchd_start_spec_weekly_includes_weekday() -> None:
    spec = launchd_start_spec(parse_cadence(None, None, "sun 04:30"))
    assert spec == {"Hour": 4, "Minute": 30, "Weekday": 0}


def test_systemd_oncalendar_daily() -> None:
    assert systemd_oncalendar(parse_cadence(None, "4:30", None)) == "*-*-* 04:30:00"


def test_systemd_oncalendar_weekly_prefixes_day_name() -> None:
    assert systemd_oncalendar(parse_cadence(None, None, "sun 04:30")) == "Sun *-*-* 04:30:00"


def test_systemd_oncalendar_rejects_interval() -> None:
    with pytest.raises(ValueError, match="OnCalendar"):
        systemd_oncalendar(Cadence(kind="interval", minutes=30))


@pytest.mark.parametrize(
    ("cadence", "expected"),
    [
        (Cadence(kind="interval", minutes=45), ["/SC", "MINUTE", "/MO", "45"]),
        (Cadence(kind="interval", minutes=120), ["/SC", "HOURLY", "/MO", "2"]),
        (Cadence(kind="daily", time="04:30"), ["/SC", "DAILY", "/ST", "04:30"]),
        (
            Cadence(kind="weekly", time="22:15", weekday=6),
            ["/SC", "WEEKLY", "/D", "SAT", "/ST", "22:15"],
        ),
    ],
)
def test_schtasks_cadence_args(cadence: Cadence, expected: list[str]) -> None:
    assert schtasks_cadence_args(cadence) == expected


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_registry_path_posix_uses_home_config_dir() -> None:
    with patch.object(pathlib.Path, "home", return_value=pathlib.Path("/home/u")):
        assert registry_path() == pathlib.Path("/home/u/.config/compman/schedules.json")


def test_load_registry_returns_empty_when_file_missing(tmp_path: pathlib.Path) -> None:
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        assert load_registry() == {"version": 1, "jobs": {}}


def test_registry_roundtrip_preserves_records(tmp_path: pathlib.Path) -> None:
    record = make_record()
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        save_registry({"version": 1, "jobs": {record.name: record}})
        loaded = load_registry()
    assert loaded["version"] == 1
    assert loaded["jobs"][record.name] == record.to_dict()
    assert not list(tmp_path.rglob("*.tmp"))


def test_save_registry_defaults_version_and_keeps_plain_dict_jobs(tmp_path: pathlib.Path) -> None:
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        save_registry({"jobs": {"a": {"kind": "daily"}}})
        stored = json.loads(registry_path().read_text(encoding="utf-8"))
    assert stored["version"] == 1
    assert stored["jobs"] == {"a": {"kind": "daily"}}


def test_load_registry_self_heals_corrupt_json(tmp_path: pathlib.Path, capsys: Any) -> None:
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        path = tmp_path / ".config" / "compman" / "schedules.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        registry = load_registry()
    assert registry == {"version": 1, "jobs": {}}
    assert not path.exists()
    assert path.with_name("schedules.json.bak").is_file()
    assert "Corrupt schedule registry" in capsys.readouterr().err


@pytest.mark.parametrize("payload", ['{"version": 1}', '{"jobs": "nope"}', '"just a string"'])
def test_load_registry_self_heals_malformed_shapes(
    tmp_path: pathlib.Path, payload: str
) -> None:
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        path = tmp_path / ".config" / "compman" / "schedules.json"
        path.parent.mkdir(parents=True)
        path.write_text(payload, encoding="utf-8")
        assert load_registry() == {"version": 1, "jobs": {}}
    assert not path.exists()


def test_load_registry_defaults_non_integer_version(tmp_path: pathlib.Path) -> None:
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        path = tmp_path / ".config" / "compman" / "schedules.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"version": "two", "jobs": {"a": {}}}', encoding="utf-8")
        registry = load_registry()
    assert registry == {"version": 1, "jobs": {"a": {}}}


def test_load_registry_preserves_integer_version(tmp_path: pathlib.Path) -> None:
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        path = tmp_path / ".config" / "compman" / "schedules.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"version": 7, "jobs": {}}', encoding="utf-8")
        assert load_registry()["version"] == 7


def test_save_registry_removes_tmp_file_when_replace_fails(tmp_path: pathlib.Path) -> None:
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        target = registry_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = target.with_name(target.name + ".tmp")
        with patch("compman.scheduling.registry.os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                save_registry({"version": 1, "jobs": {}})
    assert not tmp_file.exists()


def test_job_record_dict_roundtrip_and_cadence_view() -> None:
    record = make_record(kind="weekly", weekday=3)
    restored = JobRecord.from_dict(record.to_dict())
    assert restored == record
    assert restored.cadence() == Cadence(kind="weekly", time="04:30", weekday=3)


def test_job_record_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        make_record().name = "other"


# ---------------------------------------------------------------------------
# resolve_executable
# ---------------------------------------------------------------------------


def test_resolve_executable_prefers_which_hit() -> None:
    assert resolve_executable(which=lambda name: "/usr/local/bin/compman") == "/usr/local/bin/compman"


def test_resolve_executable_accepts_compman_shim_from_argv(tmp_path: pathlib.Path) -> None:
    shim = tmp_path / "compman"
    shim.write_text("#!/bin/sh\n", encoding="utf-8")
    shim.chmod(0o755)
    result = resolve_executable(which=lambda name: None, argv=[str(shim)])
    assert result == str(shim.resolve())


def test_resolve_executable_reads_sys_argv_when_argv_omitted(tmp_path: pathlib.Path) -> None:
    shim = tmp_path / "compman"
    shim.write_text("x", encoding="utf-8")
    shim.chmod(0o755)
    with patch.object(sys, "argv", [str(shim)]):
        assert resolve_executable(which=lambda name: None) == str(shim.resolve())


def test_resolve_executable_rejects_python_module_invocation() -> None:
    with pytest.raises(ValueError, match="uv tool install"):
        resolve_executable(which=lambda name: None, argv=["/usr/bin/python", "-m", "compman"])


@pytest.mark.skipif(sys.platform == 'win32', reason='X_OK check skipped on Windows')
def test_resolve_executable_rejects_missing_shim(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError, match="uv tool install"):
        resolve_executable(which=lambda name: None, argv=[str(tmp_path / "compman")])


@pytest.mark.skipif(sys.platform == 'win32', reason='X_OK check skipped on Windows')
def test_resolve_executable_rejects_non_executable_shim(tmp_path: pathlib.Path) -> None:
    shim = tmp_path / "compman"
    shim.write_text("x", encoding="utf-8")
    shim.chmod(0o644)
    with patch("compman.scheduling.resolve.os.access", return_value=False):
        with pytest.raises(ValueError, match="uv tool install"):
            resolve_executable(which=lambda name: None, argv=[str(shim)])


def test_resolve_executable_skips_existence_check_on_windows(tmp_path: pathlib.Path) -> None:
    missing = tmp_path / "compman.exe"
    with patch("compman.scheduling.resolve.sys.platform", "win32"):
        result = resolve_executable(which=lambda name: None, argv=[str(missing)])
    assert result == str(missing)


def test_resolve_executable_rejects_empty_argv() -> None:
    with pytest.raises(ValueError, match="uv tool install"):
        resolve_executable(which=lambda name: None, argv=[])


# ---------------------------------------------------------------------------
# pick_scheduler
# ---------------------------------------------------------------------------


def test_pick_scheduler_darwin_uses_launchd() -> None:
    assert pick_scheduler("darwin", None) == "launchd"


def test_pick_scheduler_win32_uses_schtasks() -> None:
    assert pick_scheduler("win32", None) == "schtasks"


def test_pick_scheduler_linux_force_systemd_skips_probe() -> None:
    runner = RecordingRunner()
    assert pick_scheduler("linux", "systemd", runner) == "systemd"
    assert runner.calls == []


def test_pick_scheduler_linux_force_cron() -> None:
    assert pick_scheduler("linux", "cron", RecordingRunner()) == "cron"


def test_pick_scheduler_linux_rejects_unknown_force() -> None:
    with pytest.raises(ValueError, match="Unknown scheduler 'kqueue'"):
        pick_scheduler("linux", "kqueue", RecordingRunner())


def test_pick_scheduler_linux_probes_systemd_session_present() -> None:
    runner = RecordingRunner([FakeProc(returncode=0)])
    assert pick_scheduler("linux", None, runner) == "systemd"
    assert runner.argv_lists() == [["systemctl", "--user", "show-environment"]]


def test_pick_scheduler_linux_falls_back_to_cron_without_session() -> None:
    runner = RecordingRunner([FakeProc(returncode=1)])
    assert pick_scheduler("linux", None, runner) == "cron"


def test_pick_scheduler_rejects_unknown_system() -> None:
    with pytest.raises(ValueError, match="not supported on freebsd"):
        pick_scheduler("freebsd", None)


# ---------------------------------------------------------------------------
# launchd adapter
# ---------------------------------------------------------------------------


def test_build_plist_xml_interval_uses_start_interval() -> None:
    record = make_record(kind="interval", minutes=30, time=None)
    entries = plist_entries(build_plist_xml(record))
    assert entries["Label"] == "com.compman.volume.app.volume"
    assert entries["ProgramArguments"] == record.args
    assert entries["StartInterval"] == "1800"
    assert "StartCalendarInterval" not in entries
    assert entries["WorkingDirectory"] == record.workdir
    assert entries["StandardOutPath"] == record.log_path
    assert entries["StandardErrorPath"] == record.log_path


def test_build_plist_xml_daily_omits_weekday() -> None:
    entries = plist_entries(build_plist_xml(make_record()))
    assert entries["StartCalendarInterval"] == {"Hour": "4", "Minute": "30"}


def test_build_plist_xml_weekly_includes_weekday() -> None:
    record = make_record(kind="weekly", weekday=3)
    entries = plist_entries(build_plist_xml(record))
    assert entries["StartCalendarInterval"] == {"Hour": "4", "Minute": "30", "Weekday": "3"}


@pytest.mark.skipif(sys.platform == 'win32', reason='launchd is macOS-only')
def test_launchd_install_writes_plist_and_bootstraps(tmp_path: pathlib.Path) -> None:
    record = make_record()
    runner = RecordingRunner()
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        with patch("compman.scheduling.launchd.os.getuid", return_value=501):
            LaunchdAdapter().install(record, runner)
        plist = plist_path(record.name)
        assert plist.is_file()
        assert ET.fromstring(plist.read_text(encoding="utf-8")).tag == "plist"
    assert runner.argv_lists() == [["launchctl", "bootstrap", "gui/501", str(plist)]]


@pytest.mark.skipif(sys.platform == 'win32', reason='launchd is macOS-only')
def test_launchd_remove_boots_out_then_unlinks(tmp_path: pathlib.Path) -> None:
    runner = RecordingRunner()
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        plist = plist_path("app.volume")
        plist.parent.mkdir(parents=True)
        plist.write_text("x", encoding="utf-8")
        with patch("compman.scheduling.launchd.os.getuid", return_value=501):
            LaunchdAdapter().remove("app.volume", runner)
    assert not plist.exists()
    assert runner.argv_lists() == [
        ["launchctl", "bootout", "gui/501/com.compman.volume.app.volume"]
    ]


@pytest.mark.skipif(sys.platform == 'win32', reason='launchd is macOS-only')
def test_launchd_remove_tolerates_missing_plist(tmp_path: pathlib.Path) -> None:
    runner = RecordingRunner()
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        with patch("compman.scheduling.launchd.os.getuid", return_value=501):
            LaunchdAdapter().remove("app.volume", runner)
    assert runner.argv_lists() == [
        ["launchctl", "bootout", "gui/501/com.compman.volume.app.volume"]
    ]


def test_launchd_exists_reflects_plist_file(tmp_path: pathlib.Path) -> None:
    adapter = LaunchdAdapter()
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        assert adapter.exists("app.volume") is False
        plist_path("app.volume").parent.mkdir(parents=True)
        plist_path("app.volume").write_text("x", encoding="utf-8")
        assert adapter.exists("app.volume") is True


def test_label_for_uses_compman_volume_prefix() -> None:
    assert label_for("web.volume") == "com.compman.volume.web.volume"


# ---------------------------------------------------------------------------
# systemd adapter
# ---------------------------------------------------------------------------


def test_build_systemd_units_daily_uses_oncalendar() -> None:
    service, timer = build_systemd_units(make_record())
    assert "Type=oneshot" in service
    assert "WorkingDirectory=/work/app" in service
    assert f"ExecStart={shlex.join(make_record().args)}" in service
    assert "OnCalendar=*-*-* 04:30:00" in timer
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer


def test_build_systemd_units_weekly_prefixes_day() -> None:
    _service, timer = build_systemd_units(make_record(kind="weekly", weekday=0))
    assert "OnCalendar=Sun *-*-* 04:30:00" in timer


@pytest.mark.parametrize(
    ("minutes", "span"),
    [(30, "30min"), (45, "45min"), (120, "2h"), (60, "1h")],
)
def test_build_systemd_units_interval_uses_boot_and_active_sec(minutes: int, span: str) -> None:
    record = make_record(kind="interval", minutes=minutes, time=None)
    _service, timer = build_systemd_units(record)
    assert "OnBootSec=5min" in timer
    assert f"OnUnitActiveSec={span}" in timer
    assert "OnCalendar" not in timer


def test_systemd_install_writes_units_and_enables_timer(tmp_path: pathlib.Path) -> None:
    record = make_record()
    runner = RecordingRunner()
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        SystemdAdapter().install(record, runner)
        directory = unit_dir()
        service_name, timer_name = unit_names(record.name)
        assert "Type=oneshot" in (directory / service_name).read_text(encoding="utf-8")
        assert "OnCalendar=*-*-* 04:30:00" in (directory / timer_name).read_text(encoding="utf-8")
    assert runner.argv_lists() == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", timer_name],
    ]


def test_systemd_remove_disables_unlinks_and_reloads(tmp_path: pathlib.Path) -> None:
    runner = RecordingRunner()
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        directory = unit_dir()
        directory.mkdir(parents=True)
        service_name, timer_name = unit_names("app.volume")
        (directory / service_name).write_text("x", encoding="utf-8")
        (directory / timer_name).write_text("x", encoding="utf-8")
        SystemdAdapter().remove("app.volume", runner)
    assert not (directory / service_name).exists()
    assert not (directory / timer_name).exists()
    assert runner.argv_lists() == [
        ["systemctl", "--user", "disable", "--now", timer_name],
        ["systemctl", "--user", "daemon-reload"],
    ]


def test_systemd_exists_reflects_timer_unit(tmp_path: pathlib.Path) -> None:
    adapter = SystemdAdapter()
    with patch.object(pathlib.Path, "home", return_value=tmp_path):
        assert adapter.exists("app.volume") is False
        unit_dir().mkdir(parents=True)
        unit_dir().joinpath(unit_names("app.volume")[1]).write_text("x", encoding="utf-8")
        assert adapter.exists("app.volume") is True


# ---------------------------------------------------------------------------
# crontab adapter
# ---------------------------------------------------------------------------


def test_build_crontab_block_daily_exact_format() -> None:
    record = make_record()
    expected = (
        "# BEGIN compman:app.volume\n"
        "PATH=/usr/bin:/bin\n"
        "30 4 * * * /opt/compman -c /work/app/compman.yml volume backup --no-stop"
        " >> /work/app/backup/schedule.log 2>&1\n"
        "# END compman:app.volume\n"
    )
    assert build_crontab_block(record) == expected


def test_build_crontab_block_interval_minute_divisor() -> None:
    record = make_record(kind="interval", minutes=30, time=None)
    block = build_crontab_block(record)
    assert block.splitlines()[2].startswith("*/30 * * * * ")


def test_build_crontab_block_escapes_percent_signs() -> None:
    record = make_record(log_path="/var/log/50%off.log")
    block = build_crontab_block(record)
    assert "/var/log/50\\%off.log" in block
    assert "%off" not in block.replace("\\%", "")


def test_crontab_install_filters_prior_block_and_appends() -> None:
    record = make_record()
    prior = "*/5 * * * * other-job\n"
    stale = f"# BEGIN compman:{record.name}\nSTALE LINE\n# END compman:{record.name}\n"
    runner = RecordingRunner([FakeProc(returncode=0, stdout=prior + stale)])
    CrontabAdapter().install(record, runner)
    assert len(runner.calls) == 2
    read_args, _read_kwargs = runner.calls[0]
    write_args, write_kwargs = runner.calls[1]
    assert read_args == ["crontab", "-l"]
    assert write_args == ["crontab", "-"]
    written = write_kwargs["input"]
    assert written == prior + build_crontab_block(record)


def test_crontab_install_treats_exit_one_as_empty_table() -> None:
    record = make_record()
    runner = RecordingRunner([FakeProc(returncode=1, stdout="")])
    CrontabAdapter().install(record, runner)
    written = runner.calls[1][1]["input"]
    assert written == build_crontab_block(record)


def test_crontab_install_propagates_non_divisible_interval_error() -> None:
    record = make_record(kind="interval", minutes=45, time=None)
    runner = RecordingRunner([FakeProc(returncode=1)])
    with pytest.raises(ValueError, match="cannot be expressed in cron"):
        CrontabAdapter().install(record, runner)
    assert len(runner.calls) == 1


def test_crontab_remove_strips_block_and_keeps_other_lines() -> None:
    other = "0 1 * * * keepme\n"
    record = make_record()
    table = other + build_crontab_block(record)
    runner = RecordingRunner([FakeProc(returncode=0, stdout=table)])
    CrontabAdapter().remove(record.name, runner)
    written = runner.calls[1][1]["input"]
    assert written == other


def test_crontab_remove_writes_empty_table_when_none_existed() -> None:
    runner = RecordingRunner([FakeProc(returncode=1)])
    CrontabAdapter().remove("app.volume", runner)
    assert runner.calls[1][1]["input"] == ""


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [(0, "# BEGIN compman:app.volume\n...\n", True), (0, "nothing here\n", False), (1, "", False)],
)
def test_crontab_exists_maps_markers_and_returncode(
    returncode: int, stdout: str, expected: bool
) -> None:
    runner = RecordingRunner([FakeProc(returncode=returncode, stdout=stdout)])
    assert CrontabAdapter().exists("app.volume", runner) is expected


def test_without_block_variants() -> None:
    content = "a\n# BEGIN compman:x\ninside\n# END compman:x\nb\n"
    assert without_block(content, "x") == "a\nb\n"
    assert without_block("keep\n", "x") == "keep\n"
    assert without_block("# BEGIN compman:x\nonly\n# END compman:x\n", "x") == ""
    assert without_block("", "x") == ""
    assert begin_marker("x") == "# BEGIN compman:x"
    assert end_marker("x") == "# END compman:x"


@pytest.mark.parametrize(
    ("returncode", "stderr", "expected"),
    [(0, "", (True, "")), (1, "", (True, "")), (127, "/bin/sh: crontab: not found", (False, "/bin/sh: crontab: not found"))],
)
def test_crontab_status_maps_return_codes(
    returncode: int, stderr: str, expected: tuple[bool, str]
) -> None:
    runner = RecordingRunner([FakeProc(returncode=returncode, stderr=stderr)])
    from compman.scheduling.crontab import crontab_status

    assert crontab_status(runner) == expected
    assert runner.argv_lists() == [["crontab", "-l"]]


# ---------------------------------------------------------------------------
# schtasks adapter
# ---------------------------------------------------------------------------


def test_build_schtasks_command_daily_payload() -> None:
    record = make_record()
    argv = build_schtasks_command(record)
    assert argv[:9] == ["schtasks", "/Create", "/F", "/TN", "app.volume", "/SC", "DAILY", "/ST", "04:30"]
    assert argv[9] == "/TR"
    assert argv[10] == (
        'cmd.exe /c ""/opt/compman" -c /work/app/compman.yml volume backup --no-stop'
        ' >> "/work/app/backup/schedule.log" 2>&1"'
    )


def test_build_schtasks_command_interval_uses_minute_schedule() -> None:
    record = make_record(kind="interval", minutes=45, time=None)
    argv = build_schtasks_command(record)
    assert argv[5:9] == ["/SC", "MINUTE", "/MO", "45"]


def test_build_schtasks_command_hourly_interval_uses_hourly_schedule() -> None:
    record = make_record(kind="interval", minutes=120, time=None)
    argv = build_schtasks_command(record)
    assert argv[5:9] == ["/SC", "HOURLY", "/MO", "2"]


def test_build_schtasks_command_weekly_uses_day_letter_code() -> None:
    record = make_record(kind="weekly", weekday=0)
    argv = build_schtasks_command(record)
    assert argv[5:9] == ["/SC", "WEEKLY", "/D", "SUN"]


def test_build_schtasks_command_rejects_payload_over_261_chars() -> None:
    record = make_record(log_path="/log/" + "x" * 300 + ".log")
    with pytest.raises(ValueError, match=r"limit is 261"):
        build_schtasks_command(record)


def test_schtasks_install_runs_create_with_built_command() -> None:
    record = make_record()
    runner = RecordingRunner()
    SchtasksAdapter().install(record, runner)
    assert runner.argv_lists() == [build_schtasks_command(record)]
    _args, kwargs = runner.calls[0]
    assert kwargs == {"capture_output": True, "text": True, "check": False}


def test_schtasks_remove_runs_forced_delete() -> None:
    runner = RecordingRunner()
    SchtasksAdapter().remove("app.volume", runner)
    assert runner.argv_lists() == [["schtasks", "/Delete", "/TN", "app.volume", "/F"]]


@pytest.mark.parametrize(("returncode", "expected"), [(0, True), (1, False)])
def test_schtasks_exists_maps_query_returncode(returncode: int, expected: bool) -> None:
    runner = RecordingRunner([FakeProc(returncode=returncode)])
    assert SchtasksAdapter().exists("app.volume", runner) is expected
    assert runner.argv_lists() == [["schtasks", "/Query", "/TN", "app.volume"]]
