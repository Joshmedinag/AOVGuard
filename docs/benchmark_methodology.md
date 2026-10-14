# Frame-first Benchmark Methodology

The AOV-first comparison below records the historical pre-1.3.0 experiment.
Its generator is developer-only and excluded from clean source releases.
It does not measure the current multipart reader's native memory capacity.

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

## Native process peak memory on existing sources

The current read-only benchmark launches a fresh child process for each input:

```powershell
uv run python experiments/benchmark_memory.py "D:/renders/shot" --max-frames 800
```

The unreleased admission option can be included when measuring a guarded read:

```powershell
uv run python experiments/benchmark_memory.py "D:/renders/approved/frame.0001.exr" --max-memory-mb 4096
```

Its positive finite MiB budget gates each flat frame before native pixel read,
covering every part/channel. An over-budget frame is retained as failed with
estimate evidence, not sampled or read without protection. The command still
generates no EXRs/reports and prints structured JSON. Estimate equality is
allowed, but the model does not impose an OS/global memory cap. Test accepted
and rejected budgets in separate fresh child processes and record each run;
do not interpret one source as a 4K/NFS capacity evaluation.

It generates no EXRs, reports or other output files, and prints measurement
JSON to standard output. The frame limit is a refusal threshold, not a sampling
count. Discovery patterns, recursion and depth are configurable.

The worker records the peak RSS high-water mark after imports and after
analysis. Windows uses PeakWorkingSetSize; POSIX uses the platform-specific
ru_maxrss units. Native OpenEXR/NumPy allocations are included, unlike
tracemalloc. Subtracting the two high-water marks describes peak growth, not
instantaneous allocations or a memory leak. Interpret results alongside
resolution, part/channel inventory, storage and compression, and measure 4K
or NFS explicitly before making capacity claims.
