# MVP Acceptance Verification

Verification date: 2026-02-20

## SPEC 3.6 Acceptance Criteria

1. Any valid PDF produces output or a clear validation error.
- Status: PASS
- Evidence:
  - `tests/mvp_integration/test_web_flow.py::test_upload_generate_and_download`
  - `tests/mvp_integration/test_web_flow.py::test_reject_non_pdf_upload`
  - `tests/mvp_integration/test_web_flow.py::test_reject_missing_upload`
  - `tests/mvp_integration/test_web_flow.py::test_reject_empty_pdf_upload`
  - `tests/mvp_integration/test_web_flow.py::test_reject_encrypted_pdf_upload`

2. Output page count equals expected imposed-sheet page count.
- Status: PASS
- Evidence:
  - `tests/mvp_integration/test_pipeline.py::test_manifest_samples_generate_expected_page_counts_and_dimensions`

3. Folio ordering is correct for duplex and duplex-rotate.
- Status: PASS
- Evidence:
  - `tests/mvp_unit/test_core.py::test_folio_mapping_duplex_normal`
  - `tests/mvp_unit/test_core.py::test_folio_mapping_duplex_rotate`
  - `tests/mvp_integration/test_pipeline.py::test_numeric_nine_page_sequence_first_signature`

4. Blank-page insertions do not crash output generation.
- Status: PASS
- Evidence:
  - `tests/mvp_unit/test_core.py::test_build_ordered_pages_pipeline`
  - `tests/mvp_integration/test_pipeline.py::test_manifest_samples_generate_expected_page_counts_and_dimensions`

5. For at least one numeric-page test PDF, page order matches expected sequence.
- Status: PASS
- Evidence:
  - `tests/mvp_integration/test_pipeline.py::test_numeric_nine_page_sequence_first_signature`

6. Request-scoped download endpoint rejects invalid request IDs and malformed filenames with `400`, and returns `404` for missing artifacts.
- Status: PASS
- Evidence:
  - `tests/mvp_integration/test_web_flow.py::test_download_rejects_invalid_request_id`
  - `tests/mvp_integration/test_web_flow.py::test_download_rejects_path_traversal_filename`
  - `tests/mvp_integration/test_web_flow.py::test_download_request_artifact_missing_returns_404`
  - `tests/mvp_integration/test_web_flow.py::test_legacy_download_path_resolution_and_errors`

## SPEC 3.7 Gate Evidence

- `./scripts/run-mvp-gates.sh` (installs via `constraints/worker-runtime.txt`) -> PASS
- `pytest -m mvp_unit -vv` -> PASS (`8 passed, 18 deselected`)
- `pytest -m mvp_integration -vv` -> PASS (`18 passed, 8 deselected`)
- `pytest -vv` -> PASS (`26 passed`)

Manual smoke checklist document is present at `docs/mvp-manual-smoke-checklist.md`.
