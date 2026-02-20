from __future__ import annotations

from dataclasses import dataclass

import pytest

from bookbinder.imposition.pdf_writer import _slot_transform, resolve_positioning_mode

pytestmark = pytest.mark.mvp_unit


@dataclass(frozen=True)
class _MediaBox:
    width: float
    height: float


@dataclass(frozen=True)
class _Page:
    mediabox: _MediaBox


def _translation(transform) -> tuple[float, float]:
    _, _, _, _, x_offset, y_offset = transform.ctm
    return x_offset, y_offset


def test_slot_transform_centered_positioning_offsets() -> None:
    source_page = _Page(_MediaBox(width=400, height=1000))
    output_width = 600.0
    output_height = 500.0

    left = _slot_transform(source_page, slot_index=0, output_width=output_width, output_height=output_height)
    right = _slot_transform(source_page, slot_index=1, output_width=output_width, output_height=output_height)

    assert _translation(left) == pytest.approx((50.0, 0.0))
    assert _translation(right) == pytest.approx((350.0, 0.0))


def test_slot_transform_binding_aligned_offsets() -> None:
    source_page = _Page(_MediaBox(width=400, height=1000))
    output_width = 600.0
    output_height = 500.0

    left = _slot_transform(
        source_page,
        slot_index=0,
        output_width=output_width,
        output_height=output_height,
        positioning_mode="binding_aligned",
    )
    right = _slot_transform(
        source_page,
        slot_index=1,
        output_width=output_width,
        output_height=output_height,
        positioning_mode="binding_aligned",
    )

    assert _translation(left) == pytest.approx((100.0, 0.0))
    assert _translation(right) == pytest.approx((300.0, 0.0))


def test_resolve_positioning_mode_normalizes_hyphenated_value() -> None:
    assert resolve_positioning_mode("binding-aligned") == "binding_aligned"


def test_resolve_positioning_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="unsupported positioning mode"):
        resolve_positioning_mode("outer_aligned")
