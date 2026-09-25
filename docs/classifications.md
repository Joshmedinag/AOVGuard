# Legacy Classification Logic

This document describes the threshold labels produced by the temporary
`analyze-simple` and `analyze-multilayer` compatibility commands. The canonical
AOVGuard 2.0 backend returns metrics and configurable rule findings instead.

AOVGuard classifies each AOV using simple luminance statistics. The goal is not to make a final artistic decision, but to flag passes that should be kept, reviewed, or removed from a publish.

## Metrics

### Non-black ratio

The proportion of pixels with values above the black threshold. A higher value usually means more of the image contains visible information.

### Average luminance

The average brightness of the AOV. This helps detect whether the pass contributes meaningful light overall.

### Max luminance

The brightest value found in the AOV. This helps distinguish completely black AOVs from passes that contain at least a small highlight.

## Labels

### Active

The AOV appears to contain meaningful contribution and is likely useful downstream.

### Review Recommended

The AOV contains some data, but the contribution may be weak or suspicious. In a production pipeline this would be flagged for a lighting artist, compositor, or supervisor to check.

### Nearly Empty

The AOV is close to black. It may be a very subtle pass, but it may also be wasted data.

### Empty

The AOV appears to contain no useful contribution.

## Important limitation

These labels are heuristic. Real productions may require show-specific thresholds, depending on exposure, colour management, render engine, and how light AOVs are authored.
