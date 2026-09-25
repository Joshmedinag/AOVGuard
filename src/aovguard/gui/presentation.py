"""Pure presentation helpers shared by Qt views and their tests."""

from __future__ import annotations

import math
from pathlib import Path


def display_path(path: str | Path, source: str | Path) -> str:
    """Return a compact source-relative path for result tables."""

    item_path = Path(path)
    source_path = Path(source)
    if item_path == source_path:
        return item_path.name or str(item_path)
    base = source_path.parent if source_path.suffix.lower() == ".exr" else source_path
    try:
        relative = item_path.relative_to(base)
    except ValueError:
        return item_path.name or str(item_path)
    return str(relative)


def format_percentage_change(current: float, baseline: float) -> str:
    """Format a stable percentage while suppressing negative zero."""

    if current == baseline:
        return "0.00%"
    if baseline == 0.0:
        return "new activity"
    change = ((current - baseline) / abs(baseline)) * 100.0
    if math.isclose(change, 0.0, abs_tol=0.005):
        return "0.00%"
    return f"{change:+.2f}%"


def format_technical_value(value: float) -> str:
    """Keep very large encoded-ID values compact in the technical table."""

    magnitude = abs(value)
    if magnitude >= 1e8 or (0 < magnitude < 1e-4):
        return f"{value:.6e}"
    return f"{value:.6f}"


def finding_source_label(file_count: int, has_explicit_file: bool) -> str:
    """Return a compact aggregate source label for finding tables."""

    if has_explicit_file:
        return ""
    if file_count > 1:
        return f"{file_count} files"
    return "Selected source"
