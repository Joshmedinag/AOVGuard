"""Shared frame-first analysis pipeline used by the CLI and GUI."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Callable

import numpy as np

from aovguard.core.execution import (
    FrameTimeoutError,
    FrameWorkerCrashed,
    FrameWorkerProtocolError,
    WorkerCleanupError,
)
from aovguard.core.luminance import LuminanceWeights, compute_luminance
from aovguard.core.memory import MemoryBudgetExceeded, MemoryEstimate, enforce_memory_budget
from aovguard.core.models import (
    AnalysisOptions,
    AnalysisReport,
    AOVCategory,
    AOVDescriptor,
    ChannelMetricSet,
    FileInspection,
    Finding,
    FrameExecutionRecord,
    MetricSet,
    SequenceCheckResult,
    SeriesMetricSet,
    Severity,
    SourceKind,
    SourceMode,
)
from aovguard.discovery.frame_discovery import discover_frames
from aovguard.io.process_executor import FrameProcessExecutor
from aovguard.io.protocol import MemoryBudgetReader, ProcessIsolatableReader
from aovguard.rules.builtin import default_rule_definitions, effective_rule_parameters
from aovguard.rules.definitions import RuleDefinition
from aovguard.rules.engine import execute_rules
from aovguard.sequence.sequence_checker import check_sequences, sequence_findings

if TYPE_CHECKING:
    from aovguard.io.protocol import EXRReader

ProgressCallback = Callable[[int, int, str], None]
CancellationCallback = Callable[[], bool]


class AnalysisCancelled(RuntimeError):
    """Raised when a caller requests cooperative analysis cancellation."""


@dataclass(slots=True)
class _MetricAccumulator:
    non_black_threshold: float
    luminance_weights: LuminanceWeights
    pixel_count: int = 0
    finite_count: int = 0
    non_black_count: int = 0
    luminance_sum: float = 0.0
    abs_luminance_sum: float = 0.0
    max_luminance: float = float("-inf")
    max_abs_luminance: float = float("-inf")
    nan_count: int = 0
    posinf_count: int = 0
    neginf_count: int = 0

    def update(self, pixels: np.ndarray) -> None:
        luminance = compute_luminance(pixels, self.luminance_weights)
        self.update_luminance(luminance)

    def update_luminance(self, luminance: np.ndarray) -> None:
        self.pixel_count += int(luminance.size)
        self.nan_count += int(np.count_nonzero(np.isnan(luminance)))
        self.posinf_count += int(np.count_nonzero(np.isposinf(luminance)))
        self.neginf_count += int(np.count_nonzero(np.isneginf(luminance)))

        finite = luminance[np.isfinite(luminance)]
        if finite.size == 0:
            return

        self.finite_count += int(finite.size)
        absolute = np.abs(finite)
        self.non_black_count += int(np.count_nonzero(absolute > self.non_black_threshold))
        self.luminance_sum += float(np.sum(finite, dtype=np.float64))
        self.abs_luminance_sum += float(np.sum(absolute, dtype=np.float64))
        self.max_luminance = max(self.max_luminance, float(np.max(finite)))
        self.max_abs_luminance = max(
            self.max_abs_luminance,
            float(np.max(absolute)),
        )

    def finalize(self) -> MetricSet:
        if self.finite_count:
            avg_luminance = self.luminance_sum / self.finite_count
            avg_abs_luminance = self.abs_luminance_sum / self.finite_count
            max_luminance = self.max_luminance
            max_abs_luminance = self.max_abs_luminance
        else:
            avg_luminance = float("nan")
            avg_abs_luminance = float("nan")
            max_luminance = float("nan")
            max_abs_luminance = float("nan")

        non_black_ratio = 0.0
        if self.pixel_count:
            non_black_ratio = self.non_black_count / self.pixel_count

        return MetricSet(
            non_black_ratio=non_black_ratio,
            avg_luminance=avg_luminance,
            max_luminance=max_luminance,
            pixel_count=self.pixel_count,
            nan_count=self.nan_count,
            posinf_count=self.posinf_count,
            neginf_count=self.neginf_count,
            avg_abs_luminance=avg_abs_luminance,
            max_abs_luminance=max_abs_luminance,
        )

    def merge(self, other: _MetricAccumulator) -> None:
        self.pixel_count += other.pixel_count
        self.finite_count += other.finite_count
        self.non_black_count += other.non_black_count
        self.luminance_sum += other.luminance_sum
        self.abs_luminance_sum += other.abs_luminance_sum
        self.max_luminance = max(self.max_luminance, other.max_luminance)
        self.max_abs_luminance = max(self.max_abs_luminance, other.max_abs_luminance)
        self.nan_count += other.nan_count
        self.posinf_count += other.posinf_count
        self.neginf_count += other.neginf_count


@dataclass(slots=True)
class _ChannelMetricAccumulator:
    pixel_count: int = 0
    finite_count: int = 0
    value_sum: float = 0.0
    min_value: float = float("inf")
    max_value: float = float("-inf")
    nan_count: int = 0
    posinf_count: int = 0
    neginf_count: int = 0
    negative_count: int = 0

    def update(self, values: np.ndarray) -> None:
        # Preserve the reader's floating dtype. The OpenEXR reader deliberately
        # supplies float32 frame buffers to bound memory, while in-memory or
        # future backends may provide float64 data that must not be downcast.
        array = np.asarray(values)
        if not np.issubdtype(array.dtype, np.floating):
            array = array.astype(np.float64)
        self.pixel_count += int(array.size)
        self.nan_count += int(np.count_nonzero(np.isnan(array)))
        self.posinf_count += int(np.count_nonzero(np.isposinf(array)))
        self.neginf_count += int(np.count_nonzero(np.isneginf(array)))
        finite = array[np.isfinite(array)]
        if finite.size == 0:
            return
        self.finite_count += int(finite.size)
        self.value_sum += float(np.sum(finite, dtype=np.float64))
        self.min_value = min(self.min_value, float(np.min(finite)))
        self.max_value = max(self.max_value, float(np.max(finite)))
        self.negative_count += int(np.count_nonzero(finite < 0))

    def finalize(self) -> ChannelMetricSet:
        if self.finite_count:
            avg_value = self.value_sum / self.finite_count
            min_value = self.min_value
            max_value = self.max_value
        else:
            avg_value = float("nan")
            min_value = float("nan")
            max_value = float("nan")
        return ChannelMetricSet(
            pixel_count=self.pixel_count,
            avg_value=avg_value,
            min_value=min_value,
            max_value=max_value,
            nan_count=self.nan_count,
            posinf_count=self.posinf_count,
            neginf_count=self.neginf_count,
            negative_count=self.negative_count,
        )

    def merge(self, other: _ChannelMetricAccumulator) -> None:
        self.pixel_count += other.pixel_count
        self.finite_count += other.finite_count
        self.value_sum += other.value_sum
        self.min_value = min(self.min_value, other.min_value)
        self.max_value = max(self.max_value, other.max_value)
        self.nan_count += other.nan_count
        self.posinf_count += other.posinf_count
        self.neginf_count += other.neginf_count
        self.negative_count += other.negative_count


def _aov_descriptor(
    inspection: FileInspection,
    aov_name: str,
) -> AOVDescriptor | None:
    return next((aov for aov in inspection.aovs if aov.name == aov_name), None)


def _ordered_named_channels(
    descriptor: AOVDescriptor,
    suffixes: tuple[str, ...],
) -> tuple[str, ...] | None:
    by_suffix = {
        channel.split("::")[-1].rsplit(".", 1)[-1].upper(): channel
        for channel in descriptor.channels
    }
    if not set(suffixes).issubset(by_suffix):
        return None
    return tuple(by_suffix[suffix] for suffix in suffixes)


def _component_channel_names(
    inspection: FileInspection,
    aov_name: str,
    pixels: np.ndarray,
) -> tuple[str, ...]:
    descriptor = _aov_descriptor(inspection, aov_name)
    component_count = 1 if pixels.ndim == 2 else int(pixels.shape[-1])
    if descriptor is None:
        if component_count == 3:
            return tuple(f"{aov_name}.{suffix}" for suffix in ("R", "G", "B"))
        return tuple(f"{aov_name}.{index}" for index in range(component_count))

    if component_count == 1:
        if len(descriptor.channels) == 1:
            return (descriptor.channels[0],)
        red = _ordered_named_channels(descriptor, ("R",))
        return red or (descriptor.channels[0],)

    preferred_orders: tuple[tuple[str, ...], ...]
    if descriptor.category is AOVCategory.VECTOR:
        preferred_orders = (("X", "Y", "Z"), ("R", "G", "B"))
    elif descriptor.category is AOVCategory.COLOR:
        preferred_orders = (("R", "G", "B"),)
    else:
        preferred_orders = ()
    for order in preferred_orders:
        names = _ordered_named_channels(descriptor, order)
        if names is not None and len(names) == component_count:
            return names
    if len(descriptor.channels) >= component_count:
        return descriptor.channels[:component_count]
    return tuple(f"{aov_name}.{index}" for index in range(component_count))


def _resolve_source_kind(
    options: AnalysisOptions,
    sequence_check: SequenceCheckResult,
    frame_count: int,
) -> SourceKind:
    if options.source_mode is SourceMode.COMPARISON:
        return SourceKind.COMPARISON_SET
    if options.source_mode is SourceMode.SEQUENCE:
        if not sequence_check.sequences:
            raise ValueError("Sequence mode requires at least one numbered EXR sequence.")
        if sequence_check.unnumbered_files:
            raise ValueError("Sequence mode cannot mix numbered frames with standalone EXR files.")
        if len(sequence_check.sequences) > 1 and not options.allow_multiple_sequences:
            patterns = ", ".join(sequence.pattern for sequence in sequence_check.sequences)
            raise ValueError(
                "Sequence mode found multiple numbered EXR sequences "
                f"({patterns}). Narrow the frame pattern or allow multiple sequences."
            )
        return SourceKind.NUMBERED_SEQUENCE
    if frame_count == 1 and options.expected_frame_range is None:
        return SourceKind.SINGLE_FILE
    if sequence_check.sequences:
        return SourceKind.NUMBERED_SEQUENCE
    return SourceKind.COMPARISON_SET


def _series_metrics(
    frame_metrics: dict[Path, dict[str, MetricSet]],
    *,
    frame_numbers: dict[Path, int] | None = None,
) -> dict[str, SeriesMetricSet]:
    by_aov: dict[str, list[tuple[Path, float]]] = {}
    for frame_path, metrics_by_aov in frame_metrics.items():
        for aov_name, metrics in metrics_by_aov.items():
            if np.isfinite(metrics.avg_luminance):
                by_aov.setdefault(aov_name, []).append((frame_path, metrics.avg_luminance))

    result: dict[str, SeriesMetricSet] = {}
    occurrences = Counter(frame_numbers.values()) if frame_numbers is not None else Counter()
    for aov_name, samples in sorted(by_aov.items()):
        values = np.asarray([value for _path, value in samples], dtype=np.float64)
        median = float(np.median(values))
        deviations = np.abs(values - median)
        mad = float(np.median(deviations))
        outlier_indices: np.ndarray
        if len(samples) < 3:
            outlier_indices = np.asarray([], dtype=np.int64)
        elif mad > 0.0:
            robust_z = deviations / (1.4826 * mad)
            outlier_indices = np.flatnonzero(robust_z > 3.5)
        else:
            tolerance = max(1e-12, abs(median) * 1e-6)
            outlier_indices = np.flatnonzero(deviations > tolerance)

        max_delta = 0.0
        delta_from: Path | None = None
        delta_to: Path | None = None
        for (previous_path, previous), (current_path, current) in zip(samples, samples[1:]):
            if frame_numbers is not None and (
                previous_path not in frame_numbers
                or current_path not in frame_numbers
                or frame_numbers[current_path] != frame_numbers[previous_path] + 1
                or occurrences[frame_numbers[current_path]] != 1
                or occurrences[frame_numbers[previous_path]] != 1
            ):
                continue
            delta = abs(current - previous)
            if delta > max_delta:
                max_delta = delta
                delta_from = previous_path
                delta_to = current_path

        result[aov_name] = SeriesMetricSet(
            frame_count=len(samples),
            median_luminance=median,
            mad_luminance=mad,
            min_luminance=float(np.min(values)),
            max_luminance=float(np.max(values)),
            max_frame_delta=max_delta,
            max_frame_delta_from=delta_from,
            max_frame_delta_to=delta_to,
            outlier_frames=tuple(samples[index][0] for index in outlier_indices),
        )
    return result


def _measure_frame(
    reader: "EXRReader",
    path: Path,
    weights: LuminanceWeights,
    threshold: float,
    cancellation_callback: CancellationCallback | None,
    max_memory_mb: float | None = None,
) -> tuple[
    FileInspection,
    dict[str, _MetricAccumulator],
    dict[str, dict[str, _ChannelMetricAccumulator]],
    MemoryEstimate | None,
]:
    """Decode and reduce one frame, releasing pixel references before returning."""

    if max_memory_mb is not None:
        if isinstance(reader, MemoryBudgetReader):
            frame = reader.read_frame_with_memory_budget(path, max_memory_mb)
        else:
            inspection = reader.inspect(path)
            if inspection.unsupported_reason is not None:
                return inspection, {}, {}, None
            enforce_memory_budget(inspection, max_memory_mb)
            if cancellation_callback is not None and cancellation_callback():
                raise AnalysisCancelled("Analysis cancelled by user.")
            frame = reader.read_frame(path)
    else:
        frame = reader.read_frame(path)
    if frame.inspection.unsupported_reason is not None:
        return frame.inspection, {}, {}, None
    estimate = (
        enforce_memory_budget(frame.inspection, max_memory_mb)
        if max_memory_mb is not None else None
    )
    color_stats: dict[str, _MetricAccumulator] = {}
    channel_stats: dict[str, dict[str, _ChannelMetricAccumulator]] = {}
    for aov_name, pixels in frame.aovs.items():
        if cancellation_callback is not None and cancellation_callback():
            raise AnalysisCancelled("Analysis cancelled by user.")
        descriptor = _aov_descriptor(frame.inspection, aov_name)
        if frame.channel_data and descriptor is not None:
            physical_channels = {
                name: frame.channel_data[name] for name in descriptor.channels
            }
        else:
            names = _component_channel_names(frame.inspection, aov_name, pixels)
            physical_channels = {
                name: pixels if pixels.ndim == 2 else pixels[..., index]
                for index, name in enumerate(names)
            }
        per_aov: dict[str, _ChannelMetricAccumulator] = {}
        for name, values in physical_channels.items():
            accumulator = _ChannelMetricAccumulator()
            accumulator.update(values)
            per_aov[name] = accumulator
        channel_stats[aov_name] = per_aov
        is_color = descriptor is not None and descriptor.category is AOVCategory.COLOR
        if descriptor is None:
            is_color = pixels.ndim >= 3 and pixels.shape[-1] >= 3
        if is_color:
            color = _MetricAccumulator(threshold, weights)
            color.update(pixels)
            color_stats[aov_name] = color
    return frame.inspection, color_stats, channel_stats, estimate


def analyze(
    source: str | Path,
    options: AnalysisOptions,
    reader: "EXRReader",
    rule_definitions: Sequence[RuleDefinition] | None = None,
    *,
    progress_callback: ProgressCallback | None = None,
    cancellation_callback: CancellationCallback | None = None,
) -> AnalysisReport:
    """Analyze EXR source data through the backend-independent reader protocol.

    Isolated execution requires a reader with an explicit process configuration;
    there is no silent fallback to unprotected in-process decoding. Every child
    is closed before returning a report or propagating cancellation/errors.
    """

    executor: FrameProcessExecutor | None = None
    if options.isolate_frames:
        if not isinstance(reader, ProcessIsolatableReader):
            raise ValueError("This reader does not support process isolation; use in-process mode.")
        executor = FrameProcessExecutor(reader.process_spec())

    discovery = discover_frames(
        source,
        pattern=options.frame_pattern,
        recursive=options.recursive,
        max_depth=options.max_depth,
    )
    if not discovery.frames:
        raise FileNotFoundError(f"No EXR files found in {discovery.source}")
    if options.max_frames is not None and len(discovery.frames) > options.max_frames:
        raise ValueError(
            f"Discovered {len(discovery.frames)} EXR files, exceeding the configured "
            f"max_frames limit of {options.max_frames}. Narrow the frame pattern or "
            "raise the limit explicitly."
        )
    sequence_check = check_sequences(
        discovery.frames,
        source=discovery.source,
        expected_frame_range=options.expected_frame_range,
    )
    source_kind = _resolve_source_kind(options, sequence_check, len(discovery.frames))
    if options.expected_frame_range is not None and source_kind is not SourceKind.NUMBERED_SEQUENCE:
        raise ValueError("Expected frame range requires numbered sequence interpretation.")
    if (
        source_kind is SourceKind.NUMBERED_SEQUENCE
        and options.source_mode is SourceMode.AUTO
        and options.recursive
        and not options.allow_multiple_sequences
        and len(sequence_check.sequences) > 1
    ):
        patterns = ", ".join(sequence.pattern for sequence in sequence_check.sequences)
        raise ValueError(
            "Recursive discovery found multiple numbered EXR sequences "
            f"({patterns}). Narrow --frame-pattern or enable multiple sequences."
        )
    weights = LuminanceWeights.from_values(options.luminance_weights)
    accumulators: dict[str, _MetricAccumulator] = {}
    channel_accumulators: dict[str, dict[str, _ChannelMetricAccumulator]] = {}
    findings = (
        list(sequence_findings(sequence_check))
        if source_kind is SourceKind.NUMBERED_SEQUENCE
        else []
    )
    inspections: list[FileInspection] = []
    successful_frames: list[Path] = []
    failed_frames: list[Path] = []
    frame_metrics: dict[Path, dict[str, MetricSet]] = {}
    frame_channel_metrics: dict[Path, dict[str, dict[str, ChannelMetricSet]]] = {}
    memory_estimates: dict[Path, MemoryEstimate] = {}
    frame_execution: dict[Path, FrameExecutionRecord] = {}

    total_frames = len(discovery.frames)
    with ExitStack() as cleanup:
        if executor is not None:
            cleanup.callback(executor.close)
        for frame_index, frame_path in enumerate(discovery.frames, start=1):
            if cancellation_callback is not None and cancellation_callback():
                raise AnalysisCancelled("Analysis cancelled by user.")
            if executor is not None and progress_callback is not None:
                progress_callback(frame_index - 1, total_frames, f"Analyzing {frame_path.name}")
            started = perf_counter()
            status = "read_error"
            try:
                if executor is not None:
                    inspection, colors_for_frame, channels_for_frame, estimate = executor.measure_frame(
                        frame_path, weights, options.non_black_threshold, options.max_memory_mb,
                        options.frame_timeout_seconds, cancellation_callback,
                    )
                else:
                    inspection, colors_for_frame, channels_for_frame, estimate = _measure_frame(
                        reader, frame_path, weights, options.non_black_threshold, cancellation_callback,
                        options.max_memory_mb,
                    )
                status = (
                    "unsupported_structure" if inspection.unsupported_reason is not None else "completed"
                )
            except (AnalysisCancelled, WorkerCleanupError):
                raise
            except MemoryBudgetExceeded as exc:
                status = "memory_rejected"
                inspections.append(exc.inspection)
                failed_frames.append(frame_path)
                memory_estimates[frame_path] = exc.estimate
                findings.append(Finding(
                    rule_id="memory_budget",
                    severity=Severity.ERROR,
                    message=str(exc),
                    file=frame_path,
                    affected_files=(frame_path,),
                    metrics={**asdict(exc.estimate), "max_memory_mb": exc.max_memory_mb},
                ))
                if progress_callback is not None:
                    progress_callback(frame_index, total_frames, f"Memory budget rejected: {frame_path.name}")
                continue
            except (FrameTimeoutError, FrameWorkerCrashed, FrameWorkerProtocolError) as exc:
                is_timeout = isinstance(exc, FrameTimeoutError)
                is_protocol = isinstance(exc, FrameWorkerProtocolError)
                status = "timeout" if is_timeout else "protocol_error" if is_protocol else "crash"
                rule_id = "frame_timeout" if is_timeout else "worker_protocol" if is_protocol else "worker_crash"
                if exc.inspection is not None:
                    inspections.append(exc.inspection)
                if exc.estimate is not None:
                    memory_estimates[frame_path] = exc.estimate
                failed_frames.append(frame_path)
                evidence: dict[str, object] = {"stage": exc.stage}
                if is_timeout:
                    evidence["timeout_seconds"] = exc.timeout_seconds
                else:
                    evidence["exit_code"] = exc.exit_code
                findings.append(Finding(
                    rule_id=rule_id,
                    severity=Severity.ERROR,
                    message=str(exc),
                    file=frame_path,
                    affected_files=(frame_path,),
                    metrics=evidence,
                ))
                if progress_callback is not None:
                    progress_callback(frame_index, total_frames, f"Frame {status}: {frame_path.name}")
                continue
            except Exception as exc:
                retained_inspection = getattr(exc, "inspection", None)
                retained_estimate = getattr(exc, "estimate", None)
                if isinstance(retained_inspection, FileInspection):
                    inspections.append(retained_inspection)
                if isinstance(retained_estimate, MemoryEstimate):
                    memory_estimates[frame_path] = retained_estimate
                failed_frames.append(frame_path)
                findings.append(Finding(
                    rule_id="read_frame",
                    severity=Severity.ERROR,
                    message=f"Could not read EXR frame: {exc}",
                    file=frame_path,
                    affected_files=(frame_path,),
                ))
                if progress_callback is not None:
                    progress_callback(frame_index, total_frames, f"Read failed: {frame_path.name}")
                continue
            finally:
                if executor is not None and executor.last_execution is not None:
                    frame_execution[frame_path] = executor.last_execution
                elif executor is None:
                    frame_execution[frame_path] = FrameExecutionRecord(
                        mode="in_process", status=status, worker_pid=None,
                        elapsed_seconds=perf_counter() - started, timeout_seconds=None,
                    )

            inspections.append(inspection)
            if estimate is not None:
                memory_estimates[frame_path] = estimate
            unsupported_reason = inspection.unsupported_reason
            if unsupported_reason is not None:
                failed_frames.append(frame_path)
                findings.append(Finding(
                    rule_id="unsupported_structure", severity=Severity.ERROR,
                    message=unsupported_reason, file=frame_path,
                    affected_files=(frame_path,),
                ))
                if progress_callback is not None:
                    progress_callback(frame_index, total_frames, f"Unsupported EXR: {frame_path.name}")
                continue

            channels_for_report: dict[str, dict[str, ChannelMetricSet]] = {}
            for aov_name, channels in channels_for_frame.items():
                per_aov = channel_accumulators.setdefault(aov_name, {})
                channels_for_report[aov_name] = {}
                for channel_name, frame_channel in channels.items():
                    channel_accumulator = per_aov.setdefault(channel_name, _ChannelMetricAccumulator())
                    channel_accumulator.merge(frame_channel)
                    channels_for_report[aov_name][channel_name] = frame_channel.finalize()
            metrics_for_frame: dict[str, MetricSet] = {}
            for aov_name, frame_color in colors_for_frame.items():
                accumulator = accumulators.setdefault(
                    aov_name, _MetricAccumulator(
                        non_black_threshold=options.non_black_threshold, luminance_weights=weights,
                    ),
                )
                accumulator.merge(frame_color)
                metrics_for_frame[aov_name] = frame_color.finalize()
            frame_metrics[frame_path] = metrics_for_frame
            frame_channel_metrics[frame_path] = channels_for_report
            successful_frames.append(frame_path)
            if progress_callback is not None:
                progress_callback(frame_index, total_frames, f"Processed {frame_path.name}")

    if cancellation_callback is not None and cancellation_callback():
        raise AnalysisCancelled("Analysis cancelled by user.")

    metrics_by_aov = {
        aov_name: accumulator.finalize() for aov_name, accumulator in sorted(accumulators.items())
    }
    channel_metrics_by_aov = {
        aov_name: {
            channel_name: accumulator.finalize()
            for channel_name, accumulator in sorted(channel_accumulators.items())
        }
        for aov_name, channel_accumulators in sorted(channel_accumulators.items())
    }
    sequence_series: dict[str, dict[str, SeriesMetricSet]] = {}
    for sequence in sequence_check.sequences:
        numbered = {
            path: int(path.name[len(sequence.prefix):len(path.name) - len(sequence.suffix) - 4])
            for path in sequence.files
        }
        subset = {
            path: frame_metrics[path]
            for path in sorted(sequence.files, key=lambda item: (numbered[item], str(item)))
            if path in frame_metrics
        }
        key = str(sequence.directory / sequence.pattern)
        sequence_series[key] = _series_metrics(subset, frame_numbers=numbered)
    if len(sequence_series) == 1 and not sequence_check.unnumbered_files:
        series_metrics_by_aov = next(iter(sequence_series.values()))
    elif source_kind is SourceKind.NUMBERED_SEQUENCE:
        # Ambiguous multi-sequence trends are only exposed under their sequence identity.
        series_metrics_by_aov = {}
    else:
        series_metrics_by_aov = _series_metrics(frame_metrics)

    definitions = (
        default_rule_definitions() if rule_definitions is None else tuple(rule_definitions)
    )
    if options.enabled_rules is not None:
        selected_rule_ids = set(options.enabled_rules)
        definitions = tuple(
            replace(definition, enabled=definition.id in selected_rule_ids)
            for definition in definitions
        )
    enabled_rule_ids = tuple(definition.id for definition in definitions if definition.enabled)
    report = AnalysisReport(
        source=discovery.source,
        frames=discovery.frames,
        inspections=tuple(inspections),
        metrics_by_aov=metrics_by_aov,
        successful_frames=tuple(successful_frames),
        failed_frames=tuple(failed_frames),
        findings=tuple(findings),
        warnings=(
            discovery.warnings + sequence_check.warnings
            if source_kind is SourceKind.NUMBERED_SEQUENCE
            else discovery.warnings
        ),
        rules_executed=enabled_rule_ids,
        sequence_check=sequence_check,
        channel_metrics_by_aov=channel_metrics_by_aov,
        frame_metrics=frame_metrics,
        source_kind=source_kind,
        series_metrics_by_aov=series_metrics_by_aov,
        series_metrics_by_sequence=sequence_series,
        memory_estimates=memory_estimates,
        frame_execution=frame_execution,
        frame_channel_metrics=frame_channel_metrics,
        effective_rules=tuple({
            "id": definition.id,
            "enabled": definition.enabled,
            "severity": definition.severity.value,
            "parameters": effective_rule_parameters(definition),
            "supported_aov_types": sorted(value.value for value in definition.supported_aov_types),
        } for definition in definitions),
    )
    rule_findings = execute_rules(report, definitions)
    if not rule_findings:
        return report
    return replace(report, findings=report.findings + rule_findings)
