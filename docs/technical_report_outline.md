# Technical Report Outline

This outline maps the dissertation to the MSc brief and keeps implementation
evidence connected to research questions.

## 1. Introduction

- Production context and problem statement.
- Target users and workflows.
- Aim, objectives, research questions and scope.
- Definition of AOV, multilayer, multipart and deep EXR terminology.

## 2. Related Work and Technical Context

- OpenEXR data model and channel naming.
- OpenCV, OpenEXR and OpenImageIO trade-offs.
- Luminance standards and scene-linear HDR interpretation.
- Validation and quality-control tools in VFX pipelines.
- Configurable rules, reports and sequence validation.
- Critical comparison showing the gap addressed by AOVGuard.

## 3. Requirements and Methodology

- Original prototype analysis and professor feedback.
- Functional and non-functional requirements.
- MoSCoW scope and risk management.
- Characterisation tests and backend spike.
- Iterative implementation and evaluation design.

## 4. System Design

- Architecture and reader protocol.
- Canonical models and data flow.
- EXR inspection and AOV categorisation heuristics.
- RGB normalisation and luminance.
- Frame discovery and sequence model.
- Rule engine and report schema.
- CLI/GUI separation and threading.

## 5. Implementation

- OpenEXR backend decision.
- Frame-first incremental processing.
- Non-finite and channel-level metrics.
- Rules, presets and error isolation.
- JSON/HTML reports.
- GUI progress, findings, per-frame diagnostics and cancellation.

## 6. Evaluation

- Correctness using known synthetic fixtures.
- Coverage baseline and final branch coverage.
- Frame-first benchmark method and results.
- CLI/GUI equivalence.
- Usability evaluation or expert review.
- Reproducibility and CI.

## 7. Critical Discussion

- What the evidence supports and what it does not.
- Performance/memory trade-off.
- Naming and category ambiguity.
- False positives and artistic context.
- Platform, packaging, deep and multipart limitations.
- Threats to validity.

## 8. Conclusion and Future Work

- Contribution against each objective.
- Relevance to Lighting TD and Pipeline TD practice.
- Future pass-specific rules, renderer presets, packaging and DCC integration.

## Appendices

- JSON schema example and preset examples.
- Benchmark command and raw results.
- Test/coverage summary.
- Presentation of any approved evaluation instruments.
