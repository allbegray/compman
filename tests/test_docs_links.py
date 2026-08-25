"""[L3] Documentation hygiene: every relative Markdown link must resolve."""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).parents[1]
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)\s]+(?:\s+\"[^\"]*\")?)\)")

SCAN_FILES = [
    *ROOT.glob("*.md"),
    *ROOT.glob("docs/**/*.md"),
    *ROOT.glob("examples/**/*.md"),
]


def _relative_targets() -> list[tuple[pathlib.Path, str]]:
    found: list[tuple[pathlib.Path, str]] = []
    for path in SCAN_FILES:
        for match in LINK_PATTERN.finditer(path.read_text(encoding="utf-8")):
            target = match.group(1).strip().split()[0] if " " in match.group(1).strip() else match.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            found.append((path, target))
    return found


def content_of(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def test_every_relative_markdown_link_resolves():
    missing = []
    for source_path, target in _relative_targets():
        stripped = target.split("#", 1)[0]
        if not stripped:
            continue
        resolved = (source_path.parent / stripped).resolve()
        if not resolved.exists():
            missing.append(f"{source_path} -> {target}")
    assert missing == [], f"broken relative links: {missing}"


README_FILES = [ROOT / "README.md", ROOT / "README.ko.md"]


@pytest.mark.parametrize("path", sorted(README_FILES))
def test_markdown_files_have_unique_internal_anchors(path: pathlib.Path):
    text = content_of(path)
    headings = [
        line.lstrip("#").strip().lower()
        for line in text.splitlines()
        if line.startswith("#")
    ]
    assert len(headings) == len(set(headings)), f"duplicate headings in {path}"
