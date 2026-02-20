# Bookbinder (Python) Specification

## 1. Overview

Create a web app similar to `bookbinder-js` that performs PDF imposition for **folio layout only**.

### Goal
- Upload a source PDF and generate print-ready folio-imposed output PDF(s).

### Explicit Scope Constraint
- **Wacky Small Layouts are out of scope.**
- Only **Folio** layout is required.

### Primary Target Stack
- Backend: Python 3.12+
- Web framework: FastAPI (or Flask; FastAPI preferred)
- PDF processing: `pypdf`
- Frontend: server-rendered HTML + minimal CSS (no JS framework required)
- Test framework: `pytest`

---

## 2. Functional Model (Common to MVP and Polished)

## 2.1 Core Concepts
- `ordered_pages`: source pages plus blanks/flyleafs and padding.
- `signature`: a block of sheets; each sheet = 4 folio pages.
- `per_sheet = 4` (fixed for folio).
- `blank page token`: internal sentinel for inserted blank pages.

## 2.2 Folio Imposition Rules
Use folio mappings equivalent to `bookbinder-js`:
- Front side: `[3, 2]`
- Back side (normal duplex): `[1, 4]`
- Back side (duplex-rotate): `[4, 1]`

## 2.3 Pagination Rules
1. Read source page count `N`.
2. Add flyleaf pages (if enabled): `2` blanks at start and `2` blanks at end per flyleaf set.
3. Pad with blanks so total pages is divisible by `4`.
4. Split into signatures according to configuration.
5. Impose each signature using folio mappings.

## 2.4 Output Types
- Duplex aggregated PDF (required MVP).
- Additional output variants may be added in Polished phase.

---

## 3. Phase 1: MVP

## 3.1 MVP Objective
Deliver a reliable folio-only imposition tool that works end-to-end for common use.

## 3.2 MVP Features
1. Upload input PDF.
2. Select paper size: `A4` or `Letter`.
3. Signature format: standard signature length (`sig_length` in sheets).
4. Optional flyleaf count (`0+`).
5. Duplex rotate toggle.
6. Generate **single duplex imposed PDF**.
7. Download result.

## 3.3 MVP Non-Goals
- No preview rendering.
- No crop/fold/sewing marks.
- No custom signature pattern input.
- No source-page rotation controls.
- No multi-layout support beyond folio.

## 3.4 MVP UX
- Single page form:
  - file input
  - paper size
  - signature length
  - flyleaf count
  - duplex rotate checkbox
  - generate button
- Result section:
  - success/failure status
  - generated file download link

## 3.5 MVP System Design
- `imposition/core.py`
  - pure folio algorithms (page ordering/splitting/mapping)
- `imposition/pdf_writer.py`
  - page placement, transforms, output document assembly
- `web/app.py`
  - request handling and file upload/download endpoints
- `tests/`
  - unit + integration tests

## 3.6 MVP Acceptance Criteria
1. Any valid PDF produces output or a clear validation error.
2. Output page count equals expected imposed-sheet page count.
3. Folio ordering is correct for duplex and duplex-rotate.
4. Blank-page insertions do not crash output generation.
5. For at least one numeric-page test PDF, page order matches expected sequence.
6. Request-scoped download endpoint rejects invalid request IDs and malformed filenames with `400`, and returns `404` for missing artifacts.

## 3.7 MVP Functionality Checks (Required Gate)

### Automated Checks
- `pytest -m mvp_unit`
  - page padding to multiple of 4
  - flyleaf insertion
  - signature splitting
  - folio front/back mapping
- `pytest -m mvp_integration`
  - generate imposed output from sample PDFs
  - assert output page count
  - assert mapped page index sequence for first signature

### Manual Smoke Checks
1. Upload sample numeric PDF and generate output.
2. Open output and verify first 2 imposed sheets visually.
3. Repeat with duplex rotate ON and verify back-side inversion behavior.

### MVP Exit Condition
- All automated checks pass.
- Manual smoke checklist passes on all provided sample PDFs.

---

## 4. Phase 2: Polished

## 4.1 Polished Objective
Add production-quality usability, configurability, and regression safety while staying folio-first.

## 4.2 Polished Features
1. Live preview for first imposed sheet (rendered thumbnail or downloadable preview PDF).
2. More paper sizes + custom paper size input.
3. Page scaling modes:
   - keep proportional
   - stretch
   - original size / centered
4. Page positioning modes:
   - centered
   - binding-aligned
5. Custom signatures list (e.g., `10,10,8`).
6. Output options:
   - aggregated
   - per-signature PDFs
   - both
7. Optional print marks:
   - crop marks
   - fold marks
   - signature order marks (minimal)
8. Better error reporting and job logging.
9. Persist last-used settings in browser local storage.

## 4.3 Polished Non-Goals
- Wacky Small Layouts.
- Non-folio layouts unless explicitly added later.

## 4.4 Polished Acceptance Criteria
1. All MVP scenarios continue to pass unchanged.
2. New controls produce deterministic output.
3. Preview matches generated output geometry for tested cases.
4. Custom signature validation rejects malformed input safely.
5. Performance: process a 300-page PDF within acceptable local runtime target (define target during implementation, e.g., < 20s on reference machine).

## 4.5 Polished Functionality Checks (Required Gate)

### Automated Checks
- `pytest -m polished_unit`
  - custom signature parsing and validation
  - scaling and positioning math
  - mark placement bounds
- `pytest -m polished_integration`
  - matrix tests across:
    - paper sizes
    - scaling modes
    - positioning modes
    - duplex rotate on/off
  - output metadata and page-count verification
- Snapshot checks (golden outputs for provided sample PDFs):
  - compare rendered page images or extracted transform metadata

### Manual Validation
1. Cross-check 3 sample PDFs (portrait, landscape, mixed sizes).
2. Verify preview/output consistency.
3. Validate each output mode (aggregated, signatures, both).
4. Validate malformed input handling (non-PDF file, encrypted PDF, empty upload).

### Polished Exit Condition
- MVP and polished automated suites all pass.
- Snapshot baseline accepted.
- Manual validation checklist complete.

---

## 5. Test Asset Contract (Using Current Repository Samples)

Use the sample assets already committed under:
- `sample-pdfs/`

Current source PDFs:
1. `sample-pdfs/Destruction_and_Creation_John_Boyd.pdf` (`9` pages, Letter-sized source pages)
2. `sample-pdfs/Psychology_of_Intelligence_Analysis.pdf` (`214` pages, Letter-sized source pages)

Current golden outputs (from existing tool behavior):
1. `sample-pdfs/expected_output/destruction_and_creation_output/destruction_and_creation_john_boyd_signature0_duplex.pdf` (`8` pages, A4 output pages)
2. `sample-pdfs/expected_output/psychology_of_intelligence_analysis_output/psychology_of_intelligence_analysis_signature*.pdf` (10 signature files, each A4-sized)

Baseline generation settings for these goldens:
1. paper size: `A4`
2. printer type: `duplex`
3. source rotation: `none`
4. alternate page rotation (`duplex_rotate`): `false`
5. page layout: `folio`
6. signature mode: `standardsig`
7. signature length: `6`
8. flyleafs: `1`
9. style modifications: `none`

### 5.1 Golden Comparison Strategy
1. Primary check:
   - generated file count matches expected file count per sample set
   - generated output page counts match golden output page counts
2. Secondary check:
   - compare first-page dimensions against golden outputs
3. Tertiary check (Polished phase):
   - visual snapshot compare (rendered PNGs), or
   - transform-metadata compare if rendering is not available in CI

### 5.2 Configuration Manifest Requirement
Add a manifest file so tests are deterministic:
- `sample-pdfs/expected_output/manifest.json`

Manifest must include, per source PDF:
1. input filename
2. generation settings (paper size, flyleafs, signature mode/length/custom config, duplex rotate)
3. expected output filenames
4. expected page counts per output file

Without this manifest, golden-output comparisons can still validate shape (file count/page count/dimensions), but cannot guarantee strict behavioral equivalence.

---

## 6. Risks and Mitigations

1. **PDF transform inconsistencies** across libraries.
- Mitigation: lock `pypdf` version and use snapshot tests.

2. **Blank/encrypted PDF edge cases**.
- Mitigation: explicit pre-validation and user-facing errors.

3. **Printer-specific duplex behavior confusion**.
- Mitigation: include duplex-rotate toggle with clear description and test sheet guidance.

---

## 7. Delivery Sequence

1. Implement MVP and pass MVP functionality gate.
2. Freeze MVP baseline snapshots.
3. Implement Polished features incrementally.
4. Pass full polished functionality gate.

This spec intentionally keeps folio imposition as the stable core and adds polish without introducing non-folio layout complexity.
