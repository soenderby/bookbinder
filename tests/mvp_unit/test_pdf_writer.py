from __future__ import annotations

import io
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from bookbinder.imposition.core import BLANK_PAGE
from bookbinder.imposition.pdf_writer import (
    _place_token,
    deterministic_preview_filename,
    deterministic_output_filename,
    resolve_paper_dimensions,
    write_first_sheet_preview,
    write_duplex_aggregated_pdf,
)

pytestmark = pytest.mark.mvp_unit


def _single_page_reader() -> PdfReader:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=500)
    payload = io.BytesIO()
    writer.write(payload)
    payload.seek(0)
    return PdfReader(payload)


class _FakeImposedPage:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []

    def merge_transformed_page(self, source_page, transform) -> None:
        self.calls.append((source_page, transform))


def test_resolve_paper_dimensions_rejects_unknown_paper_size() -> None:
    with pytest.raises(ValueError, match="unsupported paper size 'Unknown'"):
        resolve_paper_dimensions("Unknown")


@pytest.mark.parametrize(
    ("source_name", "expected"),
    [
        ("Quarterly Report (Final).pdf", "quarterly_report_final_imposed_duplex.pdf"),
        ("!!!.pdf", "output_imposed_duplex.pdf"),
        ("", "output_imposed_duplex.pdf"),
        ("docs/My Input v2.PDF", "my_input_v2_imposed_duplex.pdf"),
    ],
)
def test_deterministic_output_filename_handles_slug_edge_cases(source_name: str, expected: str) -> None:
    assert deterministic_output_filename(source_name) == expected


@pytest.mark.parametrize(
    ("source_name", "expected"),
    [
        ("Quarterly Report (Final).pdf", "quarterly_report_final_preview_sheet1.pdf"),
        ("!!!.pdf", "output_preview_sheet1.pdf"),
        ("", "output_preview_sheet1.pdf"),
        ("docs/My Input v2.PDF", "my_input_v2_preview_sheet1.pdf"),
    ],
)
def test_deterministic_preview_filename_handles_slug_edge_cases(source_name: str, expected: str) -> None:
    assert deterministic_preview_filename(source_name) == expected


def test_place_token_skips_blank_sentinel() -> None:
    imposed_page = _FakeImposedPage()
    reader = _single_page_reader()

    _place_token(
        imposed_page,
        reader=reader,
        token=BLANK_PAGE,
        slot_index=0,
        output_width=595.2756,
        output_height=841.8898,
        blank_token=BLANK_PAGE,
    )

    assert imposed_page.calls == []


def test_place_token_rejects_invalid_non_integer_token() -> None:
    imposed_page = _FakeImposedPage()
    reader = _single_page_reader()

    with pytest.raises(ValueError, match=r"expected int page token or blank token, got 'oops'"):
        _place_token(
            imposed_page,
            reader=reader,
            token="oops",
            slot_index=0,
            output_width=595.2756,
            output_height=841.8898,
            blank_token=BLANK_PAGE,
        )


def test_write_duplex_aggregated_pdf_surfaces_invalid_token_error(tmp_path: Path) -> None:
    reader = _single_page_reader()
    output_path = tmp_path / "out.pdf"

    with pytest.raises(ValueError, match=r"expected int page token or blank token, got 'bad'"):
        write_duplex_aggregated_pdf(
            reader=reader,
            signatures=[["bad", 0, 0, 0]],
            output_path=output_path,
            paper_size="A4",
            duplex_rotate=False,
        )


def test_write_first_sheet_preview_surfaces_invalid_token_error(tmp_path: Path) -> None:
    reader = _single_page_reader()
    output_path = tmp_path / "preview.pdf"

    with pytest.raises(ValueError, match=r"expected int page token or blank token, got 'bad'"):
        write_first_sheet_preview(
            reader=reader,
            signatures=[["bad", 0, 0, 0]],
            output_path=output_path,
            paper_size="A4",
            duplex_rotate=False,
        )
