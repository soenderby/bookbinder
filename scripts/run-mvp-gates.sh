#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "${ROOT}"

python -m pip install -c constraints/worker-runtime.txt -e ".[dev]"

python -c "from pathlib import Path; import bookbinder; from bookbinder.web.app import create_app; root=Path('.').resolve(); assert root in Path(bookbinder.__file__).resolve().parents; assert root in Path(create_app.__code__.co_filename).resolve().parents; print('import paths ok')"
pytest -m mvp_unit
pytest -m mvp_integration
