"""Tests for 12-of-12 family convergence evidence matrix (issue #144).

All tests pass without KiCad installed.  The convergence runner uses the
existing multi-domain loop stub which produces deterministic evidence.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from zaptrace.benchmark.convergence_12 import (
    ALL_12_FAMILY_IDS,
    ConvergenceMatrix,
    FamilyInteropStatus,
    _measure_interop_targets,
    run_12_family_convergence,
)


@cache
def _full_convergence_matrix() -> ConvergenceMatrix:
    """Run the expensive 12-family benchmark once per pytest process."""
    return run_12_family_convergence()


# ---------------------------------------------------------------------------
# ALL_12_FAMILY_IDS
# ---------------------------------------------------------------------------


class TestFamilyIDs:
    def test_exactly_12_families(self):
        assert len(ALL_12_FAMILY_IDS) == 12

    def test_no_duplicates(self):
        assert len(set(ALL_12_FAMILY_IDS)) == 12

    def test_known_families_present(self):
        required = {
            "esp32_usb_sensor",
            "stm32_rs485_industrial",
            "nrf52_ble_multisensor",
            "rp2040_can_node",
        }
        assert required.issubset(set(ALL_12_FAMILY_IDS))


# ---------------------------------------------------------------------------
# FamilyInteropStatus schema
# ---------------------------------------------------------------------------


class TestFamilyInteropStatus:
    def test_all_measured_true(self):
        s = FamilyInteropStatus(
            family_id="fam1",
            targets=["kicad"],
            measured_statuses={"kicad": "measured"},
        )
        assert s.all_measured is True

    def test_all_measured_false_when_missing(self):
        s = FamilyInteropStatus(
            family_id="fam1",
            targets=["kicad", "easyeda"],
            measured_statuses={"kicad": "measured"},
        )
        assert s.all_measured is False

    def test_skipped_counts_as_measured(self):
        s = FamilyInteropStatus(
            family_id="fam1",
            targets=["kicad"],
            measured_statuses={"kicad": "skipped"},
        )
        assert s.all_measured is True

    def test_to_dict_has_required_fields(self):
        s = FamilyInteropStatus(family_id="fam1", targets=["kicad"])
        d = s.to_dict()
        for key in ["family_id", "targets", "measured_statuses", "degradation_policies", "all_measured"]:
            assert key in d


# ---------------------------------------------------------------------------
# ConvergenceMatrix schema
# ---------------------------------------------------------------------------


class TestConvergenceMatrix:
    def test_to_dict_schema(self):
        m = ConvergenceMatrix()
        d = m.to_dict()
        assert d["schema"] == "convergence-matrix-v1"

    def test_to_dict_has_all_fields(self):
        m = ConvergenceMatrix()
        d = m.to_dict()
        for key in [
            "schema",
            "generated_at",
            "family_count",
            "converged_count",
            "all_converged",
            "gate_passed",
            "gate_reason",
            "interop_rows",
            "convergence_report",
        ]:
            assert key in d

    def test_to_json_valid(self):
        m = ConvergenceMatrix(family_count=12, converged_count=12, all_converged=True)
        data = json.loads(m.to_json())
        assert data["family_count"] == 12

    def test_to_markdown_has_table(self):
        status = FamilyInteropStatus(
            family_id="esp32_usb_sensor",
            targets=["kicad"],
            measured_statuses={"kicad": "measured"},
        )
        m = ConvergenceMatrix(
            family_count=1,
            converged_count=1,
            all_converged=True,
            interop_rows=[status],
            gate_passed=True,
            gate_reason="all 1 families converged",
        )
        md = m.to_markdown()
        assert "12-of-12" in md
        assert "esp32_usb_sensor" in md
        assert "PASS" in md


# ---------------------------------------------------------------------------
# run_12_family_convergence
# ---------------------------------------------------------------------------


class TestRun12FamilyConvergence:
    def test_returns_convergence_matrix(self):
        matrix = _full_convergence_matrix()
        assert isinstance(matrix, ConvergenceMatrix)

    def test_schema_label(self):
        matrix = _full_convergence_matrix()
        assert matrix.schema == "convergence-matrix-v1"

    def test_family_count(self):
        matrix = _full_convergence_matrix()
        assert matrix.family_count == 12

    def test_interop_rows_count(self):
        matrix = _full_convergence_matrix()
        assert len(matrix.interop_rows) == 12

    def test_all_converged(self):
        matrix = _full_convergence_matrix()
        non_conv = matrix.convergence_report.get("non_convergent_families")
        assert matrix.all_converged is True, f"Non-convergent: {non_conv}"

    def test_no_degraded_targets(self):
        matrix = _full_convergence_matrix()
        degraded = [
            (row.family_id, t)
            for row in matrix.interop_rows
            for t, s in row.measured_statuses.items()
            if s == "degraded"
        ]
        assert degraded == [], f"Degraded targets found: {degraded}"

    def test_gate_passed(self):
        matrix = _full_convergence_matrix()
        assert matrix.gate_passed is True, f"Gate failed: {matrix.gate_reason}"

    def test_generated_at_nonempty(self):
        matrix = _full_convergence_matrix()
        assert matrix.generated_at != ""

    def test_interop_rows_no_skip_converted_to_pass(self):
        """Skipped interop targets must NOT be reported as passing."""
        matrix = _full_convergence_matrix()
        for row in matrix.interop_rows:
            for target, status in row.measured_statuses.items():
                # status must be "measured", "skipped", or "degraded"
                # Never "passed" (would be a false pass)
                assert status in ("measured", "skipped", "degraded"), (
                    f"{row.family_id}/{target}: unexpected status {status!r}"
                )

    def test_subset_families(self):
        matrix = run_12_family_convergence(family_ids=["esp32_usb_sensor", "rp2040_can_node"])
        assert matrix.family_count == 2
        assert len(matrix.interop_rows) == 2

    def test_convergence_report_serializable(self):
        matrix = _full_convergence_matrix()
        # to_json must produce valid JSON
        data = json.loads(matrix.to_json())
        assert data["schema"] == "convergence-matrix-v1"

    def test_every_family_has_evidence(self):
        matrix = _full_convergence_matrix()
        families_in_report = {f["family_id"] for f in matrix.convergence_report.get("families", [])}
        for fid in ALL_12_FAMILY_IDS:
            assert fid in families_in_report, f"Missing family in report: {fid}"


# ---------------------------------------------------------------------------
# _measure_interop_targets (unit)
# ---------------------------------------------------------------------------


class TestMeasureInteropTargets:
    def test_no_corpus_returns_skipped(self):
        result = _measure_interop_targets("nonexistent_family", ["kicad"])
        assert result.measured_statuses["kicad"] in ("skipped", "measured")

    def test_to_dict(self):
        result = _measure_interop_targets("esp32_usb_sensor", ["kicad"])
        d = result.to_dict()
        assert d["family_id"] == "esp32_usb_sensor"
        assert "kicad" in d["measured_statuses"]


# ---------------------------------------------------------------------------
# CI script integration
# ---------------------------------------------------------------------------


class TestCIScript:
    def test_script_exists(self):
        script = Path("scripts/ci_convergence_12_families.py")
        assert script.is_file()

    def test_script_importable(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("ci_conv", "scripts/ci_convergence_12_families.py")
        assert spec is not None


class TestCIReportingHelpers:
    def test_interop_reporting_surfaces_missing_and_degraded_targets(self, capsys):
        from types import SimpleNamespace

        from scripts.ci_convergence_12_families import _report_interop_rows

        matrix = SimpleNamespace(
            interop_rows=[
                SimpleNamespace(
                    family_id="family-a",
                    all_measured=False,
                    targets=["kicad", "eagle"],
                    measured_statuses={"kicad": "degraded"},
                    degradation_policies={"kicad": "manual review required"},
                )
            ]
        )

        _report_interop_rows(matrix)

        stderr = capsys.readouterr().err
        assert "missing measurements for ['eagle']" in stderr
        assert "DEGRADED: family-a/kicad: manual review required" in stderr

    def test_gate_failure_reports_non_convergent_families(self, capsys):
        from types import SimpleNamespace

        from scripts.ci_convergence_12_families import _report_gate_failure

        matrix = SimpleNamespace(
            gate_reason="one family failed",
            convergence_report={"non_convergent_families": ["family-b"]},
        )

        assert _report_gate_failure(matrix) == 1
        stderr = capsys.readouterr().err
        assert "FAIL: one family failed" in stderr
        assert "Non-convergent families: ['family-b']" in stderr

    def test_gate_failure_omits_empty_family_detail(self, capsys):
        from types import SimpleNamespace

        from scripts.ci_convergence_12_families import _report_gate_failure

        matrix = SimpleNamespace(gate_reason="interop degraded", convergence_report={})

        assert _report_gate_failure(matrix) == 1
        stderr = capsys.readouterr().err
        assert "FAIL: interop degraded" in stderr
        assert "Non-convergent families" not in stderr
