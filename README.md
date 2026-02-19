# Bookbinder (Python MVP)

Folio-only PDF imposition web app using FastAPI and `pypdf`.

## Run Locally

```bash
python -m pip install -e .[dev]
uvicorn bookbinder.web.app:app --reload
```

Open `http://127.0.0.1:8000` and use the single-page form to upload a PDF and generate an imposed duplex output.

## Test Gates

Run the required MVP checks:

```bash
pytest -m mvp_unit
pytest -m mvp_integration
```

## MVP Notes

- Supported paper sizes: `A4`, `Letter`
- Signature mode: standard fixed `sig_length` (in sheets)
- Output: single aggregated duplex PDF
- Generated artifacts are request-scoped under `generated/<request-id>/...`
- Stale generated artifacts older than 24 hours are cleaned on each `/impose` request
- Unsupported in MVP: encrypted input PDFs, non-folio layouts
