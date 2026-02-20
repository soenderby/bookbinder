from __future__ import annotations

import io
import logging
import os
import re
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from starlette.datastructures import UploadFile

from bookbinder.web.app import (
    ImpositionOptions,
    _impose_payload,
    _parse_form_input,
    _resolve_legacy_artifact_path,
    _resolve_request_artifact_path,
    _validate_upload_metadata,
    create_app,
)

pytestmark = pytest.mark.mvp_integration


def _pdf_bytes(page_count: int, *, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    if encrypted:
        writer.encrypt("secret")

    payload = io.BytesIO()
    writer.write(payload)
    return payload.getvalue()


def _default_options() -> ImpositionOptions:
    options, _, error = _parse_form_input(
        paper_size="A4",
        signature_length=6,
        flyleafs=0,
        duplex_rotate=False,
        custom_width_mm="",
        custom_height_mm="",
    )
    assert error is None
    return options


def _request_parts(download_url: str) -> tuple[str, str]:
    parts = download_url.split("/", 3)
    assert len(parts) == 4
    _, _, request_id, filename = parts
    return request_id, filename


def test_upload_generate_and_download(tmp_path: Path) -> None:
    options = _default_options()
    source_name, upload_error = _validate_upload_metadata(
        UploadFile(filename="input.pdf", file=io.BytesIO(b"placeholder"))
    )
    assert upload_error is None
    assert source_name == "input.pdf"

    result, impose_error = _impose_payload(
        payload=_pdf_bytes(9),
        source_name=source_name,
        options=options,
        artifact_dir=tmp_path,
        artifact_retention_seconds=24 * 60 * 60,
    )

    assert impose_error is None
    assert result is not None
    assert result["status"] == "success"
    assert "Imposition complete." in result["message"]

    download_url = result["download_url"]
    assert re.fullmatch(r"/download/[a-f0-9]{32}/[^/]+", download_url)
    request_id, filename = _request_parts(download_url)
    resolved = _resolve_request_artifact_path(tmp_path, request_id, filename)
    assert resolved.is_file()
    assert resolved.suffix.lower() == ".pdf"


def test_impose_payload_emits_structured_success_log(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bookbinder.web")
    options = _default_options()

    result, impose_error = _impose_payload(
        payload=_pdf_bytes(9),
        source_name="input.pdf",
        options=options,
        artifact_dir=tmp_path,
        artifact_retention_seconds=24 * 60 * 60,
        job_id="job-123",
    )

    assert impose_error is None
    assert result is not None
    events = [record for record in caplog.records if getattr(record, "event_name", "") == "impose.job.completed"]
    assert len(events) == 1
    event = events[0]
    assert event.event_fields["job_id"] == "job-123"
    assert event.event_fields["source_name"] == "input.pdf"
    assert event.event_fields["output_pages"] == result["output_pages"]
    assert re.fullmatch(r"[a-f0-9]{32}", event.event_fields["request_id"])


def test_upload_generate_with_custom_dimensions(tmp_path: Path) -> None:
    options, _, error = _parse_form_input(
        paper_size="Custom",
        signature_length=6,
        flyleafs=0,
        duplex_rotate=False,
        custom_width_mm="210",
        custom_height_mm="297",
    )
    assert error is None

    result, impose_error = _impose_payload(
        payload=_pdf_bytes(9),
        source_name="input.pdf",
        options=options,
        artifact_dir=tmp_path,
        artifact_retention_seconds=24 * 60 * 60,
    )

    assert impose_error is None
    assert result is not None
    request_id, filename = _request_parts(result["download_url"])
    generated_path = _resolve_request_artifact_path(tmp_path, request_id, filename)
    generated_reader = PdfReader(generated_path)
    first_page = generated_reader.pages[0]
    assert float(first_page.mediabox.width) == pytest.approx(595.2756, abs=0.2)
    assert float(first_page.mediabox.height) == pytest.approx(841.8898, abs=0.2)


def test_health_endpoint_contract(tmp_path: Path) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_form_contains_required_mvp_controls(tmp_path: Path) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200

    html = response.text
    assert 'id="file"' in html
    assert 'name="file"' in html
    assert 'id="paper_size"' in html
    assert 'name="paper_size"' in html
    assert 'id="signature_length"' in html
    assert 'name="signature_length"' in html
    assert 'id="custom_width_mm"' in html
    assert 'name="custom_width_mm"' in html
    assert 'id="custom_height_mm"' in html
    assert 'name="custom_height_mm"' in html
    assert 'id="flyleafs"' in html
    assert 'name="flyleafs"' in html
    assert 'id="duplex_rotate"' in html
    assert 'name="duplex_rotate"' in html
    assert 'type="submit"' in html
    assert 'bookbinder.form.v1' in html
    assert 'window.localStorage' in html
    assert 'form.addEventListener("input", saveSettings);' in html
    assert 'form.addEventListener("change", saveSettings);' in html


def test_same_filename_uploads_get_unique_request_scoped_artifacts(tmp_path: Path) -> None:
    options = _default_options()
    payload = _pdf_bytes(9)

    first_result, first_error = _impose_payload(
        payload=payload,
        source_name="shared.pdf",
        options=options,
        artifact_dir=tmp_path,
        artifact_retention_seconds=24 * 60 * 60,
    )
    second_result, second_error = _impose_payload(
        payload=payload,
        source_name="shared.pdf",
        options=options,
        artifact_dir=tmp_path,
        artifact_retention_seconds=24 * 60 * 60,
    )

    assert first_error is None
    assert second_error is None
    assert first_result is not None
    assert second_result is not None
    assert first_result["download_url"] != second_result["download_url"]

    first_request_id, first_filename = _request_parts(first_result["download_url"])
    second_request_id, second_filename = _request_parts(second_result["download_url"])
    assert _resolve_request_artifact_path(tmp_path, first_request_id, first_filename).is_file()
    assert _resolve_request_artifact_path(tmp_path, second_request_id, second_filename).is_file()

    generated_artifacts = list(tmp_path.glob("*/*.pdf"))
    assert len(generated_artifacts) == 2


@pytest.mark.parametrize("request_id", ["invalid", "abc", "g" * 32, "A" * 32])
def test_download_rejects_invalid_request_id(tmp_path: Path, request_id: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _resolve_request_artifact_path(tmp_path, request_id, "output.pdf")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid request id"


@pytest.mark.parametrize("filename", ["nested/secret.pdf", "nested/inner/secret.pdf"])
def test_download_rejects_path_traversal_filename(tmp_path: Path, filename: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _resolve_request_artifact_path(tmp_path, "a" * 32, filename)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid filename"


def test_download_request_artifact_missing_returns_404(tmp_path: Path) -> None:
    request_dir = tmp_path / ("a" * 32)
    request_dir.mkdir()

    with pytest.raises(HTTPException) as exc_info:
        _resolve_request_artifact_path(tmp_path, "a" * 32, "missing.pdf")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "File not found"


def test_legacy_download_path_resolution_and_errors(tmp_path: Path) -> None:
    legacy_file = tmp_path / "legacy.pdf"
    legacy_file.write_bytes(b"legacy")

    resolved = _resolve_legacy_artifact_path(tmp_path, "legacy.pdf")
    assert resolved == legacy_file

    with pytest.raises(HTTPException) as missing_exc:
        _resolve_legacy_artifact_path(tmp_path, "missing.pdf")
    assert missing_exc.value.status_code == 404
    assert missing_exc.value.detail == "File not found"

    with pytest.raises(HTTPException) as invalid_exc:
        _resolve_legacy_artifact_path(tmp_path, "../legacy.pdf")
    assert invalid_exc.value.status_code == 400
    assert invalid_exc.value.detail == "Invalid filename"


def test_legacy_download_endpoint_serves_existing_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "legacy.pdf"
    artifact.write_bytes(b"legacy payload")

    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/download/legacy.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == b"legacy payload"


def test_legacy_download_endpoint_missing_artifact_returns_404(tmp_path: Path) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/download/missing.pdf")
    assert response.status_code == 404
    assert response.json() == {"detail": "File not found"}


def test_legacy_download_endpoint_rejects_path_traversal_filename(tmp_path: Path) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/download/..%5Csecret.pdf")
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid filename"}


def test_download_expired_request_artifact_returns_actionable_410(tmp_path: Path) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    expired_response = client.get(f"/download/{'a' * 32}/missing.pdf")
    assert expired_response.status_code == 410
    assert expired_response.json() == {
        "detail": "This download link has expired after cleanup. Regenerate the PDF to create a new link."
    }


def test_download_expired_request_artifact_renders_ui_guidance_for_html_clients(tmp_path: Path) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    response = client.get(
        f"/download/{'a' * 32}/missing.pdf",
        headers={"accept": "text/html"},
    )

    assert response.status_code == 410
    assert "This download link has expired after cleanup." in response.text
    assert "Regenerate the PDF to create a new link." in response.text


def test_cleanup_removes_stale_generated_artifacts(tmp_path: Path) -> None:
    stale_request_dir = tmp_path / ("a" * 32)
    stale_request_dir.mkdir()
    stale_request_file = stale_request_dir / "stale_imposed_duplex.pdf"
    stale_request_file.write_bytes(b"stale")

    stale_legacy_file = tmp_path / "legacy_imposed_duplex.pdf"
    stale_legacy_file.write_bytes(b"stale")

    fresh_marker_file = tmp_path / "fresh.marker"
    fresh_marker_file.write_text("fresh", encoding="utf-8")

    stale_timestamp = time.time() - 3600
    os.utime(stale_request_dir, (stale_timestamp, stale_timestamp))
    os.utime(stale_request_file, (stale_timestamp, stale_timestamp))
    os.utime(stale_legacy_file, (stale_timestamp, stale_timestamp))

    result, impose_error = _impose_payload(
        payload=_pdf_bytes(9),
        source_name="input.pdf",
        options=_default_options(),
        artifact_dir=tmp_path,
        artifact_retention_seconds=60,
    )

    assert impose_error is None
    assert result is not None
    assert result["status"] == "success"

    assert not stale_request_dir.exists()
    assert not stale_legacy_file.exists()
    assert fresh_marker_file.exists()


def test_reject_non_pdf_upload() -> None:
    source_name, error = _validate_upload_metadata(
        UploadFile(filename="input.txt", file=io.BytesIO(b"not a pdf"))
    )
    assert source_name is None
    assert error == "Only .pdf uploads are supported."


def test_reject_missing_upload() -> None:
    source_name, error = _validate_upload_metadata(None)
    assert source_name is None
    assert error == "Upload a PDF file to continue."


def test_reject_empty_pdf_upload(tmp_path: Path) -> None:
    result, error = _impose_payload(
        payload=b"",
        source_name="empty.pdf",
        options=_default_options(),
        artifact_dir=tmp_path,
        artifact_retention_seconds=24 * 60 * 60,
    )
    assert result is None
    assert error == "The uploaded file is empty."


def test_reject_invalid_pdf_upload_logs_actionable_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="bookbinder.web")
    result, error = _impose_payload(
        payload=b"not a pdf",
        source_name="broken.pdf",
        options=_default_options(),
        artifact_dir=tmp_path,
        artifact_retention_seconds=24 * 60 * 60,
        job_id="job-invalid",
    )

    assert result is None
    assert error == "The upload could not be parsed as a PDF. Verify the file is a valid, non-corrupted PDF and retry."
    events = [record for record in caplog.records if getattr(record, "event_name", "") == "impose.job.invalid_pdf"]
    assert len(events) == 1
    event = events[0]
    assert event.event_fields["job_id"] == "job-invalid"
    assert event.event_fields["source_name"] == "broken.pdf"
    assert event.event_fields["payload_bytes"] == len(b"not a pdf")


def test_reject_encrypted_pdf_upload(tmp_path: Path) -> None:
    result, error = _impose_payload(
        payload=_pdf_bytes(4, encrypted=True),
        source_name="locked.pdf",
        options=_default_options(),
        artifact_dir=tmp_path,
        artifact_retention_seconds=24 * 60 * 60,
    )
    assert result is None
    assert error is not None
    assert "Encrypted PDFs are not supported for MVP" in error


def test_parse_form_input_rejects_invalid_paper_size() -> None:
    _, form_values, error = _parse_form_input(
        paper_size="Unknown",
        signature_length=6,
        flyleafs=0,
        duplex_rotate=False,
        custom_width_mm="",
        custom_height_mm="",
    )
    assert form_values["paper_size"] == "Unknown"
    assert error is not None
    assert "Invalid paper size." in error


def test_parse_form_input_requires_numeric_custom_dimensions() -> None:
    _, _, error = _parse_form_input(
        paper_size="Custom",
        signature_length=6,
        flyleafs=0,
        duplex_rotate=False,
        custom_width_mm="abc",
        custom_height_mm="210",
    )
    assert error == "Custom paper dimensions must be numeric values in millimeters."


def test_parse_form_input_rejects_non_positive_custom_dimensions() -> None:
    _, _, error = _parse_form_input(
        paper_size="Custom",
        signature_length=6,
        flyleafs=0,
        duplex_rotate=False,
        custom_width_mm="0",
        custom_height_mm="-1",
    )
    assert error == "Custom paper dimensions must be greater than 0 mm."


def test_parse_form_input_accepts_valid_custom_dimensions() -> None:
    options, form_values, error = _parse_form_input(
        paper_size="Custom",
        signature_length=6,
        flyleafs=0,
        duplex_rotate=False,
        custom_width_mm="210",
        custom_height_mm="297",
    )
    assert error is None
    assert form_values["paper_size"] == "Custom"
    assert options.custom_width_points == pytest.approx(595.2756, abs=0.2)
    assert options.custom_height_points == pytest.approx(841.8898, abs=0.2)
