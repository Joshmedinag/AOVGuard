# Limitations

AOVGuard is a prototype Pipeline TD tool, not a replacement for a full studio render validation system.

Current limitations:

- Development source ZIPs have unsigned integrity manifests, not publisher
  signatures or secret scanning. Common local/private paths are excluded, but
  approved source/document content still requires human review before sharing.
  Reproducibility is for identical selected bytes on the same Python/zlib
  runtime; concurrent source edits are not an atomic snapshot. No-overwrite
  publication requires filesystem hard links and fails on unsupported storage.
  A forced kill or cleanup failure may leave a temporary ZIP sibling; this is
  not a hard power-loss durability or hostile-filesystem guarantee.

- Development report exports use atomic replacement per file, not an all-or-
  nothing JSON/HTML transaction. File synchronization does not guarantee
  power-loss durability or network-filesystem behavior. Concurrent writers
  are not coordinated; Windows may reject a locked destination. Basic mode
  bits are retained for existing files, but full ACLs/ownership are not copied.
  Forced termination or failed temporary cleanup can leave a `.tmp` sibling.
  Path checks prevent ordinary mistakes, not malicious concurrent path swaps.

- The post-1.3.0 memory guard is an unreleased, conservative per-frame admission
  estimate, not a hard OS RSS cap, total-analysis budget or guaranteed allocator/
  decoder bound. Report histories, GUI objects and concurrent jobs are not fully
  bounded. A source may change between header-only preflight and eager decode.
- The model covers every physical channel in every flat part, independent of
  category/selection, using stored windows and worst-case promotions rather
  than exact inferred pixel types. Header failures never fall back to unguarded
  reads. Over-budget frames are failed/skipped before decode; others continue.

- The analysis uses luminance statistics, so it cannot understand artistic intent.
- Thresholds should be calibrated for real shows and render settings.
- Colour analysis expects identifiable RGB channel roles. Supported technical
  AOVs receive objective channel statistics and NaN/Inf checks. The opt-in
  development `technical_range` policy checks per-AOV component bounds but
  does not infer units, coordinate space or valid ranges from the renderer.
  It does not test vector length, decode Cryptomatte IDs, count out-of-range
  pixels or locate them. An all-non-finite channel requires `nan_inf` to report
  its integrity failure. Per-frame AOV presence requires `missing_aov`.
- Cryptomatte classification relies on standard `cryptomatte/.../name` EXR
  metadata (or an explicit AOV-category preset override). If a renderer strips
  that metadata, an RGB-named ID pass can still look like a color AOV and
  should be classified explicitly in the preset.
- Flat multipart EXRs are supported, with independent channels, windows and
  namespaced AOVs. Any deep part rejects the entire file before pixel decoding;
  deep sample interpretation remains unsupported. A failure to decode any part
  or channel rejects the full frame rather than retaining partial metrics.
  Subsampled channel buffers that do not match their stored window are rejected.
- Unique named-part identities stay stable across reordering while the file
  remains multipart. A two-part file becoming single-part returns to historical
  unqualified identities and produces a structure change. Unnamed or duplicate
  part names use index-based fallback; their semantic identity cannot be
  preserved across arbitrary reordering.
- The native OpenEXR API eagerly loads all pixel data for supported parts.
  FLOAT/UINT buffer reuse and release before the next frame avoid unnecessary
  retained references, but do not establish streaming, a lower measured peak
  RSS or a fixed memory guarantee. Real process-level 4K/RAM measurements remain
  a separate evaluation task.
- Pixel metrics use `dataWindow`; resolution checks use `displayWindow`.
  Changing autocrop or overscan can therefore change the measured average
  without changing delivery resolution. Coordinates are retained for review,
  but statistics are not automatically padded to the full display window.
- Numbered sequences have separate temporal summaries. Previous-frame deltas
  skip gaps, failed frames and missing AOV samples; comparison-set variation
  describes sample order and is not evidence of temporal continuity.
- Per-frame/per-channel statistics now preserve exact-file evidence for NaN,
  infinity, negative and extreme-value findings. They retain scalar statistics,
  not pixel locations or full images. Min/max can prove a threshold crossing,
  but cannot reconstruct the number of pixels above an arbitrary new threshold
  without rereading the frame.
- ACEScg/AP1 luminance coefficients expect scene-linear AP1 RGB. AOVGuard does
  not infer primaries, linearize display-encoded data, apply OCIO transforms or
  evaluate artistic exposure. Negative values can be valid in signed color
  workflows; the negative-value rule requires project-specific calibration.
- Canonical schema `1.2` reports retain per-part provenance and effective rule
  parameters for baseline compatibility checks. Historical `1.0` and `1.1` reports
  remain readable, but absent provenance produces an explicit compatibility
  warning. Available contradictory configurations are rejected. A `null` or
  otherwise non-finite metric is unavailable, not a verified unchanged value.
- The unreleased canonical CLI/GUI default to a reusable sequential analysis
  child. Isolation permits terminating a blocked/crashed worker but is not a
  security sandbox, OS RSS cap, cache or parallel frame-processing system.
  Generic API isolation remains opt-in; explicit custom readers need a
  supported process specification.
- Isolated API scripts need the standard spawn-safe `__main__` guard.
  Notebook/REPL callers should use the in-process API or invoke the external
  CLI; unsupported contexts do not silently fall back to native in-process
  execution. Standalone inspection and legacy analyzers are outside the new
  canonical analysis execution controls.
- Frame service deadlines start after the child is ready and include headers,
  decode, reductions and IPC. Startup has a separate 30-second deadline and
  cleanup is separate; total-job elapsed time can therefore exceed the selected
  frame timeout. No timeout is configured by default.
- Source discovery, aggregate/final rules, report export and standalone header
  inspection run in the parent outside the frame deadline. Slow NFS/directory
  listing or manual inspection is not covered by a hard job-wide time limit.
- Recorded elapsed time includes frame service and can also include startup
  and cleanup, so it must not be compared directly with the configured service
  deadline as a decode-only timing.
- If bounded cleanup cannot confirm that the child/receiver stopped,
  `WorkerCleanupError` aborts the job and forbids executor reuse; the GUI blocks
  new analyses until the application is restarted after checking any remaining
  process. No bounded-wait policy can guarantee that the OS terminates an
  unkillable process.
- In-process GUI/API or CLI `--in-process` cancellation remains cooperative.
  A native OpenEXR operation must finish first; deferred window close can then
  wait for it. Isolated cancellation instead stops/reaps the child and waits
  for cleanup without blocking the GUI event loop.
- Execution PID/timing are diagnostic and not semantic baseline evidence.
  Timeout/crash/admission failures alter frame availability and can change
  aggregates or findings even though accepted-frame formulas are unchanged.
- Default frame discovery uses direct EXRs when present and ignores nested EXRs
  with a warning. Optional recursive discovery, filename patterns and bounded
  depth are available. The sequence checker detects gaps, duplicate frame numbers, and
  inconsistent padding by interpreting the final numeric token in each filename.
  An optional expected range checks completeness only for one numbered sequence.
  Show-specific naming parsers and a visual sequence picker remain future work.

Use `uv run python experiments/benchmark_memory.py "D:/renders/shot" --max-frames 800`
to measure native peak RSS on an existing source without generating EXRs. The
recorded small-input smoke measurement (320 x 180, 15 channels; 45.90 MiB peak,
38.77 MiB after-import baseline) is documented in `benchmark_results.md`; it
does not validate 4K or NFS capacity.

One existing user render at 1920 x 1080, 56 channels and 17 AOVs was measured
once per budget on Windows/Python 3.12.12/OpenEXR 3.4.12. The header estimate was
2373.9453125 MiB. Under 4096 MiB it processed one frame with peak RSS
935.59375 MiB; under 1024 MiB it failed before pixel decode, with peak RSS
39.01171875 MiB and no growth above the import baseline. This checks the gate
on one Full-HD input. It does not prove 4K/NFS capacity, a global memory cap or
a universal performance improvement. See `benchmark_results.md` for the
measurement details.
