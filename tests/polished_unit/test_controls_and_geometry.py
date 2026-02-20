from __future__ import annotations

import io

import pytest
from pypdf import PdfReader, PdfWriter

from bookbinder.imposition.core import BLANK_PAGE
from bookbinder.imposition.pdf_writer import _slot_geometry
from bookbinder.web.app import _parse_form_input

pytestmark = pytest.mark.polished_unit


def _single_page_reader(*, width: float = 300, height: float = 500) -> PdfReader:
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
    payload = io.BytesIO()
    writer.write(payload)
    payload.seek(0)
    return PdfReader(payload)


@pytest.mark.parametrize(
    ("paper_size", "scaling_mode", "output_mode", "expected_error"),
    [
        ("A0", "proportional", "aggregated", "Invalid paper size. Choose one of:"),
        ("A4", "zoom", "aggregated", "Invalid scaling mode. Choose proportional, stretch, or original."),
        ("A4", "proportional", "single", "Invalid output mode. Choose one of: aggregated, signatures, both."),
    ],
)
def test_parse_form_input_rejects_invalid_controls(
    paper_size: str,
    scaling_mode: str,
    output_mode: str,
    expected_error: str,
) -> None:
    _, form_values, error = _parse_form_input(
        paper_size=paper_size,
        signature_length=6,
        flyleafs=0,
        duplex_rotate=False,
        custom_width_mm="",
        custom_height_mm="",
        scaling_mode=scaling_mode,
        output_mode=output_mode,
    )

    assert error is not None
    assert error.startswith(expected_error)
    assert form_values["paper_size"] == paper_size.strip()
    assert form_values["scaling_mode"] == scaling_mode
    assert form_values["output_mode"] == output_mode.strip().lower()


@pytest.mark.parametrize(
    ("width_mm", "height_mm", "expected_error"),
    [
        ("abc", "210", "Custom paper dimensions must be numeric values in millimeters."),
        ("210", "xyz", "Custom paper dimensions must be numeric values in millimeters."),
        ("0", "210", "Custom paper dimensions must be greater than 0 mm."),
        ("210", "-1", "Custom paper dimensions must be greater than 0 mm."),
    ],
)
def test_parse_form_input_rejects_invalid_custom_dimensions(
    width_mm: str,
    height_mm: str,
    expected_error: str,
) -> None:
    _, _, error = _parse_form_input(
        paper_size="Custom",
        signature_length=6,
        flyleafs=0,
        duplex_rotate=False,
        custom_width_mm=width_mm,
        custom_height_mm=height_mm,
        scaling_mode="proportional",
        output_mode="aggregated",
    )

    assert error == expected_error


def test_parse_form_input_accepts_custom_dimensions_and_normalizes_output_mode() -> None:
    options, form_values, error = _parse_form_input(
        paper_size="Custom",
        signature_length=6,
        flyleafs=1,
        duplex_rotate=True,
        custom_width_mm=" 210 ",
        custom_height_mm=" 297 ",
        scaling_mode="stretch",
        output_mode=" BOTH ",
    )

    assert error is None
    assert options.output_mode == "both"
    assert options.custom_width_points == pytest.approx(595.2756, abs=0.2)
    assert options.custom_height_points == pytest.approx(841.8898, abs=0.2)
    assert form_values["output_mode"] == "both"


@pytest.mark.parametrize(
    ("scaling_mode", "fits_slot"),
    [
        ("proportional", True),
        ("stretch", True),
        ("original", False),
    ],
)
@pytest.mark.parametrize("slot_index", [0, 1])
def test_slot_geometry_keeps_rendered_page_within_slot_for_supported_scaling_modes(
    scaling_mode: str,
    fits_slot: bool,
    slot_index: int,
) -> None:
    reader = _single_page_reader(width=200, height=100)

    geometry = _slot_geometry(
        reader=reader,
        token=0,
        slot_index=slot_index,
        output_width=200,
        output_height=300,
        blank_token=BLANK_PAGE,
        scaling_mode=scaling_mode,
    )

    assert geometry.slot_index == slot_index
    assert geometry.slot_width == pytest.approx(100.0)
    assert geometry.slot_height == pytest.approx(300.0)
    if fits_slot:
        assert geometry.rendered_width <= geometry.slot_width
        assert geometry.rendered_height <= geometry.slot_height
        assert geometry.slot_x <= geometry.x_offset <= geometry.slot_x + geometry.slot_width
    else:
        assert geometry.rendered_width > geometry.slot_width
        assert geometry.x_offset < geometry.slot_x
    assert 0.0 <= geometry.y_offset <= geometry.slot_height


def test_slot_geometry_blank_token_has_zero_rendered_size() -> None:
    reader = _single_page_reader(width=200, height=100)

    geometry = _slot_geometry(
        reader=reader,
        token=BLANK_PAGE,
        slot_index=1,
        output_width=200,
        output_height=300,
        blank_token=BLANK_PAGE,
        scaling_mode="proportional",
    )

    assert geometry.rendered_width == 0.0
    assert geometry.rendered_height == 0.0
    assert geometry.scale is None
    assert geometry.scale_x is None
    assert geometry.scale_y is None


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
