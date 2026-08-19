"""Policy tests for bounded and independently observable pytest lanes."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from tests.lane_policy import (
    PRIMARY_LANES,
    TestLanePolicy,
    _required_execution_failed,
    assign_module_shards,
    classify_test_path,
    load_duration_baseline,
    load_lane_policy,
)

ROOT = Path(__file__).resolve().parents[1]


def test_lane_policy_has_explicit_default_and_approved_lanes() -> None:
    policy = load_lane_policy(ROOT / "config/test-lanes.json")

    assert policy.schema_version == "1.0"
    assert policy.default_lane == "unit"
    assert tuple(policy.primary_lanes) == PRIMARY_LANES
    assert set(policy.runtime_budgets_seconds) == set(PRIMARY_LANES)
    assert policy.runtime_budgets_seconds["unit"] <= 600


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_models.py", "unit"),
        ("tests/test_api_server.py", "integration"),
        ("tests/test_convergence_12_families.py", "benchmark"),
        ("tests/test_kicad_oracle.py", "external_tool"),
        ("tests/test_generated_board_acceptance.py", "hardware"),
        ("tests/test_native_boundary.py", "native"),
    ],
)
def test_lane_classification_is_stable(path: str, expected: str) -> None:
    policy = load_lane_policy(ROOT / "config/test-lanes.json")

    assert classify_test_path(path, policy) == expected


def test_every_test_module_has_exactly_one_primary_lane() -> None:
    policy = load_lane_policy(ROOT / "config/test-lanes.json")
    modules = sorted(path for path in (ROOT / "tests").glob("test_*.py") if path.name != Path(__file__).name)

    classified = {
        str(path.relative_to(ROOT)).replace("\\", "/"): classify_test_path(
            str(path.relative_to(ROOT)).replace("\\", "/"), policy
        )
        for path in modules
    }

    assert classified
    assert set(classified.values()) <= set(PRIMARY_LANES)
    assert all(classified.values())


def test_duration_baseline_is_measured_and_has_heavy_modules() -> None:
    baseline = load_duration_baseline(ROOT / "config/test-duration-baseline.json")

    assert baseline.schema_version == "1.0"
    assert baseline.measured_at == "2026-07-27"
    assert "pytest" in baseline.source.lower()
    assert baseline.module_seconds["tests/test_convergence_12_families.py"] > 0
    assert baseline.module_seconds["tests/test_kicad_benchmark_task.py"] > 0


def test_unit_lane_uses_three_duration_weighted_shards_in_ci_and_release() -> None:
    policy = load_lane_policy(ROOT / "config/test-lanes.json")
    quality = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert policy.shard_counts["unit"] == 3
    assert policy.runtime_budgets_seconds["unit"] == 600
    for index in range(1, 4):
        assert f"artifact: unit-{index}" in quality
        assert f'shard_index: "{index}"' in quality
        assert 'shard_count: "3"' in quality
        assert f'"unit:{index}:3"' in release


def test_unit_duration_baseline_captures_the_observed_long_tail() -> None:
    baseline = load_duration_baseline(ROOT / "config/test-duration-baseline.json")

    assert baseline.module_seconds["tests/test_synthesis_proof.py"] > 300
    assert baseline.module_seconds["tests/test_synthesis_fab.py"] > 150
    assert baseline.module_seconds["tests/test_synthesis_peripherals.py"] > 100


def test_duration_weighted_shards_are_deterministic_and_bounded() -> None:
    module_seconds = {
        "tests/test_a.py": 12.0,
        "tests/test_b.py": 8.0,
        "tests/test_c.py": 6.0,
        "tests/test_d.py": 4.0,
    }

    first = assign_module_shards(module_seconds, shard_count=2)
    second = assign_module_shards(dict(reversed(tuple(module_seconds.items()))), shard_count=2)

    assert first == second
    assert set(first) == set(module_seconds)
    totals = [sum(module_seconds[path] for path, shard in first.items() if shard == index) for index in range(2)]
    assert max(totals) - min(totals) <= max(module_seconds.values())


def test_policy_rejects_overlapping_primary_rules() -> None:
    policy = TestLanePolicy.model_validate(
        {
            "schema_version": "1.0",
            "primary_lanes": list(PRIMARY_LANES),
            "default_lane": "unit",
            "runtime_budgets_seconds": {lane: 60 for lane in PRIMARY_LANES},
            "lane_rules": [
                {"lane": "benchmark", "patterns": ["tests/test_overlap.py"]},
                {"lane": "hardware", "patterns": ["tests/test_overlap.py"]},
            ],
            "auxiliary_rules": [],
            "required_execution_lanes": ["benchmark"],
        }
    )

    with pytest.raises(ValueError, match="multiple primary lanes"):
        classify_test_path("tests/test_overlap.py", policy)


def test_required_execution_fails_for_empty_or_entirely_skipped_lane() -> None:
    assert _required_execution_failed(selected_count=0, outcomes=Counter()) is True
    assert _required_execution_failed(selected_count=4, outcomes=Counter({"skipped": 4})) is True
    assert _required_execution_failed(selected_count=4, outcomes=Counter({"passed": 1, "skipped": 3})) is False
    assert _required_execution_failed(selected_count=4, outcomes=Counter({"failed": 1, "skipped": 3})) is False


def test_required_benchmark_lane_cannot_pass_without_execution(tmp_path: Path) -> None:
    report = tmp_path / "required-lane-report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.lane_policy",
            "--collect-only",
            "--lane",
            "benchmark",
            "--require-lane-execution",
            "--lane-report",
            str(report),
            "tests/test_convergence_12_families.py",
            "-q",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["selected_count"] == 30
    assert payload["outcomes"] == {"failed": 0, "passed": 0, "skipped": 0}
    assert payload["required_execution_failed"] is True
    assert payload["passed"] is False


def test_quality_and_release_workflows_publish_lane_evidence() -> None:
    quality = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    for lane in PRIMARY_LANES:
        assert f"lane: {lane}" in quality
        assert f'"{lane}' in release
    assert '--lane "$lane"' in release
    assert "test-lane-report" in quality
    assert "test-lane-inventory.json" in quality
    assert "--require-lane-execution" in quality
    assert quality.count("-p tests.lane_policy") >= 3
    assert ".venv/bin/pytest -p tests.lane_policy" in release


def test_taskfile_exposes_local_lane_commands() -> None:
    taskfile = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")

    lane_tasks = (
        "test-unit",
        "test-integration",
        "test-benchmark",
        "test-hardware",
        "test-external-tool",
        "test-native",
    )
    for task in lane_tasks:
        assert f"{task}:" in taskfile

    release_block = taskfile[taskfile.index("  release:") : taskfile.index("\n  test-rust:")]
    for task in lane_tasks:
        assert task in release_block


def test_absolute_report_path_does_not_change_lane_classification(tmp_path: Path) -> None:
    report = tmp_path / "lane-report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.lane_policy",
            "--collect-only",
            "--lane",
            "benchmark",
            "--lane-report",
            str(report),
            "tests/test_convergence_12_families.py",
            "-q",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["inventory"]["benchmark"] == 30
    assert payload["selected_count"] == 30


def test_lane_config_is_valid_json_for_external_tooling() -> None:
    payload = json.loads((ROOT / "config/test-lanes.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
