from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import bookbinder
from bookbinder.web.app import create_app

pytestmark = pytest.mark.mvp_unit

ROOT = Path(__file__).resolve().parents[2]


def test_setuptools_discovery_is_scoped_to_bookbinder_package() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    find_config = pyproject["tool"]["setuptools"]["packages"]["find"]
    assert find_config["where"] == ["."]
    assert find_config["include"] == ["bookbinder*"]


def test_imported_package_resolves_to_active_checkout() -> None:
    package_path = Path(bookbinder.__file__).resolve()
    assert ROOT in package_path.parents


def test_create_app_import_resolves_to_active_checkout() -> None:
    source_path = Path(create_app.__code__.co_filename).resolve()
    assert ROOT in source_path.parents
