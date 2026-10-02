from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

from compman.version import package_version


def test_package_version_reports_installed_distribution():
    with patch("compman.version.version", return_value="1.12.0"):
        assert package_version() == "1.12.0"


def test_package_version_falls_back_to_dev_without_metadata():
    with patch("compman.version.version", side_effect=PackageNotFoundError):
        assert package_version() == "dev"