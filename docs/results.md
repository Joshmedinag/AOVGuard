# Results Evidence

The repository retains historical screenshots showing the original prototype
working with real EXR files. The current interface is captured in
`website/assets/aovguard-current-ui.png`.

## Real Maya/Arnold multilayer result

File: `docs/images/01_real_maya_multilayer_result.png`

This historical screenshot shows a real multilayer EXR exported from Maya/Arnold
using Merge AOVs. Its manual mode selector and result layout belong to the
original prototype. The same file was subsequently validated with the current
automatic backend, which detects 25 channels and 8 AOV descriptors:

```text
beauty
Z
specular_direct
P
N
emission
diffuse_direct
albedo
```

`beauty`, `albedo`, `diffuse_direct`, `specular_direct`, and `emission` are
analysed as colour. `N` and `P` are recognised as vectors and `Z` as depth.
The `empty_aov` rule reports `emission`; the technical passes receive
per-channel diagnostics but are not subjected to colour luminance rules.

## Real simple EXR result

File: `docs/images/04_real_simple_exr_result.png`

This is also a historical screenshot from the earlier interface. In the current
backend, root RGB/RGBA channels are detected as a `beauty` colour AOV without a
manual mode selection.

## Large EXR note

The real multilayer EXR file is not included in the repository because it is too
large. These screenshots are retained as historical evidence and are not used
as evidence of the current UI design.

## Real EXR evaluation

The project does not generate or ship demonstration EXRs. Final correctness,
workflow and performance evidence should be captured with authorised real EXR
files representing the intended lighting and compositing workflow. Record each
file's renderer, resolution, channel structure and relevant expected result
without committing confidential production data.

Anonymised report-format examples from authorised real EXR evaluation are
retained under:

```text
docs/sample_reports/multilayer_report.json
docs/sample_reports/multilayer_report.html
```

These documents illustrate the JSON/HTML schema without distributing the source
image data or exposing local production paths.

## Automated verification

Release 1.2.1 was verified locally on 18 September 2026 with 275 passing tests
and 95.57% combined statement/branch coverage on Python 3.12. An earlier
baseline had passed on both
Python 3.11 and 3.12. GitHub CI remains configured to enforce a 90% minimum
across Windows and Ubuntu for the supported Python versions. The suite includes
integration tests comparing canonical CLI and GUI payloads, explicit source
modes, robust series statistics, per-file finding evidence and JSON report
comparison.

The 1.2.1 suite retains the 1.1.0 regressions for unknown/ignored AOVs,
secondary-channel anomalies, float64 accumulation, atomic preset updates and
report provenance. It adds pure tests for all temporal chart modes and direct
outlier navigation, parameterised 100/500/1,000-frame simulated analyses, real
OpenEXR mixed-resolution/structure coverage, and recovery from a corrupt frame
between valid frames. The release also verifies explicit and double-click
outlier navigation, visible relative-change guidance and strict type checking
for the Qt modules without mypy exclusions.

## Frame-first benchmark

The reproducible 12-frame, 5-AOV benchmark reduced application-level reader
calls from 60 to 12 while preserving an identical pixel checksum. The recorded
median elapsed time on the test machine changed from 0.3255 seconds to 0.0800
seconds. See `docs/benchmark_results.md` for interpretation and limitations.
