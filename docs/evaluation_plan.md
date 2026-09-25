# Evaluation Plan

The tool should be evaluated with real EXR outputs from DCC/rendering software.

## RGB/RGBA EXR evaluation

1. Export or collect a normal RGB/RGBA EXR.
2. Place the file inside a test folder.
3. Run `aovguard inspect-structure` and `aovguard analyze`.
4. Confirm that `beauty` is detected as a colour AOV and metrics are correct.

## Multilayer EXR evaluation

1. Export a multilayer EXR from Maya/Arnold with Merge AOVs enabled.
2. Include AOVs such as `albedo`, `diffuse_direct`, `specular_direct`, and `emission`.
3. Run **Inspect Structure** to confirm the detected channels and categories.
4. Run the shared automatic analysis.
5. Check that colour AOVs are measured, technical passes are not treated as
   colour, and empty AOVs are reported as findings.

## Correctness and performance evidence

- Validate strict JSON output with NaN and Inf fixtures.
- Record discovered, successful and failed frame counts.
- Instrument the reader and verify one `OpenEXR.File` construction per frame.
- Compare runtime and peak memory on fixed frame/AOV/resolution datasets.
- Record test and branch coverage for every release candidate.

The current recorded benchmark and its method are available in
`docs/benchmark_results.md` and `docs/benchmark_methodology.md`. The executable
benchmark writes raw JSON to `experiments/benchmark_results.json`.

## Usability evidence

The seven-task protocol is defined in `docs/usability_evaluation.md`, and raw
observations should be copied into `docs/usability_results_template.csv` after
confirming the appropriate ethics route. It measures completion, time,
assistance, critical errors and SUS responses for structure inspection,
findings, outliers, temporal changes, classification, continuity and export.

`docs/usability_expert_walkthrough.md` records the completed developer-led
heuristic pass and the resulting interface changes. It is not participant
evidence and contains no fabricated timings. A study with 5-8 consenting target
users remains the next evidence step.

## Documentation evidence

Screenshots of successful tests are included in `docs/images/`. Automated tests
use temporary deterministic fixtures, while final workflow evidence uses
authorised real EXRs kept outside the repository. Anonymised reports preserve
the evidence without distributing source image data.
