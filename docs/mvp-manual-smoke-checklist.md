# MVP Manual Smoke Checklist

Use this checklist after automated gates pass.

## Setup

1. Install dependencies: `python -m pip install -c constraints/worker-runtime.txt -e '.[dev]'`
2. Start app: `uvicorn bookbinder.web.app:app --reload`
3. Open `http://127.0.0.1:8000`

## Smoke Steps

1. Upload `sample-pdfs/Destruction_and_Creation_John_Boyd.pdf`.
2. Use:
   - Paper size: `A4`
   - Signature length: `6`
   - Flyleaf sets: `1`
   - Duplex rotate: `off`
3. Click **Generate** and confirm a success status with download link.
4. Download output PDF and visually verify first two imposed sheets look correctly paired.
5. Repeat with **Duplex rotate** enabled and verify back-side pairing direction flips.
6. Repeat the same flow for `sample-pdfs/Psychology_of_Intelligence_Analysis.pdf`.

## Expected Outcome

- No crashes for valid PDFs.
- Validation errors are clear for invalid input.
- Generated PDFs are downloadable and match expected page counts.
