from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from bookbinder.constants import DEFAULT_ARTIFACT_DIR, PAPER_SIZES
from bookbinder.imposition.core import build_ordered_pages, split_signatures
from bookbinder.imposition.pdf_writer import (
    deterministic_output_filename,
    write_duplex_aggregated_pdf,
)


def create_app(artifact_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="Bookbinder", version="0.1.0")

    base_dir = Path(__file__).resolve().parent
    static_dir = base_dir / "static"
    templates = Jinja2Templates(directory=str(base_dir / "templates"))

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    target_artifact_dir = artifact_dir or (Path.cwd() / DEFAULT_ARTIFACT_DIR)
    target_artifact_dir.mkdir(parents=True, exist_ok=True)
    app.state.artifact_dir = target_artifact_dir
    app.state.templates = templates

    def render_index(
        request: Request,
        *,
        result: dict[str, Any] | None = None,
        form_values: dict[str, Any] | None = None,
        status_code: int = 200,
    ) -> HTMLResponse:
        defaults = {
            "paper_size": "A4",
            "signature_length": 6,
            "flyleafs": 0,
            "duplex_rotate": False,
        }
        if form_values:
            defaults.update(form_values)

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "result": result,
                "paper_sizes": sorted(PAPER_SIZES.keys()),
                "form": defaults,
            },
            status_code=status_code,
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return render_index(request)

    @app.post("/impose", response_class=HTMLResponse)
    async def impose(
        request: Request,
        file: UploadFile | None = File(default=None),
        paper_size: str = Form("A4"),
        signature_length: int = Form(6, ge=1),
        flyleafs: int = Form(0, ge=0),
        duplex_rotate: bool = Form(False),
    ) -> HTMLResponse:
        form_values = {
            "paper_size": paper_size,
            "signature_length": signature_length,
            "flyleafs": flyleafs,
            "duplex_rotate": duplex_rotate,
        }

        if paper_size not in PAPER_SIZES:
            return render_index(
                request,
                result={"status": "error", "message": "Invalid paper size. Choose A4 or Letter."},
                form_values=form_values,
                status_code=400,
            )

        if file is None or not file.filename:
            return render_index(
                request,
                result={"status": "error", "message": "Upload a PDF file to continue."},
                form_values=form_values,
                status_code=400,
            )

        source_name = Path(file.filename).name
        if Path(source_name).suffix.lower() != ".pdf":
            return render_index(
                request,
                result={
                    "status": "error",
                    "message": "Only .pdf uploads are supported.",
                },
                form_values=form_values,
                status_code=400,
            )

        payload = await file.read()
        if not payload:
            return render_index(
                request,
                result={"status": "error", "message": "The uploaded file is empty."},
                form_values=form_values,
                status_code=400,
            )

        try:
            reader = PdfReader(io.BytesIO(payload))
        except PdfReadError:
            return render_index(
                request,
                result={
                    "status": "error",
                    "message": "The file could not be read as a valid PDF.",
                },
                form_values=form_values,
                status_code=400,
            )

        if reader.is_encrypted:
            return render_index(
                request,
                result={
                    "status": "error",
                    "message": "Encrypted PDFs are not supported for MVP. Remove encryption and retry.",
                },
                form_values=form_values,
                status_code=400,
            )

        source_pages = list(range(len(reader.pages)))
        ordered_pages = build_ordered_pages(source_pages, flyleaf_sets=flyleafs)
        signatures = split_signatures(ordered_pages, sig_length_sheets=signature_length)

        output_name = deterministic_output_filename(source_name)
        output_path = app.state.artifact_dir / output_name
        artifact = write_duplex_aggregated_pdf(
            reader,
            signatures=signatures,
            output_path=output_path,
            paper_size=paper_size,
            duplex_rotate=duplex_rotate,
        )

        result = {
            "status": "success",
            "message": "Imposition complete.",
            "download_url": f"/download/{output_name}",
            "output_filename": output_name,
            "output_pages": artifact.page_count,
        }
        return render_index(request, result=result, form_values=form_values)

    @app.get("/download/{filename}")
    def download(filename: str) -> FileResponse:
        safe_name = Path(filename).name
        if safe_name != filename:
            raise HTTPException(status_code=400, detail="Invalid filename")

        file_path = app.state.artifact_dir / safe_name
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(path=file_path, media_type="application/pdf", filename=safe_name)

    return app


app = create_app()
