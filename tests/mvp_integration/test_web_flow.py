from __future__ import annotations

import io
import os
import re
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfWriter
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
        paper_size="Tabloid",
        signature_length=6,
        flyleafs=0,
        duplex_rotate=False,
    )
    assert form_values["paper_size"] == "Tabloid"
    assert error == "Invalid paper size. Choose A4 or Letter."
