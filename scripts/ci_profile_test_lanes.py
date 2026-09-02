#!/usr/bin/env python3
"""Profile test-lane execution durations, detect shard timing drift, and refresh baselines."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from tests.lane_policy import (
    PRIMARY_LANES,
    DriftThresholds,
    DurationBaseline,
    TestLanePolicy,
    calculate_lane_shard_profile,
    load_duration_baseline,
    load_lane_policy,
    parse_durations_log,
    parse_junit_durations,
    save_duration_baseline,
    update_duration_baseline_data,
)
from zaptrace.security.paths import resolve_trusted_path

ROOT = Path(__file__).resolve().parents[1]


def _repository_input_path(value: str) -> Path:
    """Resolve a CLI input path inside the repository trust boundary."""
    try:
        return resolve_trusted_path(value, trusted_root=ROOT, label="profiling input path")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _repository_output_path(value: str) -> Path:
    """Resolve a CLI output path inside the repository trust boundary."""
    try:
        return resolve_trusted_path(value, trusted_root=ROOT, label="profiling output path")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def run_pytest_profiling(
    *,
    lane: str = "unit",
    pytest_args: list[str] | None = None,
    root: Path = ROOT,
) -> tuple[dict[str, float], list[str]]:
    """Run pytest with lane policy and collect observed durations via JUnit XML."""
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        junit_xml = Path(tmpdir) / "junit-profiling.xml"
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.lane_policy",
            "--junitxml",
            str(junit_xml),
            "-o",
            "junit_family=legacy",
            "-q",
        ]
        if lane != "all":
            cmd.extend(["--lane", lane])
        if pytest_args:
            cmd.extend(pytest_args)

        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
        if proc.returncode not in (0, 5):  # 5 means no tests collected
            errors.append(f"Pytest run exited with code {proc.returncode}: {proc.stderr or proc.stdout}")

        if junit_xml.is_file():
            durations, parse_errs = parse_junit_durations(junit_xml, root=root)
            errors.extend(parse_errs)
            return durations, errors

        errors.append("Pytest run did not produce expected JUnit XML output.")
        return {}, errors


def _summary_header_lines(report: dict[str, Any]) -> list[str]:
    summary = report["summary"]
    status_marker = "OK" if report["passed"] else "FAIL"
    lines = [
        f"Test Lane Duration Profile Summary [{status_marker} {report['status'].upper()}]",
        (
            f"  Total modules: {summary['total_modules']} | "
            f"Observed: {summary['observed_modules']} | "
            f"Unobserved: {summary['unobserved_modules']} | "
            f"Unbaselined: {summary['unbaselined_modules']}"
        ),
        (
            f"  Total baseline weight: {summary['total_baseline_seconds']:.2f}s | "
            f"Observed total: {summary['total_observed_seconds']:.2f}s"
        ),
        f"  Drift counts: Critical: {summary['critical_drift_count']} | Warning: {summary['warning_drift_count']}",
    ]
    if summary.get("imbalanced_lanes"):
        lines.append(f"  Imbalanced lanes: {', '.join(summary['imbalanced_lanes'])}")
    return lines


def _format_shard_line(shard: dict[str, Any]) -> str:
    return (
        f"      Shard {shard['index']}: {shard['module_count']:>2} mods | "
        f"base: {shard['projected_baseline_seconds']:>6.2f}s | "
        f"eff: {shard['effective_projected_seconds']:>6.2f}s | "
        f"diff: {shard['drift_seconds']:>+6.2f}s"
    )


def _format_lane_lines(lanes: dict[str, Any]) -> list[str]:
    lines = ["\nLane Breakdown:"]
    for lane_name, lane_data in lanes.items():
        shard_count = lane_data["shard_count"]
        imbalance = f"imbalance: {lane_data['imbalance_seconds']:.2f}s" if shard_count > 1 else "single shard"
        lines.append(
            f"  - {lane_name:<14} [{lane_data['severity'].upper()}]: "
            f"{lane_data['module_count']:>3} mods ({lane_data['observed_module_count']:>3} obs) | "
            f"base: {lane_data['projected_baseline_seconds']:>7.2f}s | "
            f"eff: {lane_data['effective_projected_seconds']:>7.2f}s | "
            f"{shard_count} shard(s) ({imbalance})"
        )
        if shard_count > 1:
            lines.extend(_format_shard_line(shard) for shard in lane_data["current_shards"])
    return lines


def _format_notable_drift_lines(module_drifts: list[dict[str, Any]]) -> list[str]:
    notable = [item for item in module_drifts if item["severity"] in {"critical", "warning"}][:10]
    if not notable:
        return []
    lines = ["\nNotable Module Drifts:"]
    for item in notable:
        tag = "[NEW]" if item["is_new_module"] else ""
        lines.append(
            f"  - {item['module']:<48} [{item['severity'].upper()} {tag}]: "
            f"obs: {item['observed_seconds']:>6.2f}s "
            f"(base: {item['baseline_seconds']:>6.2f}s, "
            f"diff: {item['drift_seconds']:>+6.2f}s / {item['drift_ratio'] * 100:>+5.1f}%)"
        )
    return lines


def _format_message_lines(title: str, prefix: str, messages: list[str]) -> list[str]:
    if not messages:
        return []
    return [f"\n{title}:", *(f"  {prefix} {message}" for message in messages[:5])]


def format_summary_text(report: dict[str, Any]) -> str:
    """Format human-readable profiling summary for terminal/logs."""
    lines = _summary_header_lines(report)
    lines.extend(_format_lane_lines(report["lanes"]))
    lines.extend(_format_notable_drift_lines(report.get("module_drifts", [])))
    lines.extend(_format_message_lines("Warnings", "!", report.get("warnings", [])))
    lines.extend(_format_message_lines("Errors", "*", report.get("errors", [])))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", action="append", help="Path or glob to JUnit XML file(s)")
    parser.add_argument("--durations-log", action="append", help="Path to pytest --durations=0 stdout/log file")
    parser.add_argument(
        "--durations-json",
        action="append",
        type=_repository_input_path,
        help="Repository-contained JSON file containing module durations mapping",
    )
    parser.add_argument("--run", action="store_true", help="Execute pytest on-demand to collect fresh durations")
    parser.add_argument(
        "--run-lane",
        choices=(*PRIMARY_LANES, "all"),
        default="unit",
        help="Lane to run when --run is enabled (default: unit)",
    )
    parser.add_argument(
        "--pytest-args", nargs="*", help="Additional arguments forwarded to pytest when --run is enabled"
    )
    parser.add_argument(
        "--lane", choices=(*PRIMARY_LANES, "all"), default="all", help="Target lane to analyze (default: all)"
    )
    parser.add_argument(
        "--output",
        type=_repository_output_path,
        default=ROOT / "test-lane-profiling-report.json",
        help="Output path for deterministic machine-readable report",
    )
    parser.add_argument(
        "--update", action="store_true", help="Explicitly update checked-in duration baseline with observed timings"
    )
    parser.add_argument(
        "--write-baseline",
        type=_repository_output_path,
        help="Target path for updated duration baseline (default: config/test-duration-baseline.json)",
    )
    parser.add_argument(
        "--update-all",
        action="store_true",
        help="When updating, populate all test modules in repository with observed or default weights",
    )
    parser.add_argument(
        "--prune-missing",
        action="store_true",
        help="When updating, remove modules from baseline that no longer exist on disk",
    )
    parser.add_argument("--source", type=str, help="Custom provenance source description string for updated baseline")
    parser.add_argument(
        "--measured-at", type=str, help="Measurement date YYYY-MM-DD for updated baseline (default: current UTC date)"
    )
    parser.add_argument(
        "--warning-drift-seconds",
        type=float,
        default=2.0,
        help="Module drift warning threshold in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--warning-drift-ratio", type=float, default=0.30, help="Module drift warning ratio (default: 0.30)"
    )
    parser.add_argument(
        "--critical-drift-seconds",
        type=float,
        default=10.0,
        help="Module drift critical threshold in seconds (default: 10.0)",
    )
    parser.add_argument(
        "--critical-drift-ratio", type=float, default=0.50, help="Module drift critical ratio (default: 0.50)"
    )
    parser.add_argument(
        "--warning-shard-imbalance-seconds",
        type=float,
        default=20.0,
        help="Shard imbalance warning threshold in seconds (default: 20.0)",
    )
    parser.add_argument(
        "--critical-shard-imbalance-seconds",
        type=float,
        default=60.0,
        help="Shard imbalance critical threshold in seconds (default: 60.0)",
    )
    parser.add_argument(
        "--strict",
        "--fail-on-critical-drift",
        dest="strict",
        action="store_true",
        help="Exit with non-zero status if critical drift or errors occur",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress human-readable stdout summary")
    parser.add_argument(
        "--policy-path",
        type=_repository_input_path,
        default=ROOT / "config/test-lanes.json",
        help="Path to test-lanes policy JSON",
    )
    parser.add_argument(
        "--baseline-path",
        type=_repository_output_path,
        default=ROOT / "config/test-duration-baseline.json",
        help="Path to test-duration-baseline JSON",
    )
    return parser


def _merge_collection(
    target: dict[str, float],
    errors: list[str],
    collected: tuple[dict[str, float], list[str]],
) -> None:
    durations, collected_errors = collected
    target.update(durations)
    errors.extend(collected_errors)


def _load_durations_json(path: Path) -> tuple[dict[str, float], list[str]]:
    resolved = resolve_trusted_path(path, trusted_root=ROOT, label="durations JSON path")
    if not resolved.is_file():
        return {}, [f"Durations JSON file not found: {resolved}"]
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"Failed to parse durations JSON {resolved}: {exc}"]
    if not isinstance(data, dict):
        return {}, []
    values = data.get("module_seconds", data)
    if not isinstance(values, dict):
        return {}, []
    durations = {
        key: round(float(value), 3)
        for key, value in values.items()
        if isinstance(key, str) and isinstance(value, (int, float)) and value > 0
    }
    return durations, []


def _collect_explicit_inputs(args: argparse.Namespace) -> tuple[dict[str, float], list[str]]:
    observed: dict[str, float] = {}
    errors: list[str] = []
    for pattern in args.junit or []:
        _merge_collection(observed, errors, parse_junit_durations(pattern, root=ROOT))
    for log_path in args.durations_log or []:
        _merge_collection(observed, errors, parse_durations_log(log_path, root=ROOT))
    for json_path in args.durations_json or []:
        _merge_collection(observed, errors, _load_durations_json(json_path))
    if args.run:
        _merge_collection(
            observed,
            errors,
            run_pytest_profiling(lane=args.run_lane, pytest_args=args.pytest_args, root=ROOT),
        )
    return observed, errors


def _has_explicit_inputs(args: argparse.Namespace) -> bool:
    return bool(args.junit or args.durations_log or args.durations_json or args.run)


def _collect_default_junit() -> tuple[dict[str, float], list[str]]:
    observed: dict[str, float] = {}
    errors: list[str] = []
    paths = sorted(ROOT.glob("junit-lane-*.xml")) + sorted(ROOT.glob("junit*.xml"))
    for path in paths:
        _merge_collection(observed, errors, parse_junit_durations(path, root=ROOT))
    return observed, errors


def _collect_observed_durations(args: argparse.Namespace) -> tuple[dict[str, float], list[str]]:
    observed, errors = _collect_explicit_inputs(args)
    if _has_explicit_inputs(args):
        return observed, errors
    return _collect_default_junit()


def _thresholds_from_args(args: argparse.Namespace) -> DriftThresholds:
    return DriftThresholds(
        module_warning_seconds=args.warning_drift_seconds,
        module_warning_ratio=args.warning_drift_ratio,
        module_critical_seconds=args.critical_drift_seconds,
        module_critical_ratio=args.critical_drift_ratio,
        shard_imbalance_warning_seconds=args.warning_shard_imbalance_seconds,
        shard_imbalance_critical_seconds=args.critical_shard_imbalance_seconds,
    )


def _apply_collection_errors(report: dict[str, Any], errors: list[str]) -> None:
    if not errors:
        return
    report["errors"].extend(errors)
    if report["passed"]:
        report["passed"] = False
        report["status"] = "drift_critical"


def _write_report(report: dict[str, Any], output: Path | str) -> Path:
    target = resolve_trusted_path(output, trusted_root=ROOT, label="profiling output path")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _maybe_update_baseline(
    args: argparse.Namespace,
    baseline: DurationBaseline,
    observed_durations: dict[str, float],
) -> bool:
    if not (args.update or args.write_baseline):
        return False
    raw_target = args.write_baseline or args.baseline_path
    target = resolve_trusted_path(raw_target, trusted_root=ROOT, label="baseline target path")
    updated = update_duration_baseline_data(
        baseline=baseline,
        observed_durations=observed_durations,
        measured_at=args.measured_at,
        source=args.source,
        update_all=args.update_all,
        prune_missing=args.prune_missing,
        root=ROOT,
    )
    save_duration_baseline(updated, path=target)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    policy_path = resolve_trusted_path(args.policy_path, trusted_root=ROOT, label="policy path")
    baseline_path = resolve_trusted_path(args.baseline_path, trusted_root=ROOT, label="baseline path")
    policy: TestLanePolicy = load_lane_policy(policy_path)
    baseline: DurationBaseline = load_duration_baseline(baseline_path)
    observed_durations, collection_errors = _collect_observed_durations(args)
    report = calculate_lane_shard_profile(
        policy=policy,
        baseline=baseline,
        observed_durations=observed_durations,
        thresholds=_thresholds_from_args(args),
        target_lane=args.lane,
        root=ROOT,
    )
    _apply_collection_errors(report, collection_errors)
    _write_report(report, args.output)
    baseline_updated = _maybe_update_baseline(args, baseline, observed_durations)
    if baseline_updated and not args.quiet:
        print("Updated duration baseline written successfully.")
    if not args.quiet:
        # codeql[py/clear-text-logging-sensitive-data] -- Summary contains only test module paths and timing data; no secrets or credentials are present in profiling reports.
        print(format_summary_text(report))
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
