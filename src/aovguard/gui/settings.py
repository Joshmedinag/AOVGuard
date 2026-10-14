"""Typed preference persistence independent of the main window's widgets."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QSettings

from aovguard.core.luminance import REC709, LuminanceWeights
from aovguard.core.models import SourceMode


@dataclass(frozen=True, slots=True)
class WindowPreferences:
    """Validated saved selections and layout state for the desktop interface."""

    geometry: QByteArray | bytes | None = None
    source: str = ""
    preset: str = ""
    luminance: str = "Rec.709"
    frame_pattern: str = "*.exr"
    recursive: bool = False
    max_depth: int = 1
    allow_multiple_sequences: bool = False
    max_frames: int = 0
    max_memory_mb: int = 0
    isolate_frames: bool = True
    frame_timeout_seconds: float = 0.0
    expected_enabled: bool = False
    expected_start: int = 1
    expected_end: int = 800
    source_mode: SourceMode = SourceMode.AUTO
    custom_weights: tuple[float, float, float] = (REC709.r, REC709.g, REC709.b)
    enabled_rules: tuple[str, ...] | None = None
    analysis_expanded: bool = False
    rules_expanded: bool = True
    log_expanded: bool = False
    warnings: tuple[str, ...] = ()


class PreferencesStore:
    """Read and write stable QSettings keys with safe parsing and explicit defaults."""

    def __init__(self, settings: QSettings) -> None:
        """Use the supplied settings backend, including test-local INI stores."""

        self.settings = settings

    def _integer(self, key: str, default: int) -> int:
        value = self.settings.value(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return default
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default

    def _boolean(self, key: str, default: bool) -> bool:
        value = self.settings.value(key, default)
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "1"}:
            return True
        if text in {"false", "0"}:
            return False
        return default

    def _memory_budget(self) -> tuple[int, tuple[str, ...]]:
        key = "analysis/max_memory_mb"
        if not self.settings.contains(key):
            return 0, ()
        raw = self.settings.value(key)
        try:
            if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
                raise ValueError("Invalid memory budget")
            value = int(raw)
            if isinstance(raw, float) and raw != value:
                raise ValueError("Fractional memory budget")
            if value < 0:
                raise ValueError("Negative memory budget")
        except (TypeError, ValueError, OverflowError):
            return 1024, (
                "The saved memory budget was invalid. A 1024 MiB estimate guard is active; "
                "review Memory budget before analyzing.",
            )
        if value > 1_000_000:
            return 1_000_000, (
                "The saved memory budget exceeded the supported range and was limited to "
                "1000000 MiB. Review Memory budget before analyzing.",
            )
        return value, ()

    def _isolation_mode(self) -> tuple[bool, tuple[str, ...]]:
        key = "analysis/isolate_frames"
        if not self.settings.contains(key):
            return True, ()
        raw = self.settings.value(key)
        if isinstance(raw, bool):
            return raw, ()
        text = str(raw).strip().lower()
        if text in {"true", "1"}:
            return True, ()
        if text in {"false", "0"}:
            return False, ()
        return True, (
            "The saved execution mode was invalid. Process isolation is enabled; "
            "review Isolate analysis process before analyzing.",
        )

    def _frame_timeout(self) -> tuple[float, tuple[str, ...]]:
        key = "analysis/frame_timeout_seconds"
        if not self.settings.contains(key):
            return 0.0, ()
        raw = self.settings.value(key)
        try:
            if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
                raise ValueError("Invalid frame timeout")
            value = float(raw)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError("Invalid frame timeout")
        except (TypeError, ValueError, OverflowError):
            return 30.0, (
                "The saved frame timeout was invalid. A 30 second deadline is selected; "
                "review Frame timeout before analyzing.",
            )
        if value > 86400.0:
            return 86400.0, (
                "The saved frame timeout exceeded the supported range and was limited to "
                "86400 seconds. Review Frame timeout before analyzing.",
            )
        if 0.0 < value < 0.01:
            return 0.01, (
                "The saved frame timeout was below the supported precision and was raised to "
                "0.01 seconds. Review Frame timeout before analyzing.",
            )
        return round(value, 2), ()

    def load(self) -> WindowPreferences:
        """Parse persisted selections without letting corrupt values break startup."""

        geometry = self.settings.value("window/geometry")
        if not isinstance(geometry, (QByteArray, bytes)):
            geometry = None
        source_mode = str(self.settings.value("analysis/source_mode", SourceMode.AUTO.value))
        try:
            mode = SourceMode(source_mode)
        except ValueError:
            mode = SourceMode.AUTO
        default_weights = (REC709.r, REC709.g, REC709.b)
        weights_text = str(
            self.settings.value("analysis/custom_weights", ",".join(map(str, default_weights)))
        )
        try:
            weights = LuminanceWeights.from_values(float(value) for value in weights_text.split(","))
            custom_weights = (weights.r, weights.g, weights.b)
        except (TypeError, ValueError, OverflowError):
            custom_weights = default_weights
        enabled_rules = (
            tuple(
                rule for rule in str(self.settings.value("analysis/enabled_rules", "")).split(",")
                if rule
            )
            if self.settings.contains("analysis/enabled_rules") else None
        )
        memory_budget, warnings = self._memory_budget()
        isolated, isolation_warnings = self._isolation_mode()
        timeout, timeout_warnings = self._frame_timeout()
        return WindowPreferences(
            geometry=geometry,
            source=str(self.settings.value("analysis/source", "")),
            preset=str(self.settings.value("analysis/preset", "")),
            luminance=str(self.settings.value("analysis/luminance", "Rec.709")),
            frame_pattern=str(self.settings.value("analysis/frame_pattern", "*.exr")),
            recursive=self._boolean("analysis/recursive", False),
            max_depth=self._integer("analysis/max_depth", 1),
            allow_multiple_sequences=self._boolean("analysis/allow_multiple_sequences", False),
            max_frames=self._integer("analysis/max_frames", 0),
            max_memory_mb=memory_budget,
            isolate_frames=isolated,
            frame_timeout_seconds=timeout,
            expected_enabled=self._boolean("analysis/expected_enabled", False),
            expected_start=self._integer("analysis/expected_start", 1),
            expected_end=self._integer("analysis/expected_end", 800),
            source_mode=mode,
            custom_weights=custom_weights,
            enabled_rules=enabled_rules,
            analysis_expanded=self._boolean("sections/analysis", False),
            rules_expanded=self._boolean("sections/rules", True),
            log_expanded=self._boolean("sections/log", False),
            warnings=warnings + isolation_warnings + timeout_warnings,
        )

    def save(self, preferences: WindowPreferences) -> None:
        """Serialize a complete widget-independent preference snapshot and flush it."""

        if type(preferences.max_memory_mb) is not int or not 0 <= preferences.max_memory_mb <= 1_000_000:
            raise ValueError("Saved memory budget must be an integer between 0 and 1000000 MiB.")
        if not isinstance(preferences.isolate_frames, bool):
            raise ValueError("Saved isolation mode must be a boolean.")
        timeout = preferences.frame_timeout_seconds
        try:
            valid_timeout = (
                not isinstance(timeout, bool)
                and isinstance(timeout, (int, float))
                and math.isfinite(timeout)
                and 0 <= timeout <= 86400
            )
        except OverflowError:
            valid_timeout = False
        if not valid_timeout:
            raise ValueError("Saved frame timeout must be finite and between 0 and 86400 seconds.")
        values = {
            "window/geometry": preferences.geometry,
            "analysis/source": preferences.source,
            "analysis/preset": preferences.preset,
            "analysis/luminance": preferences.luminance,
            "analysis/frame_pattern": preferences.frame_pattern,
            "analysis/recursive": preferences.recursive,
            "analysis/max_depth": preferences.max_depth,
            "analysis/allow_multiple_sequences": preferences.allow_multiple_sequences,
            "analysis/max_frames": preferences.max_frames,
            "analysis/max_memory_mb": preferences.max_memory_mb,
            "analysis/isolate_frames": preferences.isolate_frames,
            "analysis/frame_timeout_seconds": preferences.frame_timeout_seconds,
            "analysis/expected_enabled": preferences.expected_enabled,
            "analysis/expected_start": preferences.expected_start,
            "analysis/expected_end": preferences.expected_end,
            "analysis/source_mode": preferences.source_mode.value,
            "analysis/custom_weights": ",".join(map(str, preferences.custom_weights)),
            "sections/analysis": preferences.analysis_expanded,
            "sections/rules": preferences.rules_expanded,
            "sections/log": preferences.log_expanded,
        }
        for key, value in values.items():
            if value is not None:
                self.settings.setValue(key, value)
        if preferences.enabled_rules is None:
            self.settings.remove("analysis/enabled_rules")
        else:
            self.settings.setValue("analysis/enabled_rules", ",".join(preferences.enabled_rules))
        self.settings.sync()
