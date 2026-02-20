from __future__ import annotations

import io
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from bookbinder.constants import (
    DEFAULT_ARTIFACT_DIR,
    DEFAULT_ARTIFACT_RETENTION_SECONDS,
    PAPER_SIZES,
)
from bookbinder.imposition.core import build_ordered_pages, split_signatures
from bookbinder.imposition.pdf_writer import (
    deterministic_output_filename,
    write_duplex_aggregated_pdf,
)

_REQUEST_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
_EXPIRED_ARTIFACT_MESSAGE = "This download link has expired after cleanup. Regenerate the PDF to create a new link."
_CUSTOM_PAPER_SIZE = "Custom"
_POINTS_PER_MM = 72.0 / 25.4


@dataclass(frozen=True)
class ImpositionOptions:
    paper_size: str
    signature_length: int
    flyleafs: int
    duplex_rotate: bool
    custom_width_points: float | None
    custom_height_points: float | None


def _cleanup_stale_artifacts(
    artifact_dir: Path,
    *,
    retention_seconds: int,
    now: float | None = None,
) -> int:
    if retention_seconds < 0:
        return 0

    cutoff = (time.time() if now is None else now) - retention_seconds
    removed = 0
    for child in artifact_dir.iterdir():
        try:
            is_stale = child.stat().st_mtime < cutoff
        except FileNotFoundError:
            continue

        if not is_stale:
            continue

        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
        removed += 1

    return removed


def _validated_filename(filename: str) -> str:
    if "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    safe_name = Path(filename).name
    if safe_name != filename or safe_name in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return safe_name


def _parse_form_input(
    *,
    paper_size: str,
    signature_length: int,
    flyleafs: int,
    duplex_rotate: bool,
    custom_width_mm: str,
    custom_height_mm: str,
) -> tuple[ImpositionOptions, dict[str, Any], str | None]:
    normalized_paper_size = paper_size.strip()
    width_mm_value = custom_width_mm.strip()
    height_mm_value = custom_height_mm.strip()

    options = ImpositionOptions(
        paper_size=normalized_paper_size,
        signature_length=signature_length,
        flyleafs=flyleafs,
        duplex_rotate=duplex_rotate,
        custom_width_points=None,
        custom_height_points=None,
    )
    form_values: dict[str, Any] = {
        "paper_size": options.paper_size,
        "signature_length": options.signature_length,
        "flyleafs": options.flyleafs,
        "duplex_rotate": options.duplex_rotate,
        "custom_width_mm": width_mm_value,
        "custom_height_mm": height_mm_value,
    }

    allowed_sizes = set(PAPER_SIZES)
    allowed_sizes.add(_CUSTOM_PAPER_SIZE)
    if options.paper_size not in allowed_sizes:
        valid_sizes = ", ".join(sorted(allowed_sizes))
        return options, form_values, f"Invalid paper size. Choose one of: {valid_sizes}."

    if options.paper_size == _CUSTOM_PAPER_SIZE:
        try:
            width_mm = float(width_mm_value)
            height_mm = float(height_mm_value)
        except ValueError:
            return options, form_values, "Custom paper dimensions must be numeric values in millimeters."

        if width_mm <= 0 or height_mm <= 0:
            return options, form_values, "Custom paper dimensions must be greater than 0 mm."

        options = ImpositionOptions(
            paper_size=options.paper_size,
            signature_length=options.signature_length,
            flyleafs=options.flyleafs,
            duplex_rotate=options.duplex_rotate,
            custom_width_points=width_mm * _POINTS_PER_MM,
            custom_height_points=height_mm * _POINTS_PER_MM,
        )

    return options, form_values, None


def _validate_upload_metadata(file: UploadFile | None) -> tuple[str | None, str | None]:
    if file is None or not file.filename:
        return None, "Upload a PDF file to continue."

    source_name = Path(file.filename).name
    if Path(source_name).suffix.lower() != ".pdf":
        return None, "Only .pdf uploads are supported."

    return source_name, None


def _impose_payload(
    *,
    payload: bytes,
    source_name: str,
    options: ImpositionOptions,
    artifact_dir: Path,
    artifact_retention_seconds: int,
) -> tuple[dict[str, Any] | None, str | None]:
    if not payload:
        return None, "The uploaded file is empty."

    try:
        reader = PdfReader(io.BytesIO(payload))
    except PdfReadError:
        return None, "The file could not be read as a valid PDF."

    if reader.is_encrypted:
        return None, "Encrypted PDFs are not supported for MVP. Remove encryption and retry."

    source_pages = list(range(len(reader.pages)))
    ordered_pages = build_ordered_pages(source_pages, flyleaf_sets=options.flyleafs)
    signatures = split_signatures(ordered_pages, sig_length_sheets=options.signature_length)

    _cleanup_stale_artifacts(
        artifact_dir,
        retention_seconds=artifact_retention_seconds,
    )

    request_id = uuid4().hex
    request_artifact_dir = artifact_dir / request_id
    output_name = deterministic_output_filename(source_name)
    output_path = request_artifact_dir / output_name
    artifact = write_duplex_aggregated_pdf(
        reader,
        signatures=signatures,
        output_path=output_path,
        paper_size=options.paper_size,
        duplex_rotate=options.duplex_rotate,
        custom_dimensions=(
            None
            if options.custom_width_points is None or options.custom_height_points is None
            else (options.custom_width_points, options.custom_height_points)
        ),
    )

    return {
        "status": "success",
        "message": "Imposition complete.",
        "download_url": f"/download/{request_id}/{output_name}",
        "output_filename": output_name,
        "output_pages": artifact.page_count,
    }, None


def _resolve_request_artifact_path(artifact_dir: Path, request_id: str, filename: str) -> Path:
    if _REQUEST_ID_PATTERN.fullmatch(request_id) is None:
        raise HTTPException(status_code=400, detail="Invalid request id")

    safe_name = _validated_filename(filename)
    request_artifact_dir = artifact_dir / request_id
    if not request_artifact_dir.is_dir():
        raise HTTPException(status_code=410, detail=_EXPIRED_ARTIFACT_MESSAGE)

    file_path = request_artifact_dir / safe_name
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return file_path


def _resolve_legacy_artifact_path(artifact_dir: Path, filename: str) -> Path:
    safe_name = _validated_filename(filename)
    file_path = artifact_dir / safe_name
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return file_path


def create_app(
    artifact_dir: Path | None = None,
    artifact_retention_seconds: int = DEFAULT_ARTIFACT_RETENTION_SECONDS,
) -> FastAPI:
    app = FastAPI(title="Bookbinder", version="0.1.0")

    base_dir = Path(__file__).resolve().parent
    static_dir = base_dir / "static"
    templates = Jinja2Templates(directory=str(base_dir / "templates"))

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    target_artifact_dir = artifact_dir or (Path.cwd() / DEFAULT_ARTIFACT_DIR)
    target_artifact_dir.mkdir(parents=True, exist_ok=True)
    app.state.artifact_dir = target_artifact_dir
    app.state.artifact_retention_seconds = artifact_retention_seconds
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
            "custom_width_mm": "",
            "custom_height_mm": "",
        }
        if form_values:
            defaults.update(form_values)

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "result": result,
                "paper_sizes": sorted(PAPER_SIZES.keys()) + [_CUSTOM_PAPER_SIZE],
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
        custom_width_mm: str = Form(""),
        custom_height_mm: str = Form(""),
    ) -> HTMLResponse:
        options, form_values, form_error = _parse_form_input(
            paper_size=paper_size,
            signature_length=signature_length,
            flyleafs=flyleafs,
            duplex_rotate=duplex_rotate,
            custom_width_mm=custom_width_mm,
            custom_height_mm=custom_height_mm,
        )
        if form_error is not None:
            return render_index(
                request,
                result={"status": "error", "message": form_error},
                form_values=form_values,
                status_code=400,
            )

        source_name, upload_error = _validate_upload_metadata(file)
        if upload_error is not None:
            return render_index(
                request,
                result={"status": "error", "message": upload_error},
                form_values=form_values,
                status_code=400,
            )

        if file is None or source_name is None:
            return render_index(
                request,
                result={"status": "error", "message": "Upload a PDF file to continue."},
                form_values=form_values,
                status_code=400,
            )

        payload = await file.read()
        result, impose_error = _impose_payload(
            payload=payload,
            source_name=source_name,
            options=options,
            artifact_dir=app.state.artifact_dir,
            artifact_retention_seconds=app.state.artifact_retention_seconds,
        )
        if impose_error is not None:
            return render_index(
                request,
                result={"status": "error", "message": impose_error},
                form_values=form_values,
                status_code=400,
            )

        if result is None:
            return render_index(
                request,
                result={"status": "error", "message": "Imposition failed."},
                form_values=form_values,
                status_code=500,
            )

        return render_index(request, result=result, form_values=form_values)

    @app.get("/download/{request_id}/{filename:path}")
    def download_request_artifact(request: Request, request_id: str, filename: str) -> Response:
        try:
            file_path = _resolve_request_artifact_path(app.state.artifact_dir, request_id, filename)
        except HTTPException as exc:
            if exc.status_code == 410 and "text/html" in request.headers.get("accept", ""):
                return render_index(
                    request,
                    result={"status": "error", "message": _EXPIRED_ARTIFACT_MESSAGE},
                    status_code=410,
                )
            raise

        return FileResponse(path=file_path, media_type="application/pdf", filename=file_path.name)

    @app.get("/download/{filename}")
    def download_legacy_artifact(filename: str) -> FileResponse:
        file_path = _resolve_legacy_artifact_path(app.state.artifact_dir, filename)
        return FileResponse(path=file_path, media_type="application/pdf", filename=file_path.name)

    return app


app = create_app()
