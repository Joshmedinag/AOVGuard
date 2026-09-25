# Architecture

AOVGuard now uses a shared backend for CLI and GUI analysis.

## Main flow

```text
EXR file or folder
  -> frame discovery
  -> source interpretation (single / sequence / comparison)
  -> one OpenEXR.File read per supported frame
  -> structure inspection from the same read
  -> canonical RGB color AOV data
  -> color luminance metrics + technical per-channel diagnostics
  -> configurable validation rules
  -> AnalysisReport
  -> CLI / GUI / JSON / HTML / report comparison
```

## Main modules

- `core/models.py` defines inspections, AOV descriptors, metrics, findings,
  options and reports.
- `core/luminance.py` provides Rec.709, Rec.601 and custom luminance weights.
- `core/analysis.py` coordinates discovery, reading, incremental metrics and
  rule execution. It also computes median/MAD variation and consecutive-frame
  deltas without retaining image arrays.
- `discovery/frame_discovery.py` provides the exact frame list used for
  analysis and reporting.
- `io/inspector.py` infers AOV structure and approximate categories from
  channel names.
- `io/reader.py` implements the current OpenEXR backend.
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
- `gui/worker.py` owns the Qt worker and option adapter; `gui/presentation.py`
  contains reusable result-formatting helpers; and `gui/series.py` performs
  pure luminance/delta/percentage transformations and robust display
  statistics without depending on Qt.

The GUI's dedicated Outliers tab is a presentation over canonical
`series_metrics_by_aov` results and navigates to `frame_metrics`. Changing the
chart mode recalculates presentation-only robust statistics without mutating
the analysis report or its exported evidence.

## Progress and cancellation

The shared analysis API accepts optional progress and cancellation callbacks.
The GUI worker runs in a `QThread`, updates the progress bar after each frame
and checks cancellation cooperatively between frames. The current frame is
allowed to finish so backend objects are not interrupted mid-read.

`FrameData` carries its `FileInspection`, so analysis does not perform a second
header read. Reports distinguish discovered, successfully processed and failed
frames. The JSON schema converts non-finite metric values to `null` while
preserving NaN/Inf counts in the associated metrics and findings.

`AnalysisReport.frame_metrics` stores only a `MetricSet` for each successfully
processed frame/AOV pair. Pixel arrays remain in the temporary `FrameData` and
are released as the loop advances, so reports do not retain a sequence in
memory. `core/status.py` provides the shared PASS/WARNING/FAIL decision used by
JSON, HTML and the GUI.

`AnalysisReport.source_kind` records whether discovery resolved to a single
file, numbered sequence or comparison set. Sequence findings execute only for
the numbered-sequence interpretation. Aggregate empty/near-empty findings keep
their exact `affected_files`, and `series_metrics_by_aov` stores robust summary
statistics suitable for temporal or look-comparison review.

`AnalysisOptions` also carries the frame pattern, recursive-search flag,
maximum depth and multiple-sequence policy. The same discovered frame tuple is
used for processing, progress, sequence checking and reporting. Technical AOV
arrays are read during the same frame operation as colour AOVs, aggregated per
channel and then released; only colour descriptors enter luminance metrics.
