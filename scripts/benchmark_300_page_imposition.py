#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from bookbinder.imposition.core import build_ordered_pages, split_signatures
from bookbinder.imposition.pdf_writer import write_duplex_aggregated_pdf


LETTER_WIDTH = 612
LETTER_HEIGHT = 792


def _build_synthetic_pdf(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=LETTER_WIDTH, height=LETTER_HEIGHT)

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _run_once(
    *,
    payload: bytes,
    page_count: int,
    flyleaf_sets: int,
    signature_length: int,
    paper_size: str,
) -> float:
    reader = PdfReader(io.BytesIO(payload))
    source_pages = list(range(page_count))
    ordered_pages = build_ordered_pages(source_pages, flyleaf_sets=flyleaf_sets)
    signatures = split_signatures(ordered_pages, sig_length_sheets=signature_length)

    with tempfile.TemporaryDirectory(prefix="bookbinder-bench-") as tmp_dir:
        output_path = Path(tmp_dir) / "imposed.pdf"
        started = time.perf_counter()
        write_duplex_aggregated_pdf(
            reader,
            signatures=signatures,
            output_path=output_path,
            paper_size=paper_size,
            duplex_rotate=False,
            scaling_mode="proportional",
            positioning_mode="centered",
        )
        elapsed = time.perf_counter() - started

    return elapsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark folio imposition runtime for a deterministic 300-page input "
            "and fail when median runtime exceeds threshold."
        )
    )
    parser.add_argument("--pages", type=int, default=300, help="Synthetic input page count.")
    parser.add_argument("--flyleafs", type=int, default=1, help="Flyleaf sets for ordered pages.")
    parser.add_argument("--signature-length", type=int, default=6, help="Signature length in sheets.")
    parser.add_argument("--paper-size", default="A4", help="Output paper size key.")
    parser.add_argument("--runs", type=int, default=3, help="Measured benchmark runs.")
    parser.add_argument("--warmup", type=int, default=1, help="Warmup runs excluded from threshold evaluation.")
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=20.0,
        help="Maximum allowed median seconds across measured runs.",
    )
    args = parser.parse_args()

    if args.pages <= 0:
        raise ValueError("--pages must be > 0")
    if args.flyleafs < 0:
        raise ValueError("--flyleafs must be >= 0")
    if args.signature_length <= 0:
        raise ValueError("--signature-length must be > 0")
    if args.runs <= 0:
        raise ValueError("--runs must be > 0")
    if args.warmup < 0:
        raise ValueError("--warmup must be >= 0")
    if args.max_seconds <= 0:
        raise ValueError("--max-seconds must be > 0")

    payload = _build_synthetic_pdf(args.pages)

    warmup_durations: list[float] = []
    for _ in range(args.warmup):
        warmup_durations.append(
            _run_once(
                payload=payload,
                page_count=args.pages,
                flyleaf_sets=args.flyleafs,
                signature_length=args.signature_length,
                paper_size=args.paper_size,
            )
        )

    run_durations: list[float] = []
    for _ in range(args.runs):
        run_durations.append(
            _run_once(
                payload=payload,
                page_count=args.pages,
                flyleaf_sets=args.flyleafs,
                signature_length=args.signature_length,
                paper_size=args.paper_size,
            )
        )

    median_seconds = statistics.median(run_durations)
    min_seconds = min(run_durations)
    max_seconds = max(run_durations)

    print("bookbinder-300-page-benchmark")
    print(f"python={platform.python_version()}")
    print(f"platform={platform.platform()}")
    print(
        f"config=pages:{args.pages},flyleafs:{args.flyleafs},sig_length:{args.signature_length},"
        f"paper:{args.paper_size},warmup:{args.warmup},runs:{args.runs},target_s:{args.max_seconds:.2f}"
    )
    if warmup_durations:
        print("warmup_seconds=" + ",".join(f"{value:.3f}" for value in warmup_durations))
    print("run_seconds=" + ",".join(f"{value:.3f}" for value in run_durations))
    print(f"median_seconds={median_seconds:.3f}")
    print(f"min_seconds={min_seconds:.3f}")
    print(f"max_seconds={max_seconds:.3f}")

    if median_seconds > args.max_seconds:
        print(
            f"result=FAIL median {median_seconds:.3f}s exceeds target {args.max_seconds:.3f}s",
            file=sys.stderr,
        )
        return 1

    print(f"result=PASS median {median_seconds:.3f}s within target {args.max_seconds:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
