# AOVGuard 2.0 Presentation Outline

Target duration: 15 minutes, followed by questions.

## Slide 1 - Title and objective (0:00-0:45)

**Visual:** AOVGuard GUI with a completed multilayer analysis.

**Key point:** AOVGuard 2.0 validates EXR structure and AOV data before renders
move from lighting into compositing or publishing.

## Slide 2 - Production problem (0:45-2:00)

**Visual:** A simple lighting-to-compositing pipeline diagram.

- Multilayer EXRs can contain missing, empty or invalid passes.
- Manual inspection is repetitive and naming conventions vary.
- An empty pass is not always an error; validation needs context.
- The target users are lighting artists, compositors and Pipeline/Lighting TDs.

## Slide 3 - Original prototype (2:00-3:00)

**Visual:** Original Simple/Multilayer GUI screenshot.

- Separate OpenCV and OpenEXR analysis paths.
- Manual mode selection.
- Duplicated luminance logic and different channel conventions.
- Fixed checks and low initial package coverage.
- CLI and GUI already provided a useful functional base.

## Slide 4 - Research and design questions (3:00-4:00)

- How can EXR structure be inspected automatically?
- How can RGB and luminance remain consistent across readers?
- Can a configurable rule system remain simple and testable?
- Does frame-first processing reduce redundant reads?
- How can CLI and GUI return equivalent results?

## Slide 5 - Architecture (4:00-5:20)

**Visual:** `source -> discovery -> reader -> models -> rules -> report`.

- Backend-independent core models and reader `Protocol`.
- `AnalysisReport` is the shared contract.
- UI and CLI contain presentation logic, not validation rules.
- Pixel arrays are processed incrementally and are not stored in reports.

## Slide 6 - Automatic structure inspection (5:20-6:30)

**Demo or visual:** `inspect-structure` output for an authorised real multilayer EXR.

- Root RGB becomes `beauty`.
- Named RGB groups become colour AOVs.
- Z, N and P are recognised as depth/vector data.
- Deep and multipart structures are reported as unsupported instead of being
  silently interpreted.

## Slide 7 - Canonical RGB and luminance (6:30-7:30)

- Reader output is normalised to RGB by channel name.
- One central luminance implementation supports Rec.709, Rec.601 and custom
  weights.
- NaN and Inf are counted explicitly and excluded from finite aggregates.
- Luminance rules only target colour AOVs.

## Slide 8 - Configurable validation (7:30-8:45)

**Visual:** Rule checkboxes and one TOML preset excerpt.

- Function registry plus `RuleDefinition` configuration.
- Rule severity, parameters, enabled state and supported AOV categories.
- Safe MVP rules include missing channels/AOVs, empty AOV, NaN/Inf and
  sequence consistency.
- A failing rule is isolated and reported.

## Slide 9 - Frame-first processing (8:45-10:00)

**Visual:** Benchmark table from `docs/benchmark_results.md`.

- Test dataset: 12 frames, 5 AOVs, 320 x 180, three repetitions.
- Reader calls reduced from 60 to 12.
- Pixel checksum remained identical.
- Recorded median changed from 0.3255 s to 0.0800 s on the test machine.
- Python-tracked peak memory increased because all AOVs for one frame coexist;
  native memory is not included.

## Slide 10 - CLI, GUI and reports (10:00-11:30)

**Live demo:** analyze an authorised real EXR, inspect Findings and Frames, export JSON.

- The CLI and GUI call the same API.
- GUI supports presets, individual rules, custom luminance, progress,
  cooperative cancellation, absolute/delta/percentage timelines, a dedicated
  outlier navigator and frame comparison.
- Status is explicit: PASS, WARNING or FAIL.
- JSON is canonical; HTML is a readable derived report.

## Slide 11 - Testing and reliability (11:30-12:30)

**Visual:** coverage terminal summary or CI run.

- 275 automated tests in the latest verified run.
- 95.57% total statement/branch coverage in the latest verified run.
- CI rejects coverage below 90% on Windows/Ubuntu and Python 3.11/3.12.
- Tests cover temporary deterministic EXR fixtures, corrupt files, mixed
  resolutions/AOV structures, RGB/BGR, readers, rules, 1,000-frame simulated
  sequences, reports, CLI and critical GUI workflows.

## Slide 12 - Critical evaluation (12:30-13:45)

- AOV categorisation remains heuristic.
- Deep and complete multipart processing remain outside scope.
- Technical passes receive objective channel diagnostics but still need
  renderer-aware semantic validation.
- Timing results are hardware and cache dependent.
- Rule thresholds require production presets and artist judgement.

## Slide 13 - Contribution and conclusion (13:45-15:00)

- A prototype became a modular and reproducibly evaluated validation tool.
- The strongest contribution is the shared structured analysis pipeline.
- It is relevant to both Lighting TD and Pipeline TD portfolios.
- Future work: renderer-aware presets, technical-pass rules, packaging and DCC
  integration.

End on the completed JSON/HTML report and invite questions.
