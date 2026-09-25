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
| Evaluation and release | Benchmark, examples, release evidence | In progress |

## Decision log

| Decision | Rationale | Evidence |
| --- | --- | --- |
| Describe EXR structure instead of returning a binary type | EXRs can combine colour, technical, multipart, and deep structures | Inspector models and tests |
| Use RGB internally | Removes OpenCV BGR/OpenEXR RGB ambiguity | Channel and luminance tests |
| Use OpenEXR for the 1.0 backend | Named channels worked reliably; OpenImageIO failed to import in the Windows spike | `experiments/backend_spike_summary.md` |
| Process by frame | Reduces application-level reads from frames x AOVs to frames | Benchmark and core analysis |
| Use function-based rules | Keeps the MVP configurable without a plugin hierarchy | Rule registry and loader |
| Reject unsupported structures explicitly | Prevents silent misinterpretation of deep or multipart data | Structured error findings |

## Risk register

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Renderer naming conventions are ambiguous | High | Medium | Preserve `unknown`, expose channels, allow preset overrides |
| Rules produce false positives | Medium | High | AOV-aware checks, configurable severity and thresholds |
| Large sequences exhaust memory | Medium | High | Frame-first reads and metric-only accumulation |
| Corrupt frames terminate the run | Medium | High | Per-frame exception handling and failed-frame findings |
| GUI blocks during IO | Medium | Medium | Worker thread, progress callback, cooperative cancellation |
| Backend is difficult to install | Medium | High | Locked Python 3.12 environment and documented OpenEXR decision |
| Scope expands before submission | High | High | Deep, multipart, plugins, and DCC integration remain future work |
| Evaluation is not reproducible | Medium | High | Documented real-EXR corpus, benchmark command, JSON results and recorded metadata |

## Definition of done

- Clean installation from the lock file on Python 3.12.
- CI and local tests pass with at least 90% branch coverage.
- The real-EXR evaluation corpus and expected outcomes are documented without exposing confidential image data.
- CLI and GUI produce equivalent reports for the same options.
- Benchmark records reader calls, runtime, and Python allocation peak.
- README, limitations, references, examples, and release notes are complete.
- Submission includes project files, thesis PDF, video, website files, and
  presentation materials required by the coursework brief.
