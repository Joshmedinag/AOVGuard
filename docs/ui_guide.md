# UI Guide

AOVGuard uses automatic EXR structure inspection. The user no longer selects
Simple or Multilayer mode manually.

## EXR Source

Use **File** to select one EXR or **Folder** to select an EXR sequence.

## Rule Preset

The default validation rules run when no preset is selected. Use **Browse** to
load an optional TOML or JSON rule preset.

After inspection, unknown AOVs are offered for explicit classification. Choose
the intended category and use **Save to Preset**; the preset changes only after
the confirmation dialog. The write is atomic, existing rule sections are
preserved, and the new classification takes effect after another inspection or
analysis. Choosing `ignored` records an explicit decision while retaining the
AOV and its channel integrity diagnostics.

Individual rules can be enabled or disabled using the validation-rule
checkboxes. NaN/Inf, empty AOV and sequence consistency checks are enabled by
default. Negative-value and constant-channel checks are optional because their
meaning can depend on the AOV and production.

Use **Select All**, **Clear** or **Restore Preset** to change the rule selection
as a group. Hover over a rule for a short description. The validation rules and
secondary analysis settings can be collapsed to leave more room for results.

## Luminance

Choose Rec.709 or Rec.601 for color AOV luminance metrics. Choose **Custom** to
enter explicit R, G and B weights. Values must be finite and have a positive
sum; they are recorded in the exported report.

## Frame Discovery

**Frame Pattern** accepts a filename glob such as `*.exr` or
`shot.*.exr`. Enable **Recursive** to include direct and nested matches, then
set **Max Depth**. Multiple numbered sequences require the explicit
**Allow Multiple Sequences** option so unrelated renders are not combined by
accident. **Max Frames** rejects a larger-than-expected discovery before any
pixel data is read; `0` disables the limit.

**Expected Frame Range** is a separate, optional completeness check for one
numbered sequence. For a planned 1–800 render, enter `1` and `800`: if only
1–301 exist, **Sequences** shows `302–800` missing and **Findings** records an
error. This does not generate or repair frames. Frames outside the declared
range are warnings. Comparison mode is incompatible with this setting.

**Interpret Source As** controls meaning rather than file discovery:

- **Auto** resolves one file, a numbered sequence, or an independent comparison set.
- **Sequence** requires numbered EXRs and enables gap, duplicate and padding checks.
- **Comparison** treats discovered files as independent samples and suppresses
  sequence-gap findings.

## Inspect Structure

Inspects the first discovered EXR and displays dimensions, channels, inferred
AOVs, approximate AOV categories, part count and deep-data status.

## Analyze

Runs the shared backend in a worker thread. Structure and pixels are obtained
from one OpenEXR file object per supported frame. The progress bar reports each
attempt and the final status distinguishes successful and failed frames.

The status band summarises the result as PASS, WARNING or FAIL and shows counts
by severity. **Cancel** requests a cooperative stop after the current frame.

The **Metrics** tab contains aggregated color-AOV metrics. The **Findings** tab
contains validation warnings and errors, including channel-level findings and
sequence inconsistencies. **Outliers** lists robust luminance anomalies ordered
by score. **Sequences** shows filename/range diagnostics, and **Frames** exposes
each frame/AOV metric independently so a sequence anomaly does not disappear
inside an aggregate.

After analysis, the interface opens **Findings** when findings exist, otherwise
it opens the most relevant populated results tab. The first visible finding is
selected automatically. Result tables display compact relative paths while the
full path remains in the tooltip and finding details. Double-click a frame,
finding or sequence location to open its folder.

The **Frames** table becomes **Samples** for a comparison set. It shows
average-luminance change relative to the series median and to the previous
frame/sample. The Metrics view also exposes median, median absolute deviation
(MAD) and robust outlier counts, so an anomalous first frame does not become an
unquestioned baseline.

The chart has independent AOV and display-mode selectors and is unaffected by
table sorting. **Luminance** shows the absolute average; **Delta previous** and
**Relative %** shows signed frame-to-frame change, with the first sample
anchored at zero. A visible explanation states that a transition from a zero
baseline is represented as signed 100% to remain finite and visible because a
conventional percentage is undefined. The dashed line and shaded band are
recalculated for the selected display mode; triangles mark robust outliers and
squares mark frame errors. Text and shape, not colour alone, convey state.
Hover for exact evidence and click a sample to select its corresponding row in
**Frames/Samples**.

The **Outliers** tab displays file, AOV, value, median, absolute deviation,
robust score and reason. Select an entry and press **Locate Selected Frame** to
switch the chart AOV and select the exact frame in **Frames/Samples**;
double-click provides the same action. This view reports luminance-series
outliers from the analysis; changing the chart display mode may highlight a
different presentation-only anomaly without rewriting the canonical report.

The **Technical** tab lists per-channel minimum, average and maximum values,
NaN/+Inf/-Inf counts, and negative-value counts for supported vector, depth,
mask and scalar AOVs. These values are diagnostics; technical passes are not
evaluated with a colour luminance formula.

The structure summary distinguishes color, vector, depth, mask, scalar,
Cryptomatte and unknown AOVs. Cryptomatte metadata identifies encoded IDs and
coverage; these channels stay in **Technical** and retain integrity checks,
but do not contribute luminance or temporal outliers. Very large technical
values are displayed in scientific notation.

If multiple unnumbered EXRs are selected in Auto mode, the sequence view
identifies a comparison set rather than reporting a false sequence warning.
Aggregate empty/near-empty findings show the number of affected files and list
their exact paths in Finding Details.
Right-click a table header to hide columns or restore the default layout. The
GUI remembers the last source, preset, luminance and discovery selections.

## Export JSON

Exports strict JSON schema version `1.0`, including discovered/successful/failed
frames, inspections, an AOV inventory, aggregate and per-frame metrics,
executed rules, status and findings. The inventory retains category confidence,
channels and files for unknown and explicitly ignored AOVs. Non-finite numeric
metrics are represented as `null`, with their counts retained separately.

## Export HTML

Exports a self-contained readable report derived from the same
`AnalysisReport`. It includes application/configuration provenance, analyzed
channels and cautious interpretations that distinguish an actionable error
from an AOV that may be intentionally empty. JSON remains the canonical
pipeline format.

## Compare Baseline

After analysis, **Compare Baseline** loads a canonical AOVGuard JSON report and
compares it with the current result. The Comparison tab shows added, removed,
changed and unchanged AOVs with luminance/activity deltas. The CLI offers the
same comparison through `aovguard compare-reports`.
