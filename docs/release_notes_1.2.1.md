# AOVGuard 1.2.1

Released 18 September 2026.

This hardening release makes outlier navigation more discoverable. The
score-ordered Outliers view now includes a persistent **Locate Selected Frame**
button; double-click navigation remains available. Selecting an entry and
activating either action switches to the exact AOV/frame row.

The temporal percentage view is now named **Relative %**. Its visible guidance
explains that a transition away from a zero-luminance frame is shown as signed
100% and labelled as new activity because a conventional percentage from zero
is undefined.

The two Qt modules now participate fully in strict mypy checking. Legacy enum
aliases were replaced with typed PySide6 enum members, ambiguous Qt values are
narrowed explicitly, and the analysis thread no longer shadows
`QObject.thread()`. There are no per-module mypy error suppressions.

Verification on Python 3.12: 275 tests passed with 95.57% combined statement
and branch coverage. Ruff and strict mypy pass across all 39 source modules.
