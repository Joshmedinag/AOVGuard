"""Background analysis worker and option construction for the Qt GUI."""

from __future__ import annotations

import traceback
from dataclasses import replace
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from aovguard.core.analysis import AnalysisCancelled, analyze
from aovguard.core.execution import WorkerCleanupError
from aovguard.core.luminance import LuminanceWeights, luminance_weights_for_model
from aovguard.core.models import AnalysisOptions, SourceMode
from aovguard.io.reader import OpenEXRReader
from aovguard.rules.builtin import default_rule_definitions
from aovguard.rules.definitions import RuleDefinition
from aovguard.rules.loader import load_rule_preset


def build_analysis_options(
    *,
    luminance_model: str,
    rules_config: str | None,
    selected_rule_ids: set[str] | None = None,
    custom_luminance_weights: tuple[float, float, float] | None = None,
    frame_pattern: str = "*.exr",
    recursive: bool = False,
    max_depth: int | None = 1,
    allow_multiple_sequences: bool = False,
    max_frames: int | None = None,
    max_memory_mb: float | None = None,
    isolate_frames: bool = True,
    frame_timeout_seconds: float | None = None,
    expected_frame_range: tuple[int, int] | None = None,
    source_mode: SourceMode | str = SourceMode.AUTO,
) -> tuple[AnalysisOptions, tuple[RuleDefinition, ...]]:
    """Build validated backend options and effective rule definitions."""

    if luminance_model == "Custom":
        if custom_luminance_weights is None:
            raise ValueError("Custom luminance requires R, G and B weights.")
        weights = LuminanceWeights.from_values(custom_luminance_weights)
    else:
        weights = luminance_weights_for_model(luminance_model)
    if rules_config:
        preset = load_rule_preset(rules_config)
        definitions = preset.rules
        preset_name = preset.name
        category_overrides = preset.aov_category_overrides
    else:
        definitions = default_rule_definitions()
        preset_name = None
        category_overrides = {}
    if selected_rule_ids is not None:
        definitions = tuple(
            replace(definition, enabled=definition.id in selected_rule_ids)
            for definition in definitions
        )

    enabled_rules = tuple(definition.id for definition in definitions if definition.enabled)
    options = AnalysisOptions(
        preset_name=preset_name,
        enabled_rules=enabled_rules,
        luminance_weights=(weights.r, weights.g, weights.b),
        frame_pattern=frame_pattern,
        recursive=recursive,
        max_depth=max_depth,
        allow_multiple_sequences=allow_multiple_sequences,
        max_frames=max_frames,
        max_memory_mb=max_memory_mb,
        isolate_frames=isolate_frames,
        frame_timeout_seconds=frame_timeout_seconds,
        expected_frame_range=expected_frame_range,
        source_mode=SourceMode(source_mode),
        aov_category_overrides=category_overrides,
    )
    return options, tuple(definitions)


class AnalyzeWorker(QObject):
    """Supervise analysis and relay results from the Qt worker thread."""

    finished = Signal(object)
    cancelled = Signal()
    error = Signal(str, str)
    cleanup_failed = Signal(str, str)
    log = Signal(str)
    progress = Signal(int, str)

    def __init__(
        self,
        source: str,
        *,
        rules_config: str | None = None,
        luminance_model: str = "Rec.709",
        selected_rule_ids: set[str] | None = None,
        custom_luminance_weights: tuple[float, float, float] | None = None,
        frame_pattern: str = "*.exr",
        recursive: bool = False,
        max_depth: int | None = 1,
        allow_multiple_sequences: bool = False,
        max_frames: int | None = None,
        max_memory_mb: float | None = None,
        isolate_frames: bool = True,
        frame_timeout_seconds: float | None = None,
        expected_frame_range: tuple[int, int] | None = None,
        source_mode: SourceMode | str = SourceMode.AUTO,
    ) -> None:
        """Capture immutable user selections for the pending analysis."""

        super().__init__()
        self.source = source
        self.rules_config = rules_config
        self.luminance_model = luminance_model
        self.selected_rule_ids = selected_rule_ids
        self.custom_luminance_weights = custom_luminance_weights
        self.frame_pattern = frame_pattern
        self.recursive = recursive
        self.max_depth = max_depth
        self.allow_multiple_sequences = allow_multiple_sequences
        self.max_frames = max_frames
        self.max_memory_mb = max_memory_mb
        self.isolate_frames = isolate_frames
        self.frame_timeout_seconds = frame_timeout_seconds
        self.expected_frame_range = expected_frame_range
        self.source_mode = SourceMode(source_mode)
        self._cancel_requested = Event()

    @Slot()
    def request_cancel(self) -> None:
        """Stop active isolated work, or cancel after an in-process native operation."""

        self._cancel_requested.set()

    def _on_progress(self, current: int, total: int, message: str) -> None:
        percent = int((current / total) * 100) if total > 0 else 0
        self.progress.emit(max(0, min(100, percent)), message)

    @Slot()
    def run(self) -> None:
        """Execute analysis and emit a single terminal Qt signal."""

        try:
            self.log.emit(f"Analyzing source: {self.source}")
            self.progress.emit(0, "Preparing analysis...")
            options, definitions = build_analysis_options(
                luminance_model=self.luminance_model,
                rules_config=self.rules_config,
                selected_rule_ids=self.selected_rule_ids,
                custom_luminance_weights=self.custom_luminance_weights,
                frame_pattern=self.frame_pattern,
                recursive=self.recursive,
                max_depth=self.max_depth,
                allow_multiple_sequences=self.allow_multiple_sequences,
                max_frames=self.max_frames,
                max_memory_mb=self.max_memory_mb,
                isolate_frames=self.isolate_frames,
                frame_timeout_seconds=self.frame_timeout_seconds,
                expected_frame_range=self.expected_frame_range,
                source_mode=self.source_mode,
            )
            if options.isolate_frames:
                self.log.emit("Execution mode: isolated analysis process; active frames can be stopped.")
                self.log.emit(
                    f"Per-frame timeout: {options.frame_timeout_seconds:g} seconds."
                    if options.frame_timeout_seconds is not None else "Per-frame timeout: none."
                )
            else:
                self.log.emit("Execution mode: in-process; native reads cannot be interrupted.")
            report = analyze(
                self.source,
                options,
                OpenEXRReader(options.aov_category_overrides),
                rule_definitions=definitions,
                progress_callback=self._on_progress,
                cancellation_callback=self._cancel_requested.is_set,
            )
            self.progress.emit(100, "Analysis complete.")
            self.finished.emit((report, options))
        except WorkerCleanupError as exc:
            worker = f" (worker PID {exc.worker_pid})" if exc.worker_pid is not None else ""
            recovery = (
                "Check the reported worker PID in Task Manager or your system process monitor "
                "and stop it if it is still running. "
                if exc.worker_pid is not None else
                "Check Task Manager or your system process monitor for any remaining "
                "AOVGuard analysis worker and stop it if it is still running. "
            )
            self.cleanup_failed.emit(
                f"Fatal cleanup failure{worker}: {exc}\n\n"
                "AOVGuard could not confirm that the analysis process or receiver stopped. "
                "Analysis and inspection are blocked in this window. "
                + recovery +
                "Then restart AOVGuard.",
                traceback.format_exc(),
            )
        except AnalysisCancelled:
            self.cancelled.emit()
        except (FileNotFoundError, NotADirectoryError, PermissionError, ValueError) as exc:
            self.error.emit(str(exc), "")
        except Exception as exc:
            self.error.emit(str(exc), traceback.format_exc())
