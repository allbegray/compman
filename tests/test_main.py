from __future__ import annotations

import pathlib
import runpy
from unittest.mock import patch


def test_main_guard_invokes_app_and_propagates_system_exit():
    root = pathlib.Path(__file__).parents[1]

    with patch("compman.cli.app", side_effect=SystemExit(0)) as app_mock:
        with patch("sys.argv", ["compman"]):
            try:
                runpy.run_path(str(root / "compman" / "__main__.py"), run_name="__main__")
            except SystemExit:
                pass
            else:
                raise AssertionError("python -m compman must exit through app()")

    app_mock.assert_called_once_with()


def test_main_module_can_be_loaded_without_running_cli():
    namespace = runpy.run_module("compman.__main__", run_name="compman.not_main")

    assert "app" in namespace
