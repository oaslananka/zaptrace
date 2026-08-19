"""Tests for repair and interop tracks (issue #132).

Covers:
- RepairTaskSpec / FaultSpec schema loading from YAML
- run_repair_task detection logic for each fault class
- Repair track determinism (same hash on two runs)
- Repair track threshold violations
- InteropTaskSpec schema loading from YAML
- run_interop_task scoring from evidence YAML
- Interop track determinism
- Interop track threshold violations
- Regression: grader drift detection (changing evidence changes hash)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from zaptrace.benchmark.interop_track import (
    InteropCategorySpec,
    InteropTaskSpec,
    load_interop_task,
    run_interop_task,
)
from zaptrace.benchmark.repair_track import (
    RepairFaultSpec,
    RepairTaskSpec,
    load_repair_task,
    run_repair_task,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_REPAIR_TASK_YAML = _REPO_ROOT / "benchmarks" / "repair-track-v1" / "task.yaml"
_INTEROP_TASK_YAML = _REPO_ROOT / "benchmarks" / "interop-track-v1" / "task.yaml"
_INTEROP_EVIDENCE = _REPO_ROOT / "benchmarks" / "interop-track-v1" / "evidence-battery-charger.yaml"


def _make_schematic_with_no_connect(tmp_path: Path) -> Path:
    proj = tmp_path / "with_no_connect"
    proj.mkdir()
    (proj / "test.kicad_pro").write_text("{}")
    (proj / "test.kicad_sch").write_text(
        '(kicad_sch (version 20231120)\n  (no_connect (at 100 100))\n  (net 1 "VCC")\n)'
    )
    return proj


def _make_schematic_power_no_flag(tmp_path: Path) -> Path:
    proj = tmp_path / "power_no_flag"
    proj.mkdir()
    (proj / "test.kicad_pro").write_text("{}")
    (proj / "test.kicad_sch").write_text('(kicad_sch (version 20231120)\n  (net 1 "VCC")\n  (net 2 "GND")\n)')
    return proj


def _make_minimal_project(tmp_path: Path, name: str = "minimal") -> Path:
    proj = tmp_path / name
    proj.mkdir()
    (proj / f"{name}.kicad_pro").write_text("{}")
    (proj / f"{name}.kicad_sch").write_text('(kicad_sch (version 20231120)\n  (net 1 "VCC")\n  (net 2 "GND")\n)')
    return proj


def _make_empty_project(tmp_path: Path) -> Path:
    proj = tmp_path / "empty"
    proj.mkdir()
    return proj


def _make_repair_task_spec(fault_classes: list[str]) -> RepairTaskSpec:
    faults = [
        RepairFaultSpec(
            fault_id=f"FAULT-{i:03d}",
            fault_class=fc,
            description=f"Test fault {fc}",
            expected_detector=f"test.{fc}",
            release_blocking=True,
        )
        for i, fc in enumerate(fault_classes, 1)
    ]
    return RepairTaskSpec(
        task_schema_version="1.0",
        task_id="unit-repair-001",
        name="Unit repair task",
        description="",
        faults=faults,
        thresholds={"min_detection_rate": 0.0},
        limits={"max_runtime_seconds": 30},
    )


def _make_interop_task_spec(categories: dict[str, float] | None = None) -> InteropTaskSpec:
    if categories is None:
        categories = {"connectivity": 0.75, "components": 0.75}
    cat_specs = [InteropCategorySpec(category=cat, min_score=thresh) for cat, thresh in categories.items()]
    return InteropTaskSpec(
        task_schema_version="1.0",
        task_id="unit-interop-001",
        name="Unit interop task",
        description="",
        source_format="kicad",
        target_format="easyeda_pro",
        categories=cat_specs,
        limits={"max_runtime_seconds": 30},
    )


def _write_evidence(tmp_path: Path, categories: dict[str, float]) -> Path:
    ev = tmp_path / "evidence.yaml"
    ev.write_text(
        yaml.dump(
            {
                "evidence_schema_version": "1.0",
                "source_format": "kicad",
                "target_format": "easyeda_pro",
                "categories": categories,
            }
        )
    )
    return ev


# ---------------------------------------------------------------------------
# RepairTaskSpec loading
# ---------------------------------------------------------------------------


class TestRepairTaskSpecLoading:
    def test_load_reference_task_yaml(self) -> None:
        spec = load_repair_task(_REPAIR_TASK_YAML)
        assert spec.task_id == "repair-rt-001"
        assert len(spec.faults) >= 2

    def test_reference_task_has_release_blocking_faults(self) -> None:
        spec = load_repair_task(_REPAIR_TASK_YAML)
        rb = [f for f in spec.faults if f.release_blocking]
        assert len(rb) >= 1

    def test_reference_task_has_threshold(self) -> None:
        spec = load_repair_task(_REPAIR_TASK_YAML)
        assert spec.thresholds.get("min_detection_rate", -1) >= 0

    def test_fault_spec_from_dict_minimal(self) -> None:
        f = RepairFaultSpec.from_dict({"fault_id": "F1", "fault_class": "generic", "expected_detector": "x"})
        assert f.fault_id == "F1"
        assert f.release_blocking is True  # default


# ---------------------------------------------------------------------------
# Repair track fault detection
# ---------------------------------------------------------------------------


class TestRepairFaultDetection:
    def test_detect_no_connect_fault(self, tmp_path: Path) -> None:
        proj = _make_schematic_with_no_connect(tmp_path)
        spec = _make_repair_task_spec(["erc_unconnected_pin"])
        result = run_repair_task(spec, proj)
        assert result.fault_outcomes[0].detected is True

    def test_detect_power_flag_missing(self, tmp_path: Path) -> None:
        proj = _make_schematic_power_no_flag(tmp_path)
        spec = _make_repair_task_spec(["erc_power_flag_missing"])
        result = run_repair_task(spec, proj)
        assert result.fault_outcomes[0].detected is True

    def test_no_detect_power_flag_when_flag_present(self, tmp_path: Path) -> None:
        proj = tmp_path / "with_flag"
        proj.mkdir()
        (proj / "test.kicad_sch").write_text('(kicad_sch\n  (net 1 "VCC")\n  (symbol (lib_id "power:PWR_FLAG"))\n)')
        spec = _make_repair_task_spec(["erc_power_flag_missing"])
        result = run_repair_task(spec, proj)
        assert result.fault_outcomes[0].detected is False

    def test_generic_fault_always_detected(self, tmp_path: Path) -> None:
        proj = _make_minimal_project(tmp_path)
        spec = _make_repair_task_spec(["generic"])
        result = run_repair_task(spec, proj)
        assert result.fault_outcomes[0].detected is True

    def test_detect_duplicate_net_labels(self, tmp_path: Path) -> None:
        proj = tmp_path / "duplicate_labels"
        proj.mkdir()
        (proj / "test.kicad_sch").write_text('(kicad_sch\n  (label "SDA")\n  (label "SDA")\n)')
        spec = _make_repair_task_spec(["erc_duplicate_net"])

        result = run_repair_task(spec, proj)

        assert result.fault_outcomes[0].detected is True
        assert "SDA" in result.fault_outcomes[0].detail

    def test_detect_missing_component_reference(self, tmp_path: Path) -> None:
        proj = tmp_path / "missing_reference"
        proj.mkdir()
        (proj / "test.kicad_sch").write_text('(kicad_sch\n  (property "Reference" "REF_MISSING")\n)')
        spec = _make_repair_task_spec(["parity_missing_component"])

        result = run_repair_task(spec, proj)

        assert result.fault_outcomes[0].detected is True
        assert result.fault_outcomes[0].detail == "Missing component reference found"

    def test_no_detect_on_empty_directory(self, tmp_path: Path) -> None:
        proj = _make_empty_project(tmp_path)
        spec = _make_repair_task_spec(["erc_unconnected_pin"])
        result = run_repair_task(spec, proj)
        assert result.fault_outcomes[0].detected is False


# ---------------------------------------------------------------------------
# Repair track aggregation
# ---------------------------------------------------------------------------


class TestRepairTrackAggregation:
    def test_pass_when_all_detected(self, tmp_path: Path) -> None:
        proj = _make_schematic_with_no_connect(tmp_path)
        spec = _make_repair_task_spec(["erc_unconnected_pin"])
        result = run_repair_task(spec, proj)
        assert result.status == "pass"

    def test_fail_when_release_blocking_not_detected(self, tmp_path: Path) -> None:
        proj = _make_empty_project(tmp_path)
        spec = _make_repair_task_spec(["erc_unconnected_pin"])
        result = run_repair_task(spec, proj)
        assert result.status == "fail"
        assert any("Release-blocking" in v for v in result.threshold_violations)

    def test_fail_when_detection_rate_too_low(self, tmp_path: Path) -> None:
        proj = _make_minimal_project(tmp_path)
        spec = _make_repair_task_spec(["erc_unconnected_pin"])
        spec.thresholds["min_detection_rate"] = 1.0
        spec.faults[0].release_blocking = False  # not release-blocking
        result = run_repair_task(spec, proj)
        assert result.status == "fail"

    def test_counts_are_correct(self, tmp_path: Path) -> None:
        proj = _make_schematic_with_no_connect(tmp_path)
        spec = _make_repair_task_spec(["erc_unconnected_pin", "generic"])
        result = run_repair_task(spec, proj)
        assert result.total_faults == 2
        assert result.detected_count >= 1

    def test_result_serializable(self, tmp_path: Path) -> None:
        proj = _make_minimal_project(tmp_path)
        spec = _make_repair_task_spec(["generic"])
        result = run_repair_task(spec, proj)
        serialized = json.dumps(result.to_dict())
        assert "fault_outcomes" in serialized


# ---------------------------------------------------------------------------
# Repair track determinism
# ---------------------------------------------------------------------------


class TestRepairTrackDeterminism:
    def test_two_runs_same_hash(self, tmp_path: Path) -> None:
        proj = _make_schematic_with_no_connect(tmp_path)
        spec = _make_repair_task_spec(["erc_unconnected_pin"])
        r1 = run_repair_task(spec, proj)
        r2 = run_repair_task(spec, proj)
        assert r1.compute_hash() == r2.compute_hash()

    def test_different_fixture_different_hash(self, tmp_path: Path) -> None:
        proj_a = _make_schematic_with_no_connect(tmp_path)
        proj_b = _make_minimal_project(tmp_path)
        spec = _make_repair_task_spec(["erc_unconnected_pin"])
        r1 = run_repair_task(spec, proj_a)
        r2 = run_repair_task(spec, proj_b)
        assert r1.compute_hash() != r2.compute_hash()

    def test_run_id_does_not_affect_hash(self, tmp_path: Path) -> None:
        proj = _make_minimal_project(tmp_path)
        spec = _make_repair_task_spec(["generic"])
        r1 = run_repair_task(spec, proj, run_id="RUN-A")
        r2 = run_repair_task(spec, proj, run_id="RUN-B")
        assert r1.compute_hash() == r2.compute_hash()


# ---------------------------------------------------------------------------
# InteropTaskSpec loading
# ---------------------------------------------------------------------------


class TestInteropTaskSpecLoading:
    def test_load_reference_task_yaml(self) -> None:
        spec = load_interop_task(_INTEROP_TASK_YAML)
        assert spec.task_id == "interop-rt-001"
        assert spec.source_format == "kicad"
        assert spec.target_format == "easyeda_pro"
        assert len(spec.categories) >= 3

    def test_reference_task_has_required_categories(self) -> None:
        spec = load_interop_task(_INTEROP_TASK_YAML)
        required = {c.category for c in spec.categories if c.required}
        assert "connectivity" in required
        assert "degradation_completeness" in required

    def test_category_spec_defaults(self) -> None:
        c = InteropCategorySpec.from_dict({"category": "connectivity"})
        assert c.min_score == pytest.approx(0.75)
        assert c.required is True


# ---------------------------------------------------------------------------
# Interop track scoring
# ---------------------------------------------------------------------------


class TestInteropTrackScoring:
    def test_pass_when_all_categories_meet_threshold(self, tmp_path: Path) -> None:
        ev = _write_evidence(tmp_path, {"connectivity": 0.90, "components": 0.85})
        spec = _make_interop_task_spec({"connectivity": 0.75, "components": 0.75})
        result = run_interop_task(spec, ev)
        assert result.status == "pass"
        assert len(result.threshold_violations) == 0

    def test_fail_when_category_below_threshold(self, tmp_path: Path) -> None:
        ev = _write_evidence(tmp_path, {"connectivity": 0.50, "components": 0.85})
        spec = _make_interop_task_spec({"connectivity": 0.75, "components": 0.75})
        result = run_interop_task(spec, ev)
        assert result.status == "fail"
        assert any("connectivity" in v for v in result.threshold_violations)

    def test_skip_when_evidence_not_found(self, tmp_path: Path) -> None:
        ev = tmp_path / "nonexistent.yaml"
        spec = _make_interop_task_spec()
        result = run_interop_task(spec, ev)
        assert result.status == "skip"

    def test_missing_category_scores_zero(self, tmp_path: Path) -> None:
        ev = _write_evidence(tmp_path, {"connectivity": 0.90})  # components missing
        spec = _make_interop_task_spec({"connectivity": 0.75, "components": 0.75})
        result = run_interop_task(spec, ev)
        comp = next(c for c in result.category_scores if c.category == "components")
        assert comp.score == pytest.approx(0.0)

    def test_mean_score_computed(self, tmp_path: Path) -> None:
        ev = _write_evidence(tmp_path, {"connectivity": 0.80, "components": 0.60})
        spec = _make_interop_task_spec({"connectivity": 0.75, "components": 0.50})
        result = run_interop_task(spec, ev)
        assert abs(result.mean_score - 0.70) < 0.01

    def test_reference_evidence_passes_reference_task(self) -> None:
        spec = load_interop_task(_INTEROP_TASK_YAML)
        result = run_interop_task(spec, _INTEROP_EVIDENCE)
        assert result.status == "pass", f"Violations: {result.threshold_violations}"

    def test_result_serializable(self, tmp_path: Path) -> None:
        ev = _write_evidence(tmp_path, {"connectivity": 1.0})
        spec = _make_interop_task_spec({"connectivity": 0.75})
        result = run_interop_task(spec, ev)
        serialized = json.dumps(result.to_dict())
        assert "category_scores" in serialized


# ---------------------------------------------------------------------------
# Interop track determinism
# ---------------------------------------------------------------------------


class TestInteropTrackDeterminism:
    def test_two_runs_same_hash(self, tmp_path: Path) -> None:
        ev = _write_evidence(tmp_path, {"connectivity": 0.90})
        spec = _make_interop_task_spec({"connectivity": 0.75})
        r1 = run_interop_task(spec, ev)
        r2 = run_interop_task(spec, ev)
        assert r1.compute_hash() == r2.compute_hash()

    def test_changed_score_changes_hash(self, tmp_path: Path) -> None:
        ev1 = tmp_path / "ev1.yaml"
        ev1.write_text(yaml.dump({"evidence_schema_version": "1.0", "categories": {"connectivity": 0.90}}))
        ev2 = tmp_path / "ev2.yaml"
        ev2.write_text(yaml.dump({"evidence_schema_version": "1.0", "categories": {"connectivity": 0.50}}))
        spec = _make_interop_task_spec({"connectivity": 0.75})
        r1 = run_interop_task(spec, ev1)
        r2 = run_interop_task(spec, ev2)
        assert r1.compute_hash() != r2.compute_hash()

    def test_run_id_does_not_affect_hash(self, tmp_path: Path) -> None:
        ev = _write_evidence(tmp_path, {"connectivity": 0.90})
        spec = _make_interop_task_spec({"connectivity": 0.75})
        r1 = run_interop_task(spec, ev, run_id="RUN-A")
        r2 = run_interop_task(spec, ev, run_id="RUN-B")
        assert r1.compute_hash() == r2.compute_hash()


# ---------------------------------------------------------------------------
# Regression: grader drift detection
# ---------------------------------------------------------------------------


class TestGraderDriftDetection:
    """Verify that a changed evidence score is detected as a drift."""

    def test_drift_in_interop_evidence_fails_hash_check(self, tmp_path: Path) -> None:
        ev = _write_evidence(tmp_path, {"connectivity": 0.90, "components": 0.80})
        spec = _make_interop_task_spec({"connectivity": 0.75, "components": 0.75})
        r_reference = run_interop_task(spec, ev)
        reference_hash = r_reference.run_hash

        # Simulate drift: change evidence score
        ev.write_text(
            yaml.dump({"evidence_schema_version": "1.0", "categories": {"connectivity": 0.60, "components": 0.80}})
        )
        r_drifted = run_interop_task(spec, ev)
        assert r_drifted.run_hash != reference_hash, "Drift should change the run hash"

    def test_drift_in_repair_detection_fails_hash_check(self, tmp_path: Path) -> None:
        proj_with_fault = _make_schematic_with_no_connect(tmp_path)
        spec = _make_repair_task_spec(["erc_unconnected_pin"])
        r_reference = run_repair_task(spec, proj_with_fault)

        proj_clean = _make_minimal_project(tmp_path)
        r_drifted = run_repair_task(spec, proj_clean)
        assert r_drifted.run_hash != r_reference.run_hash, "Drift should change the run hash"
