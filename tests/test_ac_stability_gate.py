"""Tests for AC stability gate for the lipo_charger_node family (issue #125).

Covers:
* AcStabilityModel: param_hash determinism, degraded flag, to_dict()
* AcStabilityReference: to_dict(), has_any_threshold, family_id
* LIPO_CHARGER_REFERENCE: has thresholds, correct family_id
* WaveformCSVRecord: from_sweep, downsampling, hash determinism, to_csv, to_dict
* AcStabilityGateResult: to_dict() keys, satisfied/blocking, model_degraded visibility
* run_ac_stability_gate():
  - default reference: PASS
  - NO_REFERENCE when no thresholds
  - FAIL on strict reference
  - status vocabulary: {pass, fail, skipped, no_reference}
  - model provenance in result
  - model_degraded always in to_dict()
  - waveform_csv produced
  - each check can fail independently (mutation tests)
  - determinism: same inputs → same status
* AcCoverageReport: pass/fail/no_reference/skipped counts, to_dict, to_json
* build_ac_coverage_report: aggregates multiple families
* Regression report: three families passing strict gates
"""

from __future__ import annotations

import json

from zaptrace.analysis.ac_stability_gate import (
    DEFAULT_AC_STABILITY_MODEL,
    LIPO_CHARGER_REFERENCE,
    AcCoverageReport,
    AcStabilityGateResult,
    AcStabilityModel,
    AcStabilityReference,
    FamilyAcSummary,
    WaveformCSVRecord,
    build_ac_coverage_report,
    run_ac_stability_gate,
)

# ---------------------------------------------------------------------------
# AcStabilityModel
# ---------------------------------------------------------------------------


class TestAcStabilityModel:
    def test_to_dict_has_required_keys(self) -> None:
        d = DEFAULT_AC_STABILITY_MODEL.to_dict()
        required = {"source", "version", "assumptions", "degraded", "degradation_reason", "param_hash"}
        assert required <= d.keys()

    def test_param_hash_is_64_char_hex(self) -> None:
        h = DEFAULT_AC_STABILITY_MODEL.param_hash
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_param_hash_deterministic(self) -> None:
        m1 = AcStabilityModel(source="s", version="1.0", assumptions=["a"])
        m2 = AcStabilityModel(source="s", version="1.0", assumptions=["a"])
        assert m1.param_hash == m2.param_hash

    def test_different_versions_different_hashes(self) -> None:
        m1 = AcStabilityModel(source="s", version="1.0")
        m2 = AcStabilityModel(source="s", version="2.0")
        assert m1.param_hash != m2.param_hash

    def test_degraded_flag(self) -> None:
        model = AcStabilityModel(source="s", version="1.0", degraded=True, degradation_reason="approx")
        assert model.to_dict()["degraded"] is True
        assert model.to_dict()["degradation_reason"] == "approx"

    def test_not_degraded_by_default(self) -> None:
        assert DEFAULT_AC_STABILITY_MODEL.degraded is False

    def test_serialisable(self) -> None:
        json.dumps(DEFAULT_AC_STABILITY_MODEL.to_dict())


# ---------------------------------------------------------------------------
# AcStabilityReference
# ---------------------------------------------------------------------------


class TestAcStabilityReference:
    def test_lipo_reference_has_thresholds(self) -> None:
        assert LIPO_CHARGER_REFERENCE.has_any_threshold is True

    def test_lipo_reference_family_id(self) -> None:
        assert LIPO_CHARGER_REFERENCE.family_id == "lipo_charger_node"

    def test_empty_reference_no_thresholds(self) -> None:
        ref = AcStabilityReference(node="vcharge")
        assert ref.has_any_threshold is False

    def test_to_dict_has_required_keys(self) -> None:
        d = LIPO_CHARGER_REFERENCE.to_dict()
        required = {
            "node",
            "min_gain_db",
            "gain_check_hz",
            "max_gain_db",
            "min_phase_margin_deg",
            "min_crossover_hz",
            "max_crossover_hz",
            "family_id",
            "model",
        }
        assert required <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(LIPO_CHARGER_REFERENCE.to_dict())


# ---------------------------------------------------------------------------
# WaveformCSVRecord
# ---------------------------------------------------------------------------


class TestWaveformCSVRecord:
    def _make_record(self, n: int = 20) -> WaveformCSVRecord:
        freqs = [100.0 * (10 ** (i / 10.0)) for i in range(n)]
        gains = [-3.0 - i * 0.5 for i in range(n)]
        phases = [-45.0 - i * 2.0 for i in range(n)]
        return WaveformCSVRecord.from_sweep("lipo_charger_node", freqs, gains, phases)

    def test_record_hash_64_chars(self) -> None:
        r = self._make_record()
        assert len(r.record_hash) == 64

    def test_record_hash_deterministic(self) -> None:
        r1 = self._make_record()
        r2 = self._make_record()
        assert r1.record_hash == r2.record_hash

    def test_no_downsampling_below_max(self) -> None:
        r = self._make_record(n=10)
        assert r.downsampled is False

    def test_downsampled_above_max(self) -> None:
        freqs = [float(i) for i in range(300)]
        gains = [0.0] * 300
        r = WaveformCSVRecord.from_sweep("test", freqs, gains)
        assert r.downsampled is True
        assert len(r.freqs_hz) <= 256

    def test_to_csv_has_header(self) -> None:
        r = self._make_record(5)
        csv = r.to_csv()
        assert csv.startswith("freq_hz,gain_db,phase_deg")

    def test_to_csv_row_count(self) -> None:
        r = self._make_record(5)
        lines = r.to_csv().splitlines()
        assert len(lines) == 6  # header + 5 rows

    def test_to_dict_required_keys(self) -> None:
        r = self._make_record()
        d = r.to_dict()
        required = {"family_id", "row_count", "downsampled", "record_hash", "freqs_hz", "gains_db", "phases_deg"}
        assert required <= d.keys()

    def test_to_dict_row_count_matches(self) -> None:
        r = self._make_record(10)
        assert r.to_dict()["row_count"] == 10

    def test_serialisable(self) -> None:
        json.dumps(self._make_record().to_dict())

    def test_no_phases_accepted(self) -> None:
        freqs = [100.0, 1000.0]
        gains = [-3.0, -6.0]
        r = WaveformCSVRecord.from_sweep("test", freqs, gains)
        assert r.phases_deg == []


# ---------------------------------------------------------------------------
# AcStabilityGateResult
# ---------------------------------------------------------------------------


class TestAcStabilityGateResult:
    def _result(self) -> AcStabilityGateResult:
        from zaptrace.analysis.sim_gate import AcCheck

        return AcStabilityGateResult(
            status="pass",
            blocking=False,
            strict=False,
            design_name="lipo_charger_node",
            reason="all checks passed",
            checks=[AcCheck(name="min_gain_db", passed=True, actual=3.0, reference=-3.0, unit="dB")],
        )

    def test_satisfied_when_not_blocking(self) -> None:
        assert self._result().satisfied is True

    def test_not_satisfied_when_blocking(self) -> None:
        r = AcStabilityGateResult(status="fail", blocking=True, strict=False, design_name="x", reason="fail")
        assert r.satisfied is False

    def test_to_dict_required_keys(self) -> None:
        d = self._result().to_dict()
        required = {
            "status",
            "blocking",
            "satisfied",
            "strict",
            "design_name",
            "reason",
            "model_degraded",
            "model_source",
            "model_version",
            "checks",
            "waveform_csv",
        }
        assert required <= d.keys()

    def test_model_degraded_always_present(self) -> None:
        d = self._result().to_dict()
        assert "model_degraded" in d

    def test_serialisable(self) -> None:
        json.dumps(self._result().to_dict())


# ---------------------------------------------------------------------------
# Internal stability-check decomposition
# ---------------------------------------------------------------------------


def test_crossover_helper_preserves_crossing_and_fallback_frequencies() -> None:
    from zaptrace.analysis import ac_stability_gate

    helper = getattr(ac_stability_gate, "_find_crossover_hz", None)
    assert helper is not None
    assert helper([1.0, 0.2, -0.4], [100.0, 1000.0, 2000.0]) == 1500.0
    assert helper([5.0, 2.0, 1.0], [100.0, 1000.0, 10000.0]) == 10000.0
    assert helper([], []) is None


def test_phase_margin_helper_preserves_missing_value_semantics() -> None:
    from zaptrace.analysis import ac_stability_gate

    helper = getattr(ac_stability_gate, "_phase_margin_at", None)
    assert helper is not None
    assert helper(None, [], []) is None


def test_empty_frequency_evaluation_preserves_empty_result() -> None:
    from zaptrace.analysis import ac_stability_gate

    helper = getattr(ac_stability_gate, "_evaluate_ac_stability_checks", None)
    assert helper is not None
    assert helper(AcStabilityReference(node="vout"), [], [], []) == []


def test_gain_check_helper_preserves_order_and_threshold_semantics() -> None:
    from zaptrace.analysis import ac_stability_gate

    helper = getattr(ac_stability_gate, "_gain_threshold_checks", None)
    assert helper is not None
    reference = AcStabilityReference(node="vout", min_gain_db=-1.0, max_gain_db=2.0)
    checks = helper(reference, 1.0)
    assert [check.to_dict() for check in checks] == [
        {"name": "min_gain_db", "passed": True, "actual": 1.0, "reference": -1.0, "unit": "dB"},
        {"name": "max_gain_db", "passed": True, "actual": 1.0, "reference": 2.0, "unit": "dB"},
    ]


def test_stability_check_helper_preserves_order_and_missing_value_fallbacks() -> None:
    from zaptrace.analysis import ac_stability_gate

    helper = getattr(ac_stability_gate, "_stability_threshold_checks", None)
    assert helper is not None
    reference = AcStabilityReference(
        node="vout",
        min_phase_margin_deg=45.0,
        min_crossover_hz=500.0,
        max_crossover_hz=1500.0,
    )
    checks = helper(reference, None, None)
    assert [check.to_dict() for check in checks] == [
        {"name": "min_phase_margin_deg", "passed": False, "actual": 0.0, "reference": 45.0, "unit": "deg"},
        {"name": "min_crossover_hz", "passed": False, "actual": 0.0, "reference": 500.0, "unit": "Hz"},
        {"name": "max_crossover_hz", "passed": True, "actual": 0.0, "reference": 1500.0, "unit": "Hz"},
    ]


# ---------------------------------------------------------------------------
# run_ac_stability_gate — status vocabulary
# ---------------------------------------------------------------------------


class TestRunAcStabilityGateStatus:
    _VALID_STATUSES = {"pass", "fail", "skipped", "no_reference"}

    def test_default_reference_passes(self) -> None:
        result = run_ac_stability_gate()
        assert result.status == "pass"

    def test_status_always_valid(self) -> None:
        result = run_ac_stability_gate()
        assert result.status in self._VALID_STATUSES

    def test_no_reference_when_no_thresholds(self) -> None:
        ref = AcStabilityReference(node="vcharge")
        result = run_ac_stability_gate(reference=ref)
        assert result.status == "no_reference"

    def test_no_reference_never_becomes_pass(self) -> None:
        ref = AcStabilityReference(node="vcharge")
        result = run_ac_stability_gate(reference=ref)
        assert result.status != "pass"
        assert result.blocking is False

    def test_fail_on_impossible_reference(self) -> None:
        ref = AcStabilityReference(
            node="vcharge",
            min_gain_db=999.0,  # impossible
        )
        result = run_ac_stability_gate(reference=ref)
        assert result.status == "fail"

    def test_model_source_in_result(self) -> None:
        result = run_ac_stability_gate()
        assert result.model.source == "fixture:ac-stability-v1.0"

    def test_model_not_degraded_by_default(self) -> None:
        result = run_ac_stability_gate()
        assert result.model.degraded is False

    def test_model_degraded_visible_in_dict(self) -> None:
        model = AcStabilityModel(source="test", version="0.1", degraded=True, degradation_reason="test")
        ref = AcStabilityReference(node="vcharge", min_gain_db=-100.0, model=model)
        result = run_ac_stability_gate(reference=ref)
        assert result.to_dict()["model_degraded"] is True

    def test_waveform_csv_produced(self) -> None:
        result = run_ac_stability_gate()
        assert result.waveform_csv is not None
        assert len(result.waveform_csv.freqs_hz) > 0

    def test_waveform_in_to_dict(self) -> None:
        result = run_ac_stability_gate()
        d = result.to_dict()
        assert "waveform_csv" in d


# ---------------------------------------------------------------------------
# run_ac_stability_gate — independent check mutation tests
# ---------------------------------------------------------------------------


class TestRunAcStabilityGateMutationTests:
    """Prove each threshold can fail independently."""

    def test_min_gain_can_fail_independently(self) -> None:
        ref = AcStabilityReference(
            node="vcharge",
            min_gain_db=999.0,  # impossible
        )
        result = run_ac_stability_gate(reference=ref)
        failed = [c.name for c in result.checks if c.passed is False]
        assert "min_gain_db" in failed

    def test_max_gain_can_fail_independently(self) -> None:
        ref = AcStabilityReference(
            node="vcharge",
            max_gain_db=-999.0,  # impossibly strict
        )
        result = run_ac_stability_gate(reference=ref)
        failed = [c.name for c in result.checks if c.passed is False]
        assert "max_gain_db" in failed

    def test_phase_margin_can_fail_independently(self) -> None:
        ref = AcStabilityReference(
            node="vcharge",
            min_phase_margin_deg=999.0,  # impossible
        )
        result = run_ac_stability_gate(reference=ref)
        failed = [c.name for c in result.checks if c.passed is False]
        assert "min_phase_margin_deg" in failed

    def test_min_crossover_can_fail_independently(self) -> None:
        ref = AcStabilityReference(
            node="vcharge",
            min_crossover_hz=1e12,  # impossibly high
        )
        result = run_ac_stability_gate(reference=ref)
        failed = [c.name for c in result.checks if c.passed is False]
        assert "min_crossover_hz" in failed

    def test_max_crossover_can_fail_independently(self) -> None:
        ref = AcStabilityReference(
            node="vcharge",
            max_crossover_hz=0.001,  # impossibly strict
        )
        result = run_ac_stability_gate(reference=ref)
        failed = [c.name for c in result.checks if c.passed is False]
        assert "max_crossover_hz" in failed


# ---------------------------------------------------------------------------
# run_ac_stability_gate — determinism
# ---------------------------------------------------------------------------


class TestRunAcStabilityGateDeterminism:
    def test_same_status_across_runs(self) -> None:
        r1 = run_ac_stability_gate()
        r2 = run_ac_stability_gate()
        assert r1.status == r2.status

    def test_same_check_count(self) -> None:
        r1 = run_ac_stability_gate()
        r2 = run_ac_stability_gate()
        assert len(r1.checks) == len(r2.checks)

    def test_waveform_hash_deterministic(self) -> None:
        r1 = run_ac_stability_gate()
        r2 = run_ac_stability_gate()
        assert r1.waveform_csv is not None
        assert r2.waveform_csv is not None
        assert r1.waveform_csv.record_hash == r2.waveform_csv.record_hash


# ---------------------------------------------------------------------------
# AcCoverageReport
# ---------------------------------------------------------------------------


class TestAcCoverageReport:
    def _report_with_statuses(self, statuses: list[str]) -> AcCoverageReport:
        report = AcCoverageReport()
        for i, status in enumerate(statuses):
            report.families.append(
                FamilyAcSummary(
                    family_id=f"family_{i}",
                    status=status,
                    model_degraded=False,
                    check_count=3,
                    waveform_present=True,
                )
            )
        return report

    def test_pass_count(self) -> None:
        report = self._report_with_statuses(["pass", "pass", "fail"])
        assert report.pass_count == 2

    def test_fail_count(self) -> None:
        report = self._report_with_statuses(["pass", "fail"])
        assert report.fail_count == 1

    def test_no_reference_count(self) -> None:
        report = self._report_with_statuses(["no_reference", "pass"])
        assert report.no_reference_count == 1

    def test_skipped_count(self) -> None:
        report = self._report_with_statuses(["skipped", "pass"])
        assert report.skipped_count == 1

    def test_degraded_count(self) -> None:
        report = AcCoverageReport()
        report.families.append(FamilyAcSummary("f1", "pass", True, 3, True))
        report.families.append(FamilyAcSummary("f2", "pass", False, 3, True))
        assert report.degraded_model_count == 1

    def test_to_dict_required_keys(self) -> None:
        report = self._report_with_statuses(["pass"])
        d = report.to_dict()
        required = {
            "family_count",
            "pass_count",
            "fail_count",
            "no_reference_count",
            "skipped_count",
            "degraded_model_count",
            "families",
        }
        assert required <= d.keys()

    def test_to_json_round_trips(self) -> None:
        report = self._report_with_statuses(["pass", "fail"])
        d = json.loads(report.to_json())
        assert d["pass_count"] == 1
        assert d["fail_count"] == 1

    def test_statuses_remain_distinguishable(self) -> None:
        """NO_REFERENCE, SKIPPED, FAIL, PASS remain separate at aggregate level."""
        report = self._report_with_statuses(["pass", "fail", "skipped", "no_reference"])
        d = report.to_dict()
        assert d["pass_count"] == 1
        assert d["fail_count"] == 1
        assert d["skipped_count"] == 1
        assert d["no_reference_count"] == 1


# ---------------------------------------------------------------------------
# build_ac_coverage_report
# ---------------------------------------------------------------------------


class TestBuildAcCoverageReport:
    def test_three_families_all_pass(self) -> None:
        results = {
            "esp32_usb_sensor": run_ac_stability_gate(design_name="esp32_usb_sensor"),
            "lipo_charger_node": run_ac_stability_gate(design_name="lipo_charger_node"),
            "rp2040_can_node": run_ac_stability_gate(design_name="rp2040_can_node"),
        }
        report = build_ac_coverage_report(results)
        assert report.pass_count == 3
        assert report.fail_count == 0

    def test_family_ids_in_report(self) -> None:
        results = {
            "family_a": run_ac_stability_gate(design_name="family_a"),
            "family_b": run_ac_stability_gate(design_name="family_b"),
        }
        report = build_ac_coverage_report(results)
        assert {f.family_id for f in report.families} == {"family_a", "family_b"}

    def test_waveform_present_tracked(self) -> None:
        results = {
            "lipo_charger_node": run_ac_stability_gate(),
        }
        report = build_ac_coverage_report(results)
        assert report.families[0].waveform_present is True

    def test_empty_results(self) -> None:
        report = build_ac_coverage_report({})
        assert report.pass_count == 0
        assert len(report.families) == 0


def test_ac_stability_result_reports_analytical_method_without_solver(monkeypatch) -> None:
    from zaptrace.analysis.sim_gate import AcGateResult

    monkeypatch.setattr(
        "zaptrace.analysis.ac_stability_gate.run_ac_gate",
        lambda **_kwargs: AcGateResult(
            status="skipped",
            blocking=False,
            strict=False,
            design_name="fixture",
            reason="solver unavailable",
        ),
    )
    result = run_ac_stability_gate(design_name="fixture")
    assert result.evidence_method == "analytical"
    assert result.to_dict()["evidence_method"] == "analytical"


def test_ac_stability_result_reports_ngspice_method_when_solver_runs(monkeypatch) -> None:
    from zaptrace.analysis.sim_gate import AcCheck, AcGateResult

    monkeypatch.setattr(
        "zaptrace.analysis.ac_stability_gate.run_ac_gate",
        lambda **_kwargs: AcGateResult(
            status="pass",
            blocking=False,
            strict=False,
            design_name="fixture",
            reason="solver passed",
            checks=[AcCheck("gain", True, 3.0, -3.0, "dB")],
        ),
    )
    result = run_ac_stability_gate(design_name="fixture")
    assert result.evidence_method == "ngspice"
    assert result.to_dict()["evidence_method"] == "ngspice"


def test_public_ac_netlist_builder_matches_gate_fixture() -> None:
    from zaptrace.analysis.ac_stability_gate import build_ac_stability_netlist

    netlist = build_ac_stability_netlist()
    assert ".title LiPo Charger AC Stability" in netlist
    assert "C1 vcharge 0 10u" in netlist
    assert netlist.rstrip().endswith(".end")
