from __future__ import annotations

import importlib
import sys
from pathlib import Path

# Ensure pytest resolves the package from the active checkout/worktree
# instead of a stale editable install target.
ROOT = Path(__file__).resolve().parents[1]
ROOT_STR = str(ROOT)
if ROOT_STR not in sys.path:
    sys.path.insert(0, ROOT_STR)


def _is_from_root(module_name: str, root: Path) -> bool:
    module = sys.modules.get(module_name)
    module_file = getattr(module, "__file__", None)
    if module is None or module_file is None:
        return False

    try:
        module_path = Path(module_file).resolve()
    except OSError:
        return False
    return root == module_path or root in module_path.parents


def _ensure_module_from_root(module_name: str, root: Path) -> None:
    if _is_from_root(module_name, root):
        return

    # Drop stale module objects (and their children) imported from other
    # editable targets so import resolution can use this worktree first.
    for loaded_name in list(sys.modules):
        if loaded_name == module_name or loaded_name.startswith(f"{module_name}."):
            sys.modules.pop(loaded_name, None)

    module = importlib.import_module(module_name)
    module_file = getattr(module, "__file__", None)
    if module_file is None:
        raise RuntimeError(
            f"Unable to verify import path for '{module_name}' (no __file__)."
        )

    module_path = Path(module_file).resolve()
    if root != module_path and root not in module_path.parents:
        raise RuntimeError(
            "Worker bootstrap detected a stale editable package mapping. "
            f"Expected '{module_name}' under '{root}', got '{module_path}'. "
            "Remediation: run `python -m pip install -e '.[dev]'` from the active worktree "
            "and re-run pytest."
        )


def pytest_sessionstart(session) -> None:  # type: ignore[no-untyped-def]
    _ensure_module_from_root("bookbinder", ROOT)
    _ensure_module_from_root("bookbinder.web.app", ROOT)
