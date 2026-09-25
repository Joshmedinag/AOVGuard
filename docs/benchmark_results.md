# Frame-first Benchmark Results

## Recorded run

- Date (UTC): 2026-08-14
- Platform: Windows 11, build 26200
- CPU: 13th Gen Intel Core i9-13900HX, 32 logical processors
- Python: 3.12.12
- NumPy: 2.4.6
- OpenEXR: 3.4.12
- Dataset: 12 frames, 5 colour AOVs, 320 x 180 pixels
- Repetitions: 30 per strategy, after one unrecorded warm-up per strategy
- Run order: alternated between strategies on each repetition

| Measure | AOV-first | Frame-first | Change |
| --- | ---: | ---: | ---: |
| Application-level read calls | 60 | 12 | 5.00x fewer |
| Median elapsed time | 0.4387 s | 0.1181 s | 3.72x faster |
| Interquartile range | 0.0730 s | 0.0369 s | Descriptive spread |
| Minimum elapsed time | 0.2571 s | 0.0617 s | Descriptive minimum |
| Median Python peak memory | 5,554,772 B | 11,077,580 B | 1.99x higher |
| Pixel checksum | 5,365,412.4943 | 5,365,412.4943 | Identical |

## Interpretation

The deterministic result is the reduction from `frames x AOVs` reader calls to
one reader call per frame. The matching checksum confirms that both strategies
consumed equivalent decoded pixel values for this fixture.

On this run, frame-first processing was also about 3.72 times faster. It held
all five AOV arrays for the current frame at once, which explains the higher
Python-tracked peak memory. It still does not retain the complete sequence.
This is a useful trade-off: memory scales primarily with one frame's requested
AOVs rather than with every frame in the sequence.

One unrecorded warm-up was completed for each strategy and the strategy order
was alternated to reduce first-run and systematic order effects. Timing and
memory remain contextual rather than universal. Filesystem caching,
compression, disk speed, resolution and AOV count can change the result.
`tracemalloc` excludes native allocations inside OpenEXR. The exact raw output
is stored in `experiments/benchmark_results.json`; the method and limitations
are defined in `docs/benchmark_methodology.md`.

## Simulated long-sequence scalability

The 1.1.0 frame-count safeguard was evaluated separately on 16 September 2026
with `experiments/benchmark_simulated_sequences.py`. This deterministic test
uses a 64 x 36 float32 color AOV supplied by an in-memory reader. It exercises
the real discovery, accumulation, robust-series and rule pipeline without
creating EXR files.

| Requested frames | Processed | Elapsed | Peak Python memory |
| ---: | ---: | ---: | ---: |
| 100 | 100 | 0.071013 s | 1.178 MB |
| 500 | 500 | 0.268410 s | 1.120 MB |
| 1,000 | 1,000 | 0.505048 s | 2.206 MB |

Reproduce it with:

```powershell
uv run python experiments/benchmark_simulated_sequences.py
```

These single-run values show bounded application-level memory for this fixture
and approximately linear processing time. They do not measure OpenEXR decode,
filesystem, compression or full-resolution native memory and must not be used
as production throughput claims. Use `--max-frames` to reject unexpectedly
large jobs before decoding and validate final capacity with authorised renders.
