"""Reader protocol used to decouple analysis from the OpenEXR backend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Collection, Protocol, runtime_checkable

from aovguard.core.models import FileInspection, FrameData


class EXRReader(Protocol):
    """Minimal interface required by the backend-independent analysis core."""

    def inspect(self, path: Path) -> FileInspection:
        """Return structural metadata without requiring pixel analysis."""

        ...

    def read_frame(
        self,
        path: Path,
        requested_aovs: Collection[str] | None = None,
    ) -> FrameData:
        """Decode one frame and optionally restrict returned AOV names."""

        ...


@runtime_checkable
class MemoryBudgetReader(Protocol):
    """Optional hook that checks the current header immediately before decode."""

    def read_frame_with_memory_budget(self, path: Path, max_memory_mb: float) -> FrameData:
        """Reject a frame exceeding the conservative budget before reading pixels."""

        ...


@dataclass(frozen=True, slots=True)
class ReaderProcessSpec:
    """Serializable configuration for a known, trusted child-process backend."""

    backend: str = "openexr"
    category_overrides: tuple[tuple[str, str], ...] = ()


@runtime_checkable
class ProcessIsolatableReader(Protocol):
    """Optional reader capability for reconstructing its configuration in a child."""

    def process_spec(self) -> ReaderProcessSpec:
        """Return a plain configuration snapshot, never live arrays or handles."""

        ...
