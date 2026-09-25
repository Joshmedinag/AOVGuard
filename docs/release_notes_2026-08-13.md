# AOVGuard 2.0 Analysis Improvements

> Historical August 2026 release evidence. The current 1.1.0 verification is
> recorded in `release_notes_1.1.0.md`.

## Source intent

- Added Auto, Sequence and Comparison source modes to the shared backend, CLI
  and GUI.
- Reports now record the resolved source kind as `single_file`,
  `numbered_sequence` or `comparison_set`.
- Sequence gaps, duplicate frames and padding checks run only when the source
  is interpreted as a numbered sequence.
- Multiple unnumbered EXRs in Auto mode are treated as a deliberate comparison
  set instead of generating a misleading sequence warning.

## Findings and variation

- Empty and near-empty AOV findings retain exact per-file evidence while
  preserving one aggregate finding per AOV.
- Added robust series statistics: median luminance, median absolute deviation,
  minimum/maximum, largest consecutive change and outlier sample paths.
- GUI sample changes are measured against the median and previous sample, not
  only the first decoded frame.
- Percentage formatting suppresses negative zero.

## Report comparison

- Added `aovguard compare-reports BASELINE CANDIDATE`.
- Added GUI comparison of the current analysis against a baseline JSON report.
- Comparison output identifies added, removed, changed and unchanged AOVs,
  plus new and resolved findings.

## GUI maintenance

- Moved worker/option construction to `aovguard.gui.worker`.
- Moved reusable result formatting to `aovguard.gui.presentation`.
- Added explicit source-mode controls, robust metric columns, a Comparison tab
  and clearer aggregate source labels.
- Successful analyses collapse the log automatically; execution failures keep
  it open.

## Verification

- 229 automated tests pass on Python 3.12.
- Total branch-aware coverage is 95.24%.
- Core analysis coverage is 91%, report comparison 93%, and GUI 91%.
