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

Choose Rec.709, Rec.601 or ACEScg for color AOV luminance metrics, matching the
scene-linear source primaries. ACEScg uses the AP1 Y coefficients
`(0.2722287168, 0.6740817658, 0.0536895174)`; it does not apply a color transform
or detect the source color space. Choose **Custom** to
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

## Development update: Memory budget

The working copy adds **Memory budget (MiB)** after release 1.3.0. `0 /
Unlimited` disables the guard and is the default for fresh/older settings.
A positive value gates each flat frame's header estimate before pixel decoding.
Units are binary MiB (1,048,576 bytes).

All parts/channels count, including unknown, ignored, alpha/AUX and Cryptomatte
data. Over-budget frames get `memory_budget` errors, retained header/estimate
evidence and exact file paths; subsequent frames continue. Invalid saved
values restore a 1024 MiB guard with a visible warning, rather than silently
disabling protection. Review the restored setting before analysis.

The model uses stored data windows and worst-case promotions, not assumed
exact header pixel types. It is not a hard RSS/global budget. Native reads
remain eager; in-process cooperative cancellation cannot abort them. A concurrent file
change can invalidate preflight assumptions. JSON/HTML show the model and
breakdown, and accepted-frame metric semantics remain unchanged.

## Development update: Execution controls

**Isolate analysis process** is enabled for fresh/older settings. One spawned
child is reused sequentially per analysis job; it returns scalar evidence, not
pixel arrays. Unchecking it displays the in-process warning and disables the
timeout control: native I/O cannot then be interrupted. Corrupt saved execution
mode values restore isolation with a visible warning.

**Frame timeout (s)** uses `0 / No timeout` by default. Positive values bound
frame service after the child is ready: header inspection, admission, decode,
reductions and IPC. Startup has a separate 30-second deadline, and cleanup can
add time. The GUI supports 0.01–86400 seconds when enabled. Invalid saved values
restore 30 seconds with a warning; out-of-range saved values are adjusted with
visible guidance. Review these settings before running.
Discovery, final rules, report export and manual **Inspect Structure** run in
the parent and are not covered by this frame deadline; a slow folder listing
is not a timed frame operation.

A timeout or crash fails the affected frame with `frame_timeout` or
`worker_crash`, then subsequent frames can use a replacement child. These
controls do not add parallel processing, caching, security sandboxing or an
OS RSS cap. Generic Python API isolation remains opt-in.

Fatal `WorkerCleanupError` is different from an ordinary frame timeout/crash:
if cleanup cannot confirm that the child/receiver stopped, the job aborts and
the GUI blocks new analyses. Follow the visible guidance to verify any remaining
process before restarting AOVGuard. There is no silent worker replacement in
this state and no guarantee of OS termination for an unkillable process.

## Inspect Structure

Inspects the first discovered EXR and displays dimensions, channels, inferred
AOVs, approximate AOV categories, part count and deep-data status. Flat multipart
inspection lists each part's original name/view and data/display windows;
namespaced AOVs remain separate rather than combining parts.

## Analyze

Runs the shared backend in a worker thread. Header-only preflight rejects
unsupported structures before pixel allocation; a supported frame then gets
one pixel decode. The progress bar reports each attempt and the final status
distinguishes successful and failed frames.

The status band summarises the result as PASS, WARNING or FAIL and shows counts
by severity. **Cancel** stops and reaps the active isolated child. In explicit
in-process mode it is cooperative, so native EXR reads must return first.
Closing during an active job requests cancellation and keeps the window open
while child/thread cleanup finishes, then closes
automatically after thread termination. The GUI event loop remains active
during this deferred close.

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

Flat multipart AOV labels use `[part:escaped-name]::AOV`, with index fallback
for unnamed/duplicate parts. Parts retain separate pixel dimensions and channel
diagnostics. A frame containing any deep part or incomplete decode fails as a
whole. Single-part names remain unqualified for backward compatibility.

The chart has independent AOV and display-mode selectors and is unaffected by
table sorting. When several numbered sequences are allowed, its **Sequence**
selector selects a separate temporal series; locating an outlier also selects
that outlier's sequence. Previous-frame chart and table deltas do not cross
missing/failed frames or absent AOV samples. **Luminance** shows the absolute average; **Delta previous** and
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
NaN/+Inf/-Inf counts, and negative-value counts for every supported physical
channel. Alpha and auxiliary channels of color/vector AOVs are included in
integrity checks, and channel findings retain exact affected files. Root RGB
alongside a named `beauty` layer appears as `beauty [root]`; UINT ID arrays
preserve their exact integers. These values are diagnostics; technical passes are not
evaluated with a colour luminance formula.

The structure summary distinguishes color, vector, depth, mask, scalar,
Cryptomatte and unknown AOVs. Cryptomatte metadata identifies encoded IDs and
coverage; these channels stay in **Technical** and retain integrity checks,
but do not contribute luminance or temporal outliers. Very large technical
values are displayed in scientific notation.

In the development checkout, **Validation Rules → Technical ranges** enables
the preset's `technical_range` rule. It is off by default and requires a
`parameters.ranges` table keyed by exact AOV name; enabling it without a policy
produces a visible `rule_error`. Set bounds/tolerance in the preset, then load
it or press **Restore Preset**. See `usage.md` for a TOML example.
Range findings appear in **Findings**, including the physical channel and
affected files in **Finding Details**, with the existing copy-path/open-folder
actions. **Technical** retains the underlying statistics. Cryptomatte and
unclassified AOVs cannot receive this range policy.

If multiple unnumbered EXRs are selected in Auto mode, the sequence view
identifies a comparison set rather than reporting a false sequence warning.
Aggregate empty/near-empty findings show the number of affected files and list
their exact paths in Finding Details.
Right-click a table header to hide columns or restore the default layout. The
GUI remembers the last source, preset, luminance and discovery selections.

## Export JSON

Exports strict JSON schema version `1.2`, including discovered/successful/failed
frames, inspections, an AOV inventory, aggregate and per-frame metrics,
executed rules, status and findings. The inventory retains category confidence,
channels and files for unknown and explicitly ignored AOVs. Non-finite numeric
metrics are represented as `null`, with their counts retained separately.
The report records exact per-frame channel statistics, every part's EXR windows/name/view and
effective rule parameters including built-in defaults. Baseline schemas 1.0 and 1.1
remain readable with a warning when configuration compatibility cannot be verified.
The development schema adds execution options and per-file `frame_execution`
diagnostics (mode/status/PID/elapsed time/timeout/exit code/stage) without changing
schema 1.2. Volatile PID/timing are not baseline metric evidence.

## Export HTML

Exports a self-contained readable report derived from the same
`AnalysisReport`. It includes application/configuration provenance, analyzed
channels and cautious interpretations that distinguish an actionable error
from an AOV that may be intentionally empty. JSON remains the canonical
pipeline format.
Development reports also include memory-admission and frame-execution tables.
Elapsed execution time can include startup, frame service and cleanup; the configured frame service
deadline excludes startup and cleanup and is not an end-to-end job timer.

## Export reliability

Development JSON/HTML exports use atomic replacement. Export failures before
replacement preserve an existing report and leave the current analysis in the
window for retry. EXR destinations, symbolic links, read-only files and known
input paths are rejected. This includes the current preset, presets used for
analyses and baselines loaded during this window's lifetime. Save a new report
under a separate filename instead of overwriting a comparison input.

## Compare Baseline

After analysis, **Compare Baseline** loads a canonical AOVGuard JSON report and
compares it with the current result. The Comparison tab shows added, removed,
changed, unchanged and unavailable AOVs with luminance/activity deltas. A
missing/non-finite metric is unavailable rather than numerically unchanged.
Recorded incompatible luminance weights, thresholds, categories, source
interpretation or effective rules reject comparison. Missing historical
configuration produces a visible compatibility warning. The CLI offers the
same comparison through `aovguard compare-reports`.

Launch from a source checkout with `uv run --extra gui aovguard-ui`, or install
the distribution's `gui` extra. The desktop's `AnalysisController` coordinates
execution and non-blocking cleanup; `PreferencesStore` manages persisted
choices. The CLI remains usable without Qt or OpenCV.
