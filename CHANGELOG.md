# Changelog

All notable project changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Standard Cryptomatte layers are identified from EXR metadata and excluded
  from color luminance, frame trends and robust outliers. All ID/coverage
  channels remain available for NaN/Inf and technical diagnostics.
- Very large technical channel statistics use compact scientific notation in
  the GUI instead of overflowing table cells.

### Added

- Optional inclusive expected frame range in the core, CLI, GUI and JSON/HTML
  reports. Missing delivery tails or leading frames become error findings;
  frames outside the declared range are warned about.
- Spanish website documentation covering installation, GUI and CLI workflows,
  Cryptomatte handling, sequence ranges, presets, reports, troubleshooting,
  limitations and development verification.

### Verification

- 282 tests pass with 95.37% combined statement/branch coverage on Python
  3.12. Ruff and strict mypy pass. Representative EXR-header and filename-only
  smoke checks confirm the new classifications and expected-range behavior.

## [1.2.1] - 2026-09-18

### Added

- An explicit **Locate Selected Frame** action in the Outliers tab while
  retaining double-click navigation for experienced users.
- Visible guidance for relative percentage charts: a zero-to-activity
  transition is labelled as new activity and displayed as signed 100% because
  the conventional percentage is undefined.

### Changed

- Removed the mypy exclusions for `ui.py` and `ui_components.py`; all 39 source
  modules now pass the same strict type-checking configuration.
- Replaced legacy Qt enum aliases with their typed PySide6 enum forms and
  separated the analysis thread attribute from `QObject.thread()`.
- Renamed the percentage chart option to **Relative %** and made its chart
  label describe the metric precisely.

### Verification

- 275 tests pass with 95.57% combined statement/branch coverage on Python
  3.12; Ruff and strict mypy pass without per-module error suppression.

## [1.2.0] - 2026-09-16

### Added

- Luminance chart modes for the absolute series, signed change from the
  previous frame and signed percentage change, with metric-specific labels,
  tooltips and robust display statistics.
- A dedicated, robust-score-ordered Outliers result tab with direct navigation
  to the exact AOV and frame row.
- Pure, independently tested frame-series transformations in `gui/series.py`.
- Real OpenEXR integration tests for mixed resolutions, mixed AOV structures
  and recovery from a corrupt frame between valid frames.
- Parameterised in-memory scalability tests for 100, 500 and 1,000 frames.
- A seven-task usability protocol with target times, raw-results CSV template
  and a clearly labelled developer-led expert walkthrough.

### Changed

- Completed public API type annotations and docstrings across the source
  package and enabled stricter mypy/Ruff gates for future regressions.
- Expanded the UI, usage, architecture, evaluation and release documentation
  for temporal charts, outlier navigation and usability evidence boundaries.
- Updated verification evidence to 275 passing tests and 95.57% combined
  statement/branch coverage on Python 3.12.

## [1.1.0] - 2026-09-16

### Added
- Explicit `unknown_aov` findings: unclassified channels are retained for
  integrity diagnostics instead of being silently omitted.
- Case-insensitive `aov_categories` preset overrides for renderer- or
  studio-specific AOV names.
- A dependency-free Qt luminance timeline in the Metrics tab with median and
  robust outlier markers, an explicit AOV selector, normal-range shading,
  accessible marker shapes, frame-error annotations and click-to-locate.
- Explicit, confirmation-gated classification of unknown AOVs from the GUI;
  TOML and JSON presets are updated atomically without losing rule sections.
- Optional `max_frames` analysis safeguard in the core, CLI, GUI and reports.
- Disabled-by-default `extreme_values` rule for exact-channel finite range
  diagnostics.
- Simulated in-memory 100/500/1,000-frame scalability benchmark that does not
  generate EXR fixtures.
- Ruff and mypy development quality gates.
- Collapsible analysis, validation-rule and log sections in the PySide6 GUI.
- Automatic result-tab selection, compact source-relative table paths,
  first-finding selection, severity icons and contextual empty states.
- Select-all, clear and restore-preset controls for validation rules, plus
  rule tooltips and header menus for hiding/restoring result columns.
- Persisted GUI source, preset, luminance, discovery, rule and layout choices.
- Explicit Auto, Sequence and Comparison source interpretation across the
  backend, CLI, GUI and canonical report.
- Robust per-AOV series statistics using median, MAD, consecutive deltas and
  outlier samples.
- Per-file evidence for aggregate empty and near-empty AOV findings.
- Canonical JSON report comparison in the CLI and GUI, including AOV metric
  deltas plus new and resolved findings.
- Dedicated Qt worker and presentation modules separated from the main window.
- Objective per-channel diagnostics for supported vector, depth, mask and
  scalar AOVs, shown separately in GUI, JSON and HTML outputs.
- Configurable frame filename patterns, recursive discovery, bounded depth and
  explicit multiple-sequence opt-in across the backend, CLI and GUI.
- CLI strict-warning mode and process exit codes suitable for CI/publishing.
- Windows/Linux and Python 3.11/3.12 CI matrix coverage.
- A regression test proving that CLI and GUI execution produce equivalent
  canonical analysis payloads for the same source and options.
- Verified academic references for EXR/VFX context, software testing, and
  reproducible benchmarking.

### Changed

- Multi-channel depth, mask and scalar AOVs now retain every component for
  NaN/Inf, range and negative-value diagnostics instead of selecting only R.
- Per-channel sums now reduce in float64 to improve accuracy for large HDR
  values and long sequences.
- Canonical JSON now includes an additive AOV inventory with category,
  confidence, channels and source files. HTML reports identify application
  version, active configuration, analyzed channels and finding interpretation.

- The `examples` directory is now intentionally empty: no EXR generator or
  synthetic sample is shipped. Git and the release packager exclude all EXR
  files so authorised real renders remain external to the repository.
- Updated release evidence to 267 passing tests and 95.60% combined
  statement/branch coverage, and aligned the website, references and delivery
  instructions with the verified real-EXR workflow.
- The EXR file picker now offers uppercase-extension and all-file views, while
  expected source/discovery errors are reported without a full traceback.
- Reordered result tabs around findings-first review and made the log expand
  automatically for running, failed and cancelled analyses, then collapse
  after a completed analysis even when validation warnings are present.
- Replaced first-frame change columns with median-relative and previous-sample
  changes; near-zero percentages no longer display as negative zero.
- Multiple unnumbered EXRs in Auto mode are now treated as a comparison set
  instead of producing a misleading sequence warning.
- Replaced long absolute paths in result tables with compact display paths;
  full paths remain available through tooltips, details and copy/open actions.
- The default reader now extracts supported technical AOVs during the existing
  per-frame read while keeping luminance calculations limited to color AOVs.
- NaN/Inf validation now covers technical channel diagnostics as well as color.
- Corrected sequence-checking documentation and explicitly labelled legacy UI
  screenshots as historical evidence.
- Changed the package maturity classifier from Production/Stable to Beta to
  match the documented limitations and current validation scope.

## [1.0.0] - 2026-08-08

### Added

- Contextual GUI help for controls, validation rules, result tabs, table
  metrics, inferred AOV meanings and technical channel categories.
- Automatic EXR structure inspection and approximate AOV categorisation.
- Shared frame-first analysis API used by the CLI and PySide6 GUI.
- Canonical RGB colour handling and central Rec.709/Rec.601 luminance.
- Configurable TOML/JSON validation rules and AOV-aware rule execution.
- Sequence grouping, missing-frame, duplicate-frame, and padding checks.
- Canonical JSON and self-contained HTML reports.
- Per-channel diagnostics, GUI finding filters, and report recommendations.
- Per-frame metrics in the shared model, GUI, JSON and HTML reports.
- Explicit PASS/WARNING/FAIL status shared across outputs.
- Custom luminance weights and cooperative cancellation in the GUI.
- Reproducible example generator, sample reports and frame-first benchmark.
- Static project website and structured MSc presentation/evaluation materials.
- Automated tests with branch coverage enforced by CI.

### Changed

- Replaced manual Simple/Multilayer selection in the primary workflow.
- Reorganised multilayer processing from AOV-first to frame-first reading.
- Moved CLI and GUI validation onto the same backend and result models.

### Known limitations

- Deep and multipart EXRs are detected but not processed by the 1.0 backend.
- Technical passes are structurally classified and now receive objective
  channel diagnostics, but not renderer-specific semantic interpretation.
- AOV category inference remains heuristic; renderer-specific names can be
  classified with `aov_categories` in a rule preset.

## [0.5.0] - 2026-07-21

- MSc release candidate with automatic inspection, configurable rules,
  sequence checking, HTML reporting, and the migrated GUI.
