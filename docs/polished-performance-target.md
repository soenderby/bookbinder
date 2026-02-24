# Polished Performance Target (300 Pages)

## SPEC alignment

SPEC section 4.4 requires a concrete local runtime target for processing a 300-page PDF during the polished phase.

## Target

- Scope: end-to-end folio imposition write for a deterministic 300-page input (A4 output, `signature_length=6`, `flyleafs=1`, `duplex_rotate=false`)
- Pass threshold: median runtime across 3 measured runs must be less than or equal to `20.0` seconds
- Regression signal: benchmark command exits non-zero if median runtime exceeds threshold

## Benchmark command

```bash
python scripts/benchmark_300_page_imposition.py --max-seconds 20 --runs 3 --warmup 1
```

## Benchmark evidence

- Date (UTC): 2026-02-24
- Command: `python scripts/benchmark_300_page_imposition.py --max-seconds 20 --runs 3 --warmup 1`
- Environment:
  - Python: 3.12.12
  - Platform: Linux-6.6.87.1-microsoft-standard-WSL2-x86_64-with-glibc2.35
- Result: PASS
- Warmup seconds: 0.049
- Run seconds: 0.049,0.046,0.061
- Median seconds: 0.049
- Min/Max seconds: 0.046 / 0.061

## Notes

- The harness uses a synthetic blank-page input to keep measurements deterministic and independent from external sample artifacts.
- Use this benchmark as a pre-merge check when touching imposition or PDF write paths.
