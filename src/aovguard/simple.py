"""Legacy simple RGB/RGBA analyzer retained for compatibility."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np

from aovguard.analysis_core import AOVResult, Thresholds, classify
from aovguard.core.channel_utils import normalize_color_to_rgb
from aovguard.core.luminance import compute_luminance

ProgressCallback = Callable[[int, int, str], None]


def _read_exr(path: Path) -> np.ndarray:
    try:
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    except cv2.error as exc:
        raise RuntimeError(f"Could not read EXR: {path}") from exc
    if img is None:
        raise RuntimeError(f"Could not read EXR: {path}")
    if img.ndim == 2:
        img = np.stack([img, img, img], axis=-1)
    if img.shape[-1] >= 3:
        img = img[..., :3]
    return img.astype(np.float32)


def _compute_metrics(image: np.ndarray) -> tuple[float, float, float]:
    # OpenCV loads RGB/RGBA EXR files as BGR/BGRA. Convert once to the internal
    # RGB convention before computing luminance.
    image_rgb = normalize_color_to_rgb(image, source_order="BGR")
    luminance = compute_luminance(image_rgb)
    non_black_ratio = float(np.count_nonzero(luminance > 1e-5) / luminance.size)
    avg_luminance = float(np.mean(luminance))
    max_luminance = float(np.max(luminance))
    return non_black_ratio, avg_luminance, max_luminance


def _result_from_frames(
    name: str,
    frames: list[Path],
    thresholds: Thresholds,
    *,
    progress_callback: ProgressCallback | None = None,
    progress_offset: int = 0,
    progress_total: int | None = None,
) -> AOVResult:
    """Aggregate one or more simple RGB/RGBA EXR frames into one result row."""

    ratios: list[float] = []
    avgs: list[float] = []
    maxes: list[float] = []
    progress_total = progress_total or len(frames)

    for index, frame in enumerate(frames, start=1):
        image = _read_exr(frame)
        ratio, avg_lum, max_lum = _compute_metrics(image)
        ratios.append(ratio)
        avgs.append(avg_lum)
        maxes.append(max_lum)
        if progress_callback is not None:
            progress_callback(progress_offset + index, progress_total, f"Processed {frame.name}")

    avg_ratio = float(np.mean(ratios))
    avg_luminance = float(np.mean(avgs))
    max_luminance = float(np.max(maxes))

    label, _ = classify(avg_ratio, avg_luminance, max_luminance, thresholds)
    return AOVResult(
        aov_name=name,
        classification=label,
        non_black_ratio=avg_ratio,
        avg_luminance=avg_luminance,
        max_luminance=max_luminance,
    )


def analyze_simple(
    folder: str | Path,
    thresholds: Thresholds | None = None,
    *,
    progress_callback: ProgressCallback | None = None,
) -> list[AOVResult]:
    """Analyze simple RGB/RGBA EXR files.

    Simple mode is intended for normal EXR image outputs that contain channels such
    as R, G, B and A. If EXR files are directly inside the selected folder, each
    file becomes one result row. If the selected folder contains one-level
    subfolders, each subfolder is aggregated into one result row.
    """

    thresholds = thresholds or Thresholds()
    folder = Path(folder)
    if not folder.exists():
        raise FileNotFoundError(folder)
    if not folder.is_dir():
        raise NotADirectoryError(folder)

    direct_frames = sorted(folder.glob("*.exr"))
    if direct_frames:
        results: list[AOVResult] = []
        total = len(direct_frames)
        for index, frame in enumerate(direct_frames):
            results.append(
                _result_from_frames(
                    frame.stem,
                    [frame],
                    thresholds,
                    progress_callback=progress_callback,
                    progress_offset=index,
                    progress_total=total,
                )
            )
        return results

    grouped_frames: list[tuple[str, list[Path]]] = []
    for aov_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
        frames = sorted(aov_dir.glob("*.exr"))
        if frames:
            grouped_frames.append((aov_dir.name, frames))

    total_frames = sum(len(frames) for _, frames in grouped_frames)
    completed = 0
    results = []
    for name, frames in grouped_frames:
        results.append(
            _result_from_frames(
                name,
                frames,
                thresholds,
                progress_callback=progress_callback,
                progress_offset=completed,
                progress_total=total_frames,
            )
        )
        completed += len(frames)

    return results
