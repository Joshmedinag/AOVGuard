"""OpenEXR-backed inspection and frame decoding implementation."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Collection, Iterable, Mapping
from urllib.parse import quote

import numpy as np
import OpenEXR

from aovguard.core.memory import enforce_memory_budget
from aovguard.core.models import (
    AOVCategory,
    AOVDescriptor,
    FileInspection,
    FrameData,
    PartInspection,
)
from aovguard.io.inspector import RGB_SUFFIXES, build_file_inspection
from aovguard.io.protocol import ReaderProcessSpec


def _window_coordinates(window: Any) -> tuple[tuple[int, int], tuple[int, int]]:
    """Normalize modern tuple and legacy Imath windows without losing origin."""

    if isinstance(window, tuple):
        minimum, maximum = window
        return (int(minimum[0]), int(minimum[1])), (int(maximum[0]), int(maximum[1]))
    return (int(window.min.x), int(window.min.y)), (int(window.max.x), int(window.max.y))


def _size_from_header(header: Mapping[str, Any]) -> tuple[int, int]:
    """Return stored pixel dimensions, which always follow dataWindow."""

    minimum, maximum = _window_coordinates(header["dataWindow"])
    return maximum[0] - minimum[0] + 1, maximum[1] - minimum[1] + 1


def _suffix(channel: str) -> str:
    suffix = channel.rsplit(".", 1)[-1]
    return RGB_SUFFIXES.get(suffix.lower(), suffix.upper())


def _channels_by_suffix(channels: Iterable[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for channel in channels:
        mapping.setdefault(_suffix(channel), channel)
    return mapping


def _ordered_channels(
    descriptor: AOVDescriptor,
    suffixes: tuple[str, ...],
) -> tuple[str, ...]:
    by_suffix = _channels_by_suffix(descriptor.channels)
    missing = [suffix for suffix in suffixes if suffix not in by_suffix]
    if missing:
        raise RuntimeError(
            f"AOV {descriptor.name!r} is missing channel suffix(es): {', '.join(missing)}"
        )
    return tuple(by_suffix[suffix] for suffix in suffixes)


def _metadata_text(value: object) -> str | None:
    """Read textual EXR metadata without inventing identities for missing values."""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace") or None
    return value if isinstance(value, str) and value else None


def _cryptomatte_names(header: Mapping[str, Any]) -> tuple[str, ...]:
    cryptomatte_names: list[str] = []
    for key, value in header.items():
        if not re.fullmatch(r"cryptomatte/[^/]+/name", str(key)):
            continue
        name = _metadata_text(value)
        if name is not None and name.strip():
            cryptomatte_names.append(name.strip())
    return tuple(cryptomatte_names)


def _escaped_identity(value: str) -> str:
    """Encode delimiter characters injectively while keeping ordinary EXR names readable."""

    return quote(value, safe="-_. ")


def _part_namespace(index: int, name: str | None, name_counts: Mapping[str, int]) -> str:
    if name is None:
        return f"[part-index:{index}]::"
    escaped = _escaped_identity(name)
    if name_counts[name] > 1:
        return f"[part-index:{index}:{escaped}]::"
    return f"[part:{escaped}]::"


def _inspection_from_file(exr: Any, path: Path) -> FileInspection:
    """Inspect every part, qualifying multipart identities and retaining raw metadata.

    A named multipart part uses ``[part:NAME]::AOV`` independently of its file
    position. Missing or duplicate names use their physical part index. Percent
    escaping prevents raw names containing delimiters from colliding with
    qualified identities. Single-part AOV and channel keys remain unchanged.
    """

    if not exr.parts:
        raise RuntimeError(f"EXR contains no image parts: {path}")

    names = tuple(_metadata_text(part.header.get("name")) for part in exr.parts)
    name_counts = Counter(name for name in names if name is not None)
    multipart = len(exr.parts) > 1
    deep_types = {OpenEXR.deepscanline, OpenEXR.deeptile}
    parts: list[PartInspection] = []
    all_channels: list[str] = []
    all_aovs: list[AOVDescriptor] = []
    first_inspection: FileInspection | None = None
    for index, part in enumerate(exr.parts):
        header = part.header
        width, height = _size_from_header(header)
        raw_channels = tuple(channel.name for channel in header["channels"])
        data_window = _window_coordinates(header["dataWindow"])
        display_window = _window_coordinates(header.get("displayWindow", header["dataWindow"]))
        base = build_file_inspection(
            path=path,
            width=width,
            height=height,
            channels=raw_channels,
            is_deep=part.type() in deep_types,
            cryptomatte_names=_cryptomatte_names(header),
            data_window=data_window,
            display_window=display_window,
        )
        if first_inspection is None:
            first_inspection = base
        namespace = _part_namespace(index, names[index], name_counts) if multipart else ""
        descriptors = tuple(
            replace(
                descriptor,
                name=namespace + _escaped_identity(descriptor.name),
                channels=tuple(namespace + _escaped_identity(channel) for channel in descriptor.channels),
                part_index=index,
                original_name=descriptor.name,
                original_channels=descriptor.channels,
            )
            if multipart else descriptor
            for descriptor in base.aovs
        )
        parts.append(PartInspection(
            index=index,
            name=names[index] or "",
            width=width,
            height=height,
            channels=raw_channels,
            aovs=descriptors,
            is_deep=base.is_deep,
            data_window=data_window,
            display_window=display_window,
            view=_metadata_text(header.get("view")),
        ))
        all_channels.extend(namespace + _escaped_identity(channel) if multipart else channel for channel in raw_channels)
        all_aovs.extend(descriptors)

    if len({descriptor.name for descriptor in all_aovs}) != len(all_aovs):
        raise RuntimeError("EXR parts produced duplicate AOV identities.")
    if len(set(all_channels)) != len(all_channels):
        raise RuntimeError("EXR parts produced duplicate channel identities.")
    assert first_inspection is not None
    return replace(
        first_inspection,
        channels=tuple(all_channels),
        aovs=tuple(all_aovs),
        part_count=len(parts),
        is_deep=any(part.is_deep for part in parts),
        parts=tuple(parts),
    )


class OpenEXRReader:
    """OpenEXR-backed reader implementing the EXRReader protocol."""

    def __init__(
        self,
        category_overrides: Mapping[str, AOVCategory | str] | None = None,
    ) -> None:
        """Create a reader with case-insensitive category overrides.

        A qualified multipart key overrides exactly that AOV. An original AOV
        name applies to every matching part; qualified keys take precedence.
        """

        self._category_overrides = {
            str(name).casefold(): (
                category
                if isinstance(category, AOVCategory)
                else AOVCategory(str(category).lower())
            )
            for name, category in (category_overrides or {}).items()
        }

    def process_spec(self) -> ReaderProcessSpec:
        """Snapshot this native reader for spawn without losing preset categories.

        Subclasses must provide their own supported process configuration instead
        of silently substituting the native reader for overridden behavior.
        """

        if type(self) is not OpenEXRReader:
            raise ValueError("Custom OpenEXRReader subclasses must define their own process spec.")
        return ReaderProcessSpec(
            category_overrides=tuple(
                (name, category.value) for name, category in sorted(self._category_overrides.items())
            ),
        )

    def _apply_category_overrides(self, inspection: FileInspection) -> FileInspection:
        if not self._category_overrides:
            return inspection
        descriptors: list[AOVDescriptor] = []
        for descriptor in inspection.aovs:
            category = self._category_overrides.get(descriptor.name.casefold())
            if category is None and descriptor.original_name is not None:
                category = self._category_overrides.get(descriptor.original_name.casefold())
            descriptors.append(
                replace(descriptor, category=category, category_confidence="preset_override")
                if category is not None else descriptor
            )
        by_name = {descriptor.name: descriptor for descriptor in descriptors}
        return replace(
            inspection,
            aovs=tuple(descriptors),
            parts=tuple(
                replace(part, aovs=tuple(by_name[descriptor.name] for descriptor in part.aovs))
                for part in inspection.parts
            ),
        )

    def inspect(self, path: Path) -> FileInspection:
        """Read EXR header structure without decoding pixel arrays."""

        exr_path = Path(path)
        exr = OpenEXR.File(
            str(exr_path),
            separate_channels=True,
            header_only=True,
        )
        return self._apply_category_overrides(_inspection_from_file(exr, exr_path))

    def read_frame(
        self,
        path: Path,
        requested_aovs: Collection[str] | None = None,
    ) -> FrameData:
        """Decode a flat frame with exact per-channel data and selected AOV views.

        Structure is inspected before pixel decoding so unsupported deep files
        do not allocate image buffers. Flat multipart AOVs use qualified keys
        and each part's own stored window. ``requested_aovs``
        selects semantic AOV views; ``channel_data`` always retains every exact
        channel for integrity checks, including alpha and auxiliary data.
        """

        return self._read_frame(path, requested_aovs=requested_aovs)

    def read_frame_with_memory_budget(self, path: Path, max_memory_mb: float) -> FrameData:
        """Check this read's own header before allocating native pixel buffers.

        The estimate covers all physical channels and parts, not a selected
        subset. It is a preventive estimate rather than an operating-system
        memory cap. Rechecking here avoids relying on an earlier inspection
        that may no longer describe the input file.
        """

        return self._read_frame(path, max_memory_mb=max_memory_mb)

    def _read_frame(
        self,
        path: Path,
        requested_aovs: Collection[str] | None = None,
        *,
        max_memory_mb: float | None = None,
    ) -> FrameData:
        exr_path = Path(path)
        inspection = self.inspect(exr_path)
        if inspection.unsupported_reason is not None:
            return FrameData(
                path=exr_path,
                width=inspection.width,
                height=inspection.height,
                inspection=inspection,
                channels=inspection.channels,
                aovs={},
            )

        if max_memory_mb is not None:
            enforce_memory_budget(inspection, max_memory_mb)

        requested = set(requested_aovs) if requested_aovs is not None else None
        descriptors: dict[str, AOVDescriptor] = {}
        for descriptor in inspection.aovs:
            if descriptor.name in descriptors:
                raise RuntimeError(f"Duplicate AOV name in inspection: {descriptor.name!r}")
            if requested is None or descriptor.name in requested:
                descriptors[descriptor.name] = descriptor

        if requested is not None:
            missing = sorted(requested - set(descriptors))
            if missing:
                raise RuntimeError(f"Requested AOV(s) not found: {', '.join(missing)}")

        exr = OpenEXR.File(str(exr_path), separate_channels=True)
        decoded_inspection = self._apply_category_overrides(_inspection_from_file(exr, exr_path))
        if (
            decoded_inspection.unsupported_reason is not None
            or decoded_inspection.part_count != inspection.part_count
            or decoded_inspection.parts != inspection.parts
            or decoded_inspection.channels != inspection.channels
            or decoded_inspection.data_window != inspection.data_window
            or decoded_inspection.display_window != inspection.display_window
            or decoded_inspection.aovs != inspection.aovs
        ):
            raise RuntimeError("EXR structure changed or was partially decoded after header inspection.")
        channel_data: dict[str, np.ndarray] = {}
        part_channel_data: dict[int, dict[str, np.ndarray]] = {}
        for part_inspection in inspection.parts:
            raw_keys = {
                original: qualified
                for descriptor in part_inspection.aovs
                for original, qualified in zip(
                    descriptor.original_channels or descriptor.channels, descriptor.channels,
                )
            }
            if set(raw_keys) != set(part_inspection.channels):
                raise RuntimeError("EXR channel descriptors do not cover every source channel.")
            raw_data = {
                channel: self._read_channel(
                    exr.parts[part_inspection.index], channel,
                    part_inspection.width, part_inspection.height,
                )
                for channel in part_inspection.channels
            }
            part_channel_data[part_inspection.index] = raw_data
            channel_data.update((raw_keys[channel], pixels) for channel, pixels in raw_data.items())
        aovs = {
            name: self._read_descriptor(
                exr.parts[descriptor.part_index],
                replace(descriptor, channels=descriptor.original_channels or descriptor.channels),
                inspection.parts[descriptor.part_index].width,
                inspection.parts[descriptor.part_index].height,
                channel_data=part_channel_data[descriptor.part_index],
            )
            for name, descriptor in descriptors.items()
        }

        return FrameData(
            path=exr_path,
            width=inspection.width,
            height=inspection.height,
            inspection=inspection,
            channels=inspection.channels,
            aovs=aovs,
            channel_data=channel_data,
        )

    def _read_channel(
        self,
        part: Any,
        channel_name: str,
        width: int,
        height: int,
    ) -> np.ndarray:
        try:
            pixels = part.channels[channel_name].pixels
        except KeyError as exc:
            raise RuntimeError(f"EXR channel not found: {channel_name}") from exc
        # UINT channels often contain IDs and must remain integer-exact.
        # FLOAT arrays are reused; only HALF needs promotion for calculations.
        # Higher precision floating sources are preserved as well.
        array = np.asarray(pixels)
        if np.issubdtype(array.dtype, np.floating) and array.dtype.itemsize < 4:
            array = array.astype(np.float32)
        if array.shape != (height, width):
            raise RuntimeError(
                f"Channel {channel_name!r} has unsupported sampled shape "
                f"{array.shape}; expected {(height, width)}."
            )
        return array

    def _read_descriptor(
        self,
        part: Any,
        descriptor: AOVDescriptor,
        width: int,
        height: int,
        *,
        channel_data: Mapping[str, np.ndarray] | None = None,
    ) -> np.ndarray:
        def read(channel: str) -> np.ndarray:
            if channel_data is not None:
                return channel_data[channel]
            return self._read_channel(part, channel, width, height)

        if descriptor.category is AOVCategory.COLOR:
            channels = _ordered_channels(descriptor, ("R", "G", "B"))
            return np.stack(
                [read(channel) for channel in channels],
                axis=-1,
            )

        if descriptor.category is AOVCategory.VECTOR:
            suffixes = {_suffix(channel) for channel in descriptor.channels}
            order = next(
                (
                    candidate
                    for candidate in (("X", "Y", "Z"), ("X", "Y"), ("U", "V"), ("R", "G", "B"))
                    if set(candidate).issubset(suffixes)
                ),
                ("R", "G", "B"),
            )
            channels = _ordered_channels(descriptor, order)
            return np.stack(
                [read(channel) for channel in channels],
                axis=-1,
            )

        if (
            descriptor.category
            in {
                AOVCategory.DEPTH,
                AOVCategory.MASK,
                AOVCategory.SCALAR,
            }
            and len(descriptor.channels) > 1
        ):
            return np.stack(
                [
                    read(channel)
                    for channel in descriptor.channels
                ],
                axis=-1,
            )

        if len(descriptor.channels) == 1:
            return read(descriptor.channels[0])

        if descriptor.category in {
            AOVCategory.UNKNOWN,
            AOVCategory.IGNORED,
            AOVCategory.CRYPTOMATTE,
        }:
            return np.stack(
                [
                    read(channel)
                    for channel in descriptor.channels
                ],
                axis=-1,
            )

        raise RuntimeError(f"AOV {descriptor.name!r} has unsupported channel structure.")
