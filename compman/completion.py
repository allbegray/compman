from __future__ import annotations

import pathlib
import subprocess
from typing import Annotated, Callable

import typer

from compman._proc import _env_timeout
from compman.errors import CommandError
from compman.i18n import t

_POSIX_SHELLS: dict[str, tuple[str, Callable[[], pathlib.Path], str, str]] = {
    "bash": (
        'eval "$(_COMPMAN_COMPLETE=bash_source compman)"',
        lambda: pathlib.Path.home() / ".bashrc",
        "Bash",
        ".bashrc",
    ),
    "zsh": (
        'eval "$(_COMPMAN_COMPLETE=zsh_source compman)"',
        lambda: pathlib.Path.home() / ".zshrc",
        "Zsh",
        ".zshrc",
    ),
    "fish": (
        "_COMPMAN_COMPLETE=fish_source compman | source",
        lambda: pathlib.Path.home() / ".config" / "fish" / "config.fish",
        "Fish",
        "config.fish",
    ),
}


def register(app: typer.Typer) -> None:
    app.command("completion", help=t("cmd.completion"))(completion_cmd)


def completion_cmd(
    shell: Annotated[str, typer.Argument()] = "powershell",
    install: Annotated[bool, typer.Option("--install", help=t("opt.install"))] = False,
) -> None:
    if shell == "powershell":
        snippet = _ps_completion_snippet()
        if install:
            try:
                ps_profile = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command", "echo $PROFILE"],
                    text=True,
                    timeout=_env_timeout(),
                ).strip()
                profile_path = pathlib.Path(ps_profile)
                profile_path.parent.mkdir(parents=True, exist_ok=True)
                current_content = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
                if "compman shell completion" in current_content:
                    lines = current_content.splitlines()
                    new_lines = [line for line in lines if "_COMPMAN_COMPLETE" not in line and "compman | Out-String" not in line]
                    current_content = "\n".join(new_lines)
                if "Register-ArgumentCompleter -Native -CommandName compman" not in current_content:
                    with profile_path.open("w", encoding="utf-8") as f:
                        f.write(current_content.strip() + "\n" + snippet)
                    typer.echo(t("msg.completion_registered", shell="PowerShell", path=profile_path))
                else:
                    typer.echo(t("msg.completion_exists", path="PowerShell profile"))
            except Exception as e:
                raise CommandError(t("msg.completion_error", error=e)) from e
        else:
            typer.echo(snippet.strip())
    elif shell in _POSIX_SHELLS:
        if install:
            _install_posix(shell)
        else:
            typer.echo(_POSIX_SHELLS[shell][0])
    else:
        raise CommandError(t("msg.unsupported_shell", shell=shell))


def _install_posix(shell: str) -> None:
    snippet, rc_path_fn, display, exists_path = _POSIX_SHELLS[shell]
    rc_path = rc_path_fn()
    rc_path.parent.mkdir(parents=True, exist_ok=True)
    current_content = rc_path.read_text(encoding="utf-8") if rc_path.exists() else ""
    if "_COMPMAN_COMPLETE" not in current_content:
        with rc_path.open("a", encoding="utf-8") as f:
            f.write(f"\n{snippet}\n")
        typer.echo(t("msg.completion_registered", shell=display, path=rc_path))
    else:
        typer.echo(t("msg.completion_exists", path=exists_path))


def _ps_completion_snippet() -> str:
    return (
        "\n# compman shell completion\n"
        "Register-ArgumentCompleter -Native -CommandName compman -ScriptBlock {\n"
        "    param($wordToComplete, $commandAst, $cursorPosition)\n"
        "    $subcommands = @('init', 'clear', 'deploy', 'rollback', 'update', 'doctor', 'status', 'ps', 'stats', 'upgrade', 'completion', 'lang', 'version', 'stack', 'service', 'volume', 'image', 'schedule', 'stacks')\n"
        "    $words = $commandAst.ToString().Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)\n"
        "    if ($words.Count -le 2) {\n"
        "        $subcommands | Where-Object { $_ -like \"$wordToComplete*\" } | ForEach-Object {\n"
        "            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)\n"
        "        }\n"
        "    } elseif ($words[1] -eq 'stack') {\n"
        "        @('up', 'down', 'update') | Where-Object { $_ -like \"$wordToComplete*\" } | ForEach-Object {\n"
        "            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)\n"
        "        }\n"
        "    } elseif ($words[1] -eq 'service') {\n"
        "        @('start', 'stop', 'restart', 'status', 'log', 'connect') | Where-Object { $_ -like \"$wordToComplete*\" } | ForEach-Object {\n"
        "            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)\n"
        "        }\n"
        "    } elseif ($words[1] -eq 'volume') {\n"
        "        @('backup', 'restore', 'pull', 'push') | Where-Object { $_ -like \"$wordToComplete*\" } | ForEach-Object {\n"
        "            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)\n"
        "        }\n"
        "    } elseif ($words[1] -eq 'image') {\n"
        "        @('backup', 'restore') | Where-Object { $_ -like \"$wordToComplete*\" } | ForEach-Object {\n"
        "            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)\n"
        "        }\n"
        "    } elseif ($words[1] -eq 'schedule') {\n"
        "        @('add', 'list', 'remove') | Where-Object { $_ -like \"$wordToComplete*\" } | ForEach-Object {\n"
        "            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)\n"
        "        }\n"
        "    } elseif ($words[1] -eq 'stacks') {\n"
        "        @('list', 'remove') | Where-Object { $_ -like \"$wordToComplete*\" } | ForEach-Object {\n"
        "            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
