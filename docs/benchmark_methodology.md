# Frame-first Benchmark Methodology

## Research question

Does reorganising multilayer EXR analysis from AOV-first iteration to
frame-first iteration reduce application-level read calls while preserving the
same decoded pixel values?

## Compared strategies

**AOV-first** iterates through every AOV and then every frame. For `F` frames
and `A` colour AOVs, AOVGuard requests approximately `F x A` frame reads.

**Frame-first** reads each frame and consumes all colour AOVs from the returned
`FrameData`. It requests approximately `F` frame reads and releases the arrays
before moving to the next frame.

## Reproduction

From the project root:

```powershell
uv run python experiments/benchmark_analysis.py
```

The script creates deterministic data below `experiments/_benchmark_data/` and
writes machine-readable results to `experiments/benchmark_results.json`.
The default run completes 30 recorded repetitions per strategy after one
unrecorded warm-up for each. Strategy order alternates on every repetition to
balance cache and order effects.

## Recorded measures

- Calls made by AOVGuard to `OpenEXRReader.read_frame`.
- Median, minimum, quartiles and interquartile range for elapsed wall-clock time.
- Peak Python-tracked memory measured by `tracemalloc`.
- A checksum of all decoded AOV values.
- Dataset dimensions, number of frames and number of colour AOVs.
- Python, NumPy, OpenEXR and platform versions.

The checksum must match between strategies. Read-call count is deterministic;
timing and memory are contextual measurements and should not be presented as
universal claims. `tracemalloc` does not measure all native allocations made by
the OpenEXR binding. Operating-system caching may also affect timing despite
warm-up and alternating order.

## Interpretation

The primary evidence is the reduction in application-level read calls while
preserving the checksum. Timing is supporting evidence. A final dissertation
comparison should run on the stated hardware, use identical generated inputs,
report medians and spread, and describe the warm-up and order-balancing policy.

## Long-sequence safeguard benchmark

For a no-file scalability smoke test, run:

```powershell
uv run python experiments/benchmark_simulated_sequences.py
```

This benchmark uses mocked discovery and an in-memory deterministic reader, so
it does not generate EXR demonstration files. It reports elapsed time and
Python-tracked peak memory at 100, 500 and 1,000 frames. Treat it as evidence
for pipeline control flow and accumulation only; real EXR I/O, resolution,
compression and native-library allocations require a separate authorised-data
benchmark.
