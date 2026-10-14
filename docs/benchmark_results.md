# Frame-first Benchmark Results

## Historical recorded run

These measurements predate the 2026-10-11 reliability changes. They are retained
as historical evaluation evidence; the revised header preflight, channel
preservation and buffer lifetime have not been rebenchmarked on this dataset.

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

## Historical simulated long-sequence scalability

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

## Native-memory smoke measurement, 2026-10-12

The isolated-process benchmark was smoke-tested locally using an existing small
320 x 180, 15-channel fixture. Peak resident memory was 45.90 MiB; the
after-import baseline high-water mark was 38.77 MiB. This confirms that native
process memory can be measured, not that the backend uses less memory than a
prior implementation. It is not a 4K, NFS or production-capacity evaluation.

For an existing authorized source:

```powershell
uv run python experiments/benchmark_memory.py "D:/renders/shot" --max-frames 800
```

No EXRs are generated. An oversized discovery is refused rather than sampled;
measurements and configuration are printed as JSON. See the methodology for
high-water-mark interpretation and platform units.

## Unreleased memory-guard calibration, 2026-10-12

One existing user render was measured read-only in separate child processes on
Windows/Python 3.12.12/OpenEXR 3.4.12. The source name/path is anonymized here:
1920 x 1080, 56 physical channels, 17 AOV descriptors. Its `flat-working-set-v1`
estimate was 2,489,262,080 bytes (2373.9453125 MiB), including all channels and
parts rather than a selected color subset.

| Budget (MiB) | Estimated MiB | Processed | Failed | Peak RSS MiB | Analysis time |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 4096 | 2373.9453125 | 1 | 0 | 935.59375 | 1.849241 s |
| 1024 | 2373.9453125 | 0 | 1 | 39.01171875 | 0.0021095 s |

The admitted run's after-import baseline high-water mark was 40,816,640 bytes;
its peak was 981,041,152 bytes. It diagnosed 7 color and 10 non-color AOVs and
produced one contextual finding. The rejected run had no peak growth above its
import baseline and never invoked pixel decode, corroborating the constructor-
spy regression tests. These are single measurements, not throughput or memory-
reduction promises. They validate the gate on one Full-HD input, not 4K, NFS,
all compressions or concurrent-source safety. 4K estimate tests use headers
without allocating 4K pixels.

Example using an existing authorized source:

```powershell
uv run python experiments/benchmark_memory.py "D:/renders/approved/frame.0001.exr" --max-memory-mb 4096
```

The guard is available in the development checkout after 1.3.0; previously
created 1.3.0 distributions have not been regenerated for this update. It is
an estimate-based admission decision, not an RSS/global memory limit.
