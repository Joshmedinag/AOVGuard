"""Verify an explicitly selected local EXR sequence without modifying its inputs.

Run from an installed checkout with ``python -m scripts.verify_real_sequence --help``.
Real renders are opt-in inputs, never bundled fixtures. Verification success and
the render's PASS/WARNING/FAIL status are separate results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import stat
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from aovguard.discovery.frame_discovery import discover_frames
from scripts.verification_memory import ProcessTreeMonitor
from scripts.verification_process import capture_descendants

PROFILE_KEYS = {
    "schema_version", "description", "metadata", "dimensions", "channel_count",
    "findings", "outliers_by_aov", "nonfinite_counts", "sequence_summary",
}
METADATA_COUNTS = {
    "frames_discovered", "frames_processed", "frames_failed", "aovs_detected",
    "aovs_analyzed", "color_aovs_analyzed", "technical_aovs_diagnosed", "aovs_diagnosed",
}
COUNT_FIELDS = ("nan_count", "posinf_count", "neginf_count")
SEQUENCE_FIELDS = {
    "sequence_count", "unnumbered_file_count", "missing_frame_count", "duplicate_frame_count",
}


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"Nonstandard JSON number: {value}")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"JSON number exceeds finite precision: {value}")
    return number


def read_json(path: Path) -> dict[str, Any]:
    """Read a strict JSON object, rejecting duplicate keys and NaN/Infinity."""

    value = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_constant,
        parse_float=_finite_float,
        object_pairs_hook=_object,
    )
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any] | list[dict[str, Any]]) -> None:
    """Write a new owned evidence file without replacing an existing target."""

    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def sha256(path: Path) -> str:
    """Hash an input or report using bounded read buffers."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def prepare_output(output: Path, source: Path, protected: list[Path]) -> Path:
    """Reserve a new evidence directory outside the input tree and linked ancestors."""

    output = output.absolute()
    if output.suffix.casefold() == ".exr":
        raise ValueError("The evidence directory must not have an EXR suffix")
    for ancestor in (output, *output.parents):
        if ancestor.exists() or ancestor.is_symlink():
            if _is_link(ancestor):
                raise ValueError(f"Linked evidence destination is not supported: {ancestor}")
    resolved = output.resolve()
    if resolved.is_relative_to(source.resolve()):
        raise ValueError("Evidence must be stored outside the source render directory")
    if any(path.resolve().is_relative_to(resolved) for path in protected):
        raise ValueError("Evidence destination contains a protected input")
    output.mkdir(parents=True, exist_ok=False)
    return output


def inventory(
    source: Path, pattern: str, *, recursive: bool, max_depth: int, hash_source: bool,
) -> list[dict[str, Any]]:
    """Record the canonical selection's relative names, sizes and write timestamps."""

    discovery = discover_frames(source, pattern=pattern, recursive=recursive, max_depth=max_depth)
    entries: list[dict[str, Any]] = []
    for path in discovery.frames:
        resolved = path.resolve()
        if not resolved.is_relative_to(source) or _is_link(path):
            raise ValueError(f"Linked or escaping EXR input is not supported: {path}")
        info = path.stat()
        entry: dict[str, Any] = {
            "name": path.relative_to(source).as_posix(),
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
        }
        if hash_source:
            entry["sha256"] = sha256(path)
        entries.append(entry)
    return entries


def _count(value: Any, label: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")


def _count_map(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object of counts")
    for key, count in value.items():
        _count(count, f"{label}.{key}")


def load_expectations(path: Path | None) -> dict[str, Any]:
    """Load a strict expectation profile; unknown/mistyped policies fail before decoding."""

    if path is None:
        return {"schema_version": 1}
    profile = read_json(path)
    if type(profile.get("schema_version")) is not int or profile["schema_version"] != 1:
        raise ValueError("Expectation schema_version must be 1")
    if unknown := set(profile) - PROFILE_KEYS:
        raise ValueError(f"Unknown expectation fields: {sorted(unknown)}")
    if "description" in profile and not isinstance(profile["description"], str):
        raise ValueError("Expectation description must be text")
    expected = profile.get("metadata", {})
    if not isinstance(expected, dict):
        raise ValueError("Expectation metadata must be an object")
    allowed = METADATA_COUNTS | {"status", "summary_by_aov_category", "summary_by_severity"}
    if set(expected) - allowed:
        raise ValueError(f"Unknown metadata expectations: {sorted(set(expected) - allowed)}")
    for key, value in expected.items():
        if key in METADATA_COUNTS:
            _count(value, f"metadata.{key}")
        elif key == "status":
            if value not in ("pass", "warning", "fail"):
                raise ValueError("Expected status must be pass, warning or fail")
        else:
            _count_map(value, f"metadata.{key}")
    for key in ("outliers_by_aov", "nonfinite_counts", "sequence_summary"):
        if key in profile:
            _count_map(profile[key], key)
    if set(profile.get("nonfinite_counts", {})) - set(COUNT_FIELDS):
        raise ValueError("Unknown nonfinite count fields")
    if set(profile.get("sequence_summary", {})) - SEQUENCE_FIELDS:
        raise ValueError("Unknown sequence summary fields")
    if "channel_count" in profile:
        _count(profile["channel_count"], "channel_count")
    if "dimensions" in profile:
        dims = profile["dimensions"]
        if not isinstance(dims, list) or len(dims) != 2:
            raise ValueError("dimensions must contain width and height")
        for dimension in dims:
            _count(dimension, "dimension")
            if not dimension:
                raise ValueError("Dimensions must be positive")
    if "findings" in profile:
        if not isinstance(profile["findings"], list):
            raise ValueError("findings must be a list")
        for finding in profile["findings"]:
            if not isinstance(finding, dict) or set(finding) - {"rule_id", "severity", "aov"}:
                raise ValueError("Finding expectations use rule_id, severity and optional aov")
            if not isinstance(finding.get("rule_id"), str) or not finding["rule_id"]:
                raise ValueError("Finding rule_id must be non-empty text")
            if finding.get("severity") not in ("error", "warning", "info"):
                raise ValueError("Finding severity must be error, warning or info")
            if finding.get("aov") is not None and not isinstance(finding["aov"], str):
                raise ValueError("Finding aov must be text or null")
    return profile


def audit_report(
    payload: dict[str, Any], profile: dict[str, Any], selected_paths: list[str],
) -> dict[str, Any]:
    """Check report completeness, preserved channels, finite counts and expected outcomes.

    This checks exported evidence, not an independent remeasurement of source pixels.
    """

    problems: list[str] = []
    checks = 0

    def check(condition: bool, label: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            problems.append(label)

    meta = payload["metadata"]
    frames, successful, failed = (
        payload[key] for key in ("frames", "successful_frames", "failed_frames")
    )
    check(payload["schema_version"] == "1.2", "supported_report_schema")
    check(frames == selected_paths, "selected_frames_exact_order")
    for label, paths in (("discovered", frames), ("successful", successful), ("failed", failed)):
        check(len(paths) == len(set(paths)), f"unique_{label}_paths")
    check(set(successful).isdisjoint(failed), "disjoint_success_and_failure")
    check(set(successful) | set(failed) == set(frames), "complete_frame_partition")
    for key, paths in (
        ("frames_discovered", frames), ("frames_processed", successful), ("frames_failed", failed),
    ):
        check(meta[key] == len(paths), f"metadata_{key}")
    expected_meta = profile.get("metadata", {})
    for key, value in expected_meta.items():
        check(meta.get(key) == value, f"expected_metadata_{key}")
    check(meta["frames_failed"] == expected_meta.get("frames_failed", 0), "expected_failed_frames")
    check(bool(successful) or expected_meta.get("status") == "fail", "processed_frames_present")
    findings = payload["findings"]
    check(dict(Counter(item["severity"] for item in findings)) == meta["summary_by_severity"],
          "severity_summary")
    status = (
        "fail" if failed or any(item["severity"] == "error" for item in findings)
        else "warning" if payload["warnings"] or any(
            item["severity"] == "warning" for item in findings
        ) else "pass"
    )
    check(meta["status"] == status, "render_status_consistent")
    check(status != "fail" or expected_meta.get("status") == "fail", "no_unexpected_render_failure")
    if "findings" in profile:
        def signature(item: dict[str, Any]) -> tuple[str, str, str | None]:
            return item["rule_id"], item["severity"], item.get("aov")

        check(Counter(map(signature, findings)) == Counter(map(signature, profile["findings"])),
              "expected_findings_exact")
    inspections = {item["path"]: item for item in payload["inspections"]}
    check(len(inspections) == len(payload["inspections"]), "unique_inspections")
    check(set(inspections).issubset(frames), "inspection_paths_in_selection")
    check(set(successful).issubset(inspections), "successful_frames_inspected")
    inventory_names = {item["name"] for item in payload["aov_inventory"]}
    detected_names: set[str] = set()
    for inspection in inspections.values():
        descriptors = inspection["aovs"]
        detected_names.update(item["name"] for item in descriptors)
        channels = [channel for item in descriptors for channel in item["channels"]]
        check(Counter(channels) == Counter(inspection["channels"]), "inspection_channel_partition")
        if "channel_count" in profile:
            check(len(channels) == profile["channel_count"], "expected_channel_count")
        if "dimensions" in profile:
            check([inspection["width"], inspection["height"]] == profile["dimensions"],
                  "expected_dimensions")
    check(inventory_names == detected_names, "inventory_preserves_detected_aovs")
    check(meta["aovs_detected"] == len(inventory_names), "metadata_detected_aovs")
    check(set(payload["frame_metrics"]) == set(successful), "frame_luminance_partition")
    check(set(payload["frame_channel_metrics"]) == set(successful), "frame_channel_partition")
    for path in successful:
        inspection = inspections[path]
        metrics = payload["frame_channel_metrics"][path]
        channels = [channel for aov in metrics.values() for channel in aov]
        check(Counter(channels) == Counter(inspection["channels"]), "successful_frame_all_channels")
        color_names = {item["name"] for item in inspection["aovs"] if item["category"] == "color"}
        check(set(payload["frame_metrics"][path]) == color_names, "only_color_luminance")
        parts = {part["index"]: part for part in inspection.get("parts", [])}
        check(not inspection.get("is_deep", False), "successful_frame_is_flat")
        for descriptor in inspection["aovs"]:
            part = parts.get(descriptor.get("part_index", 0))
            if part is None:
                check(inspection.get("part_count", 1) == 1, "multipart_dimensions_available")
                part = inspection
            width, height = part["width"], part["height"]
            check(type(width) is int and type(height) is int and width > 0 and height > 0,
                  "positive_part_dimensions")
            if window := part.get("data_window"):
                check([window[1][0] - window[0][0] + 1,
                       window[1][1] - window[0][1] + 1] == [width, height],
                      "part_dimensions_match_data_window")
            for channel in descriptor["channels"]:
                values = metrics.get(descriptor["name"], {}).get(channel)
                check(values is not None and values.get("pixel_count") == width * height,
                      "channel_pixel_count_matches_part")
            if descriptor["category"] == "color":
                values = payload["frame_metrics"][path].get(descriptor["name"])
                check(values is not None and values.get("pixel_count") == width * height,
                      "luminance_pixel_count_matches_part")
    aggregate_channels = {
        channel for aov in payload["channel_metrics_by_aov"].values() for channel in aov
    }
    measured_channels = {
        channel for frame in payload["frame_channel_metrics"].values()
        for aov in frame.values() for channel in aov
    }
    check(aggregate_channels == measured_channels, "aggregate_preserves_measured_channels")
    for aov in payload["channel_metrics_by_aov"].values():
        for channel, values in aov.items():
            frame_values = [
                channels[channel] for frame in payload["frame_channel_metrics"].values()
                for channels in frame.values() if channel in channels
            ]
            for field in ("pixel_count", *COUNT_FIELDS, "negative_count"):
                check(values[field] == sum(item[field] for item in frame_values),
                      f"aggregate_channel_{field}")
    counts = {
        key: sum(metrics[key] for aov in payload["channel_metrics_by_aov"].values()
                 for metrics in aov.values())
        for key in COUNT_FIELDS
    }
    for key in COUNT_FIELDS:
        check(counts[key] == profile.get("nonfinite_counts", {}).get(key, 0), f"expected_{key}")
    summary = payload["sequence_check"]["summary"]
    expected_sequence = {
        "sequence_count": 1, "unnumbered_file_count": 0,
        "missing_frame_count": 0, "duplicate_frame_count": 0,
        **profile.get("sequence_summary", {}),
    }
    for key, value in expected_sequence.items():
        check(summary[key] == value, f"expected_sequence_{key}")
    outliers = {
        name: len(metrics["outlier_frames"])
        for name, metrics in payload["series_metrics_by_aov"].items() if metrics["outlier_frames"]
    }
    color_names = {name for frame in payload["frame_metrics"].values() for name in frame}
    check(set(payload["series_metrics_by_aov"]) == color_names, "only_color_series")
    for name, series in payload["series_metrics_by_aov"].items():
        eligible = {path for path, values in payload["frame_metrics"].items() if name in values}
        check(set(series["outlier_frames"]).issubset(eligible), "outlier_paths_in_aov_scope")
        check(len(series["outlier_frames"]) == len(set(series["outlier_frames"])),
              "unique_outlier_paths")
    if "outliers_by_aov" in profile:
        check(set(profile["outliers_by_aov"]).issubset(color_names), "expected_outlier_aovs_exist")
        check(outliers == {key: value for key, value in profile["outliers_by_aov"].items() if value},
              "expected_outliers_exact")
    return {"passed": not problems, "checks": checks, "problems": problems,
            "nonfinite_counts": counts, "outliers_by_aov": outliers}


def _stop_process(process: subprocess.Popen[Any]) -> None:
    """Interrupt this owned process group, then force cleanup only if still running."""

    captured = None
    capture_error = None
    try:
        captured = capture_descendants(process.pid)
    except RuntimeError as exc:
        capture_error = exc
    try:
        if process.poll() is None:
            try:
                if os.name == "nt":
                    process.send_signal(getattr(signal, "CTRL_BREAK_EVENT"))
                else:
                    getattr(os, "killpg")(process.pid, signal.SIGINT)
                process.wait(timeout=35)
            except (OSError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            capture_output=True, check=False, timeout=20,
                        )
                    else:
                        getattr(os, "killpg")(process.pid, getattr(signal, "SIGKILL"))
                    process.wait(timeout=20)
        if capture_error is not None:
            raise capture_error
    finally:
        if captured is not None:
            try:
                captured.stop()
            finally:
                captured.close()


def run_command(command: list[str], log: Path, deadline_seconds: float) -> dict[str, Any]:
    """Run an argument-list command with process-tree sampling and a bounded job deadline."""

    started = time.monotonic()
    with log.open("x", encoding="utf-8") as stream:
        process = subprocess.Popen(
            command, stdout=stream, stderr=subprocess.STDOUT, shell=False,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP") if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        monitor = ProcessTreeMonitor(process.pid)
        cleanup: dict[str, Any] = {"confirmed": False}
        try:
            while True:
                monitor.sample()
                code = process.poll()
                if code is not None:
                    break
                if time.monotonic() - started >= deadline_seconds:
                    raise TimeoutError(f"Verification job exceeded {deadline_seconds:g} seconds")
                time.sleep(0.1)
            captured = capture_descendants(process.pid)
            try:
                survivors = captured.pids
                captured.stop()
                cleanup = {"confirmed": True, "descendants_observed_after_parent_exit": survivors}
                if survivors:
                    raise RuntimeError(f"Process descendants survived their parent: {survivors}")
            finally:
                captured.close()
        except BaseException:
            _stop_process(process)
            cleanup["confirmed"] = True
            raise
        finally:
            measurement = {"command": command, "exit_code": process.poll(),
                           "elapsed_seconds_including_startup_exports": time.monotonic() - started,
                           "memory": monitor.result(), "cleanup": cleanup}
            write_json(log.with_suffix(".measurement.json"), measurement)
    return measurement


def build_cli_command(args: argparse.Namespace, output: Path) -> list[str]:
    """Build the canonical isolated CLI invocation without shell interpolation."""

    entry = (
        "import signal; "
        "hasattr(signal, 'SIGBREAK') and signal.signal(signal.SIGBREAK, signal.default_int_handler); "
        "from aovguard.cli import main; raise SystemExit(main())"
    )
    command = [
        sys.executable, "-B", "-c", entry, "analyze", str(args.source),
        "--source-mode", "sequence", "--frame-pattern", args.frame_pattern,
        "--expected-frame-range", *(str(value) for value in args.expected_frame_range),
        "--max-frames", str(args.max_frames), "--luminance-model", args.luminance_model,
        "--max-memory-mb", str(args.max_memory_mb),
        "--frame-timeout-seconds", str(args.frame_timeout_seconds),
        "--max-depth", str(args.max_depth),
        "--json", str(output / "analysis.json"), "--html", str(output / "analysis.html"),
    ]
    if args.recursive:
        command.append("--recursive")
    if args.preset:
        command.extend(("--rules-config", str(args.preset)))
    return command


def _positive_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("Value must be positive and finite")
    return result


def _positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("Value must be a positive integer")
    return result


def parser() -> argparse.ArgumentParser:
    """Build the opt-in verifier interface with explicit source and color intent."""

    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("source", type=Path, help="Existing external render directory")
    result.add_argument("--output-directory", type=Path, required=True, help="New evidence directory")
    result.add_argument("--frame-pattern", required=True, help="One sequence's filename pattern")
    result.add_argument("--expected-frame-range", required=True, type=int, nargs=2,
                        metavar=("START", "END"))
    result.add_argument("--luminance-model", required=True,
                        choices=("rec709", "rec601", "acescg", "ap1"))
    result.add_argument("--expect", type=Path, help="Version-1 JSON expected-outcome profile")
    result.add_argument("--preset", type=Path, help="Existing TOML/JSON rule preset, never modified")
    result.add_argument("--max-frames", type=_positive_int,
                        help="Discovery limit; defaults to expected range length, not truncation")
    result.add_argument("--max-memory-mb", type=_positive_float, default=4096.0)
    result.add_argument("--frame-timeout-seconds", type=_positive_float, default=60.0)
    result.add_argument("--deadline-seconds", type=_positive_float, default=3600.0,
                        help="Maximum wall time for each analysis job; cleanup has separate grace")
    result.add_argument("--recursive", action="store_true")
    result.add_argument("--max-depth", type=_positive_int, default=1)
    result.add_argument("--hash-source", action="store_true", help="Also hash every selected EXR twice")
    result.add_argument("--gui", action="store_true", help="Repeat through optional offscreen Qt GUI")
    result.add_argument("--check-cancellation", action="store_true",
                        help="With --gui, require active-worker cancellation and restart")
    return result


def verify(args: argparse.Namespace) -> dict[str, Any]:
    """Analyze the chosen inputs, preserve diagnostics on failure and check input immutability."""

    args.source = args.source.resolve(strict=True)
    if not args.source.is_dir():
        raise ValueError("source must be an existing render directory")
    if args.expected_frame_range[0] > args.expected_frame_range[1]:
        raise ValueError("Expected frame range must be ascending")
    if args.check_cancellation and not args.gui:
        raise ValueError("--check-cancellation requires --gui")
    if args.gui and find_spec("PySide6") is None:
        raise ValueError("--gui requires the optional PySide6 GUI extra")
    args.max_frames = args.max_frames or args.expected_frame_range[1] - args.expected_frame_range[0] + 1
    protected = [path.resolve(strict=True) for path in (args.expect, args.preset) if path]
    profile = load_expectations(args.expect)
    options = {"recursive": args.recursive, "max_depth": args.max_depth,
               "hash_source": args.hash_source}
    before = inventory(args.source, args.frame_pattern, **options)
    if not before:
        raise ValueError("No EXRs match the requested selection")
    if len(before) > args.max_frames:
        raise ValueError(f"Selection has {len(before)} frames, exceeding --max-frames {args.max_frames}")
    protected_before = {str(path): sha256(path) for path in protected}
    output = prepare_output(args.output_directory, args.source, protected)
    write_json(output / "inventory-before.json", before)
    result: dict[str, Any] = {
        "schema_version": 1, "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(args.source), "source_pattern": args.frame_pattern,
        "passed": False, "expectations": profile, "failures": [],
        "source_unchanged": False, "protected_inputs_unchanged": False,
        "runtime": {"python": sys.version.split()[0], "platform": sys.platform,
                    "packages": {name: metadata.version(name) for name in (
                        "aovguard", "OpenEXR", "numpy", *(("PySide6",) if args.gui else ()),
                    )}},
        "preservation_method": "names/size/mtime_ns" + ("/sha256" if args.hash_source else ""),
        "source_total_bytes": sum(item["size"] for item in before),
        "protected_input_sha256": protected_before,
    }
    try:
        result["cli"] = run_command(build_cli_command(args, output), output / "cli.log",
                                    args.deadline_seconds)
        payload = read_json(output / "analysis.json")
        result["render_metadata"] = payload["metadata"]
        selected_paths = [str(args.source / entry["name"]) for entry in before]
        result["audit"] = audit_report(payload, profile, selected_paths)
        result["failures"].extend(result["audit"]["problems"])
        expected_exit = 1 if payload["metadata"]["status"] == "fail" else 0
        if result["cli"]["exit_code"] != expected_exit:
            result["failures"].append("cli_exit_code_inconsistent")
        html = output / "analysis.html"
        if not html.is_file() or html.stat().st_size == 0:
            result["failures"].append("html_export_missing_or_empty")
        if args.gui and not result["failures"]:
            command = [sys.executable, "-B", str(Path(__file__).with_name("verify_gui_sequence.py")),
                       "--baseline", str(output / "analysis.json"),
                       "--output-directory", str(output / "gui"),
                       "--deadline-seconds", str(args.deadline_seconds)]
            if args.preset:
                command.extend(("--preset", str(args.preset.resolve())))
            if args.check_cancellation:
                command.append("--check-cancellation")
            result["gui_process"] = run_command(
                command, output / "gui-process.log", args.deadline_seconds + 120,
            )
            result["gui"] = read_json(output / "gui/gui-acceptance.json")
            if result["gui_process"]["exit_code"] != 0 or not result["gui"].get("passed"):
                result["failures"].append("gui_acceptance_failed")
        elif args.gui:
            result["gui"] = {"passed": False, "skipped": "CLI verification failed"}
    except (Exception, KeyboardInterrupt) as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        result["interrupted"] = isinstance(exc, KeyboardInterrupt)
    finally:
        try:
            after = inventory(args.source, args.frame_pattern, **options)
            write_json(output / "inventory-after.json", after)
            result["source_unchanged"] = before == after
            if not result["source_unchanged"]:
                result["failures"].append("source_inventory_changed")
            result["protected_inputs_unchanged"] = all(
                path.is_file() and sha256(path) == protected_before[str(path)] for path in protected
            )
            if not result["protected_inputs_unchanged"]:
                result["failures"].append("protected_inputs_changed")
        except Exception as exc:
            result["failures"].append(f"Preservation check failed: {type(exc).__name__}: {exc}")
        result["artifacts"] = {
            path.relative_to(output).as_posix(): {"size": path.stat().st_size, "sha256": sha256(path)}
            for path in sorted(output.rglob("*")) if path.is_file()
        }
        result["passed"] = not result["failures"]
        write_json(output / "verification-summary.json", result)
    result["summary_path"] = str(output / "verification-summary.json")
    return result


def main(argv: list[str] | None = None) -> int:
    """Run opt-in verification; return 0 for matched evidence, 1 for mismatch and 130 for Ctrl+C."""

    args = parser().parse_args(argv)
    try:
        result = verify(args)
    except KeyboardInterrupt:
        print(json.dumps({"passed": False, "interrupted": True, "error": "KeyboardInterrupt"}))
        return 130
    except Exception as exc:
        print(json.dumps({"passed": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps({key: result.get(key) for key in (
        "passed", "summary_path", "source_unchanged", "failures",
    )}, ensure_ascii=False, indent=2))
    return 130 if result.get("interrupted") else 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
