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

ROOT = Path(__file__).resolve().parents[1]


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


def format_summary_text(report: dict[str, Any]) -> str:
    """Format human-readable profiling summary for terminal/logs."""
    summary = report["summary"]
    status_marker = "✓" if report["passed"] else "✗"
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

    lines.append("\nLane Breakdown:")
    for lane_name, lane_data in report["lanes"].items():
        shard_info = f"{lane_data['shard_count']} shard(s)"
        imbal_info = (
            f"imbalance: {lane_data['imbalance_seconds']:.2f}s" if lane_data["shard_count"] > 1 else "single shard"
        )
        lines.append(
            f"  - {lane_name:<14} [{lane_data['severity'].upper()}]: "
            f"{lane_data['module_count']:>3} mods ({lane_data['observed_module_count']:>3} obs) | "
            f"base: {lane_data['projected_baseline_seconds']:>7.2f}s | "
            f"eff: {lane_data['effective_projected_seconds']:>7.2f}s | "
            f"{shard_info} ({imbal_info})"
        )
        if lane_data["shard_count"] > 1:
            for shard in lane_data["current_shards"]:
                lines.append(
                    f"      Shard {shard['index']}: {shard['module_count']:>2} mods | "
                    f"base: {shard['projected_baseline_seconds']:>6.2f}s | "
                    f"eff: {shard['effective_projected_seconds']:>6.2f}s | "
                    f"diff: {shard['drift_seconds']:>+6.2f}s"
                )

    if report.get("module_drifts"):
        notable = [d for d in report["module_drifts"] if d["severity"] in ("critical", "warning")][:10]
        if notable:
            lines.append("\nNotable Module Drifts:")
            for d in notable:
                tag = "[NEW]" if d["is_new_module"] else ""
                lines.append(
                    f"  - {d['module']:<48} [{d['severity'].upper()} {tag}]: "
                    f"obs: {d['observed_seconds']:>6.2f}s "
                    f"(base: {d['baseline_seconds']:>6.2f}s, "
                    f"diff: {d['drift_seconds']:>+6.2f}s / {d['drift_ratio'] * 100:>+5.1f}%)"
                )

    if report.get("warnings"):
        lines.append("\nWarnings:")
        for w in report["warnings"][:5]:
            lines.append(f"  ! {w}")

    if report.get("errors"):
        lines.append("\nErrors:")
        for e in report["errors"][:5]:
            lines.append(f"  * {e}")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", action="append", help="Path or glob to JUnit XML file(s)")
    parser.add_argument("--durations-log", action="append", help="Path to pytest --durations=0 stdout/log file")
    parser.add_argument(
        "--durations-json", action="append", help="Path to JSON file containing module durations mapping"
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
        type=Path,
        default=Path("test-lane-profiling-report.json"),
        help="Output path for deterministic machine-readable report",
    )
    parser.add_argument(
        "--update", action="store_true", help="Explicitly update checked-in duration baseline with observed timings"
    )
    parser.add_argument(
        "--write-baseline",
        type=Path,
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
        "--policy-path", type=Path, default=ROOT / "config/test-lanes.json", help="Path to test-lanes policy JSON"
    )
    parser.add_argument(
        "--baseline-path",
        type=Path,
        default=ROOT / "config/test-duration-baseline.json",
        help="Path to test-duration-baseline JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    policy: TestLanePolicy = load_lane_policy(args.policy_path)
    baseline: DurationBaseline = load_duration_baseline(args.baseline_path)

    observed_durations: dict[str, float] = {}
    collection_errors: list[str] = []

    # Ingest from JUnit XML
    if args.junit:
        for junit_pattern in args.junit:
            durations, errs = parse_junit_durations(junit_pattern, root=ROOT)
            observed_durations.update(durations)
            collection_errors.extend(errs)

    # Ingest from durations log
    if args.durations_log:
        for log_path in args.durations_log:
            durations, errs = parse_durations_log(log_path, root=ROOT)
            observed_durations.update(durations)
            collection_errors.extend(errs)

    # Ingest from durations JSON
    if args.durations_json:
        for json_path in args.durations_json:
            p = Path(json_path)
            if not p.is_file():
                collection_errors.append(f"Durations JSON file not found: {p}")
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    if "module_seconds" in data and isinstance(data["module_seconds"], dict):
                        data = data["module_seconds"]
                    for k, v in data.items():
                        if isinstance(v, (int, float)) and v > 0:
                            observed_durations[k] = round(float(v), 3)
            except Exception as exc:
                collection_errors.append(f"Failed to parse durations JSON {p}: {exc}")

    # Run on-demand pytest if requested
    if args.run:
        run_durations, run_errs = run_pytest_profiling(
            lane=args.run_lane,
            pytest_args=args.pytest_args,
            root=ROOT,
        )
        observed_durations.update(run_durations)
        collection_errors.extend(run_errs)

    # Fallback auto-discovery of local JUnit files if no explicit inputs were provided
    if not args.junit and not args.durations_log and not args.durations_json and not args.run:
        default_junits = sorted(ROOT.glob("junit-lane-*.xml")) + sorted(ROOT.glob("junit*.xml"))
        if default_junits:
            for j_path in default_junits:
                durations, errs = parse_junit_durations(j_path, root=ROOT)
                observed_durations.update(durations)
                collection_errors.extend(errs)

    thresholds = DriftThresholds(
        module_warning_seconds=args.warning_drift_seconds,
        module_warning_ratio=args.warning_drift_ratio,
        module_critical_seconds=args.critical_drift_seconds,
        module_critical_ratio=args.critical_drift_ratio,
        shard_imbalance_warning_seconds=args.warning_shard_imbalance_seconds,
        shard_imbalance_critical_seconds=args.critical_shard_imbalance_seconds,
    )

    report = calculate_lane_shard_profile(
        policy=policy,
        baseline=baseline,
        observed_durations=observed_durations,
        thresholds=thresholds,
        target_lane=args.lane,
        root=ROOT,
    )
    if collection_errors:
        report["errors"].extend(collection_errors)
        if report["passed"]:
            report["passed"] = False
            report["status"] = "drift_critical"

    # Write profiling report
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Update baseline if requested
    if args.update or args.write_baseline:
        target_baseline_path = args.write_baseline or args.baseline_path
        updated_baseline = update_duration_baseline_data(
            baseline=baseline,
            observed_durations=observed_durations,
            measured_at=args.measured_at,
            source=args.source,
            update_all=args.update_all,
            prune_missing=args.prune_missing,
            root=ROOT,
        )
        save_duration_baseline(updated_baseline, path=target_baseline_path)
        if not args.quiet:
            print(f"Updated duration baseline written to: {target_baseline_path}")

    if not args.quiet:
        print(format_summary_text(report))

    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
