# AOVGuard 1.2.0

Released 16 September 2026.

This release makes temporal review and anomaly triage more direct. The Metrics
chart can show average luminance, signed change from the previous frame or
signed percentage change for a selected color AOV. Each mode recalculates its
own median, robust normal range and display outliers, while click navigation
continues to select the underlying frame evidence.

A dedicated Outliers tab lists canonical luminance-series anomalies by robust
score. Double-clicking an entry switches to the correct AOV and selects the
exact row in Frames/Samples. The numerical transformation is isolated in a
pure, typed module so its zero-baseline and non-finite behavior can be tested
without Qt.

Public source APIs now have complete function annotations and docstrings, with
strict mypy and Ruff rules guarding regressions. Integration coverage includes
real temporary OpenEXRs with mixed resolutions, mixed AOV structures and a
corrupt frame between valid frames. Simulated sequence tests exercise 100, 500
and 1,000 frames without creating demonstration EXRs.

The usability materials now provide seven timed tasks, a raw-observation CSV
template and a developer-led expert walkthrough. No human-participant results
are claimed; collecting evidence with 5-8 consenting target users remains a
separate next step.

Verification on Python 3.12: 275 tests passed with 95.57% combined statement
and branch coverage. Ruff and mypy also pass.
