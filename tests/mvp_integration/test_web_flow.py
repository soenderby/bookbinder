from __future__ import annotations

import io
import re
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


def test_upload_generate_and_download(tmp_path: Path) -> None:
    app = create_app(artifact_dir=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/impose",
        data={
            "paper_size": "A4",
            "signature_length": "6",
            "flyleafs": "0",
        },
        files={"file": ("input.pdf", _pdf_bytes(9), "application/pdf")},
    )

    assert response.status_code == 200
    assert "Imposition complete." in response.text

    match = re.search(r'href="(/download/[^"]+)"', response.text)
    assert match is not None

    download_response = client.get(match.group(1))
    assert download_response.status_code == 200
    assert download_response.headers["content-type"].startswith("application/pdf")


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
