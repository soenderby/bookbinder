# Bookbinder (Python MVP)

Folio-only PDF imposition web app using FastAPI and `pypdf`.

## Run Locally

```bash
python -m pip install -c constraints/worker-runtime.txt -e '.[dev]'
uvicorn bookbinder.web.app:app --reload
```

Open `http://127.0.0.1:8000` and use the single-page form to upload a PDF and generate an imposed duplex output.

## Test Gates

Run the required MVP checks:

```bash
./scripts/run-mvp-gates.sh
```

Packaging smoke coverage for editable installs with a top-level `generated/` directory runs in `tests/mvp_unit/test_packaging.py` as part of `pytest -m mvp_unit`.

## MVP Notes

- Supported paper sizes: `A3`, `A4`, `A5`, `Letter`, `Legal`, `Tabloid`, and `Custom` (width/height in mm)
- Signature mode: standard fixed `sig_length` (in sheets)
- Output: single aggregated duplex PDF
- Generated artifacts are request-scoped under `generated/<request-id>/...`
- Stale generated artifacts older than 24 hours are cleaned on each `/impose` request
- Request/job logs are structured (`event_name`, `event_fields`) and include `job_id` for imposition failure diagnostics
- Unsupported in MVP: encrypted input PDFs, non-folio layouts
