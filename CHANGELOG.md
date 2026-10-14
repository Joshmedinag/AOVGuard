# Changelog

All notable project changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.0rc1] - 2026-10-13

This release candidate consolidates the development updates after 1.3.0.
Candidate packaging, clean installation and remote CI must be recorded
separately from the pre-candidate checkpoints below. See
[release notes](docs/release_notes_1.4.0rc1.md) for scope and limitations.

### Added

- Opt-in real-sequence verification with explicit filename/range/color intent,
  strict expected-outcome JSON profiles and input-preservation checks. Existing
  EXRs stay outside the repository; verification never generates render images.
- Optional offscreen GUI repetition checks exact CLI parity, actual finding/
  chart/outlier navigation, baseline comparison, protected exports and retries.
  Active-worker cancellation/restart is explicitly opt-in, with cleanup evidence.
- New evidence directories retain canonical reports, logs, source inventories,
  report hashes and process-tree memory sampling on Windows/Linux. Unsupported
  memory measurements are marked unavailable; full source hashes are optional.
- Version-independent CI wheel selection and validation from a dedicated build
  directory. Missing/stale/ambiguous wheels fail before installation; stable
  artifacts remain separate. The workflow does not publish packages automatically.

- Verified source snapshots with deterministic metadata, a versioned root and
  per-file SHA-256/size manifest. Standard-library `--list` and `--verify` modes
  preview selection and check integrity without extracting or executing files.
- Source packaging prunes links/reparse points, local reports/examples except
  placeholders, common credential/temporary patterns and caches before descent.
  GUI spawn test helpers are no longer accidentally removed by the preview filter.
- Source ZIPs are checked before atomic no-overwrite publication. Existing
  destinations remain intact; unsupported hard-link filesystems fail explicitly.
  CI now checks website links and source manifests without publishing artifacts.

- Atomic publication for canonical JSON/HTML, comparison JSON and legacy
  JSON/CSV. Same-directory temporary files are flushed/synced before replace;
  failures before replacement preserve existing reports and attempt cleanup.
- Destination checks reject EXR filenames, links, non-regular/read-only targets,
  protected input aliases and duplicate CLI output paths, including hard links.
  The GUI protects analyzed presets/loaded baselines and permits retrying an
  export failure without reanalysis. Comparison CLI write errors now report
  exit code 1 cleanly; Ctrl+C returns 130.
- Per-file export protection is automatic and does not change report schemas.
  It does not coordinate concurrent writers or make JSON/HTML a transaction.

- Opt-in `technical_range` rule for exact depth/mask/scalar/vector AOV names,
  with independent inclusive lower/upper bounds and absolute tolerance.
  All components use existing per-frame finite statistics; findings retain
  exact channel/file evidence without rereading pixels or changing IPC.
- TOML/JSON range policies, GUI **Technical ranges** selection/help and a
  disabled example preset. Invalid/missing targets and non-technical categories
  produce `rule_error`; Cryptomatte and unknown channels stay preserved.
- Baseline compatibility ignores disabled rule definitions, including newly
  added optional rules, while still rejecting changed active range policies.

- Optional positive finite `--max-memory-mb` MiB budget per flat frame before
  pixel decode; absent CLI flag and GUI `0 / Unlimited` leave it disabled.
  Invalid saved GUI values activate 1024 MiB with a visible warning.
- Versioned conservative `flat-working-set-v1` header estimate covering every
  part/channel, native/promotion/stack buffers, largest-part scratch, fixed
  reserve and safety margin without assuming exact header pixel types.
- Exact-file `memory_budget` errors, failed-frame accounting and retained
  header/estimate evidence for over-budget frames; subsequent frames continue.
- Additive schema 1.2 budget/model/breakdown fields and HTML admission decisions.
  Gating does not change accepted-frame semantics or baseline compatibility,
  although different admitted scopes can alter aggregates and findings.
- Read-only process-memory benchmarking with an optional admission budget.
- Default isolated frame analysis in the canonical CLI/GUI, reusing one spawned
  child sequentially per job and returning scalar statistics, never pixel arrays.
  The generic Python API keeps isolation opt-in for compatibility.
- Optional positive finite `--frame-timeout-seconds` / GUI **Frame timeout (s)**.
  The deadline starts after the ready handshake and covers header inspection,
  admission, decode, reduction and IPC; startup has its own 30-second deadline.
- Exact-file `frame_timeout`, `worker_crash` and worker-protocol diagnostics,
  failed-frame accounting, child reaping and restart for subsequent frames.
- Isolated GUI cancellation/close cleanup and friendly CLI Ctrl+C exit `130`;
  explicit `--in-process` opt-out retains cooperative-only native cancellation
  and rejects combination with a frame timeout before decode.
- Additive schema 1.2 `frame_execution` records and execution-option provenance,
  plus HTML execution diagnostics. Volatile PID/timing and execution policy do
  not alter baseline semantics for otherwise identical accepted metrics.
- Fail-closed handling of `WorkerCleanupError`: abort the job, forbid executor
  reuse and block new GUI analyses when child/receiver cleanup is unconfirmed.
  Recorded elapsed time can include startup, frame service and cleanup.

### Evidence boundaries

- Released 1.3.0 artifacts and totals below predate this update. One existing
  user render at 1920 x 1080, 56 channels and 17 AOVs was measured under a
  4096 MiB budget: estimate 2373.9453125 MiB, process peak RSS 935.59375 MiB,
  after-import baseline 40,816,640 bytes, elapsed 1.849241 s, one processed,
  zero failed. This single Full-HD measurement does not validate 4K or NFS.
- Estimates and process isolation are not hard OS/global RSS limits or security
  sandboxes. In-process native eager reads cannot be aborted cooperatively;
  isolated cancellation stops the child instead. Concurrent source replacement
  can invalidate preflight assumptions. Caching, parallel frame processing,
  automatic renderer-specific semantics and table virtualization are not delivered.
- Bounded cleanup attempts cannot guarantee OS termination of an unkillable
  process; a fatal cleanup error requires checking remaining processes and
  restarting the application rather than silently resuming.

### Pre-candidate verification checkpoints

These measurements were recorded before the 1.4.0rc1 metadata freeze. They
remain historical evidence; a final candidate run must identify its exact
source snapshot and environment. No completed remote CI run is claimed here.

- Opt-in verification update on 2026-10-13, Windows/Python 3.12.12:
  1036 passed, 3 skipped, 96.34% combined application coverage in 42.37 s.
  The 188 added passing cases cover expected outcomes, complete pixel/channel
  evidence, protected inputs, GUI parity/cancellation/navigation/export failures,
  process-tree measurement/cleanup and version-independent wheel selection.
  The additional skip is the Linux-only orphaned process-group integration.
  Ruff passed; combined mypy passed for 54 files under Windows/Linux targets.
  Real Venator masters passed the maintained CLI/GUI workflow with all 144
  frames and both warnings retained; the final denoised GUI/CLI repetition
  passed 144/144 with confirmed cleanup. Source metadata remained unchanged.
  A separately built development wheel passed base installation and CLI help
  without Qt/OpenCV. This is local evidence, not a new release or remote CI run.

- Source-package update on 2026-10-12, Windows: Python 3.12.12 completed with
  848 passed, 2 skipped, 96.21% combined application coverage in 51.38 s;
  Python 3.11.14 had 848 passed, 2 skipped, 96.17% in 47.11 s. The 81 added
  cases cover package integrity, reproducibility, path safety and failure modes.
  A separate packager-only coverage run reached 98.79% (92 passed, one skip).
  Ruff passed and mypy checked 48 application modules plus the packaging script.
  Existing platform skips, locked dependencies and the 95% gate are unchanged.
- A verified 150-source-file snapshot passed clean locked installation on
  Windows/Python 3.12.12 and the complete suite: 848 passed, 2 skipped, 96.21%
  application coverage in 65.98 s. CLI help, website links, Ruff and mypy passed
  from that extracted checkout. Final documentation records these results;
  source/configuration/lock bytes are unchanged from the tested snapshot.
  Existing stable 1.3.0 artifacts remain intact; no GitHub publication was made.
- Safe-export update on 2026-10-12, Windows: Python 3.12.12 completed with
  767 passed, 2 skipped, 96.21% combined statement/branch coverage in 42.76 s;
  Python 3.11.14 completed with 767 passed, 2 skipped, 96.21% in 40.64 s.
  Ruff and configured mypy passed across 48 source modules. The 50 added cases
  cover interrupted writes, filesystem failures, input aliases, duplicate
  destinations, CLI exit handling and GUI export retries. The publication
  helper has 100% combined coverage. Both suites used locked dependencies;
  the existing platform skips, 95% coverage gate and 1.3.0 artifacts remain
  unchanged. This local development update has not been published.
- Technical-range update on 2026-10-12, Windows: Python 3.12.12 completed with
  717 passed, 2 skipped, 96.01% combined statement/branch coverage in 34.57 s;
  Python 3.11.14 completed with 717 passed, 2 skipped, 96.05% in 39.76 s.
  Ruff and configured mypy passed across 47 source modules. The 49 added cases
  cover policy errors, exact component/frame/part evidence, CLI/GUI parity,
  isolated processing and baseline compatibility. The new rule module has
  100% combined coverage. Skips retain the platform constraints listed below.
- A real existing Full-HD EXR passed an isolated read-only check with only
  `nan_inf` and a `Z` range of 0 to 10000 enabled; source size/mtime remained
  unchanged. Qt keyboard/preset behavior and the 980px rule layout were checked.
  This is a targeted policy check, not full-sequence or renderer certification.
  The 1.3.0 artifacts remain unchanged and the update remains unpublished.

- Final local execution-update freeze on 2026-10-12, Windows: Python 3.12.12
  completed with 668 passed, 2 skipped, 95.91% combined statement/branch
  coverage in 42.87 s; Python 3.11.14 had 668 passed, 2 skipped, 95.97% in
  40.21 s. Skips cover the POSIX raw IPC-fragment test and unprivileged Windows
  symlink creation. Ruff and configured mypy passed across 46 source files;
  full suites used locked NumPy 2.4.6 / OpenEXR 3.4.12.
- A separate fresh headless-wheel console-spawn smoke passed real EXR analysis
  without Qt/OpenCV using NumPy 2.5.4 / OpenEXR 3.5.2, without altering the lock.
  GUI checks covered normal/in-process execution and an injected fatal cleanup
  state; a real Full-HD EXR was checked read-only in normal isolated mode and
  with a 0.01-second frame deadline. These do not claim 4K/NFS capacity or
  Linux/remote CI completion. Existing 1.3.0 artifact hashes remain unchanged;
  the development update has not been published to GitHub.
- Earlier memory-admission milestone on Windows/Python 3.11.14 and 3.12.12: each run had
  523 passed, one Windows symlink-permission skip and 95.81% combined
  statement/branch coverage. Ruff and configured mypy passed across 43 source
  files. These are unreleased local results, not regenerated 1.3.0 artifacts
  or a completed Linux/remote CI run.
- The same existing Full-HD render under 1024 MiB was rejected before pixels:
  zero processed, one failed, peak RSS 39.01171875 MiB, zero peak growth above
  imports and one 0.0021095 s analysis measurement. No throughput claim follows.
- At that memory milestone, real GUI rejection recovered its controls and
  cleared worker/thread references while preserving EXR size/mtime. Those
  measurements predate the isolated execution update and do not establish
  a total-memory limit.

## [1.3.0] - 2026-10-12

### Fixed

- Retained alpha and auxiliary channels of known color/vector AOVs for
  integrity validation, with exact per-frame channel evidence in reports.
- Unified RGB suffix aliases between inspection and decoding; prevented root
  RGB and named `beauty` collisions by assigning a distinct `beauty [root]`
  descriptor; preserved UINT IDs without float32 quantization.
- Separated stored `dataWindow` dimensions from delivery `displayWindow`
  dimensions and retained the coordinates of both windows.
- Kept temporal summaries separate per numbered sequence and excluded
  previous-frame deltas across gaps, failed frames and missing AOV samples.
- Marked non-calculable baseline metric differences as `unavailable`, checked
  semantic configuration compatibility and included affected files and metric
  evidence when comparing findings.
- Released decoded pixel references before the next frame read and rejected
  unsupported deep structures through header-only preflight. This does not
  establish streaming or a measured reduction in peak native memory.
- Coordinated window closing with cooperative cancellation and QThread
  completion during an active GUI analysis.
- Made direct `pytest` invocation resolve the project benchmark module by
  configuring the checkout root as a test import path.
- Established resolution and AOV-structure baselines independently for each
  numbered sequence instead of comparing unrelated sequence layouts.
- Migrated legacy simple RGB/RGBA/Y grayscale decoding from OpenCV to OpenEXR,
  preserving its private BGR adapter and externally visible metrics/errors.
- Standard Cryptomatte layers are identified from EXR metadata and excluded
  from color luminance, frame trends and robust outliers. All ID/coverage
  channels remain available for NaN/Inf and technical diagnostics.
- Very large technical channel statistics use compact scientific notation in
  the GUI instead of overflowing table cells.

### Added

- ACEScg/AP1 luminance weights for scene-linear AP1 data in the shared backend,
  CLI and GUI; custom coefficients continue to override named CLI models.
- Flat multipart analysis with independent part names, views, windows, channels
  and qualified AOV identities. Unique named-part namespaces survive reordering
  while multipart; unnamed/duplicate names use index fallback. Any deep part or
  partial decode rejects the complete file/frame.
- Canonical analysis schema `1.2`, including per-part structure, per-frame
  channel statistics, sequence-specific series and effective rule definitions.
  Historical schemas `1.0` and `1.1` remain readable with explicit warnings when
  their configuration compatibility cannot be fully established.
- Optional `gui` installation extra and a lazy desktop launcher. Base runtime
  dependencies are NumPy and OpenEXR; Qt and OpenCV are not CLI requirements.
  The `dev` extra includes Qt for the complete test suite.
- Extracted Qt `AnalysisController` and `PreferencesStore`, separating job
  lifetime/cancellation/shutdown and persisted choices from the main window.
- Dynamic source archive version from `pyproject.toml` and additional cache,
  environment and external-resource exclusions; citation metadata updated to 1.3.0.
- Ruff and strict mypy checks in the Windows/Linux CI matrix, plus locked
  dependency installation; aligned the OpenEXR minimum with its modern File
  API (`>=3.3`) without upgrading the locked packages.
- Wheel-build and CLI-only installation smoke checks in CI, asserting the
  packaged CLI works without PySide6 or OpenCV.
- Optional inclusive expected frame range in the core, CLI, GUI and JSON/HTML
  reports. Missing delivery tails or leading frames become error findings;
  frames outside the declared range are warned about.
- Spanish website documentation covering installation, GUI and CLI workflows,
  Cryptomatte handling, sequence ranges, presets, reports, troubleshooting,
  limitations and development verification.
- Complete English website edition with equivalent technical content,
  bidirectional language navigation and responsive desktop/mobile layouts.

### Verification

- Final local 1.3.0 suite on 2026-10-12, Windows/Python 3.11.14 and 3.12.12:
  each run completed with 434 passed,
  1 skipped, with 95.56% combined statement/branch coverage. The skip concerns
  Windows symlink-creation permissions. Ruff and configured mypy checks passed
  across 42 source files; remote/Linux execution is not claimed.
- A temporary small-EXR 800-frame integration case retained a missing frame 17
  and corrupt frame 401: 799 discovered, 798 processed. This checks continuity
  and recovery, not performance on 800 production 4K renders.
- A wheel installed into a fresh Python 3.12 CLI-only environment imported from
  site-packages without Qt/OpenCV and passed help, real EXR structure inspection
  and analysis. The optional desktop launcher reported a missing-GUI-extra
  hint without a traceback.
- A separate fresh wheel installation with the GUI extra passed an offscreen
  desktop smoke check and a real worker/reader analysis: one existing EXR,
  five color AOVs, no failed frames and no findings. The worker/thread were
  released before closing; preferences were isolated in a temporary INI.
- Historical reliability checkpoint on 2026-10-11 with Windows and
  Python 3.12.12: 368 tests passed with 95.41% combined statement/branch
  coverage. This predates the expanded multipart/packaging/controller suite.
  Local evidence is distinct from remote CI execution.
- Historical checkpoint before the reliability corrections above (commit
  `530ed76`): 282 tests passed with 95.37% combined statement/branch coverage on
  Python 3.12. Ruff and strict mypy passed. Representative EXR-header and
  filename-only smoke checks confirmed the Cryptomatte classifications and
  expected-range behavior at that checkpoint.

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
