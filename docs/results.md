# Results Evidence

The public screenshots now show the current 1.4.0rc1 interface reproducing
recorded real-sequence JSON reports. Visible paths are anonymized; report data
and internal navigation targets remain unchanged. Capture does not decode or
inspect EXRs, so these images are interface evidence, not additional analysis
runs. Earlier screenshots with personal paths were backed up locally outside
the package. `website/assets/aovguard-current-ui.png` shows the Venator master.

## Release candidate 1.4.0rc1 verification on 2026-10-13

The versioned checkout passed 1036 tests, 3 skipped and 96.34% combined
application coverage in 45.94 seconds. A separately extracted, manifest-verified
168-file source snapshot passed the same full suite in its own locked Python
3.12.12 environment: 1036 passed, 3 skipped, 96.34%, 48.71 seconds. Ruff, mypy
and website validation passed; 115 application/test/script/configuration/lock
files matched both copies by SHA-256. Documentation evidence was finalized
after this code freeze; it does not change those verified files.

Fresh base and GUI wheel environments confirmed 1.4.0rc1 imports from their
own site-packages, not the original checkout. With locked NumPy 2.4.6/OpenEXR
3.4.12 and optional PySide6 6.11.1, the existing 144-frame Venator denoised
delivery passed the base CLI, GUI-environment CLI and real Qt analysis. CLI/GUI
semantic parity, baseline comparison, chart navigation, JSON/HTML export,
protected-destination rejection/retry and cancellation/restart passed. Full
source SHA-256 checks before/after matched; cleanup was confirmed. This corpus
has no findings or outliers, so its corresponding navigation cases were
explicitly skipped rather than claimed as exercised.

The bilingual website passed link validation and local headless Edge checks
at four viewport widths (320–1440px). Native screenshots are anonymized JSON
replays, with provenance stated in their captions. Private acceptance artifacts
remain under ignored `dist/release-1.4.0rc1`; production renders are not bundled.
Published checksums and remote CI for the exact revision are recorded on the
GitHub candidate release, separately from these local observations.

## Real sequence workflow verification on 2026-10-13

The unreleased Windows/Python 3.12.12 checkout was exercised with two existing
render projects, kept outside the repository. Both used explicit sequence scope,
Rec.709 luminance, a 4096 MiB estimated admission budget and a 60-second isolated
frame deadline. These are local workflow checks, not 4K/NFS capacity or artistic
approval evidence.

| Selected delivery | Scope | Actual outcome |
| --- | --- | --- |
| Maya/Arnold multilayer | 301 frames, 1920 × 1080, 56 channels, 17 AOVs | 301 processed, 0 failed, WARNING for empty `volume`; 7 color AOVs and 8 Cryptomatte + N/Z preserved; zero NaN/Inf |
| Venator v20 masters | 144 frames 1065–1208, 1920 × 810, 55 channels, 18 color AOVs | 144 processed, 0 failed, WARNING for empty `beauty_bridge_solar` and near-empty `beauty_ship_emission`; zero NaN/Inf |
| Venator v20 denoised beauty | 144 RGBA frames, same range/resolution | 144 processed, 0 failed, PASS with no findings or luminance outliers |

Venator masters retain the original RAW passes plus a derived `beauty_planet`
RGB pass; they are not derived from the denoised passes. Rec.709 selection is
supported by the saved RenderMan/review pipeline, not explicit EXR primaries
metadata. AOVGuard's named model uses rounded coefficients. The master and
denoised inventories are different deliveries and were not baseline-compared.

The master has 15 AOV-frame outlier samples in two passes, covering nine unique
frames: six `beauty_ship_diffuse` samples and nine `beauty_sun_key` samples near
the start. The ship-emission warning represents localized contribution (~0.2265%
non-black pixels), not an absent pass. Both passes require visual interpretation
before changing the scene or validation thresholds.

The original full CLI and GUI runs matched exactly apart from generation time
and execution PID/timing. Automated offscreen Qt acceptance checked exports,
baseline comparison, active cancellation/restart and cleanup. Venator also
exercised navigation to a real outlier; Maya had no outliers to navigate. Source
names/sizes/write timestamps remained unchanged after all checks.

Independent report audits and selected native-frame calculations were retained
locally. The first Venator master's 55 channels/beauty matched an independent
OpenEXR/NumPy calculation; its planet RGB recipe matched exactly in float32.
This pixel contrast covers that frame, not every frame independently. Original
local evidence is under ignored `dist/verification-real-2026-10-13` and
`dist/verification-venator-2026-10-13`; it is not shipped with private paths/renders.

The maintained opt-in harness and path-free expectation profiles now let owners
repeat the workflows with their existing sources. See the
[verification commands and boundaries](real_exr_validation.md).

## Maintained verifier checkpoint on 2026-10-13

The completed local Windows/Python 3.12.12 gate has **1036 passed, 3 skipped**
and **96.34% combined application statement/branch coverage**, elapsed 42.37 s.
The 188 additional passing cases cover the opt-in scripts and wheel installer;
the percentage measures `aovguard`, not a separate script-coverage total. The
new Linux-only orphan process-group integration is omitted on Windows; the two
existing platform skips remain. Ruff passed and combined mypy passed for 54
source/script files with both Windows and Linux type targets. A Linux type
target is not an executed Linux test suite or completed GitHub run.

The maintained verifier repeated all 144 real masters through CLI and GUI,
retaining the two warnings and 15 AOV-frame outlier samples. Exact report parity,
baseline, outlier navigation, cancellation/restart and cleanup passed. A final
144-frame denoised CLI/GUI repetition also passed after strengthening counter,
expectation-name and descendant-cleanup checks. Source metadata remained
unchanged. The final report audit also passed against the recorded 301-frame
Maya JSON; that audit did not repeat Maya pixel decoding in this milestone.

A separate development wheel was built and installed using the new selector in
a fresh environment, with no Qt/OpenCV and imports confirmed outside the source
checkout. CLI help passed. This base-wheel install resolved the allowed ranges
to NumPy 2.5.4/OpenEXR 3.5.2; it is a packaging smoke check, not the full locked
suite, which used NumPy 2.4.6/OpenEXR 3.4.12/PySide6 6.11.1. Original stable
1.3.0 artifacts retain their previous hashes. The version is unchanged and no
commit, push or release was performed. New private evidence stays under ignored
`dist/verification-harness-2026-10-13`.

## Historical real Maya/Arnold multilayer result

The original prototype was tested with a real multilayer EXR exported from
Maya/Arnold using Merge AOVs. That historical single-file result detects 25
channels and 8 AOV descriptors; it is distinct from the newer 56-channel sequence:

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

Root RGB/RGBA channels are detected as a `beauty` colour AOV without a manual
mode selection. The updated `docs/images/04_real_simple_exr_result.png` shows
the current GUI replaying the 144-frame Venator denoised RGBA report, not the
prototype's historical single-file test.

## Public candidate captures

- `docs/images/01_real_maya_multilayer_result.png`: 301-frame Maya report,
  56 channels, 7 color AOVs, 8 Cryptomatte passes and N/Z; one empty-volume warning.
- `website/assets/aovguard-venator-rc-metrics.png`: 144-frame master metrics,
  55 channels and 18 color AOVs.
- `website/assets/aovguard-venator-rc-outliers.png`: 15 AOV-frame samples,
  covering nine unique frames; these are not 15 independently faulty frames.
- `docs/images/04_real_simple_exr_result.png`: 144-frame denoised beauty PASS.

All four capture datasets came from the documented 1.3.0 development runs.
The native Qt widgets were captured in the 1.4.0rc1 checkout on 2026-10-13.

## Large EXR note

Production EXRs and private run artifacts are not included in the repository.
Public captures show the current UI; historical single-file measurements and
actual sequence-run evidence remain explicitly distinguished from JSON replay.

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

These historical documents illustrate the prior JSON/HTML format without
distributing source image data or exposing local production paths. New analysis
exports use schema 1.2 with part metadata and effective configuration.

## Unreleased source-package verification, 2026-10-12

The latest source checkout passed the complete local Windows suites with the
locked dependencies; existing 1.3.0 artifacts remain unchanged.

| Python | Passed | Skipped | Combined application statement/branch coverage | Suite elapsed |
| --- | ---: | ---: | ---: | ---: |
| 3.12.12 | 848 | 2 | 96.21% | 51.38 s |
| 3.11.14 | 848 | 2 | 96.17% | 47.11 s |

The 81 added cases cover deterministic archive bytes, excluded local data,
manifest membership/hashes/version, unsafe or altered archives, no-overwrite
publication including a competing destination, storage failures and cleanup.
A separate packager-only coverage run had 92 passed, one symlink-permission
skip and 98.79% combined coverage for `scripts/create_release.py`; it is not
part of the application percentage above. Ruff passed and mypy checked 48
application modules plus the packaging script. The existing two full-suite
platform skips, locked dependencies and 95% application gate remain unchanged.
Local coverage evidence is under ignored `dist/verification-package/`.

A 150-source-file development ZIP was verified and extracted into a new local
directory, then installed with `uv sync --locked --python 3.12 --extra dev`.
Imports were confirmed to originate from that extracted checkout. Its complete
suite also passed: 848 passed, 2 skipped, 96.21% combined application coverage
in 65.98 s. CLI help, website validation, Ruff and mypy (49 files) passed from
the extracted installation. The final handoff adds only documentation of this
check; packaged code/configuration and dependency-lock bytes match the tested
snapshot. This is local Windows installation evidence, not remote CI or a
published release. Existing 1.3.0 ZIP and wheel checksums remain unchanged.

## Earlier unreleased safe-export verification, 2026-10-12

The preceding export milestone passed the complete local Windows suites with
locked dependencies, separately from the unchanged 1.3.0 artifacts.

| Python | Passed | Skipped | Combined statement/branch coverage | Suite elapsed |
| --- | ---: | ---: | ---: | ---: |
| 3.12.12 | 767 | 2 | 96.21% | 42.76 s |
| 3.11.14 | 767 | 2 | 96.21% | 40.64 s |

The 50 added export cases cover partial/interrupted serialization, simulated
disk-full and permission failures, descriptor cleanup, lexical/symbolic/hard-link
aliases, duplicate destinations, target revalidation, concurrent publication,
all five report writers, CLI errors and GUI retry without reanalysis.
Concurrent writers may fail with a Windows sharing violation; the test checks
that any published report remains complete, not that every writer succeeds.
The new publication helper has 100% combined coverage. Ruff and configured
mypy pass across 48 modules. Both suites used locked NumPy 2.4.6 / OpenEXR
3.4.12; the 95% combined coverage gate is unchanged.

The two skips remain the POSIX-only raw IPC-fragment test and unprivileged
Windows symlink creation. These checks establish local per-file publication
and recovery behavior, not multi-report transactions, hard power-loss
durability, NFS guarantees or completed Linux/remote CI. Coverage JSON is in
the ignored `dist/verification-output/` directory. No production EXR was
modified or generated, and this development update remains unpublished.

## Earlier unreleased technical-range verification, 2026-10-12

The preceding technical-range milestone passed the complete local Windows
suites with locked dependencies, separately from the unchanged 1.3.0 artifacts.

| Python | Passed | Skipped | Combined statement/branch coverage | Suite elapsed |
| --- | ---: | ---: | ---: | ---: |
| 3.12.12 | 717 | 2 | 96.01% | 34.57 s |
| 3.11.14 | 717 | 2 | 96.05% | 39.76 s |

The 49 added cases cover all technical components, inclusive/one-sided bounds,
signed values and tolerance, invalid configuration, Cryptomatte/category
protection, exact multipart/frame evidence, failed frames, GUI preset/keyboard
behavior, CLI exit status and baseline compatibility. The new rule module has
100% combined coverage. Ruff and configured mypy pass across 47 modules; the
two skips retain the Windows constraints described at the earlier milestone.

One existing 1920 x 1080 render with 56 channels and 17 AOVs was analyzed
read-only with only `nan_inf` and `technical_range` enabled. The explicit
`Z` policy, min 0 and max 10000, passed with one processed frame, zero failed
and no findings. This is a test policy in the source's units, not an inferred
renderer contract or a full-sequence certification. File size and mtime were
unchanged. Local JSON/HTML evidence and a 980px Qt rule-panel capture are under
the ignored `dist/verification-technical/` directory.

## Earlier unreleased execution-update verification, 2026-10-12

The execution milestone was verified locally on Windows, separately
from the unchanged 1.3.0 artifacts:

| Python | Passed | Skipped | Combined statement/branch coverage | Suite elapsed |
| --- | ---: | ---: | ---: | ---: |
| 3.12.12 | 668 | 2 | 95.91% | 42.87 s |
| 3.11.14 | 668 | 2 | 95.97% | 40.21 s |

The skips cover a POSIX-only raw IPC-fragment test and unprivileged Windows
symlink creation. Both full suites used locked NumPy 2.4.6 / OpenEXR 3.4.12.
Ruff and configured mypy passed across 46 source files; all four website pages
passed local link/anchor validation. No Linux/remote CI completion is claimed.

A fresh headless-wheel installation separately passed real EXR console-spawn
analysis with no Qt/OpenCV, using NumPy 2.5.4 / OpenEXR 3.5.2. This unlocked
smoke does not replace locked-suite evidence or change the lock. Desktop QA
covered the normal isolated mode, explicit in-process mode and an injected
fatal-cleanup state that blocks further work. One existing Full-HD, 56-channel,
17-AOV render was checked read-only in normal isolated mode (7 color,
10 technical AOVs) and with a 0.01-second frame deadline. This is correctness/
recovery evidence on one input, not a throughput, hard-RSS or 4K/NFS claim.

The preceding memory-admission milestone had 523 passed, one Windows
symlink-permission skip and 95.81% combined coverage on Python 3.11.14 and
3.12.12, with 43 source files passing configured mypy. Its single-input memory
measurements remain documented separately in `benchmark_results.md` and
predate this execution update. Existing 1.3.0 distribution hashes remain
unchanged; the development update has not been published to GitHub.

## Historical automated verification

The 1.3.0 suite was verified locally on 2026-10-12 with Windows/Python 3.11.14
and 3.12.12: each run had 434 passed, 1 skipped, and 95.56% combined
statement/branch coverage. The skip
requires Windows permission to create a symlink; it is not a missing analysis
test. Ruff and configured mypy checks pass across 42 source files. These results
do not claim Linux or a completed remote GitHub run.

Coverage includes flat multipart cases, full-channel/UINT evidence, compatible
baseline checks, controller/preferences lifecycle tests and CLI-only packaging.
A small temporary 800-frame native-EXR stress case has missing frame 17 and
corrupt frame 401: 799 discovered, 798 processed. It demonstrates continuity
and recovery on tiny fixtures, not 800-frame production 4K capacity. A fresh
Python 3.12 wheel installation also passed CLI help, EXR inspection and analysis
without Qt/OpenCV. Earlier totals below retain their historical meaning.
The current configured gate is 95% combined statement/branch coverage; the
90% threshold discussed for release 1.2.1 below is historical.

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
median elapsed time in the recorded 30-repetition run changed from 0.4387
seconds to 0.1181 seconds. This historical result predates the 1.3.0 reader and
does not measure current full-frame native RSS or multipart capacity. See
`docs/benchmark_results.md` for interpretation and limitations.
