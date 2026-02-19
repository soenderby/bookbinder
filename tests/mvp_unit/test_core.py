from __future__ import annotations

import pytest

from bookbinder.imposition.core import (
    BLANK_PAGE,
    build_ordered_pages,
    impose_signature,
    insert_flyleafs,
    pad_to_multiple_of_four,
    split_signatures,
)

pytestmark = pytest.mark.mvp_unit


def test_insert_flyleafs_adds_two_blanks_per_edge_per_set() -> None:
    source = [0, 1, 2]
    assert insert_flyleafs(source, flyleaf_sets=1) == [BLANK_PAGE, BLANK_PAGE, 0, 1, 2, BLANK_PAGE, BLANK_PAGE]


def test_pad_to_multiple_of_four() -> None:
    source = [0, 1, 2, 3, 4]
    assert pad_to_multiple_of_four(source) == [0, 1, 2, 3, 4, BLANK_PAGE, BLANK_PAGE, BLANK_PAGE]


def test_signature_splitting_uses_standard_signature_length() -> None:
    ordered = list(range(20))
    signatures = split_signatures(ordered, sig_length_sheets=3)
    assert signatures == [list(range(12)), list(range(12, 20))]


def test_folio_mapping_duplex_normal() -> None:
    signature = list(range(8))
    sides = impose_signature(signature, duplex_rotate=False)
    assert [(side.left, side.right) for side in sides] == [
        (7, 0),
        (1, 6),
        (5, 2),
        (3, 4),
    ]


def test_folio_mapping_duplex_rotate() -> None:
    signature = list(range(8))
    sides = impose_signature(signature, duplex_rotate=True)
    assert [(side.left, side.right) for side in sides] == [
        (7, 0),
        (6, 1),
        (5, 2),
        (4, 3),
    ]


def test_build_ordered_pages_pipeline() -> None:
    ordered = build_ordered_pages(list(range(9)), flyleaf_sets=1)
    assert len(ordered) == 16
    assert ordered[:4] == [BLANK_PAGE, BLANK_PAGE, 0, 1]
    assert ordered[-3:] == [BLANK_PAGE, BLANK_PAGE, BLANK_PAGE]
