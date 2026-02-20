from __future__ import annotations

import io
import logging
import re
import shutil
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from bookbinder.constants import (
    DEFAULT_ARTIFACT_DIR,
    DEFAULT_ARTIFACT_RETENTION_SECONDS,
    PAPER_SIZES,
)
from bookbinder.imposition.core import build_ordered_pages, split_signatures
from bookbinder.imposition.pdf_writer import (
    _SCALING_MODES,
    deterministic_preview_filename,
    deterministic_output_filename,
    write_first_sheet_preview,
    write_duplex_aggregated_pdf,
)

_REQUEST_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
_EXPIRED_ARTIFACT_MESSAGE = "This download link has expired after cleanup. Regenerate the PDF to create a new link."
_CUSTOM_PAPER_SIZE = "Custom"
_POINTS_PER_MM = 72.0 / 25.4
_LOGGER = logging.getLogger("bookbinder.web")
_PREVIEW_ACTION = "preview"
_GENERATE_ACTION = "generate"
_SUPPORTED_ACTIONS = {_PREVIEW_ACTION, _GENERATE_ACTION}
OutputMode = Literal["aggregated", "signatures", "both"]
_OUTPUT_MODES: tuple[OutputMode, ...] = ("aggregated", "signatures", "both")


@dataclass(frozen=True)
class ImpositionOptions:
    paper_size: str
    signature_length: int
    flyleafs: int
    duplex_rotate: bool
    custom_width_points: float | None
    custom_height_points: float | None
    scaling_mode: str
    output_mode: OutputMode


def _log_event(level: int, event_name: str, **event_fields: Any) -> None:
    _LOGGER.log(
        level,
        event_name,
        extra={"event_name": event_name, "event_fields": event_fields},
    )


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
    scaling_mode: str,
    output_mode: str,
) -> tuple[ImpositionOptions, dict[str, Any], str | None]:
    normalized_paper_size = paper_size.strip()
    normalized_output_mode = output_mode.strip().lower()
    width_mm_value = custom_width_mm.strip()
    height_mm_value = custom_height_mm.strip()

    options = ImpositionOptions(
        paper_size=normalized_paper_size,
        signature_length=signature_length,
        flyleafs=flyleafs,
        duplex_rotate=duplex_rotate,
        custom_width_points=None,
        custom_height_points=None,
        scaling_mode=scaling_mode,
        output_mode="aggregated",
    )
    form_values: dict[str, Any] = {
        "paper_size": options.paper_size,
        "signature_length": options.signature_length,
        "flyleafs": options.flyleafs,
        "duplex_rotate": options.duplex_rotate,
        "custom_width_mm": width_mm_value,
        "custom_height_mm": height_mm_value,
        "scaling_mode": options.scaling_mode,
        "output_mode": normalized_output_mode,
    }

    allowed_sizes = set(PAPER_SIZES)
    allowed_sizes.add(_CUSTOM_PAPER_SIZE)
    if options.paper_size not in allowed_sizes:
        valid_sizes = ", ".join(sorted(allowed_sizes))
        return options, form_values, f"Invalid paper size. Choose one of: {valid_sizes}."
    if options.scaling_mode not in _SCALING_MODES:
        return options, form_values, "Invalid scaling mode. Choose proportional, stretch, or original."
    if normalized_output_mode not in _OUTPUT_MODES:
        valid_modes = ", ".join(_OUTPUT_MODES)
        return options, form_values, f"Invalid output mode. Choose one of: {valid_modes}."

    options = ImpositionOptions(
        paper_size=options.paper_size,
        signature_length=options.signature_length,
        flyleafs=options.flyleafs,
        duplex_rotate=options.duplex_rotate,
        custom_width_points=options.custom_width_points,
        custom_height_points=options.custom_height_points,
        scaling_mode=options.scaling_mode,
        output_mode=normalized_output_mode,
    )

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
            scaling_mode=options.scaling_mode,
            output_mode=options.output_mode,
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
    job_id: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if not payload:
        _log_event(logging.WARNING, "impose.job.empty_upload", job_id=job_id, source_name=source_name)
        return None, "The uploaded file is empty."

    try:
        reader = PdfReader(io.BytesIO(payload))
    except PdfReadError:
        _log_event(
            logging.WARNING,
            "impose.job.invalid_pdf",
            job_id=job_id,
            source_name=source_name,
            payload_bytes=len(payload),
        )
        return None, "The upload could not be parsed as a PDF. Verify the file is a valid, non-corrupted PDF and retry."

    if reader.is_encrypted:
        _log_event(logging.WARNING, "impose.job.encrypted_pdf", job_id=job_id, source_name=source_name)
        return None, "Encrypted PDFs are not supported for MVP. Remove encryption and retry."

    source_pages = list(range(len(reader.pages)))
    ordered_pages = build_ordered_pages(source_pages, flyleaf_sets=options.flyleafs)
    signatures = split_signatures(ordered_pages, sig_length_sheets=options.signature_length)

    removed = _cleanup_stale_artifacts(
        artifact_dir,
        retention_seconds=artifact_retention_seconds,
    )

    request_id = uuid4().hex
    request_artifact_dir = artifact_dir / request_id
    output_name = deterministic_output_filename(source_name)
    output_path = request_artifact_dir / output_name
    output_slug = Path(output_name).stem.removesuffix("_imposed_duplex")
    preview_name = deterministic_preview_filename(source_name)
    preview_path = request_artifact_dir / preview_name
    custom_dimensions = (
        None
        if options.custom_width_points is None or options.custom_height_points is None
        else (options.custom_width_points, options.custom_height_points)
    )

    try:
        preview_artifact = write_first_sheet_preview(
            reader,
            signatures=signatures,
            output_path=preview_path,
            paper_size=options.paper_size,
            duplex_rotate=options.duplex_rotate,
            custom_dimensions=custom_dimensions,
            scaling_mode=options.scaling_mode,
        )
        generated_downloads: list[dict[str, Any]] = []
        total_output_pages = 0

        if options.output_mode in ("aggregated", "both"):
            artifact = write_duplex_aggregated_pdf(
                reader,
                signatures=signatures,
                output_path=output_path,
                paper_size=options.paper_size,
                duplex_rotate=options.duplex_rotate,
                custom_dimensions=custom_dimensions,
                scaling_mode=options.scaling_mode,
            )
            generated_downloads.append(
                {
                    "download_url": f"/download/{request_id}/{output_name}",
                    "output_filename": output_name,
                    "output_pages": artifact.page_count,
                }
            )
            total_output_pages += artifact.page_count

        if options.output_mode in ("signatures", "both"):
            for signature_index, signature in enumerate(signatures):
                signature_name = f"{output_slug}_signature{signature_index}_duplex.pdf"
                signature_path = request_artifact_dir / signature_name
                artifact = write_duplex_aggregated_pdf(
                    reader,
                    signatures=[list(signature)],
                    output_path=signature_path,
                    paper_size=options.paper_size,
                    duplex_rotate=options.duplex_rotate,
                    custom_dimensions=custom_dimensions,
                    scaling_mode=options.scaling_mode,
                )
                generated_downloads.append(
                    {
                        "download_url": f"/download/{request_id}/{signature_name}",
                        "output_filename": signature_name,
                        "output_pages": artifact.page_count,
                    }
                )
                total_output_pages += artifact.page_count
    except ValueError as exc:
        _log_event(
            logging.WARNING,
            "impose.job.unsupported_options",
            job_id=job_id,
            source_name=source_name,
            error=str(exc),
        )
        return None, f"Unsupported options for imposition: {exc}."
    except Exception:
        _LOGGER.exception(
            "impose.job.unexpected_failure",
            extra={
                "event_name": "impose.job.unexpected_failure",
                "event_fields": {"job_id": job_id, "source_name": source_name},
            },
        )
        return None, "Imposition failed unexpectedly. Retry and check server logs for the associated job."

    _log_event(
        logging.INFO,
        "impose.job.completed",
        job_id=job_id,
        request_id=request_id,
        source_name=source_name,
        source_pages=len(source_pages),
        output_pages=total_output_pages,
        signatures=len(signatures),
        output_mode=options.output_mode,
        output_artifacts=len(generated_downloads),
        stale_artifacts_removed=removed,
    )

    first_output = generated_downloads[0]

    return {
        "status": "success",
        "mode": _GENERATE_ACTION,
        "output_mode": options.output_mode,
        "message": "Imposition complete.",
        "download_url": first_output["download_url"],
        "output_filename": first_output["output_filename"],
        "output_pages": total_output_pages,
        "output_count": len(generated_downloads),
        "downloads": generated_downloads,
        "preview_download_url": f"/download/{request_id}/{preview_name}",
        "preview_filename": preview_name,
        "preview_pages": preview_artifact.page_count,
        "preview_sheet": {
            "placed_tokens": list(preview_artifact.placed_tokens),
            "output_width": preview_artifact.output_width,
            "output_height": preview_artifact.output_height,
            "slots": [asdict(slot) for slot in preview_artifact.slots],
        },
    }, None


def _parse_request_download_url(download_url: str) -> tuple[str, str]:
    _, _, request_id, filename = download_url.split("/", 3)
    return request_id, filename


def _preview_filename_from_output(output_name: str) -> str:
    return f"{Path(output_name).stem}_preview_sheet1.pdf"


def _write_first_sheet_preview(*, imposed_path: Path, preview_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not imposed_path.is_file():
        return None, "Unable to locate generated output for preview."

    reader = PdfReader(str(imposed_path))
    if not reader.pages:
        return None, "Generated output has no pages to preview."

    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    with preview_path.open("wb") as handle:
        writer.write(handle)

    return {"preview_pages": 1}, None


def _resolve_request_artifact_path(artifact_dir: Path, request_id: str, filename: str) -> Path:
    if _REQUEST_ID_PATTERN.fullmatch(request_id) is None:
        _log_event(logging.WARNING, "download.request.invalid_request_id", request_id=request_id, filename=filename)
        raise HTTPException(status_code=400, detail="Invalid request id")

    safe_name = _validated_filename(filename)
    request_artifact_dir = artifact_dir / request_id
    if not request_artifact_dir.is_dir():
        _log_event(logging.WARNING, "download.request.expired", request_id=request_id, filename=safe_name)
        raise HTTPException(status_code=410, detail=_EXPIRED_ARTIFACT_MESSAGE)

    file_path = request_artifact_dir / safe_name
    if not file_path.is_file():
        _log_event(logging.WARNING, "download.request.missing_file", request_id=request_id, filename=safe_name)
        raise HTTPException(status_code=404, detail="File not found")

    return file_path


def _resolve_legacy_artifact_path(artifact_dir: Path, filename: str) -> Path:
    safe_name = _validated_filename(filename)
    file_path = artifact_dir / safe_name
    if not file_path.is_file():
        _log_event(logging.WARNING, "download.legacy.missing_file", filename=safe_name)
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
            "scaling_mode": "proportional",
            "output_mode": "aggregated",
        }
        if form_values:
            defaults.update(form_values)

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "result": result,
                "paper_sizes": sorted(PAPER_SIZES.keys()) + [_CUSTOM_PAPER_SIZE],
                "scaling_modes": list(_SCALING_MODES),
                "output_modes": _OUTPUT_MODES,
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
        action: str = Form(_GENERATE_ACTION),
        paper_size: str = Form("A4"),
        signature_length: int = Form(6, ge=1),
        flyleafs: int = Form(0, ge=0),
        duplex_rotate: bool = Form(False),
        custom_width_mm: str = Form(""),
        custom_height_mm: str = Form(""),
        scaling_mode: str = Form("proportional"),
        output_mode: str = Form("aggregated"),
    ) -> HTMLResponse:
        job_id = uuid4().hex
        _log_event(
            logging.INFO,
            "impose.request.received",
            job_id=job_id,
            action=action,
            paper_size=paper_size,
            signature_length=signature_length,
            flyleafs=flyleafs,
            duplex_rotate=duplex_rotate,
            output_mode=output_mode,
            has_upload=file is not None and bool(file.filename),
        )
        normalized_action = action.strip().lower()
        if normalized_action not in _SUPPORTED_ACTIONS:
            error = f"Invalid action '{action}'."
            _log_event(logging.WARNING, "impose.request.invalid_action", job_id=job_id, action=action, error=error)
            return render_index(
                request,
                result={"status": "error", "message": error},
                status_code=400,
            )

        options, form_values, form_error = _parse_form_input(
            paper_size=paper_size,
            signature_length=signature_length,
            flyleafs=flyleafs,
            duplex_rotate=duplex_rotate,
            custom_width_mm=custom_width_mm,
            custom_height_mm=custom_height_mm,
            scaling_mode=scaling_mode,
            output_mode=output_mode,
        )
        if form_error is not None:
            _log_event(logging.WARNING, "impose.request.form_validation_failed", job_id=job_id, error=form_error)
            return render_index(
                request,
                result={"status": "error", "message": form_error},
                form_values=form_values,
                status_code=400,
            )

        source_name, upload_error = _validate_upload_metadata(file)
        if upload_error is not None:
            _log_event(logging.WARNING, "impose.request.upload_validation_failed", job_id=job_id, error=upload_error)
            return render_index(
                request,
                result={"status": "error", "message": upload_error},
                form_values=form_values,
                status_code=400,
            )

        if file is None or source_name is None:
            _log_event(logging.WARNING, "impose.request.upload_missing", job_id=job_id)
            return render_index(
                request,
                result={"status": "error", "message": "Upload a PDF file to continue."},
                form_values=form_values,
                status_code=400,
            )

        payload = await file.read()
        impose_options = options if normalized_action == _GENERATE_ACTION else replace(options, output_mode="aggregated")
        result, impose_error = _impose_payload(
            payload=payload,
            source_name=source_name,
            options=impose_options,
            artifact_dir=app.state.artifact_dir,
            artifact_retention_seconds=app.state.artifact_retention_seconds,
            job_id=job_id,
        )
        if impose_error is not None:
            _log_event(logging.WARNING, "impose.request.failed", job_id=job_id, source_name=source_name, error=impose_error)
            return render_index(
                request,
                result={"status": "error", "message": impose_error},
                form_values=form_values,
                status_code=400,
            )

        if result is None:
            _log_event(logging.ERROR, "impose.request.missing_result", job_id=job_id, source_name=source_name)
            return render_index(
                request,
                result={"status": "error", "message": "Imposition failed."},
                form_values=form_values,
                status_code=500,
            )

        if normalized_action == _PREVIEW_ACTION:
            request_id, output_filename = _parse_request_download_url(result["download_url"])
            request_artifact_dir = app.state.artifact_dir / request_id
            preview_filename = _preview_filename_from_output(output_filename)
            preview_path = request_artifact_dir / preview_filename
            preview_meta, preview_error = _write_first_sheet_preview(
                imposed_path=request_artifact_dir / output_filename,
                preview_path=preview_path,
            )
            if preview_error is not None:
                _log_event(
                    logging.WARNING,
                    "preview.request.failed",
                    job_id=job_id,
                    source_name=source_name,
                    error=preview_error,
                )
                return render_index(
                    request,
                    result={"status": "error", "message": preview_error},
                    form_values=form_values,
                    status_code=400,
                )

            if preview_meta is None:
                _log_event(logging.ERROR, "preview.request.missing_result", job_id=job_id, source_name=source_name)
                return render_index(
                    request,
                    result={"status": "error", "message": "Preview generation failed."},
                    form_values=form_values,
                    status_code=500,
                )

            result = {
                "status": "success",
                "mode": _PREVIEW_ACTION,
                "message": "Preview ready for sheet 1.",
                "preview_pages": preview_meta["preview_pages"],
                "preview_url": f"/download/{request_id}/{preview_filename}",
                "preview_filename": preview_filename,
                "download_url": result["download_url"],
                "output_filename": result["output_filename"],
                "output_pages": result["output_pages"],
            }
            _log_event(
                logging.INFO,
                "preview.request.succeeded",
                job_id=job_id,
                source_name=source_name,
                preview_filename=preview_filename,
                preview_url=result["preview_url"],
            )

        _log_event(
            logging.INFO,
            "impose.request.succeeded",
            job_id=job_id,
            source_name=source_name,
            output_filename=result["output_filename"],
            output_pages=result.get("output_pages"),
            download_url=result["download_url"],
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
