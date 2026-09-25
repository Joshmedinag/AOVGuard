"""Legacy luminance classification models retained for compatibility."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Thresholds:
    """Threshold values used to classify an AOV contribution.

    The defaults are intentionally conservative starting values. Real productions may
    need to adjust these values per show, renderer, colour pipeline, or AOV type.
    """

    empty_max_luminance: float = 1e-5
    empty_max_average: float = 1e-6
    nearly_empty_max_ratio: float = 0.02
    nearly_empty_max_average: float = 0.001
    review_max_ratio: float = 0.05
    review_max_average: float = 0.01

    def as_dict(self) -> dict[str, float]:
        """Return thresholds as a JSON-serializable mapping."""

        return asdict(self)


@dataclass(slots=True)
class AOVResult:
    """Aggregated validation result for one AOV across a sequence."""

    aov_name: str
    classification: str
    non_black_ratio: float
    avg_luminance: float
    max_luminance: float


def classify(
    non_black_ratio: float,
    avg_luminance: float,
    max_luminance: float,
    thresholds: Thresholds | None = None,
) -> tuple[str, str]:
    """Classify an AOV using simple luminance-based heuristics."""

    thresholds = thresholds or Thresholds()

    if not all(math.isfinite(value) for value in (non_black_ratio, avg_luminance, max_luminance)):
        return "Review Recommended", "Invalid numeric metric detected."

    if (
        max_luminance <= thresholds.empty_max_luminance
        and avg_luminance <= thresholds.empty_max_average
    ):
        return "Empty", "No visible contribution detected."

    if (
        non_black_ratio <= thresholds.nearly_empty_max_ratio
        and avg_luminance <= thresholds.nearly_empty_max_average
    ):
        return "Nearly Empty", "Very small contribution detected."

    if (
        non_black_ratio <= thresholds.review_max_ratio
        and avg_luminance <= thresholds.review_max_average
    ):
        return "Review Recommended", "Contribution is limited and should be reviewed."

    return "Active", "Meaningful contribution detected."


def make_summary(results: list[AOVResult]) -> dict[str, int]:
    """Return counts per classification for a result list."""

    summary = {"Empty": 0, "Nearly Empty": 0, "Review Recommended": 0, "Active": 0}
    for result in results:
        summary[result.classification] = summary.get(result.classification, 0) + 1
    return summary


def build_report_payload(
    results: list[AOVResult],
    *,
    input_folder: str | Path | None = None,
    mode: str | None = None,
    thresholds: Thresholds | None = None,
    frames_analyzed: int | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a structured report payload suitable for JSON output."""

    metadata: dict[str, Any] = {
        "tool": "AOVGuard",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "summary": make_summary(results),
        "aovs_analyzed": len(results),
    }
    if input_folder is not None:
        metadata["input_folder"] = str(Path(input_folder))
    if mode is not None:
        metadata["mode"] = mode
    if frames_analyzed is not None:
        metadata["frames_analyzed"] = frames_analyzed
    if thresholds is not None:
        metadata["thresholds"] = thresholds.as_dict()
    if extra_metadata:
        metadata.update(extra_metadata)

    return {
        "metadata": metadata,
        "results": [asdict(r) for r in results],
    }


def write_json(
    results: list[AOVResult],
    output_path: str | Path,
    *,
    input_folder: str | Path | None = None,
    mode: str | None = None,
    thresholds: Thresholds | None = None,
    frames_analyzed: int | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    """Write a JSON report with metadata and AOV results."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_report_payload(
        results,
        input_folder=input_folder,
        mode=mode,
        thresholds=thresholds,
        frames_analyzed=frames_analyzed,
        extra_metadata=extra_metadata,
    )
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def write_csv(results: list[AOVResult], output_path: str | Path) -> None:
    """Write a compact CSV report for spreadsheet review."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["aov_name", "classification", "non_black_ratio", "avg_luminance", "max_luminance"]
        )
        for r in results:
            writer.writerow(
                [r.aov_name, r.classification, r.non_black_ratio, r.avg_luminance, r.max_luminance]
            )
