"""Infer AOV descriptors and semantic categories from EXR channel names."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Iterable

from aovguard.core.models import AOVCategory, AOVDescriptor, FileInspection

RGB_SUFFIXES = {"r": "R", "red": "R", "g": "G", "green": "G", "b": "B", "blue": "B"}
VECTOR_SUFFIXES = {"x", "y", "z"}
ALPHA_SUFFIXES = {"a", "alpha"}
DEPTH_NAMES = {"z", "depth", "depthz"}
VECTOR_NAMES = {"n", "normal", "normals", "p", "position", "point", "worldnormal", "worldposition"}
MASK_NAMES = {"a", "alpha", "mask", "matte", "holdout", "coverage"}


def _split_channel(channel: str) -> tuple[str | None, str]:
    if "." not in channel:
        return None, channel
    prefix, suffix = channel.rsplit(".", 1)
    return prefix, suffix


def _compact_name(name: str) -> str:
    return name.lower().replace("_", "").replace("-", "").replace(" ", "")


def _matches_any_name(name: str, candidates: set[str]) -> bool:
    return name in candidates or any(
        candidate in name for candidate in candidates if len(candidate) > 1
    )


def _is_cryptomatte_layer(name: str, base_names: Iterable[str]) -> bool:
    """Match a manifest-named layer and its numbered ID/coverage companions."""

    for base_name in base_names:
        suffix = name[len(base_name) :] if name.startswith(base_name) else ""
        if name == base_name or (len(suffix) >= 2 and suffix.isdigit()):
            return True
    return False


def _rgb_channels(channels: Iterable[str]) -> tuple[str, ...]:
    by_role: dict[str, str] = {}
    alpha: list[str] = []
    for channel in channels:
        _, suffix = _split_channel(channel)
        key = suffix.lower()
        role = RGB_SUFFIXES.get(key)
        if role is not None:
            by_role.setdefault(role, channel)
        elif key in ALPHA_SUFFIXES:
            alpha.append(channel)

    if not {"R", "G", "B"}.issubset(by_role):
        return ()
    return tuple(by_role[role] for role in ("R", "G", "B")) + tuple(alpha)


def _vector_channels(channels: Iterable[str]) -> tuple[str, ...]:
    by_role: dict[str, str] = {}
    for channel in channels:
        _, suffix = _split_channel(channel)
        key = suffix.lower()
        if key in VECTOR_SUFFIXES:
            by_role.setdefault(key, channel)
    if not VECTOR_SUFFIXES.issubset(by_role):
        return ()
    return tuple(by_role[role] for role in ("x", "y", "z"))


def infer_aov_descriptor(name: str, channels: Iterable[str]) -> AOVDescriptor:
    """Infer one AOV descriptor from its grouped channel names."""

    channel_tuple = tuple(channels)
    compact_name = _compact_name(name)

    rgb_channels = _rgb_channels(channel_tuple)
    vector_channels = _vector_channels(channel_tuple)

    if compact_name in DEPTH_NAMES:
        return AOVDescriptor(
            name=name,
            channels=channel_tuple,
            category=AOVCategory.DEPTH,
            category_confidence="known_depth_name",
        )

    if _matches_any_name(compact_name, VECTOR_NAMES) and (rgb_channels or vector_channels):
        return AOVDescriptor(
            name=name,
            channels=channel_tuple,
            category=AOVCategory.VECTOR,
            category_confidence="known_vector_name",
        )

    if _matches_any_name(compact_name, MASK_NAMES):
        return AOVDescriptor(
            name=name,
            channels=channel_tuple,
            category=AOVCategory.MASK,
            category_confidence="known_mask_name",
        )

    if rgb_channels:
        return AOVDescriptor(
            name=name,
            channels=channel_tuple,
            category=AOVCategory.COLOR,
            category_confidence="rgb_channels",
        )

    if vector_channels:
        return AOVDescriptor(
            name=name,
            channels=channel_tuple,
            category=AOVCategory.VECTOR,
            category_confidence="xyz_channels",
        )

    if len(channel_tuple) == 1:
        _, suffix = _split_channel(channel_tuple[0])
        compact_suffix = _compact_name(suffix)
        if compact_name in DEPTH_NAMES or compact_suffix in DEPTH_NAMES:
            return AOVDescriptor(
                name=name,
                channels=channel_tuple,
                category=AOVCategory.DEPTH,
                category_confidence="name",
            )
        if _matches_any_name(compact_name, MASK_NAMES) or compact_suffix in MASK_NAMES:
            return AOVDescriptor(
                name=name,
                channels=channel_tuple,
                category=AOVCategory.MASK,
                category_confidence="name",
            )
        if "." not in channel_tuple[0]:
            return AOVDescriptor(
                name=name,
                channels=channel_tuple,
                category=AOVCategory.SCALAR,
                category_confidence="single_root_channel",
            )

    return AOVDescriptor(
        name=name,
        channels=channel_tuple,
        category=AOVCategory.UNKNOWN,
        category_confidence="insufficient_evidence",
    )


def infer_aov_descriptors(
    channels: Iterable[str],
    *,
    beauty_name: str = "beauty",
    cryptomatte_names: Iterable[str] = (),
) -> tuple[AOVDescriptor, ...]:
    """Infer AOVs, using Cryptomatte metadata when supplied by the reader."""

    channel_tuple = tuple(channels)
    cryptomatte_bases = tuple(name for name in cryptomatte_names if name)
    root_channels = [channel for channel in channel_tuple if "." not in channel]
    named_groups: "OrderedDict[str, list[str]]" = OrderedDict()
    for channel in channel_tuple:
        prefix, _ = _split_channel(channel)
        if prefix is not None:
            named_groups.setdefault(prefix, []).append(channel)

    descriptors: list[AOVDescriptor] = []
    root_rgb = _rgb_channels(root_channels)
    consumed_root = set(root_rgb)
    if root_rgb:
        descriptors.append(
            AOVDescriptor(
                name=beauty_name,
                channels=root_rgb,
                category=AOVCategory.COLOR,
                category_confidence="root_rgb_channels",
            )
        )

    for channel in root_channels:
        if channel in consumed_root:
            continue
        descriptors.append(infer_aov_descriptor(channel, (channel,)))

    for name, group_channels in named_groups.items():
        if _is_cryptomatte_layer(name, cryptomatte_bases):
            descriptors.append(
                AOVDescriptor(
                    name=name,
                    channels=tuple(group_channels),
                    category=AOVCategory.CRYPTOMATTE,
                    category_confidence="cryptomatte_metadata",
                )
            )
        else:
            descriptors.append(infer_aov_descriptor(name, group_channels))

    return tuple(descriptors)


def build_file_inspection(
    *,
    path: str | Path,
    width: int,
    height: int,
    channels: Iterable[str],
    part_count: int = 1,
    is_deep: bool = False,
    warnings: Iterable[str] = (),
    cryptomatte_names: Iterable[str] = (),
) -> FileInspection:
    """Build a structured inspection model from backend-provided EXR metadata."""

    if width <= 0 or height <= 0:
        raise ValueError("EXR dimensions must be positive.")
    if part_count <= 0:
        raise ValueError("EXR part_count must be positive.")

    channel_tuple = tuple(channels)
    return FileInspection(
        path=Path(path),
        width=width,
        height=height,
        channels=channel_tuple,
        aovs=infer_aov_descriptors(
            channel_tuple,
            cryptomatte_names=cryptomatte_names,
        ),
        part_count=part_count,
        is_deep=is_deep,
        warnings=tuple(warnings),
    )
