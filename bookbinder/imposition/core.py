from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, TypeAlias

BlankPageToken: TypeAlias = str
PageToken: TypeAlias = int | BlankPageToken

BLANK_PAGE: BlankPageToken = "__BLANK_PAGE__"
FOLIO_FRONT_MAPPING: tuple[int, int] = (3, 2)
FOLIO_BACK_MAPPING: tuple[int, int] = (1, 4)
FOLIO_BACK_ROTATE_MAPPING: tuple[int, int] = (4, 1)


@dataclass(frozen=True)
class ImposedSide:
    face: str
    left: PageToken
    right: PageToken


def insert_flyleafs(
    source_pages: Sequence[PageToken],
    flyleaf_sets: int,
    blank_token: BlankPageToken = BLANK_PAGE,
) -> list[PageToken]:
    if flyleaf_sets < 0:
        raise ValueError("flyleaf_sets must be >= 0")

    blanks_per_edge = flyleaf_sets * 2
    front_blanks = [blank_token] * blanks_per_edge
    back_blanks = [blank_token] * blanks_per_edge
    return [*front_blanks, *source_pages, *back_blanks]


def pad_to_multiple_of_four(
    pages: Sequence[PageToken],
    blank_token: BlankPageToken = BLANK_PAGE,
) -> list[PageToken]:
    padded = list(pages)
    remainder = len(padded) % 4
    if remainder == 0:
        return padded

    padding = 4 - remainder
    padded.extend([blank_token] * padding)
    return padded


def pages_per_signature(sig_length_sheets: int) -> int:
    if sig_length_sheets <= 0:
        raise ValueError("sig_length_sheets must be > 0")
    return sig_length_sheets * 4


def split_signatures(
    ordered_pages: Sequence[PageToken],
    sig_length_sheets: int,
) -> list[list[PageToken]]:
    per_signature = pages_per_signature(sig_length_sheets)
    pages = list(ordered_pages)

    if len(pages) % 4 != 0:
        raise ValueError("ordered_pages must be padded to a multiple of 4")

    signatures = [
        pages[index : index + per_signature]
        for index in range(0, len(pages), per_signature)
    ]

    for signature in signatures:
        if len(signature) % 4 != 0:
            raise ValueError("each signature must have a page count divisible by 4")

    return signatures


def build_ordered_pages(
    source_pages: Sequence[int],
    flyleaf_sets: int,
    blank_token: BlankPageToken = BLANK_PAGE,
) -> list[PageToken]:
    with_flyleafs = insert_flyleafs(source_pages, flyleaf_sets, blank_token)
    return pad_to_multiple_of_four(with_flyleafs, blank_token)


def _pick_from_mapping(
    quartet: tuple[PageToken, PageToken, PageToken, PageToken],
    mapping: tuple[int, int],
) -> tuple[PageToken, PageToken]:
    left_pos, right_pos = mapping
    return quartet[left_pos - 1], quartet[right_pos - 1]


def _sheet_quartet(signature: Sequence[PageToken], sheet_index: int) -> tuple[PageToken, PageToken, PageToken, PageToken]:
    start = sheet_index * 2
    left_inner = signature[start + 1]
    right_outer = signature[start]
    left_outer = signature[-(start + 1)]
    right_inner = signature[-(start + 2)]

    # Quartet ordering mirrors bookbinder-js folio table semantics:
    # 1=left_inner, 2=right_outer, 3=left_outer, 4=right_inner.
    return (left_inner, right_outer, left_outer, right_inner)


def impose_signature(
    signature: Sequence[PageToken],
    duplex_rotate: bool,
) -> list[ImposedSide]:
    if len(signature) % 4 != 0:
        raise ValueError("signature length must be divisible by 4")

    sides: list[ImposedSide] = []
    sheets = len(signature) // 4
    back_mapping = FOLIO_BACK_ROTATE_MAPPING if duplex_rotate else FOLIO_BACK_MAPPING

    for sheet_index in range(sheets):
        quartet = _sheet_quartet(signature, sheet_index)
        front_left, front_right = _pick_from_mapping(quartet, FOLIO_FRONT_MAPPING)
        back_left, back_right = _pick_from_mapping(quartet, back_mapping)

        sides.append(ImposedSide(face="front", left=front_left, right=front_right))
        sides.append(ImposedSide(face="back", left=back_left, right=back_right))

    return sides


def impose_signatures(
    signatures: Sequence[Sequence[PageToken]],
    duplex_rotate: bool,
) -> list[ImposedSide]:
    output: list[ImposedSide] = []
    for signature in signatures:
        output.extend(impose_signature(signature, duplex_rotate=duplex_rotate))
    return output
