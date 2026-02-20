from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence, cast

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import DecodedStreamObject

from bookbinder.constants import PAPER_SIZES
from bookbinder.imposition.core import BLANK_PAGE, PageToken, impose_signature

ScalingMode = Literal["proportional", "stretch", "original"]
_SCALING_MODES: tuple[ScalingMode, ...] = ("proportional", "stretch", "original")
PositioningMode = Literal["centered", "binding_aligned"]
_POSITIONING_MODES: tuple[PositioningMode, ...] = ("centered", "binding_aligned")


@dataclass(frozen=True)
class PrintMarksOptions:
    crop: bool = False
    fold: bool = False
    signature_order: bool = False

    @property
    def enabled(self) -> bool:
        return self.crop or self.fold or self.signature_order


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


def _clamp(value: float, *, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _build_print_mark_commands(
    *,
    output_width: float,
    output_height: float,
    options: PrintMarksOptions,
    signature_index: int,
    side_index: int,
) -> bytes:
    if not options.enabled:
        return b""

    max_x = max(output_width, 0.0)
    max_y = max(output_height, 0.0)
    margin = max(min(min(max_x, max_y) * 0.02, 18.0), 4.0)
    mark_length = max(min(min(max_x, max_y) * 0.03, 14.0), 4.0)
    line_width = max(min(min(max_x, max_y) * 0.0018, 1.2), 0.3)
    commands: list[str] = ["q", "% bookbinder-print-marks", "0 0 0 RG", f"{line_width:.3f} w"]

    def line(x1: float, y1: float, x2: float, y2: float) -> None:
        commands.append(
            f"{_clamp(x1, lower=0.0, upper=max_x):.3f} {_clamp(y1, lower=0.0, upper=max_y):.3f} m "
            f"{_clamp(x2, lower=0.0, upper=max_x):.3f} {_clamp(y2, lower=0.0, upper=max_y):.3f} l S"
        )

    if options.crop:
        left_x = margin
        right_x = max_x - margin
        bottom_y = margin
        top_y = max_y - margin
        line(left_x, bottom_y, left_x + mark_length, bottom_y)
        line(left_x, bottom_y, left_x, bottom_y + mark_length)
        line(right_x, bottom_y, right_x - mark_length, bottom_y)
        line(right_x, bottom_y, right_x, bottom_y + mark_length)
        line(left_x, top_y, left_x + mark_length, top_y)
        line(left_x, top_y, left_x, top_y - mark_length)
        line(right_x, top_y, right_x - mark_length, top_y)
        line(right_x, top_y, right_x, top_y - mark_length)

    if options.fold:
        center_x = max_x / 2.0
        line(center_x, margin, center_x, margin + mark_length)
        line(center_x, max_y - margin, center_x, max_y - margin - mark_length)

    if options.signature_order:
        bar_width = max(mark_length * 0.55, 2.0)
        bar_height = max(mark_length * 0.45, 2.0)
        bar_gap = max(bar_width * 0.5, 1.0)
        lane_count = max(int((max_x - (2.0 * margin)) // (bar_width + bar_gap)), 1)
        lane_index = (signature_index * 2 + side_index) % lane_count
        bar_x = _clamp(margin + (lane_index * (bar_width + bar_gap)), lower=0.0, upper=max_x - bar_width)
        bar_y = _clamp(margin * 0.5, lower=0.0, upper=max_y - bar_height)
        commands.append(f"{bar_x:.3f} {bar_y:.3f} {bar_width:.3f} {bar_height:.3f} re f")

    commands.append("Q")
    return ("\n".join(commands) + "\n").encode("ascii")


def _append_page_commands(imposed_page, commands: bytes) -> None:
    if not commands:
        return

    stream = DecodedStreamObject()
    stream.set_data((imposed_page._get_contents_as_bytes() or b"") + commands)
    imposed_page.replace_contents(stream)


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


def resolve_positioning_mode(value: str) -> PositioningMode:
    normalized = value.strip().lower().replace("-", "_")
    if normalized in _POSITIONING_MODES:
        return cast(PositioningMode, normalized)

    valid = ", ".join(_POSITIONING_MODES)
    raise ValueError(f"unsupported positioning mode '{value}', expected one of: {valid}")


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
    scaling_mode: ScalingMode = "proportional",
    positioning_mode: PositioningMode = "centered",
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

    if positioning_mode == "centered":
        local_x_offset = (slot_width - rendered_width) / 2.0
    elif positioning_mode == "binding_aligned":
        local_x_offset = slot_width - rendered_width if slot_index == 0 else 0.0
    else:
        raise ValueError(f"unsupported positioning mode '{positioning_mode}'")

    x_offset = local_x_offset + (slot_width if slot_index == 1 else 0.0)

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
    positioning_mode: PositioningMode = "centered",
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
    if positioning_mode == "centered":
        local_x_offset = (slot_width - rendered_width) / 2.0
    elif positioning_mode == "binding_aligned":
        local_x_offset = slot_width - rendered_width if slot_index == 0 else 0.0
    else:
        raise ValueError(f"unsupported positioning mode '{positioning_mode}'")

    x_offset = slot_x + local_x_offset
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
    positioning_mode: PositioningMode = "centered",
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
        positioning_mode=positioning_mode,
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
    scaling_mode: ScalingMode = "proportional",
    positioning_mode: PositioningMode = "centered",
    blank_token: str = BLANK_PAGE,
    print_marks: PrintMarksOptions | None = None,
) -> PreviewArtifact:
    output_width, output_height = resolve_paper_dimensions(paper_size)
    resolved_positioning_mode = resolve_positioning_mode(positioning_mode)

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
        positioning_mode=resolved_positioning_mode,
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
        positioning_mode=resolved_positioning_mode,
    )
    mark_settings = print_marks or PrintMarksOptions()
    _append_page_commands(
        imposed_page,
        _build_print_mark_commands(
            output_width=output_width,
            output_height=output_height,
            options=mark_settings,
            signature_index=0,
            side_index=0,
        ),
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
        positioning_mode=resolved_positioning_mode,
    )
    right_geometry = _slot_geometry(
        reader=reader,
        token=first_side.right,
        slot_index=1,
        output_width=output_width,
        output_height=output_height,
        blank_token=blank_token,
        scaling_mode=scaling_mode,
        positioning_mode=resolved_positioning_mode,
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
    scaling_mode: ScalingMode = "proportional",
    positioning_mode: PositioningMode = "centered",
    blank_token: str = BLANK_PAGE,
    print_marks: PrintMarksOptions | None = None,
) -> GeneratedArtifact:
    output_width, output_height = resolve_paper_dimensions(paper_size)
    resolved_positioning_mode = resolve_positioning_mode(positioning_mode)

    writer = PdfWriter()
    placed_tokens: list[tuple[PageToken, PageToken]] = []
    mark_settings = print_marks or PrintMarksOptions()

    for signature_index, signature in enumerate(signatures):
        sides = impose_signature(signature, duplex_rotate=duplex_rotate)
        for side_index, side in enumerate(sides):
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
                positioning_mode=resolved_positioning_mode,
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
                positioning_mode=resolved_positioning_mode,
            )
            _append_page_commands(
                imposed_page,
                _build_print_mark_commands(
                    output_width=output_width,
                    output_height=output_height,
                    options=mark_settings,
                    signature_index=signature_index,
                    side_index=side_index,
                ),
            )
            placed_tokens.append((side.left, side.right))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)

    return GeneratedArtifact(path=output_path, page_count=len(writer.pages), placed_tokens=placed_tokens)
