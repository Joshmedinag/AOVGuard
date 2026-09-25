"""Human-readable remediation guidance for validation findings."""

from __future__ import annotations

from aovguard.core.models import Finding

_RECOMMENDATIONS = {
    "unknown_aov": "Review the channel purpose and classify this AOV with the preset aov_categories table when its semantics are known.",
    "nan_inf": "Inspect the source render and upstream shader calculations; replace or rerender non-finite pixels before delivery.",
    "empty_aov": "Confirm that the pass is expected to be empty. Remove it from the delivery or correct its render contribution.",
    "near_empty_aov": "Review whether the small contribution is intentional and whether the AOV is useful for compositing.",
    "negative_values": "Check the AOV type and workflow before changing values; negatives can be valid in technical or scene-linear data.",
    "extreme_values": "Confirm the expected numeric range for this pass and inspect upstream shaders, units or transforms before delivery.",
    "constant_channel": "Confirm that a constant channel is intentional, especially for masks and utility passes.",
    "missing_aov": "Enable the required AOV in the renderer or update the delivery preset when the pass is intentionally absent.",
    "missing_channels": "Verify the render output definition and ensure the expected channels are written to every frame.",
    "resolution_mismatch": "Rerender or replace the affected frame so the complete sequence has a consistent data window.",
    "aov_structure_mismatch": "Compare render output settings across frames and regenerate frames with inconsistent AOVs or channels.",
    "sequence_gap": "Locate or rerender the missing frames before publishing the sequence.",
    "duplicate_frame": "Remove or rename the duplicate file after confirming which frame is the correct delivery.",
    "inconsistent_padding": "Rename the sequence to use one frame-padding convention throughout.",
    "read_frame": "Verify that the file exists, is a valid EXR and is not truncated or locked by another process.",
    "unsupported_structure": "Convert the file to a supported scanline or tiled single-part EXR, or use a compatible inspection backend.",
    "rule_error": "Review the rule configuration and parameters; the affected validation rule did not complete.",
}


def finding_recommendation(finding: Finding) -> str:
    """Return practical next-step guidance for a finding."""

    return _RECOMMENDATIONS.get(
        finding.rule_id,
        "Review the reported file, AOV and metrics in the context of the delivery requirements.",
    )
