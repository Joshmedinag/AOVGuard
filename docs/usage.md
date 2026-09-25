# Usage

## UI workflow

Start the interface:

```powershell
uv run aovguard-ui
```

1. Select an EXR file or folder.
2. Optionally select a TOML or JSON rule preset.
3. Select Rec.709 or Rec.601 luminance.
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

## CLI workflow

Inspect an EXR structure:

```powershell
uv run aovguard inspect-structure ./renders/shot.1001.exr
```

Analyze a file or folder:

```powershell
uv run aovguard analyze ./renders --json ./reports/report.json
```

Analyze with a rule preset:

```powershell
uv run aovguard analyze ./renders --rules-config ./config/rules.example.toml --json ./reports/report.json
```

Analyze matching files in nested folders:

```powershell
uv run aovguard analyze ./renders --frame-pattern "shot.*.exr" --recursive --max-depth 2 --json ./reports/report.json
```

Reject discoveries larger than an intended job before frame decoding:

```powershell
uv run aovguard analyze ./renders --max-frames 1000 --json ./reports/report.json
```

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

Recursive analysis rejects multiple numbered sequences by default. Use
`--allow-multiple-sequences` only when combining them is deliberate. Use
`--fail-on-warning` for strict publishing or CI checks.

Exit codes for `analyze`:

- `0`: PASS, or WARNING in the default mode.
- `1`: FAIL, or WARNING when `--fail-on-warning` is active.
- argparse still uses its standard non-zero code for invalid command syntax.

The legacy `analyze-simple`, `analyze-multilayer` and `inspect` commands remain
available temporarily for compatibility.
