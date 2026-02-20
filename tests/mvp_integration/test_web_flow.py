from __future__ import annotations

import io
import os
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from bookbinder.web.app import create_app

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


def _extract_download_url(response_text: str) -> str:
    match = re.search(r'href="(/download/[^"]+)"', response_text)
    assert match is not None
    return match.group(1)


def _post_impose(client: TestClient, *, filename: str = "input.pdf") -> tuple[int, str]:
    response = client.post(
        "/impose",
        data={
            "paper_size": "A4",
            "signature_length": "6",
            "flyleafs": "0",
        },
        files={"file": (filename, _pdf_bytes(9), "application/pdf")},
    )
    return response.status_code, response.text


def test_upload_generate_and_download(tmp_path: Path) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    status_code, response_text = _post_impose(client)

    assert status_code == 200
    assert "Imposition complete." in response_text

    download_url = _extract_download_url(response_text)
    assert re.fullmatch(r"/download/[a-f0-9]{32}/[^/]+", download_url)

    download_response = client.get(download_url)
    assert download_response.status_code == 200
    assert download_response.headers["content-type"].startswith("application/pdf")


def test_same_filename_uploads_get_unique_request_scoped_artifacts(tmp_path: Path) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    first_status, first_text = _post_impose(client, filename="shared.pdf")
    second_status, second_text = _post_impose(client, filename="shared.pdf")

    assert first_status == 200
    assert second_status == 200

    first_download = _extract_download_url(first_text)
    second_download = _extract_download_url(second_text)
    assert first_download != second_download

    assert client.get(first_download).status_code == 200
    assert client.get(second_download).status_code == 200

    generated_artifacts = list(tmp_path.glob("*/*.pdf"))
    assert len(generated_artifacts) == 2


@pytest.mark.parametrize("request_id", ["invalid", "abc", "g" * 32, "A" * 32])
def test_download_rejects_invalid_request_id(tmp_path: Path, request_id: str) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    response = client.get(f"/download/{request_id}/output.pdf")

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid request id"}


@pytest.mark.parametrize("filename", ["nested/secret.pdf", "nested/inner/secret.pdf"])
def test_download_rejects_path_traversal_filename(tmp_path: Path, filename: str) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    response = client.get(f"/download/{'a' * 32}/{filename}")

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid filename"}


def test_download_request_artifact_missing_returns_404(tmp_path: Path) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    response = client.get(f"/download/{'a' * 32}/missing.pdf")

    assert response.status_code == 404
    assert response.json() == {"detail": "File not found"}


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

    app = create_app(artifact_dir=tmp_path, artifact_retention_seconds=60)
    client = TestClient(app)

    status_code, response_text = _post_impose(client)
    assert status_code == 200
    assert "Imposition complete." in response_text

    assert not stale_request_dir.exists()
    assert not stale_legacy_file.exists()
    assert fresh_marker_file.exists()


def test_reject_non_pdf_upload(tmp_path: Path) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/impose",
        data={
            "paper_size": "A4",
            "signature_length": "6",
            "flyleafs": "0",
        },
        files={"file": ("input.txt", b"not a pdf", "text/plain")},
    )

    assert response.status_code == 400
    assert "Only .pdf uploads are supported." in response.text


def test_reject_missing_upload(tmp_path: Path) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/impose",
        data={
            "paper_size": "A4",
            "signature_length": "6",
            "flyleafs": "0",
        },
    )

    assert response.status_code == 400
    assert "Upload a PDF file to continue." in response.text


def test_reject_empty_pdf_upload(tmp_path: Path) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/impose",
        data={
            "paper_size": "A4",
            "signature_length": "6",
            "flyleafs": "0",
        },
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )

    assert response.status_code == 400
    assert "The uploaded file is empty." in response.text


def test_reject_encrypted_pdf_upload(tmp_path: Path) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/impose",
        data={
            "paper_size": "A4",
            "signature_length": "6",
            "flyleafs": "0",
        },
        files={"file": ("locked.pdf", _pdf_bytes(4, encrypted=True), "application/pdf")},
    )

    assert response.status_code == 400
    assert "Encrypted PDFs are not supported for MVP" in response.text
