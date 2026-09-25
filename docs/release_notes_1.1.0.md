# AOVGuard 1.1.0

Released 16 September 2026.

This release hardens AOVGuard for renderer- and studio-specific data. Unknown
AOVs and explicitly ignored AOVs remain visible with every channel retained.
The GUI can save a confirmed classification atomically to TOML or JSON, and
multi-channel depth, mask and scalar passes are validated component by
component. Numeric channel accumulation uses float64 reductions.

The luminance chart now provides an explicit AOV selector, median and robust
normal range, accessible outlier/error shapes, evidence tooltips and direct
frame navigation. The optional maximum-frame limit rejects oversized discovery
before pixel decoding.

JSON reports add an AOV inventory without changing schema version `1.0`. HTML
reports add version/configuration provenance, analyzed channels, sequence
status and cautious finding interpretation. The new `extreme_values` rule is
disabled by default and reports the exact channel exceeding its configured
finite absolute limit.

Verification on Python 3.12: 267 tests passed, with 95.60% combined statement
and branch coverage. Ruff and mypy also pass. The in-memory scalability smoke
test processed 100, 500 and 1,000 simulated frames without generating EXR
fixtures; results and limitations are documented in `benchmark_results.md`.
