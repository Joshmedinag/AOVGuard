# AOVGuard

**Current release candidate: 1.4.0rc1 - prepared 2026-10-13**

This candidate includes memory admission, process isolation, technical-range
policies, safe exports, verified source packages and opt-in real-sequence
verification. It is a prerelease for evaluation before stable 1.4.0. Existing
1.3.0 artifacts retain their original bytes and behavior. See the
[1.4.0rc1 release notes](docs/release_notes_1.4.0rc1.md) for the release scope,
previous verification checkpoints and outstanding candidate-validation gates.

AOVGuard is a small Pipeline TD validation tool for checking EXR render outputs. It helps artists and technical directors identify whether render passes / AOVs contain useful image data or whether they are empty, nearly empty, or need manual review before the renders move further down the pipeline.

The main focus of the project is **multilayer EXR AOV validation**, especially for renders exported from DCC/rendering tools such as **Maya/Arnold** with **Merge AOVs** enabled.

---

## Project Context

In a VFX or animation pipeline, lighting artists often export multiple AOVs or render passes for compositing. Some of these passes are useful, while others may be completely black or almost empty. Empty AOVs can create unnecessary storage usage, longer transfer/review times, and confusion for compositors.

AOVGuard provides a lightweight validation step before the render is published or passed downstream.

---

## Current Version Updates

The current backend automatically inspects EXR channels, parts and AOV
structure. Users no longer select Simple or Multilayer mode in the main CLI or
GUI workflow. Header inspection rejects unsupported structures before pixel
decoding. Each supported frame is decoded once and its colour AOVs are
normalised to RGB before metrics and rules are evaluated.
Technical AOVs such as `Z`, `N` and `P` are diagnosed per channel without
being sent through a colour-luminance formula.

Every physical channel is preserved for integrity checks, including alpha and
auxiliary components of known color/vector AOVs. UINT channel arrays retain
their exact integer values. RGB aliases such as `red/green/blue` are supported;
when root RGB and a named `beauty` layer coexist, root RGB is labelled
`beauty [root]` to avoid overwriting either group.

Flat multipart EXRs retain each part independently. Qualified keys such as
`[part:left]::beauty` preserve named-part identity and original metadata; parts
with absent or duplicate names use index-based identities. Any deep part or
partial decode rejects the whole frame, rather than publishing partial metrics.

The canonical JSON analysis report uses schema version `1.2`, never emits non-standard
NaN/Infinity tokens, and reports discovered, successful and failed frames
separately. It includes per-frame/per-channel evidence, both EXR windows and
the effective rule configuration. Comparisons accept historical schemas `1.0` and `1.1`
reports with an explicit warning when configuration compatibility cannot be
fully established.

Sources can be interpreted automatically, explicitly as a numbered sequence,
or as an independent comparison set. The report records the resolved source
kind so sequence gaps are never confused with deliberate look comparisons.

The released 1.3.0 baseline was verified on 2026-10-12, Windows/Python 3.11.14
and 3.12.12: **434 tests passed,
1 skipped**, with **95.56% combined statement/branch coverage**. The skip is
the unprivileged Windows symlink-permission check. Ruff and configured mypy
checks pass across all 42 source modules. Earlier checkpoints of 368/95.41%
and 282/95.37% at `530ed76` remain historical; these local results do not imply
a completed Linux or remote CI run.

---

## Features

- Automatically inspect simple and multilayer EXR channel structures.
- Analyze every flat multipart part without combining channels, dimensions or
  AOVs from unrelated parts; retain per-part names, views and window coordinates.
- Detect colour, scalar, vector, mask, depth, Cryptomatte and unknown AOV categories.
- Use OpenEXR Cryptomatte metadata to keep encoded object/material IDs out of
  colour luminance and temporal-outlier calculations while retaining channel
  integrity diagnostics.
- Preserve unknown AOVs and all their channels for integrity diagnostics;
  explicitly ignored AOVs also remain visible rather than disappearing.
- Normalise colour AOVs to an internal RGB convention.
- Calculate non-black ratio and signed/absolute luminance metrics.
- Record per-channel min/average/max, non-finite and negative-value counts for
  every supported channel, with lightweight per-frame histories and exact
  affected-file paths for channel findings.
- Preserve each part's `dataWindow` and `displayWindow` coordinates separately;
  delivery resolution checks use the display window while pixel metrics use
  stored data. Numbered sequences have independent structural baselines.
- Use Rec.709, Rec.601, ACEScg/AP1 or custom coefficients for scene-linear RGB
  luminance; choosing coefficients does not transform the input color space.
- Validate NaN/Inf, empty and near-empty AOVs, missing AOVs/channels,
  negative values, optional extreme finite values, constant channels and
  sequence consistency.
- Group numbered EXR sequences and detect missing frames, duplicate frame
  numbers and inconsistent padding without decoding pixels.
- Optionally declare an inclusive expected frame range, so missing delivery
  tails and leading frames are reported as errors rather than going unnoticed.
- Select frames with an explicit filename pattern, optional recursive search
  and bounded folder depth, plus an optional maximum frame-count safeguard.
- The candidate can optionally gate each flat EXR's pixel decode
  against a conservative memory estimate covering every part/channel. It is
  disabled by default and is an admission estimate, not an OS memory cap.
- The candidate CLI/GUI run frame inspection, decode and reductions in a
  reusable child process by default, with an optional per-frame deadline.
  Timeout/crash failures retain exact-file evidence and allow the next frame
  to use a replacement worker; no pixel arrays are transferred to the parent.
- Load validation rules and custom AOV category overrides from TOML or JSON presets.
- Optionally check inclusive numeric ranges for explicitly named depth, mask,
  scalar and vector AOVs. The candidate `technical_range` rule checks every
  component and retains exact frame/channel evidence, with project-defined
  bounds and absolute tolerance. It is disabled by default.
- Classify an unknown AOV from the GUI only after explicit confirmation and
  save the override atomically to a preset.
- Display progress during analysis using a UI progress bar.
- Show explicit PASS, WARNING or FAIL status and per-frame diagnostic metrics.
- Compute robust cross-frame statistics using median, median absolute deviation
  (MAD), consecutive-frame deltas and outlier samples. Numbered sequence series
  remain separate, and previous-frame deltas do not cross missing/failed frames.
- Plot average luminance, signed change from the previous frame or percentage
  change for the selected color AOV, including a robust median/normal range,
  outlier/error markers and click-to-locate frame navigation. Marker shape and
  text preserve meaning without colour alone.
- Review robust luminance outliers in a dedicated score-ordered view and use
  the explicit navigation button or double-click an entry to select its exact
  AOV and frame evidence.
- Preserve per-file evidence for aggregate empty and near-empty AOV findings.
- Compare a current analysis against a previous canonical JSON report in both
  the CLI and GUI.
- Cancel isolated analysis by stopping and reaping its active child process;
  in-process execution remains cooperative. Closing during analysis requests
  cancellation and waits for worker/thread cleanup without blocking the GUI.
- Export a strict, schema-versioned JSON report.
- Export a self-contained HTML report with status, metrics, sequences,
  findings and recommendations.
- Publish reports atomically in the development checkout: failures before
  replacement preserve the previous file. Destination checks protect EXRs,
  selected presets and comparison inputs, and reject duplicate CLI outputs.
- Record version/configuration provenance, analyzed channels, AOV inventory
  and cautious finding interpretations in reports.
- Filter GUI findings by severity, text or failed-frame status and inspect
  detailed evidence for each result.
- Use compact source-relative paths, automatic result-tab selection and
  per-frame change columns for faster comparison.
- Preserve the last source, preset, luminance and discovery settings between
  GUI sessions.
- Collapse secondary analysis settings and logs to keep the results area
  focused, while retaining contextual empty states and column controls.
- Provide contextual hover definitions for controls, validation rules, result
  tabs, table metrics and inferred AOV meanings.
- Provide a simple PySide6 graphical user interface.
- Provide a command-line interface for pipeline-style usage with only NumPy and
  OpenEXR runtime dependencies; install the `gui` extra for the desktop interface.
- Include automated tests with branch coverage using `pytest-cov`.

---

## Automatic EXR Structure Inspection

Regular RGB/RGBA files with channels such as the following are detected as a
`beauty` colour AOV:

```text
R
G
B
A
```

Named multilayer channels are grouped automatically, for example:

```text
albedo.R
albedo.G
albedo.B

diffuse_direct.R
diffuse_direct.G
diffuse_direct.B

specular_direct.R
specular_direct.G
specular_direct.B

emission.R
emission.G
emission.B
```

A real test was completed using a multilayer EXR exported from **Maya/Arnold**
with **Merge AOVs** enabled. AOVGuard detected the following structure:

```text
Z
P
N
albedo
diffuse_direct
specular_direct
emission
```

`N` and `P` are recognised as vectors, `Z` as depth, and colour AOVs are
analyzed using luminance rules. Flat multipart EXRs are processed part by part
under qualified identities. Deep EXRs remain unsupported; if any part is deep,
the entire frame is rejected before pixel decoding.

---

## Requirements

Recommended:

```text
Python 3.12
uv
```

Python 3.9 is not supported.

---

## Installation

### 1. Install uv

If `uv` is not installed, install it with:

```powershell
python -m pip install uv
```

Or install it from Astral:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Open the correct project folder

Make sure you are inside the folder that contains:

```text
pyproject.toml
README.md
src
tests
docs
examples
reports
```

Example:

```powershell
cd "C:\path\to\AOVGuard"
```

### 3. Install Python 3.12

```powershell
uv python install 3.12
```

### 4. Install dependencies

For development and the full test suite, including the Qt interface:

```powershell
uv sync --locked --python 3.12 --extra dev
```

For a CLI-only checkout, use `uv sync --locked --python 3.12`. Build a candidate
wheel with `uv build --wheel --out-dir dist/rc-wheel`, then install it with
`python -m pip install ./dist/rc-wheel/aovguard-1.4.0rc1-py3-none-any.whl`;
the CLI does not require Qt or OpenCV. Include the optional desktop dependencies
with `python -m pip install "./dist/rc-wheel/aovguard-1.4.0rc1-py3-none-any.whl[gui]"`.

---

## Running the Tests

Install the `dev` extra, then run:

```powershell
uv run --locked --extra dev pytest
```

The default test configuration measures statement and branch coverage for the
`aovguard` package and prints missing lines. CI also enforces a 95% minimum:

```powershell
uv run --locked --extra dev pytest --cov-fail-under=95
```

Development quality checks:

```powershell
uv run --locked --extra dev ruff check src tests scripts experiments/benchmark_simulated_sequences.py experiments/benchmark_memory.py
uv run --locked --extra dev mypy src/aovguard scripts/create_release.py scripts/install_built_wheel.py scripts/verification_memory.py scripts/verify_real_sequence.py scripts/verify_gui_sequence.py
```

Ruff also enforces module, public API and constructor docstrings, while mypy
rejects untyped function definitions in the source package. CI runs both checks
and installs dependencies using `uv sync --locked`. Pytest's project-root path
is configured explicitly, so `pytest` and `python -m pytest` have the same
project import paths.

---

## Running the UI

Run:

```powershell
uv run --extra gui aovguard-ui
```

---

## How to Use the UI

1. Select an EXR file or render folder.
2. Optionally select a TOML or JSON validation preset.
3. Select Rec.709, Rec.601, ACEScg or custom RGB luminance weights according to
   the source primaries. ACEScg expects scene-linear AP1 RGB data.
4. Under **Analysis Settings**, leave source interpretation on **Auto** or
   choose **Sequence** / **Comparison** explicitly. In the development checkout,
   keep **Isolate analysis process** enabled and optionally set **Frame timeout
   (s)**; `0 / No timeout` leaves frame duration unlimited.
5. Click **Inspect Structure** to review detected channels and AOVs.
   Unknown AOVs can be assigned a category and saved to a preset only after a
   confirmation dialog; rerun inspection or analysis to apply the override.
6. Click **Analyze**.
7. Review the **Findings**, **Metrics**, **Outliers**, **Frames/Samples**,
   **Technical** and **Sequences** tabs. The GUI opens the most relevant result
   automatically.
8. Filter findings; the first visible result is selected automatically and its
   evidence and recommended action are displayed.
9. Use **Median Change** and **Previous Change** to inspect variation without
   treating the first decoded frame as an unquestioned baseline.
   Select a color AOV and switch the chart between luminance, signed delta and
   relative percentage change. The interface explains zero-to-activity
   transitions explicitly. Click a plotted sample, or select an entry in
   **Outliers** and use **Locate Selected Frame**, to locate its exact row in
   **Frames/Samples**.
10. Export JSON/HTML, or use **Compare Baseline** to compare the current result
    with a previously exported canonical JSON report.

The current GUI uses automatic EXR structure inspection and no longer asks the
user to choose Simple or Multilayer mode manually.

The GUI also reports the detected AOV categories and allows individual
validation rules to be enabled or disabled. Channel-level NaN/Inf, negative
values and constant-channel checks are available, together with frame-to-frame
resolution and AOV-structure consistency checks.

For folders, **Frame Pattern** filters filenames. **Recursive** includes direct
and nested matches up to **Max Depth**. Analysis stops when recursive discovery
finds multiple numbered sequences unless **Allow Multiple Sequences** is
enabled explicitly. **Max Frames** can reject an unexpectedly large discovery
before any frame is decoded; `0` means unlimited.

---

## Exporting Multilayer EXRs from Maya / Arnold

To create a multilayer EXR from Maya using Arnold:

1. Open **Render Settings**.
2. Set **Render Using** to `Arnold Renderer`.
3. Go to the **AOVs** tab.
4. Add AOVs such as:

```text
RGBA
albedo
diffuse_direct
specular_direct
emission
N
P
Z
```

5. Go to the **Common** tab.
6. Set **Image Format** to `exr`.
7. Enable **Merge AOVs**.
8. Render the frame or sequence.

The resulting EXR should contain channels such as:

```text
albedo.R
albedo.G
albedo.B
diffuse_direct.R
diffuse_direct.G
diffuse_direct.B
specular_direct.R
specular_direct.G
specular_direct.B
```

This structure is detected automatically by the current backend.

---

## Command-Line Usage

### Inspect an EXR

```powershell
uv run aovguard inspect-structure ./renders/shot.1001.exr
```

### Analyze an EXR file or folder

```powershell
uv run aovguard analyze ./renders --json ./reports/report.json --html ./reports/report.html
```

Use explicit discovery when renders are nested or a folder contains several
outputs:

```powershell
uv run aovguard analyze ./renders --frame-pattern "beauty.*.exr" --recursive --max-depth 2 --json ./reports/beauty.json
```

Bound a scheduled job before pixel decoding when its discovery scope is not
fully trusted:

```powershell
uv run aovguard analyze ./renders --max-frames 1000 --json ./reports/report.json
```

### Development update: per-frame memory estimate guard

```powershell
uv run aovguard analyze ./renders --max-memory-mb 4096 --json ./reports/report.json --html ./reports/report.html
```

`--max-memory-mb` accepts a positive finite budget in **MiB** (1,048,576 bytes),
including fractions. Omit it to disable the guard; CLI `0` is invalid. The GUI
**Memory budget (MiB)** control uses `0 / Unlimited` for disabled and defaults
to that value for fresh/older settings. Invalid stored values activate a
1024 MiB guard with a visible warning instead of disabling it.

Before each supported flat frame is decoded, valid header metadata is checked
for all parts and all physical channels, including unknown, ignored, alpha,
auxiliary and Cryptomatte data. Category or AOV selection does not shrink the
estimate. An over-budget frame gets an exact-file `memory_budget` error with
header/estimate evidence, is counted as failed and is skipped before pixel
decode; remaining frames continue. Header errors never fall back to an
unguarded read.

Model `flat-working-set-v1` reserves 4 bytes of native data, 4 bytes of
worst-case promotion and 8 bytes of stacks per channel/pixel. It adds 32 bytes
of scratch per pixel in the largest stored part plus 64 MiB fixed reserve,
then applies a 1.25 safety factor rounded upward in bytes. It uses stored
`dataWindow` pixels, not the display canvas, and does not infer exact header
channel types. JSON schema stays 1.2 with additive budget/model/estimate fields;
HTML shows the estimate and decision. Gating does not change accepted-frame
metric semantics, but different admitted frame sets can change aggregates.

This is not a global/hard RSS cap: decoder internals, report history, GUI
allocations and concurrent work are not bounded. A source can change between
header preflight and eager native decode. Isolation permits stopping the child,
not imposing an allocator cap. In-process cancellation cannot abort a native
read. Caching, automatic renderer-specific semantics and table virtualization remain
separate work.

The preceding memory-admission milestone was verified locally on Windows/Python 3.11.14
and 3.12.12: **523 passed, 1 symlink-permission skip, 95.81% combined coverage**
in each run, with clean Ruff and configured mypy on 43 source modules. A real
Full-HD user EXR was admitted under 4096 MiB and rejected before pixels under
1024 MiB; GUI rejection recovered controls and released worker/thread state.
See the single-input measurements and their limits in `docs/benchmark_results.md`.

### Development update: isolated frame execution

The canonical `analyze` CLI and GUI isolate frame work by default. One spawned
child is reused sequentially for the job, reducing pixels into scalar statistics
before returning them. Configure a positive finite frame deadline in seconds:

```powershell
uv run aovguard analyze ./renders --frame-timeout-seconds 60 --max-memory-mb 4096 --json ./reports/report.json
```

The frame deadline starts after the child's ready handshake and covers header
inspection, memory admission, native decoding, reductions and IPC. Child startup
has a separate 30-second deadline; startup and cleanup are not part of the frame
service deadline. Recorded elapsed time includes frame service and may also
include startup and cleanup, so it is not a
pure decode benchmark. Discovery, final rules and export remain in the parent
outside the deadline; slow folder/NFS listing is not covered. Omitting the flag disables the frame deadline, not
isolation. A timeout yields `frame_timeout`; a child crash yields `worker_crash`.
The affected frame fails, the child is reaped, and subsequent frames can restart
in a replacement process. These controls do not add parallel processing,
streaming, a security sandbox or a hard RSS limit.

If bounded cleanup cannot confirm that the child/receiver was reaped,
`WorkerCleanupError` stops the job instead of starting more work. The executor
is not reusable; the GUI blocks new analyses and explains how to verify any
remaining process before restarting AOVGuard. This fails closed, but cannot
guarantee OS termination of an unkillable process.

Use `--in-process` only when that tradeoff is deliberate:

```powershell
uv run aovguard analyze ./renders --in-process --json ./reports/report.json
```

Native reads cannot be interrupted in this mode, and combining it with
`--frame-timeout-seconds` is rejected before decode. The generic Python API
remains opt-in: `AnalysisOptions(isolate_frames=True, frame_timeout_seconds=60)`;
an explicitly isolated custom reader must supply a supported process specification.
For scripts, invoke isolated API work from a function under
`if __name__ == "__main__":`; notebooks/REPL should use the default in-process
API or run the external CLI. See `docs/usage.md` for a complete script example.
The execution controls apply to canonical analysis, not standalone header
inspection or legacy commands.
GUI **Cancel** stops the active child in isolated mode. Closing waits for child
and QThread cleanup while keeping the event loop active. CLI Ctrl+C cleans up
the child and returns exit code `130` with a short message.

Schema `1.2` gains additive `metadata.options.isolate_frames`,
`metadata.options.frame_timeout_seconds` and per-file `frame_execution` records
(mode, status, PID, elapsed time, timeout, exit code and stage). HTML shows these
execution diagnostics. Volatile PID/timing and execution-policy settings do not
make otherwise identical numeric evidence baseline-incompatible; actual failed
or omitted frames can still change findings and aggregates.

### Opt-in real-sequence verification

The maintained verifier runs the actual isolated CLI against an explicitly
selected external sequence. Source/pattern/range and scene-linear luminance
model are required; it never creates EXRs or overwrites a prior evidence folder.
Run `uv run --locked python -m scripts.verify_real_sequence --help` from this
checkout. Add `--gui` to repeat through the real optional Qt GUI, and
`--check-cancellation` to require an active-worker cancellation/restart check.

Strict JSON expectation profiles in `config/verification/` describe the recorded
Maya/Arnold and Venator datasets, not universal renderer presets. A verification
can pass while preserving known render warnings. With a profile, new/missing
findings fail; dropped channels, unexpected frame failures or modified inputs
always fail the verification.
Default input preservation compares names, sizes and write timestamps;
`--hash-source` also reads every selected EXR twice for SHA-256 comparison.

JSON/HTML, logs, GUI captures, report hashes and optional Windows/Linux native
process-tree memory samples remain in the caller's new evidence directory.
Keep it under ignored `dist/` and review/anonymize evidence before sharing.
See [commands, expected outcomes and limits](docs/real_exr_validation.md).

The pre-candidate 2026-10-13 Windows/Python 3.12.12 checkpoint has **1036 passed, 3 skipped,
96.34% combined application statement/branch coverage** (42.37 s). Ruff and
combined mypy checks passed, including Windows/Linux type targets (54 files).
The new Linux-only orphan-process integration is skipped on Windows alongside
the two existing platform skips. Real Venator CLI/GUI runs retained their known
warnings, matched reports and confirmed cancellation/navigation/cleanup.
The final denoised repetition passed 144/144; source metadata stayed unchanged.
The build/install helper also passed an isolated base-wheel CLI smoke check
without Qt/OpenCV. This checkpoint predates the 1.4.0rc1 version freeze and does
not establish final candidate installation or a completed remote CI run.

### Source-package verification checkpoint (2026-10-12)

The unreleased source-package update was verified locally on Windows:
Python 3.12.12 had **848 passed, 2 skipped, 96.21% combined statement/branch
coverage** (51.38 s); Python 3.11.14 had **848 passed, 2 skipped, 96.17%**
(47.11 s). The skips cover a POSIX-only raw IPC-fragment test and unprivileged
Windows symlink creation. Ruff passed; mypy passed across 48 application files
plus the packaging script.
Both full suites used locked NumPy 2.4.6 / OpenEXR 3.4.12.

The 81 new packaging cases cover reproducibility, manifests, altered/incomplete
archives, unsafe paths, excluded local data, publication failures and refusal
to overwrite existing artifacts. A separate focused run measured 98.79%
combined coverage for `scripts/create_release.py`; this is not included in the
application coverage above.

A 150-source-file ZIP was separately verified, extracted and installed from the
lock into a new Python 3.12 environment. Its full suite also passed (848 passed,
2 skipped, 96.21%), together with CLI help, website links, Ruff and mypy.
The historical handoff snapshot records this check without changing its tested
code or lock. It predates the maintained real-sequence verifier and candidate
metadata; it is not the 1.4.0rc1 package.

At the preceding safe-export milestone, both Python versions had 767 passing
tests and 96.21% combined application coverage. Its 50 new cases cover interrupted writes, disk/permission failures,
protected input aliases, duplicate destinations, CLI errors and GUI retries.
The atomic-publication helper has 100% combined coverage. Protection applies
automatically, per output file; JSON and HTML are not a single transaction.
See [export protection](docs/usage.md#development-export-protection) for API
input-path requirements and filesystem limitations.

At the preceding technical-range milestone, 717 tests passed on each Python
version (96.01% on 3.12 and 96.05% on 3.11). Its 49 new cases cover range
boundaries, invalid policies, all technical
components, exact frame/part evidence, baseline compatibility and CLI/GUI
integration. One existing Full-HD render passed a read-only `Z` range check
from 0 to 10000 plus `nan_inf`; its size and modification time were unchanged.
This targeted policy check does not certify the whole sequence or all default
rules. See [usage](docs/usage.md#development-technical-range-policies) to enable
the rule and adapt bounds to the delivery contract.

At the preceding execution milestone, a fresh CLI-only wheel smoke passed real console-spawn EXR analysis
without Qt/OpenCV using NumPy 2.5.4 / OpenEXR 3.5.2; that smoke does not replace
the locked suites or upgrade the lock. GUI checks covered normal/in-process
execution and an injected fatal-cleanup state. One existing Full-HD render was
checked read-only in normal isolated mode and with a 0.01-second frame deadline.
These are local Windows results, not a completed Linux/remote CI run or a
production capacity guarantee. Existing 1.3.0 artifacts/hashes remain unchanged;
these historical checkpoints do not establish final candidate publication or CI.

Add `--allow-multiple-sequences` only when combining independent numbered
sequences is intentional. Add `--fail-on-warning` in CI or publishing scripts
when warnings must fail the command. `analyze` returns `0` for PASS and, by
default, WARNING; it returns `1` for FAIL or for WARNING in strict mode.

Use `--source-mode sequence` to require numbered frames, or
`--source-mode comparison` to treat every discovered EXR as an independent
sample. The default `auto` mode resolves one file, a numbered sequence, or a
comparison set from the discovered names.

### Compare two canonical reports

```powershell
uv run aovguard compare-reports ./reports/baseline.json ./reports/candidate.json --json ./reports/comparison.json
```

The comparison records added, removed, changed and unchanged AOV metrics plus
new and resolved findings. A missing/non-finite metric is `unavailable`, rather
than `unchanged`. Different luminance weights, non-black thresholds, AOV
classifications, source interpretations or effective rules make reports
incompatible. Findings include their affected source-relative paths and metric
evidence when establishing whether they changed.

### Analyze scene-linear ACEScg renders

```powershell
uv run aovguard analyze ./renders --luminance-model acescg --json ./reports/acescg.json
```

ACEScg uses the AP1 Y coefficients `(0.2722287168, 0.6740817658, 0.0536895174)`.
The input color space is not inferred from pixels and no color transformation
is applied. `--luminance-weights R G B` overrides the selected named model.

### Check sequence names and gaps without reading pixels

```powershell
uv run aovguard check-sequence ./renders
```

The checker recognises patterns such as `shot.1001.exr` and
`shot_1001.exr`, reports compact missing ranges, separates multiple sequences
and flags duplicate frame numbers or mixed padding widths.

### Analyze with a rule preset

```powershell
uv run aovguard analyze ./renders --rules-config ./config/rules.example.toml --json ./reports/report.json
```

Unknown AOVs are retained, diagnosed per channel and reported by the
`unknown_aov` rule. When a renderer-specific name has known semantics, classify
it in the preset so the relevant category-aware rules can be applied:

```toml
[aov_categories]
crypto_asset = "mask"
custom_depth = "depth"
motion_vector = "vector"
vendor_payload = "ignored"
```

Override names are matched case-insensitively. Supported categories are
`color`, `scalar`, `vector`, `mask`, `depth` and `ignored`. `ignored` is an
explicit classification: the AOV remains in inventories and integrity checks,
but category-specific semantics are not inferred for it.

The legacy `inspect`, `analyze-simple` and `analyze-multilayer` commands remain
available temporarily for comparison and backward compatibility. Their output
schema and classification model are not the canonical analysis workflow.

---

## Legacy Classification Meaning

The following labels belong to the temporary legacy commands. The canonical
backend reports metrics and rule findings instead.

### Active

The AOV contains clear image information and is likely useful.

### Review Recommended

The AOV contains some data, but the contribution is weak or limited. This does not always mean the AOV is wrong, but it should be checked manually.

### Nearly Empty

The AOV contains very little information and may not be useful.

### Empty

The AOV appears to contain no meaningful information. For example, an `emission` AOV may be empty if the scene has no emissive materials.

---

## Evidence

The current candidate interface reproducing the recorded real Venator master
report is shown here. This is a JSON replay, not a new EXR analysis; visible
source paths are anonymized:

```text
website/assets/aovguard-current-ui.png
```

The following established asset names now contain the current interface
reproducing the recorded 301-frame Maya and 144-frame denoised reports. Earlier
screenshots contained personal paths and were backed up locally, outside the
source package. Full run evidence and screenshot replay are documented separately:

```text
docs/images/01_real_maya_multilayer_result.png
docs/images/04_real_simple_exr_result.png
```

No EXR demonstration data is generated by the product workflow or bundled in a
release. The `examples/` directory intentionally contains only `.gitkeep`.
Automated tests may create temporary fixtures in pytest-managed directories,
and the historical backend research spike remains developer-only; neither is
packaged as demonstration data. Real production renders should remain outside
the repository and can be selected directly through the CLI or GUI.

---

## Project Structure

```text
AOVGuard/
  README.md
  pyproject.toml
  src/
    aovguard/
      __init__.py
      cli.py
      ui.py
      ui_components.py
      core/
        analysis.py
        channel_utils.py
        findings.py
        execution.py
        luminance.py
        memory.py
        models.py
        status.py
      discovery/
        frame_discovery.py
      io/
        inspector.py
        protocol.py
        process_executor.py
        process_worker.py
        reader.py
      gui/
        controller.py
        help_text.py
        launcher.py
        presentation.py
        series.py
        settings.py
        worker.py
      rules/
        builtin.py
        definitions.py
        engine.py
        loader.py
        preset_writer.py
        registry.py
      sequence/
        sequence_checker.py
      reports/
        comparison.py
        json_report.py
        html_report.py
      analysis_core.py
      config.py
      simple.py
      multilayer.py
  tests/
  docs/
  examples/
  reports/
  config/
  experiments/
    benchmark_memory.py
    benchmark_simulated_sequences.py
  scripts/
    create_release.py
    validate_website.py
  website/
```

The root compatibility analyzers retain their older result model; the canonical
workflow lives in `core`, `io`, `discovery`, `rules`, `sequence` and `reports`.

---

## Troubleshooting

### `pip: command not found`

Use:

```powershell
python -m pip install uv
```

### Python 3.9 is not supported

Install Python 3.12 using uv:

```powershell
uv python install 3.12
uv sync --locked --python 3.12 --extra dev
```

### The desktop interface requires the GUI extra

Run `uv run --extra gui aovguard-ui` from the checkout, or install
`aovguard[gui]` alongside a packaged installation. OpenCV has been removed from
the product and tests; its EXR codec environment switch is no longer required.

### `No RGB AOV groups found in the EXR files`

This means the selected EXR does not contain multilayer RGB AOV groups.

Try one of the following:

- check that **Merge AOVs** was enabled when exporting from Maya/Arnold;
- use **Inspect Structure** to see what channels and AOVs exist in the file.

### `0 AOVs analyzed`

This usually means that no files matched the selected frame pattern, or that
the relevant nested folder is deeper than the configured discovery depth.

---

## Limitations

- Luminance metrics apply only to colour AOVs. Technical passes receive
  per-channel statistics and NaN/Inf validation; the development
  `technical_range` rule adds explicit per-AOV bounds. It does not infer units,
  validate normal-vector lengths or establish renderer-specific semantics.
- Deep data remains unsupported. Any deep part or failed channel/part decode
  rejects the complete frame; flat multipart data is supported.
- Named multipart identities remain stable across reordering while there are
  at least two parts. A two-part file becoming single-part returns to historical
  unqualified keys and is reported as a structure change. Unnamed/duplicate
  parts are identified by index, so their reordering cannot preserve semantic
  identity reliably.
- Pixel loading still reads a complete supported frame. Avoid interpreting the
  small in-memory scalability benchmark as a measured 4K memory guarantee.
  The native API eagerly loads all part pixels; this backend is not streaming.
- The development memory guard estimates each frame's admission working set;
  it does not bound process RSS or establish production 4K/NFS capacity.
- Development process isolation is a sequential worker boundary, not a
  security sandbox or OS resource cap. In-process mode cannot interrupt native
  I/O; frame service timeouts exclude startup and cleanup time.
- Luminance statistics use stored `dataWindow` pixels. A changing crop can alter
  averages even when the delivery `displayWindow` stays constant.
- ACEScg supports signed scene-linear values; negative-value thresholds remain
  a project policy, rather than proof of a faulty render.
- Thresholds are conservative and may need adjustment per project.
- Sequence inference uses the final numeric block in each EXR filename. The
  filename glob and recursion depth are configurable, but show-specific token
  parsers are not implemented.
- The tool does not replace artistic judgement; it is designed as a validation aid.
- Unreal EXRs may export as simple RGBA files unless render passes are configured separately.

---

## Future Improvements

Possible future improvements include:

- renderer-aware rules for technical AOVs;
- configurable thresholds in the UI;
- clearer visual previews;
- packaged executable using PyInstaller;
- automated Sphinx documentation;
- Docker-based deployment for reproducible environments.

---

## Project Evidence and References

- [Technical references](docs/references.md) provides annotated primary sources
  for EXR, OpenEXR, OpenImageIO, luminance standards, testing and VFX platform
  compatibility.
- [Project management](docs/project_management.md) records milestones,
  architectural decisions, risks and the definition of done.
- [Architecture](docs/architecture.md) describes the shared backend and data
  flow used by the CLI and GUI.
- [Evaluation plan](docs/evaluation_plan.md) defines correctness, performance,
  coverage and usability evidence.
- [Usability protocol](docs/usability_evaluation.md), [raw-results
  template](docs/usability_results_template.csv) and [expert
  walkthrough](docs/usability_expert_walkthrough.md) separate planned
  participant evidence from the completed developer-led review.
- [Benchmark results](docs/benchmark_results.md) compare AOV-first and
  frame-first processing and record a separate in-memory 100/500/1,000-frame
  scalability run. Final evaluation should additionally use authorised real
  EXRs.

Measure native process peak memory on an existing authorized source in an
isolated child process:

```powershell
uv run python experiments/benchmark_memory.py "D:/renders/shot" --max-frames 800
```

This command generates no EXRs or reports and prints JSON to standard output.
`--max-frames` refuses an oversized source rather than silently sampling it.
Peak RSS includes native allocations; it is a high-water mark, not a leak test
or proof of 4K/NFS performance.
- [Changelog](CHANGELOG.md) records release-level changes.
- [Citation metadata](CITATION.cff) and the [MIT licence](LICENSE) describe how
  to cite and reuse the software.
- [Project website](website/index.html), [video script](docs/demo_script.md),
  [presentation outline](docs/presentation_outline.md) and
  [submission checklist](docs/submission_checklist.md) support the final MSc
  delivery.

Create a clean submission archive without virtual environments, caches or EXR
image data. The release policy excludes every `.exr` file, including files
temporarily placed under `examples/`. Development packaging also excludes
local `reports/` contents (except `.gitkeep`), common secret/temporary filenames,
symlinks and Windows reparse points. Approved anonymized examples under
`docs/sample_reports/` remain included. Required GUI test helpers are retained.

```powershell
python scripts/create_release.py --list
python scripts/create_release.py --output dist/AOVGuard-1.4.0rc1-source.zip
python scripts/create_release.py --verify dist/AOVGuard-1.4.0rc1-source.zip
```

These commands require only Python 3.11/3.12 standard-library modules. The ZIP
has one `AOVGuard-<version>/` root and a `RELEASE_MANIFEST.json` recording each
source path, byte count and SHA-256. Creation verifies the temporary ZIP before
publishing it and prints its overall checksum. An existing destination is never
overwritten: choose another filename. Publication requires same-filesystem hard
links (for example, local NTFS); unsupported storage fails without a copy fallback.

Identical selected bytes produce identical ZIP bytes with the same Python/zlib
runtime, regardless of checkout name or mtimes. Freeze edits during packaging;
this is not a simultaneous filesystem snapshot. Review `--list` and file contents
before sharing: exclusion rules are not a secret scanner. The unsigned manifest
detects corruption, not publisher authenticity; verification does not extract or
execute files. Legacy 1.3.0 ZIPs lack this manifest and remain unchanged.

A versioned source snapshot alone does not establish a completed publication or
stable release. The 1.4.0rc1 archive has a distinct candidate identifier; preserve
it separately from 1.3.0. See [installation](docs/installation.md#verify-a-source-snapshot)
for the clean-install check before distribution.
