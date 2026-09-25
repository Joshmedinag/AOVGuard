# Expert Usability Walkthrough

Date: 18 September 2026  
Build: AOVGuard 1.2.1

This is a developer-led heuristic walkthrough, not a human-participant study.
It records interface risks found while following the seven tasks in
`usability_evaluation.md`; it contains no fabricated participant timings.

## Findings and actions

| Task | Observation | Severity | Action |
| --- | --- | --- | --- |
| T1 | Unknown AOVs were visible but classification required leaving the inspection context. | Medium | Added an explicit, confirmation-gated classification control that preserves channels and writes presets atomically. |
| T3 | Outliers were visible only as chart markers and aggregate counts. | High | Added a dedicated Outliers tab ordered by robust score plus a visible Locate Selected Frame button; double-click remains a shortcut. |
| T4 | A luminance curve did not expose whether a transition was an absolute or relative jump. | Medium | Added Luminance, Delta previous and Relative % modes, plus visible guidance for the mathematically undefined zero baseline. |
| T5 | Automatic mutation of presets would be unsafe and difficult to understand. | High | Preset writes require confirmation and the UI states that reinspection or reanalysis is required. |
| T6 | A failed frame could be confused with a validation-only warning. | High | Existing FAIL state, failed-frame evidence and concise error handling retained; integration tests now cover a corrupt frame between valid EXRs. |
| T7 | Report provenance and interpretation were not sufficiently prominent. | Medium | JSON/HTML retain version, configuration, AOV inventory, channels and cautious interpretation. |

## Residual risks to test with participants

- Seven result tabs may be crowded on smaller displays.
- The relative-percentage convention after a zero-luminance frame still needs
  validation with target users despite the visible explanation.
- Users may interpret an empty AOV as an error even when it is intentional.
- Production terminology varies by renderer and studio; preset classification
  wording must be tested with the intended audience.

## Next evidence step

Run the protocol with 5-8 consenting participants using authorised or fully
anonymised data. Store raw observations in a copy of
`usability_results_template.csv`, calculate medians only after data collection,
and report non-completion and assistance rather than excluding them.
