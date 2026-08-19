#!/usr/bin/env python3
"""Validate test-lane classification and emit deterministic inventory evidence."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from tests.lane_policy import (
    PRIMARY_LANES,
    assign_module_shards,
    classify_test_path,
    load_duration_baseline,
    load_lane_policy,
    module_weight,
)

ROOT = Path(__file__).resolve().parents[1]


def build_inventory(root: Path = ROOT) -> dict[str, Any]:
    policy = load_lane_policy(root / "config/test-lanes.json")
    baseline = load_duration_baseline(root / "config/test-duration-baseline.json")
    modules = sorted((root / "tests").glob("test_*.py"))
    lanes: dict[str, list[str]] = {lane: [] for lane in PRIMARY_LANES}
    errors: list[str] = []

    for module in modules:
        relative = str(module.relative_to(root)).replace("\\", "/")
        try:
            lane = classify_test_path(relative, policy)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        lanes[lane].append(relative)

    missing_baseline = sorted(path for path in baseline.module_seconds if not (root / path).is_file())
    errors.extend(f"duration baseline references missing module: {path}" for path in missing_baseline)
    empty_required = sorted(lane for lane in policy.required_execution_lanes if not lanes[lane])
    errors.extend(f"required execution lane has no modules: {lane}" for lane in empty_required)

    shard_evidence: dict[str, Any] = {}
    for lane, shard_count in policy.shard_counts.items():
        weights = {path: module_weight(path, baseline) for path in lanes[lane]}
        assignments = assign_module_shards(weights, shard_count=shard_count)
        shard_evidence[lane] = [
            {
                "index": index + 1,
                "module_count": sum(1 for shard in assignments.values() if shard == index),
                "projected_seconds": round(
                    sum(weights[path] for path, shard in assignments.items() if shard == index), 3
                ),
                "modules": sorted(path for path, shard in assignments.items() if shard == index),
            }
            for index in range(shard_count)
        ]

    counts = Counter({lane: len(paths) for lane, paths in lanes.items()})
    return {
        "schema_version": "1.0",
        "gate_id": "test-lane-policy-v1",
        "passed": not errors,
        "default_lane": policy.default_lane,
        "runtime_budgets_seconds": policy.runtime_budgets_seconds,
        "counts": {lane: counts[lane] for lane in PRIMARY_LANES},
        "lanes": lanes,
        "shards": shard_evidence,
        "duration_baseline": {
            "measured_at": baseline.measured_at,
            "source": baseline.source,
            "explicit_module_count": len(baseline.module_seconds),
        },
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("test-lane-inventory.json"))
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    report = build_inventory()
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
