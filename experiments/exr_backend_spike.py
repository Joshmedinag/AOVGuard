from __future__ import annotations

import argparse
import json
import os
import time
import tracemalloc
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import Imath
import numpy as np
import OpenEXR

from aovguard.io.inspector import build_file_inspection


@dataclass(slots=True)
class OperationResult:
    supported: bool
    ok: bool
    elapsed_ms: float | None = None
    python_peak_kib: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class BackendResult:
    backend: str
    available: bool
    version: str | None = None
    operations: dict[str, OperationResult] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _timed(operation: Callable[[], dict[str, Any]]) -> OperationResult:
    tracemalloc.start()
    start = time.perf_counter()
    try:
        details = operation()
    except Exception as exc:
        _, peak = tracemalloc.get_traced_memory()
        elapsed = (time.perf_counter() - start) * 1000
        tracemalloc.stop()
        return OperationResult(
            supported=True,
            ok=False,
            elapsed_ms=round(elapsed, 3),
            python_peak_kib=round(peak / 1024, 3),
            error=f"{type(exc).__name__}: {exc}",
        )
    _, peak = tracemalloc.get_traced_memory()
    elapsed = (time.perf_counter() - start) * 1000
    tracemalloc.stop()
    return OperationResult(
        supported=True,
        ok=True,
        elapsed_ms=round(elapsed, 3),
        python_peak_kib=round(peak / 1024, 3),
        details=details,
    )


def _float_channel(value: float, width: int, height: int) -> bytes:
    return (np.ones((height, width), dtype=np.float32) * value).tobytes()


def _write_exr(path: Path, width: int, height: int, channels: dict[str, float]) -> None:
    pixel_type = Imath.PixelType(Imath.PixelType.FLOAT)
    header = OpenEXR.Header(width, height)
    header["channels"] = {name: Imath.Channel(pixel_type) for name in channels}
    output = OpenEXR.OutputFile(str(path), header)
    try:
        output.writePixels(
            {
                name: _float_channel(value, width, height)
                for name, value in channels.items()
            }
        )
    finally:
        output.close()


def create_spike_files(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "rgb": output_dir / "spike_rgb.exr",
        "rgba": output_dir / "spike_rgba.exr",
        "multichannel": output_dir / "spike_multichannel.exr",
    }
    _write_exr(files["rgb"], 4, 3, {"R": 1.0, "G": 2.0, "B": 3.0})
    _write_exr(files["rgba"], 4, 3, {"R": 1.0, "G": 2.0, "B": 3.0, "A": 0.5})
    _write_exr(
        files["multichannel"],
        4,
        3,
        {
            "R": 0.25,
            "G": 0.25,
            "B": 0.25,
            "diffuse.R": 1.0,
            "diffuse.G": 0.5,
            "diffuse.B": 0.25,
            "specular.R": 0.25,
            "specular.G": 0.5,
            "specular.B": 1.0,
            "Z": 10.0,
            "N.X": 0.0,
            "N.Y": 1.0,
            "N.Z": 0.0,
        },
    )
    return files


def _openexr_channels(path: Path) -> tuple[int, int, tuple[str, ...]]:
    exr = OpenEXR.InputFile(str(path))
    try:
        header = exr.header()
        data_window = header["dataWindow"]
        width = data_window.max.x - data_window.min.x + 1
        height = data_window.max.y - data_window.min.y + 1
        channels = tuple(header["channels"].keys())
    finally:
        exr.close()
    return width, height, channels


def _openexr_inspect(path: Path) -> dict[str, Any]:
    width, height, channels = _openexr_channels(path)
    inspection = build_file_inspection(
        path=path,
        width=width,
        height=height,
        channels=channels,
    )
    return {
        "width": width,
        "height": height,
        "channels": list(channels),
        "aovs": [
            {
                "name": aov.name,
                "channels": list(aov.channels),
                "category": aov.category.value,
                "category_confidence": aov.category_confidence,
            }
            for aov in inspection.aovs
        ],
    }


def _openexr_read_named_rgb(path: Path, prefix: str) -> dict[str, Any]:
    exr = OpenEXR.InputFile(str(path))
    try:
        width, height, channels = _openexr_channels(path)
        pixel_type = Imath.PixelType(Imath.PixelType.FLOAT)
        names = [f"{prefix}.{suffix}" for suffix in ("R", "G", "B")]
        arrays = []
        for name in names:
            if name not in channels:
                raise RuntimeError(f"Missing channel {name}")
            arrays.append(np.frombuffer(exr.channel(name, pixel_type), dtype=np.float32))
        stacked = np.stack(arrays, axis=-1).reshape((height, width, 3))
    finally:
        exr.close()
    return {
        "shape": list(stacked.shape),
        "first_pixel_rgb": stacked[0, 0, :].astype(float).tolist(),
    }


def run_openexr(files: dict[str, Path]) -> BackendResult:
    result = BackendResult(
        backend="OpenEXR",
        available=True,
        version=getattr(OpenEXR, "__version__", None),
    )
    result.operations["inspect_multichannel"] = _timed(lambda: _openexr_inspect(files["multichannel"]))
    result.operations["read_named_rgb"] = _timed(
        lambda: _openexr_read_named_rgb(files["multichannel"], "diffuse")
    )
    result.operations["multipart_probe"] = OperationResult(
        supported=False,
        ok=False,
        details={"note": "Not tested by this MVP spike; generated fixtures are single-part."},
    )
    return result


def run_opencv(files: dict[str, Path]) -> BackendResult:
    try:
        import cv2
    except Exception as exc:
        return BackendResult(
            backend="OpenCV",
            available=False,
            notes=[f"Import failed: {type(exc).__name__}: {exc}"],
        )

    result = BackendResult(
        backend="OpenCV",
        available=True,
        version=getattr(cv2, "__version__", None),
    )

    def read_rgb() -> dict[str, Any]:
        image = cv2.imread(str(files["rgb"]), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise RuntimeError("cv2.imread returned None")
        return {
            "shape": list(image.shape),
            "first_pixel_as_loaded": image[0, 0, :].astype(float).tolist(),
            "channel_order_observation": "OpenCV loads this RGB EXR as BGR.",
        }

    def read_multichannel() -> dict[str, Any]:
        image = cv2.imread(str(files["multichannel"]), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise RuntimeError("cv2.imread returned None")
        return {
            "shape": list(image.shape),
            "first_pixel_as_loaded": image[0, 0, :].astype(float).tolist(),
            "note": "OpenCV does not expose named EXR channels through this API.",
        }

    result.operations["read_rgb"] = _timed(read_rgb)
    result.operations["read_multichannel"] = _timed(read_multichannel)
    result.operations["named_channels"] = OperationResult(
        supported=False,
        ok=False,
        details={"note": "cv2.imread returns image arrays but not EXR channel names."},
    )
    return result


def run_openimageio(files: dict[str, Path]) -> BackendResult:
    try:
        import OpenImageIO as oiio
    except Exception as exc:
        return BackendResult(
            backend="OpenImageIO",
            available=False,
            notes=[f"Import failed: {type(exc).__name__}: {exc}"],
        )

    result = BackendResult(
        backend="OpenImageIO",
        available=True,
        version=getattr(oiio, "VERSION_STRING", None),
    )

    def inspect() -> dict[str, Any]:
        image_input = oiio.ImageInput.open(str(files["multichannel"]))
        if image_input is None:
            raise RuntimeError("ImageInput.open returned None")
        try:
            spec = image_input.spec()
            channels = tuple(spec.channelnames)
            inspection = build_file_inspection(
                path=files["multichannel"],
                width=int(spec.width),
                height=int(spec.height),
                channels=channels,
                part_count=1,
                is_deep=bool(getattr(spec, "deep", False)),
            )
            return {
                "width": int(spec.width),
                "height": int(spec.height),
                "nchannels": int(spec.nchannels),
                "channels": list(channels),
                "format": str(spec.format),
                "aovs": [
                    {
                        "name": aov.name,
                        "channels": list(aov.channels),
                        "category": aov.category.value,
                        "category_confidence": aov.category_confidence,
                    }
                    for aov in inspection.aovs
                ],
            }
        finally:
            image_input.close()

    def read_image() -> dict[str, Any]:
        image_input = oiio.ImageInput.open(str(files["rgb"]))
        if image_input is None:
            raise RuntimeError("ImageInput.open returned None")
        try:
            pixels = image_input.read_image(format=oiio.FLOAT)
            array = np.asarray(pixels)
            return {
                "shape": list(array.shape),
                "first_pixel": array.reshape((-1, array.shape[-1]))[0].astype(float).tolist()
                if array.ndim >= 3
                else array.reshape((-1,))[0:3].astype(float).tolist(),
            }
        finally:
            image_input.close()

    result.operations["inspect_multichannel"] = _timed(inspect)
    result.operations["read_rgb"] = _timed(read_image)
    result.operations["image_cache"] = OperationResult(
        supported=True,
        ok=True,
        details={"note": "OpenImageIO exposes ImageCache; not benchmarked in this minimal spike."},
    )
    return result


def _to_jsonable(result: BackendResult) -> dict[str, Any]:
    data = asdict(result)
    data["operations"] = {
        name: asdict(operation)
        for name, operation in result.operations.items()
    }
    return data


def run_spike(output_dir: Path) -> dict[str, Any]:
    files = create_spike_files(output_dir / "fixtures")
    backends = [
        run_openexr(files),
        run_opencv(files),
        run_openimageio(files),
    ]
    return {
        "fixtures": {name: str(path) for name, path in files.items()},
        "backends": [_to_jsonable(result) for result in backends],
        "notes": [
            "Memory is measured with tracemalloc and reflects Python allocations, not full native backend memory.",
            "Timing is a small local smoke benchmark, not a statistically rigorous benchmark.",
            "Generated EXRs are single-part float fixtures intended for backend comparison only.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare candidate EXR reading backends for AOVGuard.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("experiments") / "_spike_output",
        help="Directory for generated EXR fixtures and JSON result.",
    )
    args = parser.parse_args()

    result = run_spike(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "backend_spike_results.json"
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"\nWrote spike results to: {output_path}")


if __name__ == "__main__":
    main()

