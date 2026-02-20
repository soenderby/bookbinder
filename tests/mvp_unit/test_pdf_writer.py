from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from bookbinder.imposition.core import BLANK_PAGE
from bookbinder.imposition.pdf_writer import (
    PrintMarksOptions,
    _build_print_mark_commands,
    _place_token,
    _slot_geometry,
    deterministic_preview_filename,
    deterministic_output_filename,
    resolve_paper_dimensions,
    write_first_sheet_preview,
    write_duplex_aggregated_pdf,
)

pytestmark = pytest.mark.mvp_unit


def _single_page_reader(*, width: float = 300, height: float = 500) -> PdfReader:
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
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
    with pytest.raises(ValueError, match="unsupported paper size 'A5', expected one of: A4, Letter"):
        resolve_paper_dimensions("A5")


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


@pytest.mark.parametrize(
    (
        "scaling_mode",
        "expected_scale_x",
        "expected_scale_y",
        "expected_rendered_width",
        "expected_rendered_height",
        "expected_x_offset",
        "expected_y_offset",
    ),
    [
        ("proportional", 0.5, 0.5, 100.0, 50.0, 100.0, 125.0),
        ("stretch", 0.5, 3.0, 100.0, 300.0, 100.0, 0.0),
        ("original", 1.0, 1.0, 200.0, 100.0, 50.0, 100.0),
    ],
)
def test_slot_geometry_applies_requested_scaling_mode(
    scaling_mode: str,
    expected_scale_x: float,
    expected_scale_y: float,
    expected_rendered_width: float,
    expected_rendered_height: float,
    expected_x_offset: float,
    expected_y_offset: float,
) -> None:
    reader = _single_page_reader(width=200, height=100)

    geometry = _slot_geometry(
        reader=reader,
        token=0,
        slot_index=1,
        output_width=200,
        output_height=300,
        blank_token=BLANK_PAGE,
        scaling_mode=scaling_mode,
    )

    assert geometry.slot_width == 100
    assert geometry.slot_height == 300
    assert geometry.rendered_width == pytest.approx(expected_rendered_width)
    assert geometry.rendered_height == pytest.approx(expected_rendered_height)
    assert geometry.scale_x == pytest.approx(expected_scale_x)
    assert geometry.scale_y == pytest.approx(expected_scale_y)
    assert geometry.x_offset == pytest.approx(expected_x_offset)
    assert geometry.y_offset == pytest.approx(expected_y_offset)
    if expected_scale_x == expected_scale_y:
        assert geometry.scale == pytest.approx(expected_scale_x)
    else:
        assert geometry.scale is None


def test_slot_geometry_rejects_unknown_scaling_mode() -> None:
    reader = _single_page_reader(width=200, height=100)

    with pytest.raises(
        ValueError,
        match="unsupported scaling mode 'invalid', expected one of: proportional, stretch, original",
    ):
        _slot_geometry(
            reader=reader,
            token=0,
            slot_index=0,
            output_width=200,
            output_height=300,
            blank_token=BLANK_PAGE,
            scaling_mode="invalid",  # type: ignore[arg-type]
        )


def test_write_duplex_aggregated_pdf_marks_disabled_keeps_baseline_output(tmp_path: Path) -> None:
    reader = _single_page_reader()
    signatures = [[0, BLANK_PAGE, BLANK_PAGE, BLANK_PAGE]]
    baseline_path = tmp_path / "baseline.pdf"
    disabled_path = tmp_path / "disabled.pdf"

    write_duplex_aggregated_pdf(
        reader=reader,
        signatures=signatures,
        output_path=baseline_path,
        paper_size="A4",
        duplex_rotate=False,
    )
    write_duplex_aggregated_pdf(
        reader=reader,
        signatures=signatures,
        output_path=disabled_path,
        paper_size="A4",
        duplex_rotate=False,
        print_marks=PrintMarksOptions(),
    )

    baseline_reader = PdfReader(str(baseline_path))
    disabled_reader = PdfReader(str(disabled_path))
    assert len(baseline_reader.pages) == len(disabled_reader.pages)
    for baseline_page, disabled_page in zip(baseline_reader.pages, disabled_reader.pages, strict=True):
        assert baseline_page._get_contents_as_bytes() == disabled_page._get_contents_as_bytes()


def test_write_duplex_aggregated_pdf_enabled_marks_injects_content(tmp_path: Path) -> None:
    reader = _single_page_reader()
    output_path = tmp_path / "marked.pdf"

    write_duplex_aggregated_pdf(
        reader=reader,
        signatures=[[0, BLANK_PAGE, BLANK_PAGE, BLANK_PAGE]],
        output_path=output_path,
        paper_size="A4",
        duplex_rotate=False,
        print_marks=PrintMarksOptions(crop=True, fold=True, signature_order=True),
    )

    generated = PdfReader(str(output_path))
    assert generated.pages
    first_page_bytes = generated.pages[0]._get_contents_as_bytes()
    assert first_page_bytes is not None
    assert b"bookbinder-print-marks" in first_page_bytes
    assert b" re f" in first_page_bytes


def test_build_print_mark_commands_stay_within_page_bounds() -> None:
    output_width = 40.0
    output_height = 30.0
    commands = _build_print_mark_commands(
        output_width=output_width,
        output_height=output_height,
        options=PrintMarksOptions(crop=True, fold=True, signature_order=True),
        signature_index=13,
        side_index=1,
    ).decode("ascii")
    for line_match in re.finditer(
        r"(?P<x1>-?\d+\.\d+) (?P<y1>-?\d+\.\d+) m (?P<x2>-?\d+\.\d+) (?P<y2>-?\d+\.\d+) l S",
        commands,
    ):
        x1 = float(line_match.group("x1"))
        y1 = float(line_match.group("y1"))
        x2 = float(line_match.group("x2"))
        y2 = float(line_match.group("y2"))
        assert 0.0 <= x1 <= output_width
        assert 0.0 <= x2 <= output_width
        assert 0.0 <= y1 <= output_height
        assert 0.0 <= y2 <= output_height

    rect_match = re.search(r"(?P<x>-?\d+\.\d+) (?P<y>-?\d+\.\d+) (?P<w>-?\d+\.\d+) (?P<h>-?\d+\.\d+) re f", commands)
    assert rect_match is not None
    x = float(rect_match.group("x"))
    y = float(rect_match.group("y"))
    width = float(rect_match.group("w"))
    height = float(rect_match.group("h"))
    assert 0.0 <= x <= output_width
    assert 0.0 <= y <= output_height
    assert width >= 0.0
    assert height >= 0.0
    assert x + width <= output_width
    assert y + height <= output_height
