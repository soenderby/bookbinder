from __future__ import annotations

import os
import subprocess
import sys
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


def test_editable_install_smoke_with_generated_dir(tmp_path: Path) -> None:
    generated_dir = ROOT / "generated"
    generated_dir.mkdir(exist_ok=True)

    venv_dir = tmp_path / "editable-smoke-venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True, cwd=ROOT)

    venv_python = venv_dir / "bin" / "python"
    if os.name == "nt":
        venv_python = venv_dir / "Scripts" / "python.exe"

    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PYTHONWARNINGS"] = "ignore::DeprecationWarning"
    install = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--no-deps", "-e", str(ROOT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert install.returncode == 0, install.stderr
