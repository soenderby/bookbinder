from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from pypdf import PdfReader, PdfWriter, Transformation

from bookbinder.constants import PAPER_SIZES
from bookbinder.imposition.core import BLANK_PAGE, PageToken, impose_signature

ScalingMode = Literal["proportional", "stretch", "original"]
_SCALING_MODES: tuple[ScalingMode, ...] = ("proportional", "stretch", "original")


@dataclass(frozen=True)
class GeneratedArtifact:
    path: Path
    page_count: int
    placed_tokens: list[tuple[PageToken, PageToken]]


@dataclass(frozen=True)
class SlotGeometry:
    token: PageToken
    slot_index: int
    slot_x: float
    slot_y: float
    slot_width: float
    slot_height: float
    rendered_width: float
    rendered_height: float
    x_offset: float
    y_offset: float
    scale: float | None
    scale_x: float | None
    scale_y: float | None


@dataclass(frozen=True)
class PreviewArtifact:
    path: Path
    page_count: int
    placed_tokens: tuple[PageToken, PageToken]
    output_width: float
    output_height: float
    slots: tuple[SlotGeometry, SlotGeometry]


def resolve_paper_dimensions(paper_size: str) -> tuple[float, float]:
    try:
        return PAPER_SIZES[paper_size]
    except KeyError as exc:
        valid = ", ".join(sorted(PAPER_SIZES))
        raise ValueError(f"unsupported paper size '{paper_size}', expected one of: {valid}") from exc


def deterministic_output_filename(source_name: str) -> str:
    stem = Path(source_name).stem.strip()
    if not stem:
        stem = "output"

    slug = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").lower()
    slug = slug or "output"
    return f"{slug}_imposed_duplex.pdf"


def _resolve_scales(
    *,
    source_width: float,
    source_height: float,
    slot_width: float,
    slot_height: float,
    scaling_mode: ScalingMode,
) -> tuple[float, float]:
    if scaling_mode == "proportional":
        scale = min(slot_width / source_width, slot_height / source_height)
        return scale, scale
    if scaling_mode == "stretch":
        return slot_width / source_width, slot_height / source_height
    if scaling_mode == "original":
        return 1.0, 1.0

    valid = ", ".join(_SCALING_MODES)
    raise ValueError(f"unsupported scaling mode '{scaling_mode}', expected one of: {valid}")


def _slot_transform(
    source_page,
    slot_index: int,
    output_width: float,
    output_height: float,
    scaling_mode: ScalingMode,
) -> Transformation:
    source_width = float(source_page.mediabox.width)
    source_height = float(source_page.mediabox.height)

    slot_width = output_width / 2.0
    slot_height = output_height

    scale_x, scale_y = _resolve_scales(
        source_width=source_width,
        source_height=source_height,
        slot_width=slot_width,
        slot_height=slot_height,
        scaling_mode=scaling_mode,
    )
    rendered_width = source_width * scale_x
    rendered_height = source_height * scale_y

    x_offset = (slot_width - rendered_width) / 2.0
    if slot_index == 1:
        x_offset += slot_width

    y_offset = (slot_height - rendered_height) / 2.0
    return Transformation().scale(scale_x, scale_y).translate(x_offset, y_offset)


def _slot_geometry(
    reader: PdfReader,
    token: PageToken,
    slot_index: int,
    output_width: float,
    output_height: float,
    blank_token: str,
    scaling_mode: ScalingMode = "proportional",
) -> SlotGeometry:
    slot_width = output_width / 2.0
    slot_height = output_height
    slot_x = slot_width if slot_index == 1 else 0.0
    slot_y = 0.0

    if token == blank_token:
        return SlotGeometry(
            token=token,
            slot_index=slot_index,
            slot_x=slot_x,
            slot_y=slot_y,
            slot_width=slot_width,
            slot_height=slot_height,
            rendered_width=0.0,
            rendered_height=0.0,
            x_offset=slot_x,
            y_offset=0.0,
            scale=None,
            scale_x=None,
            scale_y=None,
        )

    if not isinstance(token, int):
        raise ValueError(f"expected int page token or blank token, got {token!r}")

    source_page = reader.pages[token]
    source_width = float(source_page.mediabox.width)
    source_height = float(source_page.mediabox.height)
    scale_x, scale_y = _resolve_scales(
        source_width=source_width,
        source_height=source_height,
        slot_width=slot_width,
        slot_height=slot_height,
        scaling_mode=scaling_mode,
    )
    rendered_width = source_width * scale_x
    rendered_height = source_height * scale_y
    x_offset = slot_x + (slot_width - rendered_width) / 2.0
    y_offset = (slot_height - rendered_height) / 2.0

    return SlotGeometry(
        token=token,
        slot_index=slot_index,
        slot_x=slot_x,
        slot_y=slot_y,
        slot_width=slot_width,
        slot_height=slot_height,
        rendered_width=rendered_width,
        rendered_height=rendered_height,
        x_offset=x_offset,
        y_offset=y_offset,
        scale=scale_x if scale_x == scale_y else None,
        scale_x=scale_x,
        scale_y=scale_y,
    )


def _place_token(
    imposed_page,
    reader: PdfReader,
    token: PageToken,
    slot_index: int,
    output_width: float,
    output_height: float,
    blank_token: str,
    scaling_mode: ScalingMode = "proportional",
) -> None:
    if token == blank_token:
        return

    if not isinstance(token, int):
        raise ValueError(f"expected int page token or blank token, got {token!r}")

    source_page = reader.pages[token]
    transform = _slot_transform(
        source_page,
        slot_index,
        output_width,
        output_height,
        scaling_mode=scaling_mode,
    )
    imposed_page.merge_transformed_page(source_page, transform)


def deterministic_preview_filename(source_name: str) -> str:
    stem = Path(source_name).stem.strip()
    if not stem:
        stem = "output"

    slug = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").lower()
    slug = slug or "output"
    return f"{slug}_preview_sheet1.pdf"


def write_first_sheet_preview(
    reader: PdfReader,
    signatures: Sequence[Sequence[PageToken]],
    output_path: Path,
    paper_size: str,
    duplex_rotate: bool,
    custom_dimensions: tuple[float, float] | None = None,
    scaling_mode: ScalingMode = "proportional",
    blank_token: str = BLANK_PAGE,
) -> PreviewArtifact:
    if custom_dimensions is not None:
        output_width, output_height = custom_dimensions
    else:
        output_width, output_height = resolve_paper_dimensions(paper_size)

    first_side = None
    for signature in signatures:
        sides = impose_signature(signature, duplex_rotate=duplex_rotate)
        if sides:
            first_side = sides[0]
            break
    if first_side is None:
        raise ValueError("cannot generate preview for an empty imposed document")

    writer = PdfWriter()
    imposed_page = writer.add_blank_page(width=output_width, height=output_height)
    _place_token(
        imposed_page,
        reader=reader,
        token=first_side.left,
        slot_index=0,
        output_width=output_width,
        output_height=output_height,
        blank_token=blank_token,
        scaling_mode=scaling_mode,
    )
    _place_token(
        imposed_page,
        reader=reader,
        token=first_side.right,
        slot_index=1,
        output_width=output_width,
        output_height=output_height,
        blank_token=blank_token,
        scaling_mode=scaling_mode,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)

    left_geometry = _slot_geometry(
        reader=reader,
        token=first_side.left,
        slot_index=0,
        output_width=output_width,
        output_height=output_height,
        blank_token=blank_token,
        scaling_mode=scaling_mode,
    )
    right_geometry = _slot_geometry(
        reader=reader,
        token=first_side.right,
        slot_index=1,
        output_width=output_width,
        output_height=output_height,
        blank_token=blank_token,
        scaling_mode=scaling_mode,
    )

    return PreviewArtifact(
        path=output_path,
        page_count=len(writer.pages),
        placed_tokens=(first_side.left, first_side.right),
        output_width=output_width,
        output_height=output_height,
        slots=(left_geometry, right_geometry),
    )


def write_duplex_aggregated_pdf(
    reader: PdfReader,
    signatures: Sequence[Sequence[PageToken]],
    output_path: Path,
    paper_size: str,
    duplex_rotate: bool,
    custom_dimensions: tuple[float, float] | None = None,
    scaling_mode: ScalingMode = "proportional",
    blank_token: str = BLANK_PAGE,
) -> GeneratedArtifact:
    if custom_dimensions is not None:
        output_width, output_height = custom_dimensions
    else:
        output_width, output_height = resolve_paper_dimensions(paper_size)

    writer = PdfWriter()
    placed_tokens: list[tuple[PageToken, PageToken]] = []

    for signature in signatures:
        sides = impose_signature(signature, duplex_rotate=duplex_rotate)
        for side in sides:
            imposed_page = writer.add_blank_page(width=output_width, height=output_height)
            _place_token(
                imposed_page,
                reader=reader,
                token=side.left,
                slot_index=0,
                output_width=output_width,
                output_height=output_height,
                blank_token=blank_token,
                scaling_mode=scaling_mode,
            )
            _place_token(
                imposed_page,
                reader=reader,
                token=side.right,
                slot_index=1,
                output_width=output_width,
                output_height=output_height,
                blank_token=blank_token,
                scaling_mode=scaling_mode,
            )
            placed_tokens.append((side.left, side.right))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)

    return GeneratedArtifact(path=output_path, page_count=len(writer.pages), placed_tokens=placed_tokens)
