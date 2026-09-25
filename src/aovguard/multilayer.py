"""Legacy multilayer EXR analyzer retained for command compatibility."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

import Imath
import numpy as np
import OpenEXR

from aovguard.analysis_core import AOVResult, Thresholds, classify
from aovguard.core.luminance import compute_luminance

RGB_SUFFIXES = {"R", "G", "B"}
ProgressCallback = Callable[[int, int, str], None]


def inspect_exr(path: str | Path) -> str:
    """Return a legacy human-readable summary of multilayer channels."""

    path = Path(path)
    exr = OpenEXR.InputFile(str(path))
    try:
        header = exr.header()
        dw = header["dataWindow"]
        width = dw.max.x - dw.min.x + 1
        height = dw.max.y - dw.min.y + 1

        lines = [
            f"EXR file: {path}",
            f"Part size: {width}x{height}",
            "",
            "Channels:",
        ]
        for ch in header["channels"].keys():
            lines.append(f"  - {ch}")

        groups: dict[str, list[str]] = {}
        for ch in header["channels"].keys():
            if "." not in ch:
                continue
            prefix, suffix = ch.rsplit(".", 1)
            groups.setdefault(prefix, []).append(ch)

        lines.append("")
        lines.append("Detected RGB AOV groups:")
        for name, channels in sorted(groups.items()):
            rgb = [f"{name}.R", f"{name}.G", f"{name}.B"]
            if all(c in channels for c in rgb):
                lines.append(f"  - {name}: {rgb}")

        return "\n".join(lines)
    finally:
        exr.close()


def _get_size_from_header(header: Mapping[str, Any]) -> tuple[int, int]:
    dw = header["dataWindow"]
    width = dw.max.x - dw.min.x + 1
    height = dw.max.y - dw.min.y + 1
    return width, height


def _list_rgb_aovs(exr_path: Path) -> list[str]:
    exr = OpenEXR.InputFile(str(exr_path))
    try:
        header = exr.header()
        channels = list(header["channels"].keys())
    finally:
        exr.close()

    groups: dict[str, set[str]] = {}
    for ch in channels:
        if "." not in ch:
            continue
        prefix, suffix = ch.rsplit(".", 1)
        if suffix in RGB_SUFFIXES:
            groups.setdefault(prefix, set()).add(suffix)

    return sorted(name for name, suffixes in groups.items() if RGB_SUFFIXES.issubset(suffixes))


def _read_rgb_aov(exr_path: Path, aov_name: str) -> np.ndarray:
    exr = OpenEXR.InputFile(str(exr_path))
    try:
        header = exr.header()
        width, height = _get_size_from_header(header)

        pixel_type = Imath.PixelType(Imath.PixelType.FLOAT)

        channels = []
        for suffix in ("R", "G", "B"):
            channel_name = f"{aov_name}.{suffix}"
            if channel_name not in header["channels"]:
                raise RuntimeError(f"Missing channel {channel_name} in {exr_path}")
            raw = exr.channel(channel_name, pixel_type)
            arr = np.frombuffer(raw, dtype=np.float32).reshape((height, width))
            channels.append(arr)

        return np.stack(channels, axis=-1)
    finally:
        exr.close()


def _compute_metrics(image: np.ndarray) -> tuple[float, float, float]:
    luminance = compute_luminance(image)
    non_black_ratio = float(np.count_nonzero(luminance > 1e-5) / luminance.size)
    avg_luminance = float(np.mean(luminance))
    max_luminance = float(np.max(luminance))
    return non_black_ratio, avg_luminance, max_luminance


def analyze_multilayer(
    folder: str | Path,
    thresholds: Thresholds | None = None,
    *,
    progress_callback: ProgressCallback | None = None,
) -> list[AOVResult]:
    """Analyze legacy RGB AOV groups across direct child EXR files."""

    thresholds = thresholds or Thresholds()
    folder = Path(folder)
    if not folder.exists():
        raise FileNotFoundError(f"Input folder does not exist: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Input path is not a folder: {folder}")

    exr_files = sorted(folder.glob("*.exr"))
    if not exr_files:
        raise FileNotFoundError(f"No EXR files found in {folder}")

    aov_names = _list_rgb_aovs(exr_files[0])
    if not aov_names:
        raise RuntimeError("No RGB AOV groups found in the EXR files.")

    results: list[AOVResult] = []
    total_steps = len(aov_names) * len(exr_files)
    completed_steps = 0

    for aov in aov_names:
        ratios = []
        avgs = []
        maxes = []

        for exr_path in exr_files:
            image = _read_rgb_aov(exr_path, aov)
            ratio, avg_lum, max_lum = _compute_metrics(image)
            ratios.append(ratio)
            avgs.append(avg_lum)
            maxes.append(max_lum)
            completed_steps += 1
            if progress_callback is not None:
                progress_callback(
                    completed_steps,
                    total_steps,
                    f"Processed {aov} in {exr_path.name}",
                )

        avg_ratio = float(np.mean(ratios))
        avg_luminance = float(np.mean(avgs))
        max_luminance = float(np.max(maxes))

        label, _ = classify(avg_ratio, avg_luminance, max_luminance, thresholds)
        results.append(
            AOVResult(
                aov_name=aov,
                classification=label,
                non_black_ratio=avg_ratio,
                avg_luminance=avg_luminance,
                max_luminance=max_luminance,
            )
        )
    return results
