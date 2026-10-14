# Project Planning and Risk Management

## Agreed project objective

Deliver a production-oriented MSc prototype that automatically inspects EXR
structure, validates colour AOVs and sequences through configurable rules, and
provides the same structured result through a CLI and an artist-facing GUI.

## Milestones

| Milestone | Evidence | Status |
| --- | --- | --- |
| Baseline and characterisation | Legacy behaviour tests and initial coverage record | Complete |
| Backend-independent core | Models, luminance, channel utilities, reader protocol | Complete |
| EXR backend spike | OpenEXR/OpenCV/OpenImageIO comparison | Complete |
| Shared reader and inspector | Named channels, AOV categories, RGB normalisation | Complete |
| Frame-first processing | Incremental analysis and reader-call tests | Complete |
| Configurable rules | TOML/JSON presets, registry, isolated execution | Complete |
| Shared CLI and GUI | Common report, progress, findings, exports | Complete |
| Sequence and report improvements | Sequence checker and HTML report | Complete |
| Source intent and report comparison | Auto/sequence/comparison modes, robust statistics, JSON comparison | Complete |
| Reliability and flat multipart delivery | Per-part identities/windows, full-channel evidence, compatible baselines, optional GUI packaging | Implemented in 1.3.0 |
| Resource controls and technical policies | Memory admission, isolated workers, cancellation/timeouts, explicit per-AOV ranges | Implemented, unreleased |
| Report publication integrity | Atomic writes, protected inputs, fault-injection and GUI retry tests | Implemented, unreleased |
| Source package integrity | Reproducible ZIP, manifest verification, private-output exclusions and no-overwrite publication | Implemented, unreleased |
| Reproducible real-sequence acceptance | Explicit local inputs, expectation profiles, CLI/GUI parity, preservation, cancellation and version-independent wheel CI | Implemented, unreleased |
| Evaluation and release | Benchmark, examples, release evidence | In progress |

## Decision log

| Decision | Rationale | Evidence |
| --- | --- | --- |
| Describe EXR structure instead of returning a binary type | EXRs can combine colour, technical, multipart, and deep structures | Inspector models and tests |
| Use RGB internally | Removes OpenCV BGR/OpenEXR RGB ambiguity | Channel and luminance tests |
| Use OpenEXR for the 1.0 backend | Named channels worked reliably; OpenImageIO failed to import in the Windows spike | `experiments/backend_spike_summary.md` |
| Process by frame | Reduces application-level reads from frames x AOVs to frames | Benchmark and core analysis |
| Use function-based rules | Keeps the MVP configurable without a plugin hierarchy | Rule registry and loader |
| Keep flat multipart parts independent; reject any deep part | Prevents channel collisions and partial/deep misinterpretation | Part inspections, namespaced descriptors and atomic frame findings |
| Make Qt optional and use OpenEXR for legacy decoding | Allows CLI-only installs without desktop/OpenCV dependencies | Wheel smoke checks and real grayscale/RGBA regressions |
| Extract controller and preferences ownership | Keeps thread cleanup and persisted settings separate from rendering tables | `gui/controller.py` and `gui/settings.py` |

## Risk register

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Renderer naming conventions are ambiguous | High | Medium | Preserve `unknown`, expose channels, allow preset overrides |
| Rules produce false positives | Medium | High | AOV-aware checks, configurable severity and thresholds |
| Large frames exhaust memory | Medium | High | Release buffers after measurement; measure native RSS before claiming a capacity limit |
| Corrupt frames terminate the run | Medium | High | Per-frame exception handling and failed-frame findings |
| Export truncates a report or overwrites an input | Medium | High | Same-directory atomic replacement, destination/input checks and failure-path tests |
| Source package leaks local output or omits test helpers | Medium | High | Pruned selection, manifest checks, preview before sharing and tests from an extracted snapshot; filters are not a secret scanner |
| GUI blocks during IO | Medium | Medium | Development isolated child cancellation and optional frame service deadline; explicit in-process mode remains cooperative, and parent discovery/manual inspection/final rules/export are outside that deadline |
| Backend is difficult to install | Medium | High | Locked Python 3.12 environment and documented OpenEXR decision |
| Scope expands before submission | High | High | Deep sample semantics, plugins, and DCC integration remain future work; flat multipart is supported |
| Evaluation is not reproducible | Medium | High | Documented real-EXR corpus, benchmark command, JSON results and recorded metadata |

## Definition of done

- Clean installation from the lock file on Python 3.12.
- Configured local checks pass with at least 95% combined statement/branch
  coverage; completed remote CI is recorded separately when run.
- The real-EXR evaluation corpus and expected outcomes are documented without exposing confidential image data.
- CLI and GUI produce equivalent reports for the same options.
- Benchmark records reader calls, runtime, and Python allocation peak.
- README, limitations, references, examples, and release notes are complete.
- Submission includes project files, thesis PDF, video, website files, and
  presentation materials required by the coursework brief.
