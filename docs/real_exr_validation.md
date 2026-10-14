# Real EXR Validation Checklist

Before using AOVGuard on production-style renders, check:

- Are the EXRs readable by OpenEXR?
- Are the AOV channel names consistent across frames?
- Do multilayer AOVs use the pattern `aovName.R`, `aovName.G`, `aovName.B`?
- Are thresholds appropriate for the show, colour pipeline and renderer?
- Does the discovered frame list match the intended sequence? AOVGuard sorts
  numeric frame tokens naturally and checks gaps, duplicates, and padding under
  its documented final-numeric-token filename convention. Confirm that this
  convention matches the show's sequence naming policy.
- Are output report paths writable?
- Do flat multipart parts retain unique names and independent window/view
  metadata? Review namespaced channels rather than combining unrelated parts.
- Are any parts deep or incompletely decoded? Those invalidate the entire frame.
- Do data/display windows and scene-linear source primaries match expectations?

For best results, start with a short sequence, tune thresholds, then run on a larger render folder.

## Reproducible opt-in verification

`scripts/verify_real_sequence.py` runs the actual CLI in a fresh interpreter,
using isolated frame processing. It requires an existing external render folder,
an explicit filename pattern, the inclusive expected range, a scene-linear
luminance model and a new output directory outside the source folder. It does
not generate EXRs, truncate a larger discovery to a sample, change rules/presets,
or overwrite an existing evidence directory. `--max-frames` is a refusal limit;
by default it equals the expected range length.

From the checkout, obtain the interface with:

```text
uv run --locked python -m scripts.verify_real_sequence --help
```

For the recorded Venator masters, set `RENDER_FOLDER` below to the existing
external `master_passes` directory; use a distinct output directory on every run:

```text
uv run --locked python -m scripts.verify_real_sequence RENDER_FOLDER --frame-pattern "Venator_v20_xpu_passes.*.exr" --expected-frame-range 1065 1208 --luminance-model rec709 --expect config/verification/venator-master.json --output-directory dist/verification-venator-new --gui --check-cancellation
```

The initial CLI-only environment does not require Qt. For `--gui`, install the
optional GUI extra, for example `uv sync --locked --extra gui`, or use the dev
environment. The GUI subprocess uses its own QSettings file and automated
dialogs. It checks the complete CLI report for exact parity, excluding only
generation time and execution PID/timing; native baseline comparison; finding,
chart and outlier navigation where data exists; exports; a blocked new EXR
destination; retry without reanalysis; and worker/thread cleanup. It rejects
options the GUI cannot represent exactly before decoding any EXR.

Cancellation is not required unless `--check-cancellation` is supplied with
`--gui`. That option requires an observed active isolated worker and a successful
restart. If a tiny sequence finishes before a worker can be observed, the check
fails instead of claiming cancellation was tested. Without findings/outliers,
the corresponding navigation check is explicitly skipped with a reason. These
automated checks are not human-participant usability evidence.

## Expected outcomes are not rule presets

The version-1 JSON profiles in `config/verification/` contain observed outcomes
without source pixels or machine-specific paths:

| Profile | Pattern and range | Expected result |
| --- | --- | --- |
| `maya-arnold.json` | `guarida3.*.exr`, 1–301 | 301 readable frames, 56 channels, 7 color + 8 Cryptomatte + N/Z; empty `volume` warning |
| `venator-master.json` | `Venator_v20_xpu_passes.*.exr`, 1065–1208 | 144 readable frames, 55 channels, 18 color AOVs; empty bridge-solar and near-empty ship-emission warnings; 15 AOV-frame outlier samples |
| `venator-denoised.json` | `Venator_v20_xpu.*.exr`, 1065–1208 | 144 readable RGBA beauty frames, PASS, no findings or luminance outliers |

These profiles do not suppress warnings or modify thresholds. Venator's empty
and localized passes still require scene interpretation. Do not apply a
dataset-specific profile to unrelated renders or blindly update it to make a
regression pass. `--preset` instead selects a real TOML/JSON analysis rule preset
and forwards it to both CLI and GUI without changing that file.

Profiles support exact metadata counts/status/category/severity summaries,
dimensions/channel count, finding signatures, per-AOV outlier counts, nonfinite
counts and sequence continuity counts. Unknown fields, duplicate JSON keys,
invalid types and nonfinite numbers are rejected. Without a profile, successful
decoding, complete channel evidence, zero NaN/Inf, one continuous numbered
sequence and no unexpected render FAIL are required; warnings remain visible.
An intentionally failing corpus must explicitly expect FAIL and its failed
frame count. Matching its expected diagnosis is verification success, not
render approval. Exit 0 means matched verification, 1 means failed checks or
execution, 2 denotes argument syntax errors, and 130 denotes Ctrl+C in the
orchestrator.

## Evidence and preservation boundaries

The new directory includes canonical `analysis.json` / `analysis.html`, CLI
logs and measurements, inventories before/after, and `verification-summary.json`
with runtime versions, expected outcomes, checks and hashes of retained evidence.
GUI runs add a separate `gui/` directory and their own acceptance summary/captures.
The JSON audit checks channel/frame completeness and counter consistency; it is
not independent pixel remeasurement. The earlier numeric audits are separate
evidence in the [recorded results](results.md).

Default preservation compares names, byte sizes and last-write nanosecond
timestamps, not source content hashes. `--hash-source` adds SHA-256 of every
selected EXR before and after all analyses, increasing IO. Rule/expectation inputs
are always hashed before/after. Concurrent input replacement is detected where
these comparisons differ; the verifier does not lock a render farm's files.
Keep outputs under ignored `dist/` and anonymize paths/captures before publishing.

Memory sampling uses Windows working-set counters or Linux procfs for the owned
process tree every 0.1 seconds. Per-process high-water marks are not simultaneous,
and the tree sample may miss brief spikes or double-count shared pages. Other
platforms or unavailable readings retain null measurements with explanations.
`--max-memory-mb` defaults to a 4096 MiB estimated admission budget, not a hard OS
limit. Per-frame service timeout defaults to 60 seconds. The job deadline defaults
to 3600 seconds per analysis, with additional bounded cleanup grace; its elapsed
time includes CLI startup/exports and is not a statistical performance benchmark.
Owned descendants are checked even after the parent exits; a surviving child or
unconfirmed cleanup fails verification. Windows retains process handles for
termination, and Linux checks private process-group identities. These controls
are not a security sandbox and cannot guarantee termination of an unkillable OS
process. Other POSIX hosts fail closed when a live group cannot be enumerated.
