# Usage

## UI workflow

Start the interface:

```powershell
uv run --extra gui aovguard-ui
```

1. Select an EXR file or folder.
2. Optionally select a TOML or JSON rule preset.
3. Select Rec.709, Rec.601, ACEScg or custom luminance weights matching the
   scene-linear source primaries. ACEScg uses AP1 coefficients and does not
   transform the image into another color space.
4. Choose **Auto**, **Sequence** or **Comparison** source interpretation.
5. Optionally set a filename pattern, recursive search depth and maximum frame
   count (`0` means unlimited). For a known delivery, enable **Expected Frame
   Range** and enter the first and last required frame.
6. Use **Inspect Structure** to review detected channels and AOVs.
   Unknown AOVs can be assigned an explicit category and saved to a preset only
   after confirmation. Reinspect or reanalyze to apply the saved override.
7. Click **Analyze**.
8. Review color metrics, robust sample variation, technical diagnostics and
   findings. Choose the plotted color AOV and switch between **Luminance**,
   **Delta previous** and **Relative %**. The visible explanation identifies a
   zero-to-activity transition as signed 100% because its conventional
   percentage is undefined. The shaded range, shapes and labels distinguish
   normal samples, robust outliers and frame errors. Click a plotted point, or
   select a score-ordered entry in **Outliers** and press **Locate Selected
   Frame**, to locate the exact AOV/frame evidence. Double-click remains
   available as a shortcut.
9. Export JSON/HTML or compare the current analysis with a baseline JSON report.

The GUI automatically inspects the EXR structure and does not require manual
Simple or Multilayer selection.

Channel findings identify the exact channel and affected files, including
alpha and auxiliary data. Use the finding details/copy path/open folder actions
to locate their evidence. A root RGB group alongside a named `beauty` layer is
labelled `beauty [root]`, so both appear separately.

Flat multipart parts appear independently, for example
`[part:left]::beauty` and `[part:right]::beauty`. Each retains its own channels,
view and windows. Unique names preserve identity across multipart reordering;
unnamed or duplicate names use index-based fallback. If any part is deep or
cannot be decoded completely, the whole frame fails.

In the development checkout, **Isolate analysis process** is enabled by default.
**Cancel** stops and reaps the active child; closing requests cancellation and
defers closing until child/QThread cleanup finishes without blocking the event
loop. Disabling isolation uses cooperative cancellation: native reads must
finish before it takes effect.

The unreleased **Memory budget (MiB)** control gates frames using header
estimates. `0 / Unlimited` disables it and is the fresh/older preference
default. Invalid saved values activate 1024 MiB with a visible warning; review
that value before running. It is not a hard process-memory cap.

**Frame timeout (s)** defaults to `0 / No timeout` and is available only with
isolation. A positive value bounds frame service after the child is ready:
headers, memory admission, decode, reductions and IPC. Startup has a separate
30-second deadline; startup/cleanup can add time to the overall job. Invalid
saved timeouts select 30 seconds with a visible warning; review before running.

## CLI workflow

Inspect an EXR structure:

```powershell
uv run aovguard inspect-structure ./renders/shot.1001.exr
```

Analyze a file or folder:

```powershell
uv run aovguard analyze ./renders --json ./reports/report.json
```

The canonical development CLI isolates analysis by default and reuses one
spawned child sequentially per job. Optional positive finite seconds bound each
frame after worker readiness:

```powershell
uv run aovguard analyze ./renders --frame-timeout-seconds 60 --json ./reports/report.json
```

The frame service deadline covers inspection, decode, reductions and IPC,
including the memory gate if enabled. Worker startup has a separate 30-second
deadline and cleanup is separate. A timeout/crash fails the exact frame with
`frame_timeout`/`worker_crash`; the worker is reaped and subsequent frames can
restart. Omitting the timeout permits unlimited frame duration, not in-process
execution. Explicit opt-out:

```powershell
uv run aovguard analyze ./renders --in-process --json ./reports/report.json
```

In-process native I/O cannot be interrupted. `--in-process` combined with a
frame timeout is invalid before decode. Ctrl+C during canonical analysis cleans
up the child and returns `130`. The generic Python API defaults to in-process;
opt in with `AnalysisOptions(isolate_frames=True, frame_timeout_seconds=60)`.
An isolated custom reader must provide a supported process specification.

For an isolated API job, run a normal Python script with the spawn-safe entry
guard (for example, `validate_render.py`):

```python
from aovguard.core.analysis import analyze
from aovguard.core.models import AnalysisOptions
from aovguard.io.reader import OpenEXRReader


def main() -> None:
    options = AnalysisOptions(isolate_frames=True, frame_timeout_seconds=60)
    report = analyze("D:/renders/shot", options, OpenEXRReader())
    print(f"Processed: {report.frame_count}; failed: {report.failed_frame_count}")


if __name__ == "__main__":
    main()
```

Notebook/REPL callers should keep the default in-process API or invoke the
external CLI; do not rely on a silent fallback from unsupported spawn contexts.
The execution flags apply to canonical `analyze`, not the legacy analyzers or
standalone header-only `inspect-structure` command.
Source discovery, final rule evaluation and export also run in the parent,
outside the frame service deadline. Slow folder/NFS listing has no hard job
deadline from this option.

An unconfirmed child/receiver cleanup raises fatal `WorkerCleanupError` and
stops the job: there is no automatic replacement or executor reuse in that
case. The GUI blocks further analyses and asks you to verify remaining
processes, then restart the application. Bounded cleanup attempts do not
guarantee that the OS can terminate an unkillable process.

Analyze with a rule preset:

```powershell
uv run aovguard analyze ./renders --rules-config ./config/rules.example.toml --json ./reports/report.json
```

### Development technical range policies

`technical_range` is disabled by default. Enable it in a TOML/JSON preset
when the project defines numeric bounds for specific depth, mask, scalar or
vector AOVs. In the GUI, load that preset and keep **Technical ranges** checked.
The repository's `config/rules.example.toml` includes a disabled `Z` example.

```toml
[aov_categories]
matte = "mask"

[rules.nan_inf]
severity = "error"

[rules.technical_range]
enabled = true
severity = "warning"

[rules.technical_range.parameters.ranges.Z]
min = 0.0

[rules.technical_range.parameters.ranges.matte]
min = 0.0
max = 1.0
tolerance = 0.000001
```

These are example delivery policies, not universal depth/mask requirements.
Use the actual AOV names and source units. At least one finite `min` or `max`
is required; bounds are inclusive, signed values are supported, and an omitted
bound is open. `tolerance` defaults to zero and extends each bound by that
non-negative absolute amount in channel units. It is not a percentage.
Rejecting invalid ranges produces a visible `rule_error`; it never clamps pixels.

Unlike category overrides, range targets match exact case-sensitive inspected
names, with no globbing. For multipart, quote the full key, for example
`[rules.technical_range.parameters.ranges."[part:left]::Z"]`. A target absent
from all inspections, or classified as color, Cryptomatte, unknown or ignored,
produces a `rule_error` instead of silently passing. Use **Inspect Structure**
to verify names and categories first. If an AOV must exist in every frame,
also configure `missing_aov`; a range policy does not check per-frame presence.
The optional `supported_aov_types` list further narrows the eligible technical
categories without allowing non-technical categories.

Every component is checked, including auxiliary channels. Only successful
frames' finite minima/maxima are evaluated. NaN/Inf remain covered by
`nan_inf`, which should stay enabled; failed reads keep their original errors.
Findings contain each affected file, physical channel, bounds, tolerance and
per-frame extrema. They do not claim the number or position of out-of-range
pixels. Range changes are semantic configuration changes for baselines;
disabled rules are ignored for compatibility so adding an opt-in rule does
not invalidate an otherwise equivalent baseline.

Presets replace the default rule set. When using the short example above,
add any other required integrity, structure, empty-pass and delivery rules,
or adapt the repository's fuller example preset.

### Other analysis options

Analyze scene-linear ACEScg/AP1 data:

```powershell
uv run aovguard analyze ./renders --luminance-model acescg --json ./reports/acescg.json
```

The AP1 luminance weights are `(0.2722287168, 0.6740817658, 0.0536895174)`.
`--luminance-weights R G B` overrides any named model. Select the source model
explicitly; the tool does not infer color space or apply a color transform.

Analyze matching files in nested folders:

```powershell
uv run aovguard analyze ./renders --frame-pattern "shot.*.exr" --recursive --max-depth 2 --json ./reports/report.json
```

Reject discoveries larger than an intended job before frame decoding:

```powershell
uv run aovguard analyze ./renders --max-frames 1000 --json ./reports/report.json
```

In the current development checkout, independently guard estimated memory
admission per frame:

```powershell
uv run aovguard analyze ./renders --max-memory-mb 4096 --json ./reports/report.json --html ./reports/report.html
```

The value must be positive/finite; fractions are supported and units are MiB,
not decimal MB. Omit the flag to disable it (CLI `0` is invalid). All flat
parts/channels count regardless of category or AOV selection. Over-budget
frames fail before pixel decode with exact-file `memory_budget` evidence;
remaining frames continue. Header errors do not trigger an unguarded fallback.
See the architecture for the formula and its limitations.

Check an expected delivery without decoding EXR pixels, or include the range
in a full analysis. Missing frames at either end are included:

```powershell
uv run aovguard check-sequence ./renders --expected-frame-range 1 800
uv run aovguard analyze ./renders --expected-frame-range 1 800 --json ./reports/report.json
```

The expected range applies to exactly one numbered sequence; unlike
`--max-frames`, it describes which frame numbers must exist. An incomplete
range is a FAIL finding, and `check-sequence` returns exit code `1` for missing
or out-of-range frames.

Force source interpretation when filename intent is known:

```powershell
uv run aovguard analyze ./renders --source-mode sequence --json ./reports/sequence.json
uv run aovguard analyze ./looks --source-mode comparison --json ./reports/looks.json
```

Compare two exported reports:

```powershell
uv run aovguard compare-reports ./reports/baseline.json ./reports/candidate.json --json ./reports/comparison.json
```

Analysis JSON uses schema `1.2` and includes `frame_channel_metrics`, per-part
names/views/window coordinates, sequence-specific summaries and `metadata.effective_rules`.
Baseline comparison checks luminance weights, non-black threshold, category
overrides, source interpretation and effective rules. A contradictory recorded
configuration is rejected; reanalyze with matching settings before comparing.
Historical schemas `1.0` and `1.1` are accepted with a warning when configuration
compatibility cannot be fully verified. An absent/non-finite numeric metric is
reported as `unavailable`, rather than `unchanged`. Finding changes include
their affected source-relative paths and recorded metric evidence.
Comparison JSON retains its independent output schema `1.0`.

### Development export protection

Report exports now write a temporary file beside the destination, flush and
sync it, then replace the destination. JSON, HTML, comparison JSON and legacy
JSON/CSV all use this path. A serialization, disk-space or permission failure
before replacement preserves the old report; normal error handling and Ctrl+C
attempt to remove the temporary. Existing report files can still be replaced
when they are not protected inputs.

The CLI checks destinations before analysis/comparison and rejects outputs
that share a path or existing hard-link identity. Outputs cannot use an `.exr`
suffix, overwrite known input files, selected presets/configuration, or replace
the baseline/candidate supplied to `compare-reports`. Symlink destinations,
directories and read-only files are rejected. Use separate output filenames:

```powershell
uv run aovguard analyze ./renders --json ./reports/current.json --html ./reports/current.html
uv run aovguard compare-reports ./reports/baseline.json ./reports/current.json --json ./reports/comparison.json
```

The GUI also protects presets used for analyses and baselines loaded in the
current window. An export error keeps the analysis available so you can choose
another destination or release the file lock and retry without reanalysis.
Canonical analysis and comparison report export failures return CLI exit code
`1`; Ctrl+C returns `130`.

Python callers can pass `protected_paths=(preset_path, ...)` to report writers.
Canonical analysis writers automatically include `report.source` and all
`report.frames`; comparison writers need the baseline/candidate report paths
supplied explicitly, because comparison source metadata describes the renders.

Atomicity is per file: if JSON succeeds and HTML fails, JSON remains published.
Concurrent writers are not locked or queued; Windows may reject a contending
replacement, and the last successful writer wins. This does not guarantee
power-loss durability, network-filesystem atomicity, preservation of every
ACL/owner attribute, or protection against external path changes racing the
final rename. A forced process kill or cleanup error can leave a `.tmp` sibling.

### Report provenance

Development memory fields are additive to schema 1.2:
`metadata.options.max_memory_mb`, model/units/caveat in
`metadata.memory_estimation`, and the full `memory_estimates` breakdown keyed
by frame path. HTML shows budget, estimated MiB and admission decision. The
budget is not a semantic color/rule comparison constraint; accepted metrics
remain unchanged, but admitting different frames can change aggregate results.

Development execution fields are also additive to schema 1.2:
`metadata.options.isolate_frames`, `metadata.options.frame_timeout_seconds`
and `frame_execution`, keyed by frame path with mode/status/PID/elapsed time/
timeout/exit code/stage. HTML presents the same diagnostics. Recorded elapsed
time includes frame service and can include worker startup and cleanup; it is
not a pure decode measurement. Volatile
PID/timing and execution policies are ignored for baseline compatibility when
numeric evidence is identical. Actual execution failures still affect findings
and available metrics. This is not a security sandbox or OS memory cap.

Stored pixel size and delivery size can differ. Inspect the `dataWindow` and
`displayWindow` coordinates before interpreting average-luminance changes in
autocropped sequences: the averages cover stored pixels, not a padded canvas.

Recursive analysis rejects multiple numbered sequences by default. Use
`--allow-multiple-sequences` only when combining them is deliberate. Use
`--fail-on-warning` for strict publishing or CI checks.

When several numbered sequences are explicitly allowed, temporal summaries
remain separate in `series_metrics_by_sequence`; no previous-frame delta joins
different sequences or skips across a missing/failed frame. Global per-AOV
metrics still summarize the selected analysis scope.
Resolution and AOV-structure rules establish a separate baseline for each
numbered sequence rather than comparing unrelated deliveries.

Exit codes for `analyze`:

- `0`: PASS, or WARNING in the default mode.
- `1`: FAIL, or WARNING when `--fail-on-warning` is active.
- `130`: user interruption (Ctrl+C) during canonical analysis, after cleanup.
- `2`: invalid command syntax or incompatible in-process/timeout combination.
- argparse still uses its standard non-zero code for invalid command syntax.

The legacy `analyze-simple`, `analyze-multilayer` and `inspect` commands remain
available temporarily for compatibility.
They now use OpenEXR without OpenCV. The legacy simple reader accepts root
RGB/RGBA or Y grayscale and rejects multipart rather than truncating it;
use canonical `analyze` for full flat multipart support. Base CLI installation
requires no Qt; use the `gui` extra only when launching the desktop interface.
