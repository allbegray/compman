from __future__ import annotations

import ast
import os
import pathlib
import string
from unittest.mock import patch

import pytest

from compman import i18n
from compman.i18n import get_lang, set_lang, t


def _usage_keys() -> set[str]:
    root = pathlib.Path(__file__).parents[1] / "compman"
    keys: set[str] = set()
    for path in root.rglob("*.py"):
        if path.name == "i18n.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "t"
                and node.args
            ):
                candidates = [node.args[0]]
                if isinstance(node.args[0], ast.IfExp):
                    candidates = [node.args[0].body, node.args[0].orelse]
                for cand in candidates:
                    if isinstance(cand, ast.Constant) and isinstance(cand.value, str):
                        keys.add(cand.value)
    return keys


def test_all_used_translation_keys_exist():
    assert _usage_keys() <= set(i18n.TRANSLATIONS)


def test_all_translation_keys_are_bilingual():
    assert all(set(entry) == {"en", "ko"} for entry in i18n.TRANSLATIONS.values())



def _placeholders(text: str) -> set[str]:
    return {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(text)
        if field_name
    }


def test_all_translation_placeholders_match_between_locales():
    mismatched = {
        key
        for key, entry in i18n.TRANSLATIONS.items()
        if _placeholders(entry["en"]) != _placeholders(entry["ko"])
    }
    assert mismatched == set()


def test_placeholder_guard_detects_seeded_locale_mismatch():
    corrupted = {"en": "Snapshot {name} saved to {path}", "ko": "{path} 스냅샷 저장됨"}
    with patch.dict(i18n.TRANSLATIONS, {"msg.guard_probe": corrupted}):
        with pytest.raises(AssertionError, match="msg.guard_probe"):
            test_all_translation_placeholders_match_between_locales()


def test_no_unused_translation_keys():
    assert set(i18n.TRANSLATIONS) <= _usage_keys()


def test_i18n_lang_setting():
    set_lang("ko")
    assert get_lang() == "ko"
    set_lang("en")
    assert get_lang() == "en"
    set_lang("invalid")
    assert get_lang() == "en"
    set_lang(None)


def test_i18n_env_variable():
    with patch.dict(os.environ, {"COMPMAN_LANG": "ko"}):
        i18n._CURRENT_LANG.set(None)
        assert get_lang() == "ko"

    with patch.dict(os.environ, {"COMPMAN_LANG": "korean"}):
        i18n._CURRENT_LANG.set(None)
        assert get_lang() == "ko"

    with patch.dict(os.environ, {"COMPMAN_LANG": "en"}):
        i18n._CURRENT_LANG.set(None)
        assert get_lang() == "en"


def test_i18n_translation_fallback():
    set_lang("ko")
    res_ko = t("cmd.init")
    assert "프로젝트" in res_ko

    set_lang("en")
    res_en = t("cmd.init")
    assert "Initialize" in res_en

    # Non-existent key
    assert t("non_existent_key_123") == "non_existent_key_123"


def test_i18n_formatting_error():
    set_lang("en")
    # Formatting mismatch error branch test
    res = t("msg.seed_created", invalid_kwarg="foo")
    assert "{path}" in res
