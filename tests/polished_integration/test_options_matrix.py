from __future__ import annotations

import io
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from bookbinder.constants import PAPER_SIZES
from bookbinder.imposition.core import build_ordered_pages, split_signatures
from bookbinder.web.app import _impose_payload, _parse_form_input, _resolve_request_artifact_path

pytestmark = pytest.mark.polished_integration


def _pdf_bytes(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)

    payload = io.BytesIO()
    writer.write(payload)
    return payload.getvalue()


def _request_parts(download_url: str) -> tuple[str, str]:
    _, _, request_id, filename = download_url.split("/", 3)
    return request_id, filename


@pytest.mark.parametrize(
    ("paper_size", "scaling_mode", "duplex_rotate", "output_mode"),
    [
        ("A4", "proportional", False, "aggregated"),
        ("A4", "proportional", True, "aggregated"),
        ("A4", "stretch", False, "signatures"),
        ("A4", "original", True, "both"),
        ("Letter", "proportional", False, "signatures"),
        ("Letter", "stretch", True, "both"),
        ("Letter", "original", False, "aggregated"),
    ],
)
def test_impose_payload_polished_options_matrix_preserves_output_invariants(
    tmp_path: Path,
    paper_size: str,
    scaling_mode: str,
    duplex_rotate: bool,
    output_mode: str,
) -> None:
    options, _, error = _parse_form_input(
        paper_size=paper_size,
        signature_length=1,
        flyleafs=0,
        duplex_rotate=duplex_rotate,
        custom_width_mm="",
        custom_height_mm="",
        scaling_mode=scaling_mode,
        output_mode=output_mode,
    )
    assert error is None

    result, impose_error = _impose_payload(
        payload=_pdf_bytes(9),
        source_name="matrix.pdf",
        options=options,
        artifact_dir=tmp_path,
        artifact_retention_seconds=24 * 60 * 60,
    )
    assert impose_error is None
    assert result is not None
    assert result["status"] == "success"
    assert result["output_mode"] == output_mode

    downloads = result["downloads"]
    assert result["output_count"] == len(downloads)
    assert result["download_url"] == downloads[0]["download_url"]
    assert result["output_filename"] == downloads[0]["output_filename"]
    assert result["preview_pages"] == 1
    assert len(result["preview_sheet"]["slots"]) == 2

    if output_mode == "aggregated":
        assert len(downloads) == 1
        assert downloads[0]["output_filename"].endswith("_imposed_duplex.pdf")
    elif output_mode == "signatures":
        assert len(downloads) == 3
        assert all(entry["output_filename"].endswith(f"_signature{idx}_duplex.pdf") for idx, entry in enumerate(downloads))
    else:
        assert len(downloads) == 4
        assert downloads[0]["output_filename"].endswith("_imposed_duplex.pdf")
        assert all(
            entry["output_filename"].endswith(f"_signature{idx}_duplex.pdf")
            for idx, entry in enumerate(downloads[1:])
        )

    measured_pages: list[int] = []
    for entry in downloads:
        request_id, filename = _request_parts(entry["download_url"])
        assert filename == entry["output_filename"]
        output_path = _resolve_request_artifact_path(tmp_path, request_id, filename)
        reader = PdfReader(output_path)
        measured_pages.append(len(reader.pages))
        assert entry["output_pages"] == len(reader.pages)
        first_page = reader.pages[0]
        width, height = PAPER_SIZES[paper_size]
        assert float(first_page.mediabox.width) == pytest.approx(width, abs=0.2)
        assert float(first_page.mediabox.height) == pytest.approx(height, abs=0.2)

    assert result["output_pages"] == sum(measured_pages)


def test_output_metadata_page_counts_align_with_signature_breakdown(tmp_path: Path) -> None:
    options, _, error = _parse_form_input(
        paper_size="A4",
        signature_length=2,
        flyleafs=1,
        duplex_rotate=True,
        custom_width_mm="",
        custom_height_mm="",
        scaling_mode="proportional",
        output_mode="both",
    )
    assert error is None

    result, impose_error = _impose_payload(
        payload=_pdf_bytes(9),
        source_name="counts.pdf",
        options=options,
        artifact_dir=tmp_path,
        artifact_retention_seconds=24 * 60 * 60,
    )
    assert impose_error is None
    assert result is not None

    source_pages = list(range(9))
    ordered_pages = build_ordered_pages(source_pages, flyleaf_sets=options.flyleafs)
    signatures = split_signatures(ordered_pages, sig_length_sheets=options.signature_length)
    expected_signature_pages = [len(signature) // 2 for signature in signatures]
    expected_aggregate_pages = sum(expected_signature_pages)

    downloads = result["downloads"]
    assert len(downloads) == 1 + len(expected_signature_pages)
    assert downloads[0]["output_pages"] == expected_aggregate_pages

    per_signature_downloads = downloads[1:]
    for expected_pages, download in zip(expected_signature_pages, per_signature_downloads, strict=True):
        assert download["output_pages"] == expected_pages

    assert result["output_pages"] == expected_aggregate_pages + sum(expected_signature_pages)
