# Architecture

AOVGuard now uses a shared backend for CLI and GUI analysis.

## Main flow

```text
EXR file or folder
  -> frame discovery
  -> source interpretation (single / sequence / comparison)
  -> execution policy (reusable sequential child, or explicit in-process)
  -> header-only structure inspection and unsupported-structure rejection
  -> one pixel decode per supported frame
  -> exact channel arrays + semantic AOV views
  -> canonical RGB color AOV data
  -> color luminance metrics + every physical channel's integrity diagnostics
  -> per-frame/per-channel statistics + aggregate and sequence-specific metrics
  -> configurable validation rules
  -> AnalysisReport
  -> CLI / GUI / JSON / HTML / report comparison
```

## Main modules

- `core/models.py` defines file/part inspections, AOV descriptors, metrics,
  findings, options and reports. Every part retains its original name, view,
  channel names and independent data/display windows.
- `core/luminance.py` provides Rec.709, Rec.601, ACEScg/AP1 and custom luminance
  weights. Named coefficients describe scene-linear source primaries, not color
  transformations.
- `core/memory.py` supplies the unreleased `flat-working-set-v1` estimate and
  positive finite MiB validation from complete headers without loading pixels.
- `core/execution.py` defines typed timeout, crash, protocol and cleanup failures.
- `io/process_executor.py` owns spawn/readiness, sequential child reuse,
  request deadlines, scalar-only result validation and bounded child cleanup;
  `io/process_worker.py` inspects, decodes and reduces frames inside the child.
- `core/analysis.py` coordinates discovery, reading, incremental metrics and
  rule execution. It also computes median/MAD variation and consecutive-frame
  deltas without retaining image arrays. `_measure_frame` reduces and releases
  one frame's buffers before the next frame is read.
- `discovery/frame_discovery.py` provides the exact frame list used for
  analysis and reporting.
- `io/inspector.py` infers AOV structure and approximate categories from
  channel names.
- `io/reader.py` implements the current OpenEXR backend.
  `FrameData.channel_data` retains exact source-channel names, including alpha
  and auxiliary components. UINT arrays remain integer-exact, FLOAT buffers
  can be reused and HALF buffers are promoted to float32. RGB aliases are
  resolved consistently; colliding root groups get a distinct `[root]` label.
  Flat multipart arrays remain separated under namespaced identities, while a
  deep part or partial decode rejects the complete frame.
- `rules/` contains configurable rule definitions, loading, registration and
  isolated execution. Built-in checks include channel NaN/Inf, negative values,
  constant channels, empty AOVs, resolution mismatch and AOV-structure mismatch.
- `reports/json_report.py` writes the canonical JSON report.
- `reports/html_report.py` derives a human-readable report from the same model.
- `reports/comparison.py` compares two canonical JSON reports and identifies
  AOV metric changes plus new or resolved findings.
- `cli.py` provides the new `analyze` and `inspect-structure` commands while
  retaining legacy commands temporarily.
- `ui.py` provides the PySide6 main window over the same backend.
- `gui/controller.py` owns `AnalysisController`: job startup, cancellation,
  thread cleanup and shutdown readiness. `gui/settings.py` owns
  `PreferencesStore`; presentation no longer manages those responsibilities.
- `gui/launcher.py` loads Qt only when launching the optional desktop UI. Base
  CLI installations import neither Qt nor OpenCV; legacy simple analysis now
  uses OpenEXR while preserving its private BGR adapter contract.
- `gui/worker.py` owns the Qt worker and option adapter; `gui/presentation.py`
  contains reusable result-formatting helpers; and `gui/series.py` performs
  pure luminance/delta/percentage transformations and robust display
  statistics without depending on Qt.

The GUI's dedicated Outliers tab is a presentation over canonical
`series_metrics_by_aov` results and navigates to `frame_metrics`. Changing the
chart mode recalculates presentation-only robust statistics without mutating
the analysis report or its exported evidence.

## Technical range policies

The development `rules/technical.py` validator applies an opt-in
`technical_range` policy to exact AOV identities. It validates the complete
configuration before evaluating per-frame channel minima/maxima, with category
checks against each frame's inspection. It reuses existing float64-derived
statistics, adds no pixel reads or worker IPC fields, and groups only affected
frames into each channel finding. Numeric bounds and zero-default tolerance
are normalized in effective-rule provenance. Baseline compatibility compares
enabled definitions; changes to inactive definitions have no semantic effect.

## Report publication

Report writers share `io/output.py`: `validate_output_paths` checks destination
and input identities, while `atomic_text_writer` owns a same-directory temporary
file, UTF-8 stream, flush/fsync, mode-bit copy and final `os.replace`. Validation
is repeated before replacement. Failures before that commit leave the previous
target intact; cleanup errors are attached to the original exception. Writers
protect frame inputs, the CLI supplies configuration/comparison inputs, and the
GUI remembers analyzed presets and loaded baselines for the current window.
This is per-file publication, not a multi-output transaction or an OS lock.

## Progress and cancellation

The shared analysis API accepts optional progress and cancellation callbacks.
The GUI worker runs in a `QThread` and updates progress after each frame. In the
unreleased isolated mode, cancellation is polled during startup/request waits
and stops/reaps the child rather than interrupting native objects in the parent.
In-process mode only checks cancellation cooperatively; a native operation must
return before the current frame can finish and cancellation is observed.

`FrameData` carries its `FileInspection`; header-only preflight permits deep
rejection before pixel allocation. Supported flat single/multipart files undergo
one pixel decode. Reports distinguish discovered, successfully processed and
failed frames. The JSON schema converts non-finite metric values to `null`
while preserving NaN/Inf counts in the associated metrics and findings.

`FileInspection.width/height` follow the stored `dataWindow` buffer. Separate
`data_window` and `display_window` fields preserve both origins and extents;
delivery-resolution rules use display dimensions. Pixel statistics retain the
stored-region interpretation and do not synthesize a padded display canvas.
For multipart files, `PartInspection` supplies the corresponding dimensions and
coordinates for each AOV; file-level width/height remain first-part compatibility
fields. Resolution and AOV-structure baselines are isolated by numbered sequence.

Multipart identities follow `[part:escaped-name]::AOV` for unique named parts,
`[part-index:N]::AOV` for unnamed parts, and `[part-index:N:escaped-name]::AOV`
for duplicate names. Percent escaping preserves delimiter-containing names.
Unique named parts retain identity when reordered within multipart files;
unnamed/duplicate parts depend on physical index. Single-part keys remain
historically unqualified, so a two-part file becoming single-part is a detected
structural transition rather than a stable namespace.

`AnalysisReport.frame_metrics` stores a `MetricSet` for each successfully
processed frame/AOV pair. `frame_channel_metrics` stores scalar channel
statistics keyed by frame, AOV and exact channel. Pixel arrays remain in the
temporary `FrameData` and are released before the next frame read; reports do
not retain sequence pixels. The complete-frame OpenEXR backend still requires
memory proportional to channels and resolution, plus semantic view and
calculation temporaries. The native API eagerly loads all part pixels; releasing
frame references does not imply streaming or a measured peak-RSS reduction.
`core/status.py` provides the shared PASS/WARNING/FAIL decision used by
JSON, HTML and the GUI.

`AnalysisReport.source_kind` records whether discovery resolved to a single
file, numbered sequence or comparison set. Sequence findings execute only for
the numbered-sequence interpretation. Aggregate empty/near-empty findings keep
their exact `affected_files`, and `series_metrics_by_aov` stores robust summary
statistics suitable for temporal or look-comparison review. Channel rules also
derive exact affected files from per-frame histories. For numbered sequences,
`series_metrics_by_sequence` groups summaries by directory/pattern; deltas
require consecutive frame numbers. Multi-sequence analysis avoids exposing a
single combined temporal trend under `series_metrics_by_aov`.

Canonical analysis schema `1.2` serializes per-part structure, per-frame channel evidence and
`metadata.effective_rules` (IDs, enablement, severity, parameters and supported
AOV types). Report comparison accepts schemas `1.0`, `1.1` and `1.2`, validates the
available semantic configuration, and warns when old provenance is missing.
Unavailable numeric differences cannot be reported as unchanged. Finding
identity includes source-relative affected paths and metric evidence.
The derived comparison-output schema remains `1.0`; it is separate from the
analysis-report schema.

`AnalysisOptions` also carries the frame pattern, recursive-search flag,
maximum depth and multiple-sequence policy. The same discovered frame tuple is
used for processing, progress, sequence checking and reporting. Technical AOV
arrays are read during the same frame operation as colour AOVs, aggregated per
channel and then released; only colour descriptors enter luminance metrics.

Closing during a job requests cancellation and defers window destruction until
child cleanup and QThread completion. Progress and terminal signals govern that
non-blocking lifecycle; explicit in-process mode can still delay it in native I/O.

## Unreleased isolated frame execution

Canonical CLI/GUI default to isolation; `AnalysisOptions.isolate_frames=False`
preserves the generic API's previous in-process behavior. Explicit API isolation
requires a reader with a supported `ReaderProcessSpec` (the native OpenEXR
reader supplies it); unsupported custom readers fail rather than silently
falling back. One persistent spawned process handles frames sequentially.
API scripts require the standard `if __name__ == "__main__":` guard for spawn;
notebook/REPL callers should use the in-process API or an external CLI job.
Headers, decode, reductions and memory admission happen inside that child,
and only scalar inspections/accumulators/estimates return through IPC. Arrays
are released after measurement; there is no parallel frame processing or cache.

`frame_timeout_seconds=None` permits unlimited frame service. Positive finite
deadlines require isolation and start after the ready handshake. They cover
header inspection, optional memory gating, native decode, reductions and IPC;
interpreter startup has a separate 30-second deadline. Cleanup is also separate,
so this is not a total-job wall-time guarantee. Recorded `elapsed_seconds` can
include startup, frame service and cleanup. Timeout, crash and protocol failure retain exact-file evidence,
mark the frame failed, reap the child and permit restart for the next frame.
Cancellation ends the job and reaps the active worker; final cleanup runs on
normal return, exceptions and CLI KeyboardInterrupt.
Discovery, aggregate/final rule evaluation, report export and standalone
inspection run in the parent outside the service deadline. In particular,
NFS/directory listing and manual header inspection have no hard time bound
from this frame execution policy.

If termination/join cannot confirm child or receiver cleanup, fatal
`WorkerCleanupError` stops the analysis. The executor is poisoned and cannot
be reused or start another worker. GUI recovery remains fail-closed: further
analyses are blocked with guidance to verify remaining processes and restart
the application. Cleanup attempts use bounded waits, but cannot guarantee
that the OS can terminate an unkillable process.

`AnalysisReport.frame_execution` retains each frame's execution mode, status,
worker PID, elapsed seconds, configured timeout, exit code and stage. These
diagnostics and execution options are additive to JSON schema 1.2 and are shown
in HTML. PID/timing are volatile, not finding identity or numerical metric
evidence; comparison ignores execution policy when accepted metric semantics
are unchanged. Failures can still alter the admitted frame set and results.
The process boundary is not a security sandbox or hard RSS cap.
Standalone header inspection and compatibility analyzers are outside this
canonical analysis execution policy.

## Unreleased per-frame memory admission

`AnalysisOptions.max_memory_mb=None` disables the guard. A positive finite
MiB value requires consistent, complete header preflight for every frame.
Invalid/incomplete metadata fails explicitly without unguarded fallback.
`MemoryBudgetExceeded` carries the inspection and estimate; analysis retains
them, emits an exact-file `memory_budget` error, marks the frame failed and
continues with remaining frames. Equality is allowed using exact integer-byte
comparison with the configured float's integer ratio.

For each stored part with `P` pixels and `C` physical channels, model v1 reserves
`P*C*(4+4+8)` bytes for native data, worst-case promotion and stacks. It adds
`32*max(P)` scratch bytes across parts and a fixed 64 MiB reserve, multiplies
the subtotal by 1.25 and rounds upward in bytes. Unknown/ignored/alpha/AUX/
Cryptomatte channels count identically. Category/selection does not lower the
estimate, exact channel types are not assumed and display-window padding is
not substituted for stored data.

`AnalysisReport.memory_estimates` stores model version, part/channel counts,
buffer/reserve/margin components and estimated bytes/MiB per frame. JSON budget/
model/breakdown fields are additive to schema 1.2. Gating changes availability,
not accepted metric semantics, so baseline configuration comparison ignores
the budget; different accepted frame sets can still change aggregate results.

This is not a hard/global RSS cap. Native OpenEXR eagerly loads all part pixels;
source replacement between header and pixel opens can invalidate assumptions.
Decoder internals, report history, GUI allocations and concurrent work are not
fully bounded. In-process native reads remain non-interruptible by cooperative
cancellation; isolated cancellation stops the child. Caching and table
virtualization remain separate work, not features of this admission layer.
