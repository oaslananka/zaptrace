"""Tests for test-lane duration profiling, drift classification, and re-baselining."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from scripts.ci_profile_test_lanes import format_summary_text, format_terminal_summary
from tests.lane_policy import (
    DriftThresholds,
    DurationBaseline,
    _normalize_test_path,
    calculate_lane_shard_profile,
    load_duration_baseline,
    load_lane_policy,
    parse_durations_log,
    parse_junit_durations,
    save_duration_baseline,
    update_duration_baseline_data,
)

ROOT = Path(__file__).resolve().parents[1]


def test_profile_summary_omits_untrusted_detail_strings() -> None:
    synthetic_token = "AKIA" + "1234567890123456"
    report = {
        "passed": False,
        "status": "drift_critical",
        "summary": {
            "total_modules": 1,
            "observed_modules": 1,
            "unobserved_modules": 0,
            "unbaselined_modules": 0,
            "total_baseline_seconds": 1.0,
            "total_observed_seconds": 2.0,
            "critical_drift_count": 1,
            "warning_drift_count": 0,
        },
        "lanes": {},
        "module_drifts": [
            {
                "module": f"tests/{synthetic_token}.py",
                "severity": "critical",
                "is_new_module": False,
                "observed_seconds": 2.0,
                "baseline_seconds": 1.0,
                "drift_seconds": 1.0,
                "drift_ratio": 1.0,
            }
        ],
        "warnings": [f"credential={synthetic_token}"],
        "errors": ["token=secret-value"],
    }

    summary = format_summary_text(report)

    assert synthetic_token not in summary
    assert "secret-value" not in summary
    assert "Critical module drifts: 1" in summary
    assert "Warnings: 1 detail(s) retained in the JSON report." in summary
    assert "Errors: 1 detail(s) retained in the JSON report." in summary


def test_terminal_summary_renders_only_explicit_aggregate_values() -> None:
    synthetic_token = "AKIA" + "1234567890123456"

    summary = format_terminal_summary(
        passed=False,
        total_modules=1,
        observed_modules=1,
        unobserved_modules=0,
        unbaselined_modules=0,
        total_baseline_seconds=1.0,
        total_observed_seconds=2.0,
        critical_drift_count=1,
        warning_drift_count=0,
        lane_detail_count=0,
        notable_drift_count=1,
        warnings_count=1,
        errors_count=1,
        untrusted_detail=synthetic_token,
    )

    assert synthetic_token not in summary
    assert "Test Lane Duration Profile Summary [FAIL FAILED]" in summary
    assert "Critical module drifts: 1 detail(s) retained in the JSON report." in summary


@contextmanager
def _repository_dir():
    with tempfile.TemporaryDirectory(prefix="lane-profile-test-", dir=ROOT) as temp_dir:
        yield Path(temp_dir)


@contextmanager
def _repository_json(payload: dict[str, float]):
    with _repository_dir() as temp_dir:
        path = temp_dir / "durations.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        yield path


def test_normalize_test_path() -> None:
    assert _normalize_test_path("tests/test_models.py") == "tests/test_models.py"
    assert _normalize_test_path("tests\\test_models.py") == "tests/test_models.py"
    assert _normalize_test_path(str(ROOT / "tests/test_models.py")) == "tests/test_models.py"
    assert _normalize_test_path("tests.test_models.TestPin") == "tests/test_models.py"
    assert _normalize_test_path("tests/test_models.py::TestPin::test_foo") == "tests/test_models.py"


def test_parse_junit_durations_success(tmp_path: Path) -> None:
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="3">
    <testcase classname="tests.test_models.TestPin" name="test_one" file="tests/test_models.py" time="1.250" />
    <testcase classname="tests.test_models.TestPin" name="test_two" file="tests/test_models.py" time="0.750" />
    <testcase classname="tests.test_cli.TestCli" name="test_help" file="tests/test_cli.py" time="2.100" />
  </testsuite>
</testsuites>
"""
    junit_file = tmp_path / "junit-sample.xml"
    junit_file.write_text(xml_content, encoding="utf-8")

    durations, errors = parse_junit_durations(junit_file, root=ROOT)
    assert not errors
    assert durations["tests/test_models.py"] == 2.0
    assert durations["tests/test_cli.py"] == 2.1


def test_parse_junit_durations_without_file_attribute(tmp_path: Path) -> None:
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="2">
    <testcase classname="tests.test_models.TestPin" name="test_one" time="0.500" />
    <testcase classname="test_models.TestPin" name="test_two" time="0.300" />
  </testsuite>
</testsuites>
"""
    junit_file = tmp_path / "junit-classname.xml"
    junit_file.write_text(xml_content, encoding="utf-8")

    durations, errors = parse_junit_durations(junit_file, root=ROOT)
    assert not errors
    assert durations["tests/test_models.py"] == 0.8


def test_parse_junit_durations_malformed_and_missing(tmp_path: Path) -> None:
    bad_xml = tmp_path / "corrupt.xml"
    bad_xml.write_text("<testsuites><unclosed>", encoding="utf-8")

    durations, errors = parse_junit_durations(bad_xml, root=ROOT)
    assert not durations
    assert len(errors) == 1
    assert "Failed to parse JUnit XML" in errors[0]

    non_existent = tmp_path / "missing.xml"
    durations2, errors2 = parse_junit_durations(non_existent, root=ROOT)
    assert not durations2
    assert any("not found" in err.lower() for err in errors2)


def test_parse_durations_log_text() -> None:
    log_text = """
============================= slowest durations ==============================
18.09s call     tests/test_autopilot_adapter.py::test_workflow_loop
 8.09s call     tests/test_benchmark_board_families.py::test_families
 0.12s setup    tests/test_benchmark_board_families.py::test_families
 0.05s teardown tests/test_autopilot_adapter.py::test_workflow_loop
"""
    durations, errors = parse_durations_log(log_text, root=ROOT)
    assert not errors
    assert durations["tests/test_autopilot_adapter.py"] == 18.14
    assert durations["tests/test_benchmark_board_families.py"] == 8.21


def test_save_and_load_duration_baseline(tmp_path: Path) -> None:
    baseline = DurationBaseline(
        schema_version="1.0",
        measured_at="2026-08-21",
        source="Synthetic test baseline for verification",
        default_module_seconds=1.5,
        module_seconds={
            "tests/test_b.py": 10.5,
            "tests/test_a.py": 5.25,
        },
    )
    target_path = tmp_path / "test-baseline.json"
    save_duration_baseline(baseline, path=target_path)

    loaded = load_duration_baseline(target_path)
    assert loaded == baseline
    raw_json = json.loads(target_path.read_text(encoding="utf-8"))
    assert list(raw_json["module_seconds"].keys()) == ["tests/test_a.py", "tests/test_b.py"]


def test_update_duration_baseline_data() -> None:
    original = DurationBaseline(
        schema_version="1.0",
        measured_at="2026-07-27",
        source="Original source",
        default_module_seconds=1.0,
        module_seconds={
            "tests/test_a.py": 5.0,
            "tests/test_b.py": 8.0,
        },
    )

    observed = {
        "tests/test_a.py": 6.5,
        "tests/test_c.py": 12.0,
    }

    updated = update_duration_baseline_data(
        original,
        observed,
        measured_at="2026-08-21",
        source="Updated source description",
        update_all=False,
    )

    assert original.module_seconds["tests/test_a.py"] == 5.0
    assert updated.measured_at == "2026-08-21"
    assert updated.source == "Updated source description"
    assert updated.module_seconds["tests/test_a.py"] == 6.5
    assert updated.module_seconds["tests/test_b.py"] == 8.0
    assert updated.module_seconds["tests/test_c.py"] == 12.0


def test_calculate_lane_shard_profile_and_drift_classification() -> None:
    policy = load_lane_policy(ROOT / "config/test-lanes.json")
    baseline = load_duration_baseline(ROOT / "config/test-duration-baseline.json")

    observed = {
        # Minor change
        "tests/test_models.py": 0.044 + 0.1,
        # Moderate warning drift (>2.0s and >30%)
        "tests/test_copper_pour.py": 0.832 + 3.0,
        # Critical drift (>10.0s and >50%)
        "tests/test_dc_bias.py": 69.324 + 40.0,
        # Unbaselined new heavy test (>15s -> critical)
        "tests/test_new_unbaselined_heavy.py": 25.0,
    }

    thresholds = DriftThresholds(
        module_warning_seconds=2.0,
        module_warning_ratio=0.30,
        module_critical_seconds=10.0,
        module_critical_ratio=0.50,
        shard_imbalance_warning_seconds=20.0,
        shard_imbalance_critical_seconds=60.0,
    )

    report = calculate_lane_shard_profile(
        policy=policy,
        baseline=baseline,
        observed_durations=observed,
        thresholds=thresholds,
        target_lane="all",
        root=ROOT,
    )

    assert report["schema_version"] == "1.0"
    assert report["gate_id"] == "test-lane-profiling-v1"
    assert report["status"] == "drift_critical"
    assert report["passed"] is False
    assert report["summary"]["critical_drift_count"] >= 1
    assert report["summary"]["warning_drift_count"] >= 1

    drifts_by_mod = {d["module"]: d for d in report["module_drifts"]}
    assert drifts_by_mod["tests/test_models.py"]["severity"] == "info"
    assert drifts_by_mod["tests/test_copper_pour.py"]["severity"] == "warning"
    assert drifts_by_mod["tests/test_dc_bias.py"]["severity"] == "critical"


def test_cli_check_mode_does_not_mutate_baseline() -> None:
    with _repository_dir() as temp_dir:
        report_file = temp_dir / "profile-report.json"
        baseline_before = (ROOT / "config/test-duration-baseline.json").read_text(encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "scripts/ci_profile_test_lanes.py",
                "--output",
                str(report_file),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        assert report_file.is_file()
        report = json.loads(report_file.read_text(encoding="utf-8"))
        assert report["gate_id"] == "test-lane-profiling-v1"

        baseline_after = (ROOT / "config/test-duration-baseline.json").read_text(encoding="utf-8")
        assert baseline_before == baseline_after


def test_cli_update_mode_explicit() -> None:
    with _repository_dir() as temp_dir:
        report_file = temp_dir / "profile-report.json"
        target_baseline = temp_dir / "custom-baseline.json"
        # Copy current baseline to target
        target_baseline.write_text(
            (ROOT / "config/test-duration-baseline.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        durations_json = temp_dir / "durations.json"
        durations_json.write_text(json.dumps({"tests/test_models.py": 1.234}), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "scripts/ci_profile_test_lanes.py",
                "--durations-json",
                str(durations_json),
                "--update",
                "--write-baseline",
                str(target_baseline),
                "--measured-at",
                "2026-08-21",
                "--source",
                "Automated test run in isolated test suite",
                "--output",
                str(report_file),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        updated = json.loads(target_baseline.read_text(encoding="utf-8"))
        assert updated["measured_at"] == "2026-08-21"
        assert updated["source"] == "Automated test run in isolated test suite"
        assert updated["module_seconds"]["tests/test_models.py"] == 1.234


def test_cli_strict_exit_code() -> None:
    with _repository_dir() as temp_dir:
        report_file = temp_dir / "strict-report.json"
        durations_json = temp_dir / "durations.json"
        durations_json.write_text(json.dumps({"tests/test_models.py": 60.0}), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "scripts/ci_profile_test_lanes.py",
                "--durations-json",
                str(durations_json),
                "--strict",
                "--output",
                str(report_file),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 1


def test_cli_rejects_durations_json_outside_repository_root(tmp_path: Path) -> None:
    durations_json = tmp_path / "outside-durations.json"
    durations_json.write_text(json.dumps({"tests/test_models.py": 1.0}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/ci_profile_test_lanes.py",
            "--durations-json",
            str(durations_json),
            "--quiet",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "escapes repository root" in result.stderr


def test_cli_rejects_output_outside_repository_root(tmp_path: Path) -> None:
    outside_output = tmp_path / "outside-report.json"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/ci_profile_test_lanes.py",
            "--output",
            str(outside_output),
            "--quiet",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "escapes repository root" in result.stderr


def test_cli_rejects_write_baseline_outside_repository_root(tmp_path: Path) -> None:
    outside_baseline = tmp_path / "outside-baseline.json"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/ci_profile_test_lanes.py",
            "--update",
            "--write-baseline",
            str(outside_baseline),
            "--quiet",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "escapes repository root" in result.stderr
