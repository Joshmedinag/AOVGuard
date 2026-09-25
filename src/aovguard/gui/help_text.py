"""Central contextual help text for AOVGuard GUI controls and results."""

from __future__ import annotations

from collections.abc import Collection

from aovguard.core.models import AOVCategory

AOV_CATEGORY_TOOLTIPS = {
    AOVCategory.COLOR: (
        "Color AOV: an RGB-like render pass that can be evaluated with color "
        "luminance when the required channels are present."
    ),
    AOVCategory.SCALAR: (
        "Scalar AOV: one numerical value per pixel. It is diagnosed per channel "
        "and is not treated as color."
    ),
    AOVCategory.VECTOR: (
        "Vector AOV: multi-component directional or positional data. Negative "
        "values can be valid and color luminance does not apply."
    ),
    AOVCategory.MASK: (
        "Mask AOV: a matte or selection value. Black, white or constant values "
        "may be intentional depending on the shot."
    ),
    AOVCategory.DEPTH: (
        "Depth AOV: a renderer-defined distance or depth value. It is diagnosed "
        "numerically and is not treated as color."
    ),
    AOVCategory.CRYPTOMATTE: (
        "Cryptomatte AOV: encoded object/material IDs and coverage. Channels "
        "remain available for integrity checks, but ID values are not color "
        "and are excluded from luminance and temporal outlier statistics."
    ),
    AOVCategory.UNKNOWN: (
        "Unknown AOV: AOVGuard could not infer a reliable semantic category. "
        "Review its channels or override its type in a preset."
    ),
    AOVCategory.IGNORED: (
        "Ignored AOV: a user explicitly chose not to assign color or technical "
        "semantics. Its channels remain visible and retain integrity diagnostics."
    ),
}

SEVERITY_TOOLTIPS = {
    "error": "Error: a strong validation failure that should normally block delivery.",
    "warning": "Warning: a condition that needs review but may be valid for the shot.",
    "info": "Info: diagnostic evidence provided without declaring a failure.",
}

LUMINANCE_MODEL_TOOLTIPS = {
    "Rec.709": (
        "Rec.709 luminance uses 0.2126 R + 0.7152 G + 0.0722 B. "
        "This is the default model for color AOV metrics."
    ),
    "Rec.601": (
        "Rec.601 luminance uses 0.299 R + 0.587 G + 0.114 B. "
        "Choose it when this weighting matches the evaluation requirement."
    ),
    "Custom": (
        "Custom luminance uses the R, G and B weights entered beside this menu. "
        "Weights must be finite and have a positive total."
    ),
}

TABLE_HEADER_TOOLTIPS = {
    "Severity": "Importance assigned to the validation finding: error, warning or info.",
    "Rule": "Identifier of the validation rule that produced the finding.",
    "AOV": "Arbitrary Output Variable, also called a render pass.",
    "Channel": "Named component stored in the EXR, such as R, G, B, X, Y or Z.",
    "Message": "Human-readable explanation of the detected condition.",
    "File": "EXR file associated with this row. Double-click supported paths to open their folder.",
    "Category": "Approximate AOV type inferred from channel structure and naming.",
    "Non-black Ratio": "Fraction of analyzed pixels considered non-black by the configured threshold.",
    "Average Luminance": "Mean luminance of finite pixels using the selected RGB weighting model.",
    "Max Luminance": "Highest finite luminance measured in the analyzed pixels.",
    "Median": "Median of the per-sample average luminance values for this AOV.",
    "MAD": "Median absolute deviation, a robust measure of variation around the median.",
    "Outliers": "Number of samples flagged as robust luminance outliers when enough samples exist.",
    "Channels": "EXR channels grouped into this AOV.",
    "NaN": "Count of pixels containing Not-a-Number values.",
    "+Inf": "Count of pixels containing positive infinity.",
    "-Inf": "Count of pixels containing negative infinity.",
    "Median Change": "Percentage difference between this sample and the AOV set median.",
    "Previous Change": "Percentage difference from the previous discovered sample.",
    "Minimum": "Lowest finite value measured in this technical channel.",
    "Average": "Mean finite value measured in this technical channel.",
    "Maximum": "Highest finite value measured in this technical channel.",
    "Negative": "Number of finite values below zero. This can be valid for vector data.",
    "Pattern": "Detected numbered-sequence pattern, with frame digits represented by #.",
    "Directory": "Folder containing the detected sequence.",
    "Range": "Lowest and highest detected frame numbers.",
    "Present": "Number of unique frame numbers currently present.",
    "Missing": "Frame numbers absent between the detected start and end frames.",
    "Duplicates": "Frame numbers represented by more than one file.",
    "Padding": "Digit widths used by frame numbers, such as 4 for 1001.",
    "Status": "Whether this AOV is unchanged, changed, new or missing relative to the baseline report.",
    "Average Delta": "Current average luminance minus baseline average luminance.",
    "Activity Delta": "Current non-black ratio minus baseline non-black ratio.",
    "Maximum Delta": "Current maximum luminance minus baseline maximum luminance.",
}

TABLE_VIEW_TOOLTIPS = {
    "findings": "Validation findings produced by the enabled rules.",
    "metrics": "Aggregate color-AOV statistics and a selectable luminance-over-frames chart.",
    "frames": "Per-file or per-frame color-AOV metrics and changes between samples.",
    "technical": "Per-channel diagnostics for vector, scalar, mask, depth and Cryptomatte AOVs.",
    "sequences": "Numbered-sequence discovery, missing frames, duplicates and padding.",
    "comparison": "Metric differences between the current result and a saved baseline JSON report.",
    "outliers": "Robust luminance outliers with direct navigation to the corresponding frame.",
}

TAB_TOOLTIPS = {
    "findings": "Review validation errors, warnings and informational findings.",
    "metrics": "Review aggregate metrics and luminance changes across frames for the selected color AOV.",
    "frames": "Review each processed frame or independent comparison sample.",
    "technical": "Review non-color AOVs as objective per-channel numerical data.",
    "sequences": "Review how files were discovered and whether numbered sequences are complete.",
    "comparison": "Compare the current analysis with a previously exported AOVGuard JSON report.",
    "outliers": "Review robust luminance outliers and jump directly to their frame evidence.",
}

STATUS_TOOLTIPS = {
    "pass": "PASS: no enabled validation rule produced a warning or error.",
    "warning": "WARNING: at least one condition needs review, but no error was produced.",
    "fail": "FAIL: an error-level finding or analysis failure was detected.",
    "running": "RUNNING: AOVGuard is currently reading and validating the selected source.",
    "cancelled": "The analysis was cancelled or is finishing the current frame before stopping.",
    "neutral": "No completed analysis result is currently available.",
}


def category_tooltip(category: AOVCategory | str) -> str:
    """Return contextual help for a semantic AOV category."""

    try:
        resolved = category if isinstance(category, AOVCategory) else AOVCategory(category)
    except (TypeError, ValueError):
        resolved = AOVCategory.UNKNOWN
    return AOV_CATEGORY_TOOLTIPS[resolved]


def _specific_aov_description(name: str, category: AOVCategory) -> str:
    normalized = name.casefold().replace("-", "_").replace(" ", "_")
    if category is AOVCategory.CRYPTOMATTE:
        return "Encoded Cryptomatte ID/coverage layer; numerical ID magnitude is not luminance."
    if normalized in {"beauty", "rgba", "combined", "main"}:
        return "Combined rendered image containing the final visible lighting result."
    if "albedo" in normalized or "basecolor" in normalized or "base_color" in normalized:
        return "Surface base color contribution, normally separated from scene lighting."
    if "diffuse_direct" in normalized or "direct_diffuse" in normalized:
        return "Direct diffuse illumination contribution from light sources."
    if "diffuse_indirect" in normalized or "indirect_diffuse" in normalized:
        return "Indirect diffuse illumination, such as bounced light."
    if "specular_direct" in normalized or "direct_specular" in normalized:
        return "Direct specular reflection or highlight contribution."
    if "specular_indirect" in normalized or "indirect_specular" in normalized:
        return "Indirect specular reflection contribution."
    if "emission" in normalized or "emissive" in normalized:
        return "Light contribution emitted directly by emissive materials or geometry."
    if normalized in {"n", "normal", "normals"} or "normal" in normalized:
        return (
            "Surface normal vector; component meaning and coordinate space depend on the renderer."
        )
    if normalized in {"p", "position", "position_world"} or "position" in normalized:
        return "Three-dimensional position data; coordinate space depends on the renderer."
    if normalized in {"z", "depth", "depth_z"} or normalized.endswith("_depth"):
        return "Scene depth or camera-distance data; units and direction depend on the renderer."
    if "mask" in normalized or "matte" in normalized or normalized in {"alpha", "a"}:
        return "Mask or matte data used to isolate part of the image."
    return AOV_CATEGORY_TOOLTIPS[category]


def aov_tooltip(
    name: str,
    category: AOVCategory | str = AOVCategory.UNKNOWN,
    channels: Collection[str] = (),
) -> str:
    """Describe an AOV using its name, category and exact channels."""

    try:
        resolved = category if isinstance(category, AOVCategory) else AOVCategory(category)
    except (TypeError, ValueError):
        resolved = AOVCategory.UNKNOWN
    channel_text = ", ".join(channels) if channels else "not available"
    return (
        f"{name}: {_specific_aov_description(name, resolved)}\n"
        f"Category: {resolved.value}. {AOV_CATEGORY_TOOLTIPS[resolved]}\n"
        f"Channels: {channel_text}."
    )
