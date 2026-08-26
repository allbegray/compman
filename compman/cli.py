from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
from enum import Enum
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import TYPE_CHECKING, Annotated

import typer
from typer.core import TyperGroup

from compman._proc import _env_timeout
from compman.completion import register as register_completion
from compman.errors import CommandError, ConfigError
from compman.i18n import get_lang, set_lang, t
from compman.init_cmd import register as register_init

if TYPE_CHECKING:
    from compman.config import Config
    from compman.diagnostics import DoctorReport, StatusReport
    from compman.docker import ContainerRuntime


def dump_default_config(name: str) -> str:
    from compman.config import dump_default_config as _dump_default_config

    return _dump_default_config(name)


def load_config(config_path: str | None = None):
    from compman.config import load_config as _load_config

    return _load_config(config_path)


def detect_runtime():
    from compman.docker import detect_runtime as _detect_runtime

    return _detect_runtime()


def _deploy(
    *,
    build: bool,
    tag: str | None,
    s3_path: str | None,
    config: Config | None = None,
    runtime: ContainerRuntime | None = None,
    sha256: str | None = None,
) -> None:
    from compman.deploy import deploy

    deploy(build=build, tag=tag, s3_path=s3_path, config=config, runtime=runtime, sha256=sha256)


def collect_doctor(config_path: str | None, profile: str | None):
    from compman.diagnostics import collect_doctor as _collect_doctor

    return _collect_doctor(config_path, profile)


def collect_status(config_path: str | None, profile: str | None):
    from compman.diagnostics import collect_status as _collect_status

    return _collect_status(config_path, profile)


def _stack_ops():
    from compman.ops import stack

    return stack


def _service_ops():
    from compman.ops import service

    return service


def _volume_ops():
    from compman.ops import volume

    return volume


def _image_ops():
    from compman.ops import image

    return image


def _container_ops():
    from compman.ops import container

    return container


def _schedule_ops():
    from compman.ops import schedule

    return schedule


def _stack_registry():
    from compman import stack_registry

    return stack_registry


def _resolved_config_path(config_path: str | None) -> str | None:
    """Resolve the config path an invocation should load.

    An explicit -c/--config always wins. Otherwise, a root ``--stack NAME``
    selection resolves to the registered directory's compman.yml so commands
    work from any working directory; unknown names are a hard error.
    """
    if config_path is not None:
        return config_path
    registry = _stack_registry()
    stack_name = registry.current_stack()
    if stack_name is None:
        return None
    stack_dir = registry.resolve(stack_name)
    if stack_dir is None:
        raise CommandError(t("msg.stacks_not_found", name=stack_name))
    return str(stack_dir / "compman.yml")

def _configure_console_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:  # pragma: no branch - standard Python text streams provide it
            reconfigure(errors="replace")


_configure_console_output()

_CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}
ConfigOpt = Annotated[str | None, typer.Option("--config", "-c", help=t("opt.config"))]
ProfileOpt = Annotated[str | None, typer.Option("--profile", help=t("opt.profile"))]


def _version_callback(value: bool) -> None:
    if value:
        try:
            v = _pkg_version("compman")
        except PackageNotFoundError:
            v = "dev"
        typer.echo(f"compman {v}")
        raise typer.Exit()


class HelpOnUnknownCommandGroup(TyperGroup):
    def resolve_command(self, ctx, args):
        if args and self.get_command(ctx, args[0]) is None:
            command = args[0]
            typer.echo(t("msg.unknown_command", command=command), err=True)
            typer.echo(ctx.get_help())
            raise CommandError("", code=2)
        return super().resolve_command(ctx, args)

    def main(self, *args, **kwargs):
        try:
            return super().main(*args, **kwargs)
        except CommandError as error:
            if error.message:
                typer.echo(error.message, err=True)
            raise SystemExit(error.code)
        except subprocess.TimeoutExpired as error:
            seconds = error.timeout if error.timeout is not None else _env_timeout()
            shown = int(seconds) if float(seconds).is_integer() else seconds
            typer.echo(t("msg.timeout_expired", seconds=shown), err=True)
            raise SystemExit(1)
        except (ConfigError, RuntimeError) as error:
            typer.echo(t("msg.command_failed", error=error), err=True)
            raise SystemExit(1)


def _make_group(help_text: str) -> typer.Typer:
    """Build a sub-app group sharing the unknown-command class and help options."""
    return typer.Typer(
        cls=HelpOnUnknownCommandGroup,
        help=help_text,
        no_args_is_help=True,
        context_settings=_CONTEXT_SETTINGS,
    )


# ---- pre-parse --lang for help text resolution ----
for _idx, _arg in enumerate(sys.argv):
    if _arg in ("--lang", "-l") and _idx + 1 < len(sys.argv):
        set_lang(sys.argv[_idx + 1])
        break
    elif _arg.startswith("--lang="):
        set_lang(_arg.split("=", 1)[1])
    elif _arg.startswith("-l="):
        set_lang(_arg.split("=", 1)[1])

app = typer.Typer(
    name="compman",
    cls=HelpOnUnknownCommandGroup,
    help=t("cmd.root"),
    no_args_is_help=True,
    invoke_without_command=True,
    context_settings=_CONTEXT_SETTINGS,
)

def _load(config_path: str | None = None):
    try:
        cfg = load_config(_resolved_config_path(config_path))
    except ConfigError as e:
        typer.echo(t("msg.config_not_found", err=e), err=True)
        typer.echo("", err=True)
        typer.echo(t("msg.start_guide"), err=True)
        typer.echo(f"  - compman init                              ({t('msg.init_desc')})", err=True)
        typer.echo(f"  - compman deploy --path <source-uri>  ({t('msg.deploy_desc')})", err=True)
        raise CommandError("", code=1) from e
    except OSError as e:
        typer.echo(t("msg.config_unreadable", detail=str(e)), err=True)
        raise CommandError("", code=1) from e
    try:
        runtime = detect_runtime()
    except RuntimeError as e:
        typer.echo(t("msg.runtime_error", error=e), err=True)
        raise CommandError("", code=1) from e
    return {"config": cfg, "runtime": runtime}


# ---- Root callback ----
@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    lang: Annotated[str | None, typer.Option("--lang", "-l", help=t("opt.lang"))] = None,
    version: Annotated[bool, typer.Option("--version", "-v", callback=_version_callback, is_eager=True)] = False,
    stack: Annotated[str | None, typer.Option("--stack", help=t("opt.stack"))] = None,
) -> None:
    if lang:
        set_lang(lang)
    if stack:
        _stack_registry().set_current_stack(stack)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())



# ---- init ----
register_init(app, _deploy, dump_default_config)


# ---- clear ----
@app.command("clear", help=t("cmd.clear"))
def clear_cmd(
    yes: Annotated[bool, typer.Option("--yes", help=t("opt.clear_yes"))] = False,
) -> None:
    if not yes:
        typer.confirm(t("msg.clear_confirm"), abort=True)
    typer.echo(t("msg.prune_images"))
    runtime = detect_runtime()
    runtime.passthru_cli(["image", "prune", "-af"])


# ---- deploy ----
@app.command("deploy", help=t("cmd.deploy"))
def deploy_cmd(
    path: Annotated[str | None, typer.Option("--path", help=t("opt.path"))] = None,
    build: Annotated[bool, typer.Option("--build", help=t("opt.build"))] = False,
    tag: Annotated[str | None, typer.Option("--tag", help=t("opt.tag"))] = None,
    sha256: Annotated[str | None, typer.Option("--sha256", help=t("opt.path_sha256"))] = None,
) -> None:
    _deploy(build=build, tag=tag, s3_path=path, sha256=sha256)


# ---- rollback ----
@app.command("rollback", help=t("cmd.rollback"))
def rollback_cmd() -> None:
    from compman.deploy import restore_rollback

    timestamp = restore_rollback(pathlib.Path.cwd())
    typer.echo(t("msg.rollback_done", time=timestamp))


def _existing_stack_image(cfg) -> tuple[str | None, list[str]]:
    """Return (single service image or None, distinct service images).

    Reads the resolved compose files so an update rebuilds exactly the image
    the running stack references instead of a directory-derived default.
    """

    import yaml

    from compman.docker import resolve_compose_context as _resolve

    try:
        context = _resolve(cfg, None)
    except Exception:
        return None, []
    images: list[str] = []
    for file in context.files:
        try:
            data = yaml.safe_load(pathlib.Path(file).read_text(encoding="utf-8-sig"))
        except (OSError, yaml.YAMLError):
            continue
        services = data.get("services") if isinstance(data, dict) else None
        if not isinstance(services, dict):
            continue
        for svc in services.values():
            image = svc.get("image") if isinstance(svc, dict) else None
            if isinstance(image, str) and image not in images:
                images.append(image)
    return (images[0] if len(images) == 1 else None), images


# ---- update ----
@app.command("update", help=t("cmd.update"))
def update_cmd(
    profile: Annotated[str | None, typer.Argument()] = None,
    config: ConfigOpt = None,
) -> None:
    ctx = _load(config)
    cfg = ctx["config"]
    if cfg.deploy:
        tag, images = _existing_stack_image(cfg)
        if tag is None and images:
            typer.echo(t("msg.update_tag_mismatch", images=", ".join(sorted(images))), err=True)
        _deploy(build=True, tag=tag, s3_path=cfg.deploy, config=cfg, runtime=ctx["runtime"])
        _stack_ops().up(ctx["runtime"], cfg, profile=profile)
    else:
        _stack_ops().update(ctx["runtime"], cfg, profile=profile)


def _render_doctor(report: DoctorReport) -> None:
    typer.echo(t("msg.doctor_header"))
    for check in report.checks:
        marker = "!" if check.severity == "warning" else "OK" if check.ok else "X"
        typer.echo(f"{marker} {check.id}: {check.message}")
        if not check.ok or check.severity == "warning":
            if check.detail:
                typer.echo(f"    {check.detail}")
            if check.remediation:
                typer.echo(f"    {check.remediation}")


def _render_status(report: StatusReport) -> None:
    header = f"{t('msg.status_header')} {report.stack or 'unknown'}"
    if report.runtime:
        header += f" ({t('msg.status_runtime')} {report.runtime})"
    if report.profile:
        header += f" ({t('msg.status_profile')} {report.profile})"
    if report.error:
        header += f" - {report.error}"
        if report.error_code:
            header += f" [{report.error_code}]"
    typer.echo(header)
    for service_status in report.services:
        health = f", health: {service_status.health}" if service_status.health else ""
        typer.echo(
            f"{service_status.service}: {service_status.state} - "
            f"{service_status.status} (container: {service_status.container}{health})"
        )


# ---- doctor ----
@app.command("doctor", help=t("cmd.doctor"))
def doctor_cmd(
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
    json_output: Annotated[bool, typer.Option("--json", help=t("opt.json"))] = False,
) -> None:
    report = collect_doctor(_resolved_config_path(config), profile)
    if json_output:
        typer.echo(json.dumps(report.to_dict(), ensure_ascii=False))
    else:
        _render_doctor(report)
    if not report.ok:
        raise CommandError("", code=1)


# ---- status ----
@app.command("status", help=t("cmd.status"))
def status_cmd(
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
    json_output: Annotated[bool, typer.Option("--json", help=t("opt.json"))] = False,
) -> None:
    report = collect_status(_resolved_config_path(config), profile)
    if json_output:
        typer.echo(json.dumps(report.to_dict(), ensure_ascii=False))
    else:
        _render_status(report)
    if not report.ok:
        raise CommandError("", code=1)


# ---- project containers ----
@app.command("ps", help=t("cmd.ps"))
def ps_cmd(
    profile: Annotated[str | None, typer.Argument()] = None,
    all_containers: Annotated[
        bool, typer.Option("--all", "-a", help=t("opt.all"))
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help=t("opt.json"))] = False,
    config: ConfigOpt = None,
) -> None:
    ctx = _load(config)
    _container_ops().ps(ctx["runtime"], ctx["config"], profile, all_containers, json_output)


@app.command("stats", help=t("cmd.stats"))
def stats_cmd(
    profile: Annotated[str | None, typer.Argument()] = None,
    follow: Annotated[
        bool, typer.Option("--follow", "-f", help=t("opt.follow"))
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help=t("opt.json"))] = False,
    config: ConfigOpt = None,
) -> None:
    ctx = _load(config)
    _container_ops().stats(ctx["runtime"], ctx["config"], profile, follow, json_output)


# ---- completion ----
register_completion(app)


# ---- upgrade ----
def _run_upgrade_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_env_timeout(),
    )


def _managed_python() -> str:
    """Interpreter version (major.minor) for uv's managed python."""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


@app.command("upgrade", help=t("cmd.upgrade"))
def upgrade_cmd(
    repo: Annotated[str, typer.Option("--repo", help=t("opt.repo"))] = "https://github.com/allbegray/compman.git",
) -> None:
    typer.echo(t("msg.upgrade_start"))

    uv_cmd = _find_uv()
    try:
        result = _run_upgrade_command(
            [
                uv_cmd,
                "tool",
                "upgrade",
                "compman",
                "--reinstall",
                "--managed-python",
                "--python",
                _managed_python(),
            ]
        )
    except FileNotFoundError:
        result = _run_upgrade_command(
            [sys.executable, "-m", "pip", "install", "--upgrade", f"git+{repo}"]
        )

    if result.returncode == 0:
        typer.echo(t("msg.upgrade_success"))
        return
    typer.echo(t("msg.upgrade_error", error=result.stderr or result.stdout), err=True)
    raise CommandError("", code=1)





# ---- lang ----
@app.command("lang", help=t("cmd.lang"))
def lang_cmd(
    language: Annotated[str | None, typer.Argument(help=t("opt.language_code"))] = None,
) -> None:
    if language:
        if language.lower() in ("en", "ko"):
            set_lang(language.lower())
            typer.echo(t("msg.lang_set", language=language.lower()))
        else:
            typer.echo(t("msg.lang_unsupported", language=language), err=True)
            raise CommandError("", code=1)

    curr = get_lang()
    env_val = os.environ.get("COMPMAN_LANG", "<not set>")

    typer.echo(t("msg.lang_info"))
    typer.echo(t("msg.lang_active", language=curr.upper()))
    typer.echo(t("msg.lang_env", value=env_val))
    typer.echo("")
    typer.echo(t("msg.lang_persistent"))
    typer.echo("  PowerShell : $env:COMPMAN_LANG=\"ko\"")
    typer.echo("  CMD        : set COMPMAN_LANG=ko")
    typer.echo("  Bash/Zsh   : export COMPMAN_LANG=ko")


# ---- version ----
@app.command("version", help=t("cmd.version"))
def version_cmd() -> None:
    try:
        v = _pkg_version("compman")
    except PackageNotFoundError:
        v = "dev"
    typer.echo(f"compman {v}")


# ---- stack group ----
stack_app = _make_group(t("cmd.stack"))


@stack_app.command("up", help=t("cmd.stack.up"))
def stack_up(
    profile: Annotated[str | None, typer.Argument()] = None,
    config: ConfigOpt = None,
    wait: Annotated[bool, typer.Option("--wait", help=t("opt.wait"))] = False,
) -> None:
    ctx = _load(config)
    _stack_ops().up(ctx["runtime"], ctx["config"], profile, wait=wait)


@stack_app.command("down", help=t("cmd.stack.down"))
def stack_down(
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
    yes: Annotated[bool, typer.Option("--yes", help=t("opt.confirm_stack_removal"))] = False,
) -> None:
    if not yes:
        typer.confirm(t("msg.remove_stack_confirm"), abort=True)
    ctx = _load(config)
    _stack_ops().down(ctx["runtime"], ctx["config"], profile)


@stack_app.command("update", help=t("cmd.stack.update"))
def stack_update(
    profile: Annotated[str | None, typer.Argument()] = None,
    config: ConfigOpt = None,
    wait: Annotated[bool, typer.Option("--wait", help=t("opt.wait"))] = False,
) -> None:
    ctx = _load(config)
    _stack_ops().update(ctx["runtime"], ctx["config"], profile, wait=wait)


app.add_typer(stack_app, name="stack")


# ---- service group ----
service_app = _make_group(t("cmd.service"))


@service_app.command("start", help=t("cmd.service.start"))
def service_start(
    services: Annotated[list[str], typer.Argument()] = [],
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
) -> None:
    ctx = _load(config)
    _service_ops().start(ctx["runtime"], ctx["config"], tuple(services), profile)


@service_app.command("stop", help=t("cmd.service.stop"))
def service_stop(
    services: Annotated[list[str], typer.Argument()] = [],
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
) -> None:
    ctx = _load(config)
    _service_ops().stop(ctx["runtime"], ctx["config"], tuple(services), profile)


@service_app.command("restart", help=t("cmd.service.restart"))
def service_restart(
    services: Annotated[list[str], typer.Argument()] = [],
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
) -> None:
    ctx = _load(config)
    _service_ops().restart(ctx["runtime"], ctx["config"], tuple(services), profile)


@service_app.command("status", help=t("cmd.service.status"))
def service_status(
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
) -> None:
    ctx = _load(config)
    _service_ops().status(ctx["runtime"], ctx["config"], profile)


@service_app.command("log", help=t("cmd.service.log"))
def service_log(
    name: Annotated[str | None, typer.Argument()] = None,
    follow: Annotated[bool, typer.Option("-f", "--follow", help=t("opt.follow"))] = False,
    tail: Annotated[int, typer.Option("-n", "--tail", help=t("opt.tail"))] = 50,
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
) -> None:
    ctx = _load(config)
    _service_ops().log(ctx["runtime"], ctx["config"], name, follow=follow, tail=tail, profile=profile)


@service_app.command("connect", help=t("cmd.service.connect"))
def service_connect(
    name: Annotated[str | None, typer.Argument()] = None,
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
) -> None:
    ctx = _load(config)
    _service_ops().connect(ctx["runtime"], ctx["config"], name, profile)


app.add_typer(service_app, name="service")


# ---- volume group ----
volume_app = _make_group(t("cmd.volume"))


@volume_app.command("backup", help=t("cmd.volume.backup"))
def volume_backup(
    no_stop: Annotated[bool, typer.Option("--no-stop", help=t("opt.no_stop"))] = False,
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
    level: Annotated[int, typer.Option("-z", "--level", min=1, max=9, help=t("opt.compression_level"))] = 6,
    zstd_format: Annotated[bool, typer.Option("--zstd", help=t("opt.zstd"))] = False,
) -> None:
    ctx = _load(config)
    _volume_ops().backup(
        ctx["runtime"],
        ctx["config"],
        no_stop=no_stop,
        profile=profile,
        compression_level=level,
        zstd_format=zstd_format,
    )


@volume_app.command("restore", help=t("cmd.volume.restore"))
def volume_restore(
    timestamp: Annotated[str | None, typer.Argument(help=t("opt.restore_timestamp"))] = None,
    no_stop: Annotated[bool, typer.Option("--no-stop", help=t("opt.no_stop"))] = False,
    replace: Annotated[bool, typer.Option("--replace", help=t("opt.replace"))] = False,
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
) -> None:
    ctx = _load(config)
    _volume_ops().restore(
        ctx["runtime"], ctx["config"], timestamp, no_stop=no_stop, profile=profile, replace=replace
    )


@volume_app.command("pull", help=t("cmd.volume.pull"))
def volume_pull(
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
) -> None:
    ctx = _load(config)
    _volume_ops().pull(ctx["runtime"], ctx["config"], profile)


@volume_app.command("push", help=t("cmd.volume.push"))
def volume_push(
    replace: Annotated[bool, typer.Option("--replace", help=t("opt.replace"))] = False,
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
) -> None:
    ctx = _load(config)
    _volume_ops().push(ctx["runtime"], ctx["config"], profile, replace=replace)


app.add_typer(volume_app, name="volume")


# ---- image group ----
image_app = _make_group(t("cmd.image"))


@image_app.command("backup", help=t("cmd.image.backup"))
def image_backup(
    source_image: Annotated[bool, typer.Option("--source-image", help=t("opt.source_image"))] = False,
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
    level: Annotated[int, typer.Option("-z", "--level", min=1, max=9, help=t("opt.compression_level"))] = 6,
    zstd_format: Annotated[bool, typer.Option("--zstd", help=t("opt.zstd"))] = False,
) -> None:
    ctx = _load(config)
    _image_ops().backup(
        ctx["runtime"],
        ctx["config"],
        source_mode=source_image,
        profile=profile,
        compression_level=level,
        zstd_format=zstd_format,
    )


@image_app.command("restore", help=t("cmd.image.restore"))
def image_restore(
    timestamp: Annotated[str | None, typer.Argument(help=t("opt.restore_timestamp"))] = None,
    profile: ProfileOpt = None,
    config: ConfigOpt = None,
) -> None:
    ctx = _load(config)
    _image_ops().restore(ctx["runtime"], ctx["config"], timestamp, profile)


app.add_typer(image_app, name="image")


# ---- schedule group ----
class SchedulerChoice(str, Enum):
    systemd = "systemd"
    cron = "cron"


schedule_app = _make_group(t("cmd.schedule.help"))


@schedule_app.command("add", help=t("cmd.schedule.add.help"))
def schedule_add(
    every: Annotated[str | None, typer.Option("--every", help=t("opt.every"))] = None,
    daily: Annotated[str | None, typer.Option("--daily", help=t("opt.daily"))] = None,
    weekly: Annotated[str | None, typer.Option("--weekly", help=t("opt.weekly"))] = None,
    no_stop: Annotated[bool, typer.Option("--no-stop", help=t("opt.no_stop"))] = False,
    level: Annotated[int, typer.Option("-z", "--level", min=1, max=9, help=t("opt.compression_level"))] = 6,
    profile: ProfileOpt = None,
    name: Annotated[str | None, typer.Option("--name", help=t("opt.job_name"))] = None,
    scheduler: Annotated[
        SchedulerChoice | None, typer.Option("--scheduler", help=t("opt.scheduler"))
    ] = None,
    config: ConfigOpt = None,
) -> None:
    ctx = _load(config)
    _schedule_ops().add_schedule(
        ctx["config"],
        every=every,
        daily=daily,
        weekly=weekly,
        no_stop=no_stop,
        level=level,
        profile=profile,
        name=name,
        scheduler=scheduler.value if scheduler else None,
    )


@schedule_app.command("list", help=t("cmd.schedule.list.help"))
def schedule_list(
    json_output: Annotated[bool, typer.Option("--json", help=t("opt.json"))] = False,
) -> None:
    _schedule_ops().list_schedules(json_output=json_output)


@schedule_app.command("remove", help=t("cmd.schedule.remove.help"))
def schedule_remove(
    name: Annotated[str, typer.Argument()],
) -> None:
    _schedule_ops().remove_schedule(name)


app.add_typer(schedule_app, name="schedule")


# ---- stacks group ----
stacks_app = _make_group(t("cmd.stacks.help"))


@stacks_app.command("list", help=t("cmd.stacks_list.help"))
def stacks_list(
    json_output: Annotated[bool, typer.Option("--json", help=t("opt.json"))] = False,
) -> None:
    registered = _stack_registry().entries()
    if json_output:
        from compman.ops.common import utc_now_iso

        payload = {
            "schema_version": 1,
            "generated_at": utc_now_iso(),
            "stacks": [
                {"name": name, "path": path} for name, path in registered.items()
            ],
        }
        typer.echo(json.dumps(payload))
        return
    if not registered:
        typer.echo(t("msg.no_registered_stacks"))
        return
    typer.echo(t("msg.stacks_header"))
    for name, path in registered.items():
        typer.echo(f"{name} -> {path}")


@stacks_app.command("remove", help=t("cmd.stacks_remove.help"))
def stacks_remove(
    name: Annotated[str, typer.Argument()],
) -> None:
    if not _stack_registry().remove(name):
        raise CommandError(t("msg.stacks_not_found", name=name))
    typer.echo(t("msg.stacks_removed", name=name))


app.add_typer(stacks_app, name="stacks")


# ---- utils ----
def _find_uv() -> str:
    path = shutil.which("uv") or shutil.which("uv.exe")
    if path:
        return path
    home = pathlib.Path.home()
    local_app_data = pathlib.Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    candidates = [
        home / "AppData" / "Roaming" / "Python" / "Scripts" / "uv.exe",
        home / ".local" / "bin" / "uv.exe",
        home / ".local" / "bin" / "uv",
        home / ".cargo" / "bin" / "uv.exe",
        home / ".cargo" / "bin" / "uv",
        local_app_data / "Programs" / "uv" / "uv.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return "uv"


if __name__ == "__main__":
    app()
