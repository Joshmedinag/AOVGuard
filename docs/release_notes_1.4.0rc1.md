# AOVGuard 1.4.0rc1

Prepared on **2026-10-13**. This is a release candidate for pipeline evaluation
before stable 1.4.0. It builds on the 1.3.0 multipart, channel-integrity and
Cryptomatte corrections. Existing stable 1.3.0 ZIPs and wheels remain separate.

## Changes included in this candidate

- Header-based memory admission: an optional MiB budget checks a conservative
  estimate before native pixel decoding, retains exact failed-frame evidence
  and continues subsequent eligible frames.
- Isolated frame execution: the canonical CLI and GUI reuse a spawned worker
  sequentially. Optional frame deadlines cover inspection, admission, decoding,
  reduction and IPC after a separate startup handshake. Cancellation stops the
  isolated worker; unconfirmed cleanup aborts the job and blocks unsafe reuse.
  The generic Python API keeps isolation opt-in for compatibility.
- Optional technical ranges: exact depth, mask, scalar and vector AOV names can
  have finite inclusive bounds and tolerance. All their components are checked
  using existing per-frame statistics. Invalid targets produce visible errors.
- Safe report exports: same-directory atomic publication protects analyzed EXR
  inputs, presets and baselines from accidental aliases. Failed exports preserve
  prior reports and allow GUI retries without repeating analysis.
- Verified source packaging: deterministic file selection, a versioned root,
  per-file SHA-256 manifest, archive validation and no-overwrite publication.
  EXRs, environments, caches and local private reports are excluded.
- Maintained real-sequence verification: explicitly chosen existing sources,
  filename patterns, ranges and luminance models; strict expected outcomes;
  source-preservation evidence; optional real GUI parity, navigation,
  cancellation/restart, baseline comparison and export acceptance.
- CI wheel installation follows `pyproject.toml` and embedded wheel metadata,
  uses a dedicated build directory and fails on missing, stale or ambiguous
  outputs. The base wheel continues to run without Qt or OpenCV.

The analysis JSON schema remains **1.2**, with additive admission/execution
provenance. Color coefficients do not transform a source color space. Unknown
AOVs and every physical channel remain visible for integrity checks.

## Verification evidence and candidate gates

The first push matrix passed, but its separate PR execution exposed Windows
3.11 access denial during descendant capture in the verifier's deadline test. Publication
was held. The final verifier now probes query/synchronize access after a denied
terminate-access open and omits the process only when a retained handle is
signaled, confirming exit. Live or unconfirmed processes still fail cleanup.
Five deterministic regressions cover both outcomes and API failures; 60 real
deadline/cleanup repetitions also passed on local Windows/Python 3.11.14.
This changes the opt-in verification script, not the application's 48 wheel
modules. Earlier packaging checkpoints below precede this final hardening.

After hardening, a new verified source snapshot was extracted and installed in
its own locked Python 3.12.12 environment: **1041 passed, 3 skipped, 0 failed,
96.34% combined application coverage in 46.80 seconds**. Ruff, mypy (54 files)
and four-page website validation passed. All 115 critical files matched the
original, archive and extraction even after testing. The installed GUI wheel
was exercised again with the current copied verifier outside the checkout:
144-frame CLI/GUI PASS, exact semantic parity, baseline/export/retry checks,
cancellation/restart (0.094 seconds to idle), confirmed cleanup and unchanged
source SHA-256. CLI took 13.610 seconds; GUI took 13.047 seconds including
presentation. These are local observations, not performance guarantees.

The pre-hardening candidate checkout on Windows/Python 3.12.12 passed **1036 tests, 3 skipped
and 96.34% combined application statement/branch coverage** (45.94 seconds).
Ruff and mypy passed, including both Windows and Linux type targets for 54
application/script files. Type targeting alone is not executed Linux testing.

A verified 168-file rc1 source snapshot was extracted into a new directory and
installed using its own locked Python 3.12.12 environment. Its full suite passed
again: **1036 passed, 3 skipped, 96.34% coverage in 48.71 seconds**. Ruff, mypy
and four-page website validation passed there too. All 115 code/configuration,
test, script and lock files matched the original and extracted snapshot by
SHA-256; final evidence notes were added after that code-bearing freeze.

Fresh base-wheel and GUI-wheel environments loaded 1.4.0rc1 from their own
site-packages, with installed application-file hashes matching the wheel.
Both passed CLI entry-point help. The base installation had neither Qt nor
OpenCV; the GUI extra used PySide6 6.11.1. These acceptance environments used
NumPy 2.4.6/OpenEXR 3.4.12 from the lock, not an unrestricted dependency upgrade.

The installed base CLI processed all 144 existing Venator denoised frames with
no findings (13.281 seconds). The GUI-wheel environment repeated CLI and real
Qt analysis, with exact semantic report parity, JSON/HTML export, baseline
comparison, chart navigation and export rejection/retry checks. Cancellation
returned to idle in 0.078 seconds; the subsequent GUI run processed 144/144
frames in 13.203 seconds including presentation. Cleanup left no worker/thread
references or active children. There were no findings/outliers in this corpus,
so those navigation cases were explicitly skipped. Full SHA-256 checks before
and after confirmed every selected EXR unchanged. Timings are observations on
this machine, not general performance guarantees.

Public screenshots reproduce earlier real-sequence reports in the current GUI,
with visible paths anonymized. They are JSON replays, not additional EXR runs.
The bilingual web pages passed local-link validation and a headless Edge check
at 320, 768, 1024 and 1440 pixels, with images loaded and no horizontal page
overflow or script errors.

The previous development checkpoint on Windows/Python 3.12.12 had **1036 tests
passed, 3 skipped and 96.34% combined application statement/branch coverage**
(42.37 seconds), with Ruff and mypy checks passing. The extra skip was a
Linux-only orphan-process integration test. These results predate the candidate
metadata freeze and must not be labelled as a new clean installation of rc1.

The earlier source-package checkpoint had **848 tests passed, 2 skipped** on
both supported Python versions: 96.21% coverage on 3.12 and 96.17% on 3.11.
Its 150-file source snapshot was also extracted and installed into a clean
3.12 environment. That snapshot predates this candidate; its original evidence
and the stable 1.3.0 artifacts are retained as historical checkpoints.

Existing external real sequences supplied separate acceptance evidence:

| Source scope | Frames processed | Channels per frame | Result |
| --- | ---: | ---: | --- |
| Maya/Arnold sequence | 301/301 | 56 | One retained warning: `volume` empty |
| Venator RAW-derived master passes | 144/144 | 55 | Two retained warnings: `beauty_bridge_solar` empty and sparse `beauty_ship_emission` |
| Venator denoised beauty | 144/144 | 4 | No findings under the selected default rules |

These runs used selected scene-linear Rec.709 coefficients. Cryptomatte stayed
outside luminance in the Maya case; the Venator master had 18 color AOVs.
Maintained Venator CLI/GUI repetitions matched semantic report evidence and
confirmed cancellation/restart and cleanup. The original inputs' names, sizes
and write timestamps remained unchanged. Independent first-frame calculations
were separate checks, not a full-corpus remeasurement by the verification script.

Final source-package verification and remote Windows/Linux CI are distinct
gates. Published asset checksums, the exact source revision and completed remote
results are recorded on the candidate's GitHub release page, not inferred from
local type checks. This candidate does not imply a PyPI publication.
See [verification evidence](results.md),
[real-input procedure](real_exr_validation.md) and [CI workflow](github_workflow.md).

## Limits that still apply

- The memory estimate is an admission check, not a hard operating-system or
  global RSS limit. Observed Full-HD performance does not establish 4K, network
  storage or arbitrary-channel capacity.
- A spawned process is not a security sandbox. OS-level unkillable processes
  cannot be guaranteed to terminate; fatal cleanup requires investigation and
  application restart. In-process native work has cooperative cancellation only.
- Flat multipart input is supported; deep data and partial decode fail the whole
  frame. Streaming, caching, parallel frame processing and table virtualization
  are not delivered in this candidate.
- Each report file is published separately. JSON and HTML are not a transaction;
  concurrent writers, network filesystems, power-loss durability and ACL
  preservation have additional filesystem constraints.
- Source manifests detect corruption but do not authenticate a publisher.
  Packaging is not a simultaneous snapshot or a private-data scanner. Review
  selected content before distributing it.
- Real-input verification is opt-in. No production EXRs are bundled or generated
  by the tool. Default preservation checks names, sizes and timestamps;
  `--hash-source` adds two complete SHA-256 passes over the selected inputs.
- Expected warnings and statistical outliers require artistic context. Sparse
  emission can be intentional; passing automated QC is not artistic approval.
  Automated GUI acceptance is not participant usability research.

## Working with the candidate

From a checkout or verified source archive, install locked dependencies and run
the candidate without modifying your source renders:

```bash
uv sync --locked --python 3.12 --extra dev
uv run --locked aovguard --help
uv run --locked --extra gui aovguard-ui
uv run --locked python -m scripts.verify_real_sequence --help
```

For separate wheel environments, source-manifest checks and clean-install
commands, follow [installation](installation.md). Keep source renders outside
the project, choose new evidence destinations and preserve the rc1 identifier
when sharing candidate packages.
