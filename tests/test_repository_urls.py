import ast
import re
from pathlib import Path


def test_official_repository_urls_use_current_owner():
    root = Path(__file__).parents[1]
    files = ("README.md", "install.cmd", "install.ps1", "install.sh")

    for name in files:
        content = (root / name).read_text(encoding="utf-8")
        assert "aimnext-dev1/compman" not in content
        assert "allbegray/compman" in content


def test_package_version_is_1_6_0():
    root = Path(__file__).parents[1]
    project = (root / "pyproject.toml").read_text(encoding="utf-8")
    lock = (root / "uv.lock").read_text(encoding="utf-8")

    assert re.search(r'(?m)^version = "1\.6\.0"$', project)
    assert re.search(r'(?m)^name = "compman"\r?\nversion = "1\.6\.0"$', lock)
    assert "## [1.6.0]" in (root / "CHANGELOG.md").read_text(encoding="utf-8")


def test_successful_main_ci_run_creates_version_tag_once():
    root = Path(__file__).parents[1]
    release = (root / ".github" / "workflows" / "release-tag.yml").read_text(encoding="utf-8")
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    for expected in (
        "workflow_run:",
        "workflows: [CI]",
        "types: [completed]",
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.event == 'push'",
        "github.event.workflow_run.head_branch == 'main'",
        "contents: write",
        "github.event.workflow_run.head_sha",
        "tomllib",
        "CHANGELOG.md",
        "git rev-list -n 1",
        "git tag -a",
        "git push origin",
    ):
        assert expected in release

    assert 'tags-ignore: ["**"]' in ci


def test_github_pages_homepage_contract():
    root = Path(__file__).parents[1]
    html = (root / "docs" / "site" / "index.html").read_text(encoding="utf-8")
    css = (root / "docs" / "site" / "styles.css").read_text(encoding="utf-8")

    for expected in (
        'name="viewport"',
        'name="description"',
        'href="styles.css"',
        'id="features"',
        'id="quick-start"',
        'id="commands"',
        'id="deploy"',
        'id="faq"',
        "compman init --scaffold",
        "compman ps",
        "compman stats -f",
        "s3://my-bucket/releases/app.tar.gz",
        "https://example.com/releases/app.zip",
        "https://github.com/allbegray/compman",
        "LICENSE",
    ):
        assert expected in html

    assert "<script" not in html
    assert "http://" not in html
    assert "@media" in css
    assert ":focus-visible" in css


def test_github_pages_workflow_contract():
    root = Path(__file__).parents[1]
    workflow = (root / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")

    for expected in (
        "workflow_dispatch:",
        "actions/configure-pages@",
        "actions/upload-pages-artifact@",
        "actions/deploy-pages@",
        "path: docs/site",
        "contents: read",
        "pages: write",
        "id-token: write",
        "environment:",
        "name: github-pages",
        "cancel-in-progress: false",
    ):
        assert expected in workflow


def test_project_uses_mit_license():
    root = Path(__file__).parents[1]
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    project = (root / "pyproject.toml").read_text(encoding="utf-8")

    assert license_text.startswith("MIT License\n")
    assert "Copyright (c) 2026 allbegray" in license_text
    assert 'license = "MIT"' in project


def test_user_facing_echo_strings_are_translated():
    root = Path(__file__).parents[1]
    # Intentionally untranslated: shell/command usage examples and verbatim
    # completion snippets (bash/zsh/fish eval lines are shell code, not prose).
    allowlist = {
        '  PowerShell : $env:COMPMAN_LANG="ko"',
        "  CMD        : set COMPMAN_LANG=ko",
        "  Bash/Zsh   : export COMPMAN_LANG=ko",
        'eval "$(_COMPMAN_COMPLETE=bash_source compman)"',
        'eval "$(_COMPMAN_COMPLETE=zsh_source compman)"',
        "_COMPMAN_COMPLETE=fish_source compman | source",
        "     compman deploy --path s3://<your-bucket>/path/to/app.tar.gz",
        "     compman init",
        "compman ",
    }

    def sentence_like(text: str) -> bool:
        stripped = text.lstrip()
        if len(stripped) < 4 or " " not in stripped:
            return False
        if sum(character.isalpha() for character in stripped) < 3:
            return False
        return stripped[0].isalnum()

    def collect_strings(node: ast.AST) -> list[str]:
        return [
            sub.value
            for sub in ast.walk(node)
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
        ]

    offenders: list[str] = []
    for path in (root / "compman").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))

        # assigned[name] holds every string literal ever bound to that name,
        # including literals nested in literal containers and += targets.
        assigned: dict[str, list[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                strings = collect_strings(node.value)
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.setdefault(target.id, []).extend(strings)
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                assigned.setdefault(node.target.id, []).extend(collect_strings(node.value))

        def flag(text: str, location: str) -> None:
            if text not in allowlist and sentence_like(text):
                offenders.append(f"{location}: {text!r}")

        def handle(arg: ast.expr, location: str) -> None:
            texts: list[str] = []
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                texts.append(arg.value)
            elif isinstance(arg, ast.JoinedStr):
                texts.extend(
                    value.value
                    for value in arg.values
                    if isinstance(value, ast.Constant) and isinstance(value.value, str)
                )
            elif isinstance(arg, ast.Name):
                texts.extend(assigned.get(arg.id, []))
            elif isinstance(arg, ast.Subscript):
                base = arg
                while isinstance(base, ast.Subscript):
                    base = base.value
                if isinstance(base, ast.Name):
                    texts.extend(assigned.get(base.id, []))
            for text in texts:
                flag(text, location)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "prompt_select":
                if node.args:
                    handle(node.args[0], f"{path.relative_to(root)}:{node.lineno}")
                    if len(node.args) > 1:
                        handle(node.args[1], f"{path.relative_to(root)}:{node.lineno}")
                continue
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "typer":
                continue
            location = f"{path.relative_to(root)}:{node.lineno}"
            if node.func.attr in ("echo", "confirm", "prompt"):
                if not node.args:
                    continue
                handle(node.args[0], location)
            elif node.func.attr in ("Option", "Argument"):
                for kw in node.keywords:
                    if kw.arg == "help" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        flag(kw.value.value, location)
    assert offenders == []


def test_english_is_used_outside_korean_localization_resources():
    root = Path(__file__).parents[1]
    allowed = {
        root / "compman" / "i18n.py",
        root / "tests" / "test_i18n.py",
        root / "tests" / "test_cli.py",
    }
    suffixes = {".cmd", ".html", ".md", ".ps1", ".py", ".sh", ".toml", ".yaml", ".yml"}
    candidates = [root / "AGENTS.md", root / "README.md", root / "BACKLOG.md", root / "pyproject.toml"]
    for directory in ("compman", "docs", "scratch", "test", "tests"):
        candidates.extend(path for path in (root / directory).rglob("*") if path.suffix in suffixes)

    hangul = re.compile(r"[\uac00-\ud7a3]")
    offenders = [
        str(path.relative_to(root))
        for path in candidates
        if path not in allowed and hangul.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert [
        str(path.relative_to(root))
        for path in candidates
        if path.suffix == ".html" and 'lang="ko"' in path.read_text(encoding="utf-8")
    ] == []
