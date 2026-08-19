"""Tests for benchmark convergence runner (issue #115).

Covers:
* DRC repair handlers: spacing, via_geometry, courtyard
* apply_drc_repair_chain: all repaired, all escalated, mixed
* DrcRepairOutcome.to_dict() keys
* FamilyConvergenceResult.to_dict() keys
* AggregateConvergenceReport: converged_count, all_converged, to_dict(), to_json()
* run_benchmark_convergence: four families converge, all required keys present
* Non-convergent families: explicit escalation in report
* DRC repair chain: deterministic across two calls
* Repair handler: spacing handler ignores non-spacing violation
* Repair handler: via handler ignores non-via violation
* Repair handler: courtyard handler ignores non-courtyard violation
"""

from __future__ import annotations

import json

import pytest

from zaptrace.benchmark.convergence import (
    CANONICAL_FAMILY_IDS,
    AggregateConvergenceReport,
    DrcRepairOutcome,
    DrcViolation,
    FamilyConvergenceResult,
    apply_drc_repair_chain,
    courtyard_repair,
    run_benchmark_convergence,
    spacing_repair,
    via_geometry_repair,
)

# ---------------------------------------------------------------------------
# DrcViolation helpers
# ---------------------------------------------------------------------------


def _spacing_v() -> DrcViolation:
    return DrcViolation(rule="clearance.min_spacing")


def _via_v() -> DrcViolation:
    return DrcViolation(rule="via.min_annular_ring")


def _courtyard_v() -> DrcViolation:
    return DrcViolation(rule="courtyard.overlap")


def _unknown_v() -> DrcViolation:
    return DrcViolation(rule="silk.overlap")


# ---------------------------------------------------------------------------
# Unit tests: individual repair handlers
# ---------------------------------------------------------------------------


class TestSpacingRepair:
    def test_repairs_clearance_violation(self) -> None:
        out = spacing_repair(_spacing_v())
        assert out.repaired is True

    def test_does_not_repair_via_violation(self) -> None:
        out = spacing_repair(_via_v())
        assert out.repaired is False

    def test_does_not_repair_courtyard_violation(self) -> None:
        out = spacing_repair(_courtyard_v())
        assert out.repaired is False

    def test_handler_name_set(self) -> None:
        assert spacing_repair(_spacing_v()).handler == "spacing_repair"

    def test_rule_preserved(self) -> None:
        v = _spacing_v()
        out = spacing_repair(v)
        assert out.rule == v.rule


class TestViaGeometryRepair:
    def test_repairs_via_violation(self) -> None:
        out = via_geometry_repair(_via_v())
        assert out.repaired is True

    def test_does_not_repair_spacing_violation(self) -> None:
        out = via_geometry_repair(_spacing_v())
        assert out.repaired is False

    def test_handler_name_set(self) -> None:
        assert via_geometry_repair(_via_v()).handler == "via_geometry_repair"


class TestCourtyardRepair:
    def test_repairs_courtyard_violation(self) -> None:
        out = courtyard_repair(_courtyard_v())
        assert out.repaired is True

    def test_does_not_repair_spacing_violation(self) -> None:
        out = courtyard_repair(_spacing_v())
        assert out.repaired is False

    def test_handler_name_set(self) -> None:
        assert courtyard_repair(_courtyard_v()).handler == "courtyard_repair"


class TestDrcRepairOutcomeToDict:
    def test_required_keys(self) -> None:
        out = DrcRepairOutcome(rule="test.rule", handler="test_handler", repaired=True)
        d = out.to_dict()
        assert {"rule", "handler", "repaired", "escalated", "note"} <= d.keys()

    def test_serialisable(self) -> None:
        out = DrcRepairOutcome(rule="test.rule", handler="test_handler", repaired=False, escalated=True)
        json.dumps(out.to_dict())


# ---------------------------------------------------------------------------
# apply_drc_repair_chain
# ---------------------------------------------------------------------------


class TestApplyDrcRepairChain:
    def test_all_three_canonical_violations_repaired(self) -> None:
        violations = [_spacing_v(), _via_v(), _courtyard_v()]
        outcomes, escalations = apply_drc_repair_chain(violations)
        assert len(escalations) == 0
        assert all(o.repaired for o in outcomes)

    def test_unknown_violation_escalated(self) -> None:
        outcomes, escalations = apply_drc_repair_chain([_unknown_v()])
        assert len(escalations) == 1
        assert outcomes[0].escalated is True

    def test_mixed_violations(self) -> None:
        violations = [_spacing_v(), _unknown_v()]
        outcomes, escalations = apply_drc_repair_chain(violations)
        assert len(escalations) == 1
        assert len([o for o in outcomes if o.repaired]) == 1

    def test_empty_input(self) -> None:
        outcomes, escalations = apply_drc_repair_chain([])
        assert outcomes == []
        assert escalations == []

    def test_deterministic(self) -> None:
        violations = [_spacing_v(), _via_v()]
        r1, _ = apply_drc_repair_chain(violations)
        r2, _ = apply_drc_repair_chain(violations)
        assert [o.handler for o in r1] == [o.handler for o in r2]


# ---------------------------------------------------------------------------
# FamilyConvergenceResult.to_dict()
# ---------------------------------------------------------------------------


class TestFamilyConvergenceResultToDict:
    def _make_result(self) -> FamilyConvergenceResult:
        return FamilyConvergenceResult(
            family_id="esp32_usb_sensor",
            intent="test intent",
            converged=True,
            blocking_stage=None,
            erc_violations_remaining=0,
        )

    def test_required_keys(self) -> None:
        d = self._make_result().to_dict()
        required = {
            "family_id",
            "intent",
            "converged",
            "blocking_stage",
            "erc_violations_remaining",
            "drc_repair_outcomes",
            "drc_escalations",
            "stage_statuses",
            "total_duration_s",
            "iterations_in_loop",
            "proof_pack_hash",
        }
        assert required <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(self._make_result().to_dict())


# ---------------------------------------------------------------------------
# AggregateConvergenceReport
# ---------------------------------------------------------------------------


class TestAggregateConvergenceReport:
    def _empty_report(self) -> AggregateConvergenceReport:
        return AggregateConvergenceReport()

    def _report_with_families(self, *, converged: list[bool]) -> AggregateConvergenceReport:
        report = AggregateConvergenceReport()
        for i, c in enumerate(converged):
            report.families.append(
                FamilyConvergenceResult(
                    family_id=f"family_{i}",
                    intent="intent",
                    converged=c,
                    blocking_stage=None if c else "synthesis",
                    erc_violations_remaining=0,
                )
            )
        return report

    def test_converged_count_all_pass(self) -> None:
        report = self._report_with_families(converged=[True, True, True, True])
        assert report.converged_count == 4

    def test_converged_count_partial(self) -> None:
        report = self._report_with_families(converged=[True, False, True, False])
        assert report.converged_count == 2

    def test_all_converged_true(self) -> None:
        report = self._report_with_families(converged=[True, True])
        assert report.all_converged is True

    def test_all_converged_false(self) -> None:
        report = self._report_with_families(converged=[True, False])
        assert report.all_converged is False

    def test_non_convergent_families(self) -> None:
        report = self._report_with_families(converged=[True, False])
        assert report.non_convergent_families == ["family_1"]

    def test_total_erc_violations_sums(self) -> None:
        report = self._report_with_families(converged=[True, True])
        report.families[0].erc_violations_remaining = 2
        report.families[1].erc_violations_remaining = 3
        assert report.total_erc_violations_remaining == 5

    def test_to_dict_required_keys(self) -> None:
        report = self._empty_report()
        d = report.to_dict()
        required = {
            "run_at",
            "converged_count",
            "total_count",
            "all_converged",
            "non_convergent_families",
            "total_erc_violations_remaining",
            "total_drc_escalations",
            "families",
        }
        assert required <= d.keys()

    def test_to_json_round_trips(self) -> None:
        report = self._report_with_families(converged=[True])
        d = json.loads(report.to_json())
        assert d["converged_count"] == 1

    def test_run_at_nonempty(self) -> None:
        assert len(AggregateConvergenceReport().run_at) > 0


# ---------------------------------------------------------------------------
# run_benchmark_convergence — end-to-end
# ---------------------------------------------------------------------------


class TestRunBenchmarkConvergenceEndToEnd:
    @pytest.fixture(scope="class")
    def report(self) -> AggregateConvergenceReport:
        return run_benchmark_convergence()

    def test_four_families_produced(self, report: AggregateConvergenceReport) -> None:
        assert report.total_count == 4

    def test_all_four_converged(self, report: AggregateConvergenceReport) -> None:
        assert report.converged_count == 4, f"Non-convergent families: {report.non_convergent_families}"

    def test_family_ids_match_canonical(self, report: AggregateConvergenceReport) -> None:
        ids = [f.family_id for f in report.families]
        assert ids == list(CANONICAL_FAMILY_IDS)

    def test_erc_violations_remaining_non_negative(self, report: AggregateConvergenceReport) -> None:
        for f in report.families:
            assert f.erc_violations_remaining >= 0

    def test_drc_escalations_recorded(self, report: AggregateConvergenceReport) -> None:
        for f in report.families:
            # Default fixture has 3 violations; all should be repaired (0 escalations)
            assert f.drc_escalations == 0, f"{f.family_id}: {f.drc_escalations} escalations"

    def test_drc_repair_outcomes_have_three_entries(self, report: AggregateConvergenceReport) -> None:
        for f in report.families:
            assert len(f.drc_repair_outcomes) == 3, f"{f.family_id}: got {len(f.drc_repair_outcomes)} outcomes"

    def test_proof_pack_hashes_all_present(self, report: AggregateConvergenceReport) -> None:
        for f in report.families:
            assert f.proof_pack_hash is not None, f"{f.family_id} missing proof_pack_hash"
            assert len(f.proof_pack_hash) == 64

    def test_stage_statuses_have_synthesis_pass(self, report: AggregateConvergenceReport) -> None:
        for f in report.families:
            assert f.stage_statuses.get("synthesis") == "pass", (
                f"{f.family_id}: synthesis status = {f.stage_statuses.get('synthesis')}"
            )

    def test_total_duration_positive(self, report: AggregateConvergenceReport) -> None:
        for f in report.families:
            assert f.total_duration_s > 0

    def test_to_dict_serialisable(self, report: AggregateConvergenceReport) -> None:
        json.dumps(report.to_dict())

    def test_to_json_has_expected_structure(self, report: AggregateConvergenceReport) -> None:
        d = json.loads(report.to_json())
        assert d["converged_count"] == 4
        assert len(d["families"]) == 4
        assert d["total_drc_escalations"] == 0

    def test_non_convergent_families_empty(self, report: AggregateConvergenceReport) -> None:
        assert report.non_convergent_families == []

    def test_each_family_has_iterations_recorded(self, report: AggregateConvergenceReport) -> None:
        for f in report.families:
            assert f.iterations_in_loop >= 0


class TestRunBenchmarkConvergenceDeterminism:
    def test_pack_hashes_deterministic(self) -> None:
        r1 = run_benchmark_convergence()
        r2 = run_benchmark_convergence()
        hashes1 = [f.proof_pack_hash for f in r1.families]
        hashes2 = [f.proof_pack_hash for f in r2.families]
        assert hashes1 == hashes2

    def test_family_ids_same_across_runs(self) -> None:
        r1 = run_benchmark_convergence()
        r2 = run_benchmark_convergence()
        ids1 = [f.family_id for f in r1.families]
        ids2 = [f.family_id for f in r2.families]
        assert ids1 == ids2


class TestRunBenchmarkConvergenceCustomFamilies:
    def test_single_family_run(self) -> None:
        report = run_benchmark_convergence(family_ids=["esp32_usb_sensor"])
        assert report.total_count == 1
        assert report.families[0].family_id == "esp32_usb_sensor"

    def test_empty_drc_violations(self) -> None:
        report = run_benchmark_convergence(
            family_ids=["esp32_usb_sensor"],
            drc_violations=[],
        )
        assert report.families[0].drc_repair_outcomes == []
        assert report.families[0].drc_escalations == 0

    def test_unknown_violations_escalated(self) -> None:
        report = run_benchmark_convergence(
            family_ids=["esp32_usb_sensor"],
            drc_violations=[DrcViolation(rule="silk.overlap")],
        )
        assert report.families[0].drc_escalations == 1

    def test_two_families_run(self) -> None:
        report = run_benchmark_convergence(family_ids=["esp32_usb_sensor", "rp2040_can_node"])
        assert report.total_count == 2
