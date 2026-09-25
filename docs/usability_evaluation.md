# Usability Evaluation Protocol

This is a small formative evaluation for the GUI and CLI. Confirm university
ethics requirements before recruiting or recording participants. If formal
approval is not available, use expert review or clearly labelled informal peer
feedback instead of presenting the work as a user study.

**Current status:** the protocol, observation sheet and expert walkthrough are
complete. No human-participant timings or SUS results have been collected yet;
the templates must not be presented as participant evidence until real sessions
have taken place.

## Participants

Aim for 5-8 people familiar with at least one of lighting, compositing,
rendering or Python pipeline work. Record their relevant experience, not
unnecessary personal data.

Use participant codes such as `P01`. Record only an experience band
(`novice`, `intermediate`, `expert`) and relevant role. Do not record production
file names, client names or confidential image content.

## Tasks

1. **T1 — Inspect structure:** select and inspect an authorised multilayer EXR;
   state the number of color, technical and unknown AOVs. Target: 90 seconds.
2. **T2 — Run validation:** analyze the supplied sequence and explain its
   overall status and highest-severity finding. Target: 120 seconds.
3. **T3 — Locate an outlier:** use the Outliers view to navigate to the known
   anomalous frame and identify its AOV. Target: 60 seconds.
4. **T4 — Interpret temporal change:** switch the chart between Luminance,
   Delta previous and Relative % and explain the largest transition, including
   what signed 100% means after a zero-luminance frame.
   Target: 90 seconds.
5. **T5 — Classify an unknown AOV:** assign the supplied renderer-specific AOV
   to the stated category, confirm the change and identify when it takes effect.
   Target: 120 seconds. Use a disposable copy of the preset.
6. **T6 — Diagnose continuity:** identify a missing frame, mixed resolution or
   corrupt-frame failure in the supplied sequence. Target: 90 seconds.
7. **T7 — Export evidence:** export JSON and HTML, then locate the version,
   active configuration, overall status and per-frame evidence. Target: 120
   seconds.

Counterbalance the starting file or sequence when possible. Give each
participant the same task wording and do not teach the interface during the
timed portion.

## Measures

- Task completion without assistance.
- Time per task.
- Number of navigation or interpretation errors.
- Whether PASS, WARNING and FAIL are understood correctly.
- Whether the finding message and recommendation lead to the expected action.
- A 1-5 confidence rating after each task.
- Start and finish timestamps and elapsed seconds.
- Assistance level: `none`, `prompt`, or `demonstration`.
- Critical error: an action that produces the wrong source, frame, category or
  delivery status without the participant noticing.

Use `docs/usability_results_template.csv` for raw observations. Stop timing
when the success criterion is met, the participant abandons the task, or five
minutes have elapsed.

## Success criteria

- At least 80% task completion without demonstration.
- No critical error in status interpretation or AOV classification.
- Median task time at or below the stated target for T1-T7.
- Median confidence of at least 4/5.
- System Usability Scale (SUS) reported as a descriptive score, not a claim of
  population-wide usability.

With fewer than five completed participants, report individual results and
observations rather than percentages.

## Post-session SUS

Ask the standard ten SUS statements using a 1-5 agreement scale, alternating
positive and negative wording. Score odd items as `response - 1`, even items as
`5 - response`, sum and multiply by 2.5. Preserve the ten raw responses so the
calculation can be audited.

## Interview prompts

- Which result would you check first in a real delivery?
- Was any label ambiguous?
- Did the distinction between aggregate and per-frame metrics make sense?
- Which rule would you enable or disable for your own workflow?
- What information is still missing before you would trust the tool?

## Reporting

Report participant count, background, task success, median completion time and
recurring observations. Separate direct observations from interpretation.
Do not generalise a small convenience sample to the whole VFX industry.

Include the test build/version, operating system, screen resolution, input
dataset description, facilitator, deviations from the protocol and whether
sessions were in person or remote. Keep empty templates and real observations
in separate files.
