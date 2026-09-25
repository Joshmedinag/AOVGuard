# AOVGuard 2.0 Video Demonstration Script

Target duration: 6-8 minutes. Record at 1080p or higher with readable terminal
and GUI text. Use authorised real EXRs and record their technical provenance so
the demonstration remains traceable.

## Preparation

```powershell
uv sync --python 3.12 --extra dev
$exr = "D:\renders\approved\shot.1001.exr"
$sequence = "D:\renders\approved\shot_sequence"
```

Choose one representative multilayer EXR and, when available, one numbered
sequence. Verify permission to show their content and metadata. Open a terminal
in the project root, the GUI and the exported HTML report in a browser. Keep
private paths and unrelated windows out of the recording.

## 1. Introduction (0:00-0:40)

**Screen:** Website title or final GUI.

**Narration:**

"AOVGuard 2.0 is my MSc project for validating EXR files and AOVs in VFX
lighting, rendering and compositing workflows. It inspects the actual EXR
structure, applies configurable checks and returns the same structured result
through a command line interface, a PySide6 interface and machine-readable
reports."

## 2. Real evaluation inputs (0:40-1:20)

**Screen:** The approved real-EXR directory and a short evaluation table.

State the renderer, resolution, channel count and intended AOVs for each input.
Explain which result is expected before running AOVGuard. Do not expose client,
studio or production information without permission.

## 3. Automatic inspection (1:20-2:10)

Run:

```powershell
uv run aovguard inspect-structure $exr
```

Highlight the actual dimensions, channels, colour AOVs and technical passes
reported by the selected file. Explain that the user no longer chooses Simple
or Multilayer mode.

## 4. GUI analysis (2:10-4:20)

Run:

```powershell
uv run aovguard-ui
```

1. Select the real EXR stored in `$exr`.
2. Choose Rec.709, then briefly show Rec.601 and Custom weights.
3. Show individual rule checkboxes.
4. Click **Inspect Structure**.
5. Click **Analyze**.
6. Explain the resulting PASS, WARNING or FAIL state using the real findings.
7. Review Findings, aggregate Metrics, per-frame comparison, Technical and
   Sequences tabs. Point out that the GUI opens the most relevant tab and
   selects the first finding automatically.
8. Select the finding and explain its evidence and recommendation.
9. Explain that Cancel stops cooperatively after the current frame.

Distinguish objective data errors from contextual warnings. For example, an
empty emission pass may be valid for a scene without emissive contribution.

## 5. Sequence checking (4:20-5:00)

Run:

```powershell
uv run aovguard check-sequence $sequence
```

Show the detected pattern and any genuine missing frames. Explain that the same
discovered frame list drives processing, progress and reporting. If no suitable
real sequence is available, omit this section instead of fabricating one.

## 6. Reports and integration (5:00-5:50)

Run:

```powershell
uv run aovguard analyze $exr `
  --json reports/demo.json `
  --html reports/demo.html
```

Open both outputs. In JSON show schema version, status, frames, structure,
aggregate metrics, per-frame metrics and findings. In HTML show the human
readable summary. State that JSON is the canonical pipeline output.

## 7. Evidence and close (5:50-7:00)

Show:

```powershell
uv run pytest --cov-fail-under=90
```

Then show the benchmark result: 60 to 12 application-level reader calls with an
identical checksum. Mention the timing and memory limitations rather than
claiming universal performance.

Close with the supported scope and the deliberate limitations: deep EXR,
complete multipart processing and renderer/DCC integration remain future work.
