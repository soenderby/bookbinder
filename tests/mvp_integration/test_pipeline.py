from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from bookbinder.constants import PAPER_SIZES
from bookbinder.imposition.core import BLANK_PAGE, build_ordered_pages, split_signatures
from bookbinder.imposition.pdf_writer import (
    deterministic_output_filename,
    write_duplex_aggregated_pdf,
)

pytestmark = pytest.mark.mvp_integration

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "sample-pdfs" / "expected_output" / "manifest.json"
SAMPLE_DIR = ROOT / "sample-pdfs"


def _numeric_pdf_bytes(page_count: int) -> bytes:
    writer = PdfWriter()
    for index in range(page_count):
        writer.add_blank_page(width=300 + index, height=500 + index)
    payload = io.BytesIO()
    writer.write(payload)
    return payload.getvalue()


def test_manifest_samples_generate_expected_page_counts_and_dimensions(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    for case in manifest["cases"]:
        source_path = SAMPLE_DIR / case["input"]
        reader = PdfReader(source_path)
        settings = case["settings"]

        ordered_pages = build_ordered_pages(
            list(range(len(reader.pages))),
            flyleaf_sets=settings["flyleafs"],
        )
        signatures = split_signatures(
            ordered_pages,
            sig_length_sheets=settings["signature_length"],
        )

        output_path = tmp_path / deterministic_output_filename(case["input"])
        artifact = write_duplex_aggregated_pdf(
            reader,
            signatures=signatures,
            output_path=output_path,
            paper_size=settings["paper_size"],
            duplex_rotate=settings["duplex_rotate"],
        )

        expected_page_count = sum(entry["pages"] for entry in case["outputs"])
        assert artifact.page_count == expected_page_count

        generated_reader = PdfReader(output_path)
        assert len(generated_reader.pages) == expected_page_count
        expected_width, expected_height = PAPER_SIZES[settings["paper_size"]]
        first_page = generated_reader.pages[0]
        assert float(first_page.mediabox.width) == pytest.approx(expected_width, abs=0.2)
        assert float(first_page.mediabox.height) == pytest.approx(expected_height, abs=0.2)


def test_numeric_nine_page_sequence_first_signature(tmp_path: Path) -> None:
    source_pdf = tmp_path / "numeric9.pdf"
    source_pdf.write_bytes(_numeric_pdf_bytes(9))

    reader = PdfReader(source_pdf)
    ordered_pages = build_ordered_pages(list(range(9)), flyleaf_sets=0)
    signatures = split_signatures(ordered_pages, sig_length_sheets=6)

    output_path = tmp_path / "numeric9_imposed.pdf"
    artifact = write_duplex_aggregated_pdf(
        reader,
        signatures=signatures,
        output_path=output_path,
        paper_size="A4",
        duplex_rotate=False,
    )

    assert artifact.placed_tokens == [
        (BLANK_PAGE, 0),
        (1, BLANK_PAGE),
        (BLANK_PAGE, 2),
        (3, 8),
        (7, 4),
        (5, 6),
    ]
