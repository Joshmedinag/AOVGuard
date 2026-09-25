"""Reader protocol used to decouple analysis from the OpenEXR backend."""

from __future__ import annotations

from pathlib import Path
from typing import Collection, Protocol

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
