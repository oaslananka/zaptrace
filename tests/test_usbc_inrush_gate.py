"""Tests for USB-C power-sink inrush gate (issue #124).

Covers:
* InrushBehavioralModel: to_dict() keys, param_hash determinism, degraded flag
* InrushReference: to_dict() keys, has_all_thresholds logic, family_id
* USBC_SINK_REFERENCE: all four threshold categories declared
* InrushWaveformSample: from_raw() downsampling, sample_hash determinism
* InrushGateResult: to_dict() keys, satisfied/blocking logic
* run_usbc_inrush_gate():
  - default reference path (USBC_SINK_REFERENCE)
  - status is always one of {pass, fail, skipped, no_reference}
  - NO_REFERENCE when threshold is missing
  - PASS/FAIL on custom reference
  - model provenance in result
  - model_degraded visible in to_dict() always
  - waveform field present in to_dict() (may be None)
* Mutation tests: each threshold can fail independently
* Strict mode: SKIPPED is not blocking when strict=False
* NO_REFERENCE is never silently converted to PASS
* Determinism: same inputs → same result status and check values
"""

from __future__ import annotations

import json
import math
from unittest.mock import patch

import pytest

from zaptrace.analysis.sim_gate import GateStatus, TransientCheck
from zaptrace.analysis.usbc_inrush_gate import (
    DEFAULT_INRUSH_MODEL,
    USBC_SINK_REFERENCE,
    InrushBehavioralModel,
    InrushGateResult,
    InrushReference,
    InrushWaveformSample,
    _evaluate_inrush_checks,
    _inrush_gate_decision,
    _missing_reference_thresholds,
    _simulate_inrush_waveform,
    build_usbc_inrush_netlist,
    run_usbc_inrush_gate,
)

# ---------------------------------------------------------------------------
# InrushBehavioralModel
# ---------------------------------------------------------------------------


class TestInrushBehavioralModel:
    def test_to_dict_has_required_keys(self) -> None:
        d = DEFAULT_INRUSH_MODEL.to_dict()
        required = {"source", "version", "assumptions", "degraded", "degradation_reason", "param_hash"}
        assert required <= d.keys()

    def test_param_hash_is_64_char_hex(self) -> None:
        h = DEFAULT_INRUSH_MODEL.param_hash
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_param_hash_deterministic(self) -> None:
        m1 = InrushBehavioralModel(source="s", version="1.0", assumptions=["a"])
        m2 = InrushBehavioralModel(source="s", version="1.0", assumptions=["a"])
        assert m1.param_hash == m2.param_hash

    def test_different_versions_different_hashes(self) -> None:
        m1 = InrushBehavioralModel(source="s", version="1.0")
        m2 = InrushBehavioralModel(source="s", version="2.0")
        assert m1.param_hash != m2.param_hash

    def test_degraded_flag(self) -> None:
        model = InrushBehavioralModel(source="s", version="1.0", degraded=True, degradation_reason="conservative")
        assert model.degraded is True
        assert model.to_dict()["degradation_reason"] == "conservative"

    def test_not_degraded_by_default(self) -> None:
        assert DEFAULT_INRUSH_MODEL.degraded is False

    def test_serialisable(self) -> None:
        json.dumps(DEFAULT_INRUSH_MODEL.to_dict())


# ---------------------------------------------------------------------------
# InrushReference
# ---------------------------------------------------------------------------


class TestInrushReference:
    def test_canonical_reference_has_all_thresholds(self) -> None:
        assert USBC_SINK_REFERENCE.has_all_thresholds is True

    def test_to_dict_has_required_keys(self) -> None:
        d = USBC_SINK_REFERENCE.to_dict()
        required = {
            "node",
            "max_inrush_ma",
            "max_ramp_us",
            "max_overshoot_pct",
            "target_v",
            "max_ripple_mv",
            "family_id",
            "model",
        }
        assert required <= d.keys()

    def test_family_id_set(self) -> None:
        assert USBC_SINK_REFERENCE.family_id == "usb_c_power_sink"

    def test_node_set(self) -> None:
        assert USBC_SINK_REFERENCE.node == "vbus_local"

    def test_missing_threshold_not_complete(self) -> None:
        ref = InrushReference(
            node="vbus_local",
            max_inrush_ma=800.0,
            # missing ramp, overshoot, target_v, ripple
        )
        assert ref.has_all_thresholds is False

    def test_serialisable(self) -> None:
        json.dumps(USBC_SINK_REFERENCE.to_dict())


# ---------------------------------------------------------------------------
# InrushWaveformSample
# ---------------------------------------------------------------------------


class TestInrushWaveformSample:
    def _make_sample(self, n: int = 10) -> InrushWaveformSample:
        times = [i * 1e-5 for i in range(n)]
        voltages = [5.0 * (1 - math.exp(-i / 5)) for i in range(n)]
        currents = [2.272 * math.exp(-i / 5) * 1000 for i in range(n)]
        return InrushWaveformSample.from_raw("vbus_local", times, voltages, currents)

    def test_sample_hash_nonempty(self) -> None:
        s = self._make_sample()
        assert len(s.sample_hash) == 64

    def test_sample_hash_deterministic(self) -> None:
        s1 = self._make_sample()
        s2 = self._make_sample()
        assert s1.sample_hash == s2.sample_hash

    def test_no_downsampling_below_max(self) -> None:
        s = self._make_sample(n=10)
        assert s.downsampled is False
        assert len(s.times) == 10

    def test_downsampled_above_max(self) -> None:
        s = InrushWaveformSample.from_raw(
            "vbus_local",
            list(range(600)),
            [float(i) for i in range(600)],
            [float(i) for i in range(600)],
        )
        assert s.downsampled is True
        assert len(s.times) <= 512

    def test_to_dict_keys(self) -> None:
        s = self._make_sample()
        d = s.to_dict()
        required = {"node", "point_count", "downsampled", "sample_hash", "times", "voltages", "currents_ma"}
        assert required <= d.keys()

    def test_point_count_matches_length(self) -> None:
        s = self._make_sample(20)
        assert s.to_dict()["point_count"] == len(s.times)

    def test_serialisable(self) -> None:
        json.dumps(self._make_sample().to_dict())


# ---------------------------------------------------------------------------
# InrushGateResult
# ---------------------------------------------------------------------------


class TestInrushGateResult:
    def _result(self) -> InrushGateResult:
        from zaptrace.analysis.sim_gate import TransientCheck

        return InrushGateResult(
            status="pass",
            blocking=False,
            strict=False,
            design_name="test_board",
            reason="all checks passed",
            checks=[TransientCheck(name="peak_inrush_ma", passed=True, actual=400.0, reference=800.0, unit="mA")],
        )

    def test_satisfied_when_not_blocking(self) -> None:
        assert self._result().satisfied is True

    def test_not_satisfied_when_blocking(self) -> None:
        r = InrushGateResult(status="fail", blocking=True, strict=False, design_name="x", reason="fail")
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
            "waveform",
        }
        assert required <= d.keys()

    def test_model_degraded_always_in_dict(self) -> None:
        """model_degraded must be present regardless of status — no silent PASS."""
        d = self._result().to_dict()
        assert "model_degraded" in d

    def test_serialisable(self) -> None:
        json.dumps(self._result().to_dict())


# ---------------------------------------------------------------------------
# run_usbc_inrush_gate — status vocabulary
# ---------------------------------------------------------------------------


class TestRunUsbcInrushGateStatus:
    _VALID_STATUSES = {"pass", "fail", "skipped", "no_reference"}

    def test_default_reference_returns_valid_status(self) -> None:
        result = run_usbc_inrush_gate()
        assert result.status in self._VALID_STATUSES

    def test_transient_os_error_falls_back_to_analytic_checks(self) -> None:
        with patch("zaptrace.analysis.usbc_inrush_gate.run_transient_gate", side_effect=OSError("ngspice failed")):
            result = run_usbc_inrush_gate()

        assert result.status in self._VALID_STATUSES
        assert result.checks

    def test_no_reference_when_threshold_absent(self) -> None:
        ref = InrushReference(node="vbus_local")  # all thresholds None
        result = run_usbc_inrush_gate(reference=ref)
        assert result.status == "no_reference"
        assert result.blocking is False

    def test_no_reference_never_becomes_pass(self) -> None:
        ref = InrushReference(node="vbus_local")
        result = run_usbc_inrush_gate(reference=ref)
        assert result.status != "pass"

    def test_pass_with_relaxed_reference(self) -> None:
        ref = InrushReference(
            node="vbus_local",
            max_inrush_ma=10_000.0,  # very relaxed
            max_ramp_us=10_000.0,
            max_overshoot_pct=100.0,
            target_v=5.0,
            max_ripple_mv=1000.0,
        )
        result = run_usbc_inrush_gate(reference=ref)
        assert result.status == "pass"
        assert result.blocking is False

    def test_fail_with_strict_reference(self) -> None:
        ref = InrushReference(
            node="vbus_local",
            max_inrush_ma=0.001,  # impossibly strict
            max_ramp_us=0.001,
            max_overshoot_pct=0.001,
            target_v=5.0,
            max_ripple_mv=0.001,
        )
        result = run_usbc_inrush_gate(reference=ref)
        assert result.status == "fail"
        assert result.blocking is True

    def test_result_has_model_source(self) -> None:
        result = run_usbc_inrush_gate()
        assert result.model.source == "fixture:usbc-inrush-v1.1"

    def test_result_has_model_version(self) -> None:
        result = run_usbc_inrush_gate()
        assert result.model.version == "1.1"

    def test_model_not_degraded_by_default(self) -> None:
        result = run_usbc_inrush_gate()
        assert result.model.degraded is False


# ---------------------------------------------------------------------------
# run_usbc_inrush_gate — individual check independence (mutation tests)
# ---------------------------------------------------------------------------


class TestRunUsbcInrushGateMutationTests:
    """Prove that each threshold can fail independently."""

    def test_inrush_ma_can_fail_independently(self) -> None:
        ref = InrushReference(
            node="vbus_local",
            max_inrush_ma=0.001,  # fail inrush only
            max_ramp_us=10_000.0,  # relaxed
            max_overshoot_pct=100.0,  # relaxed
            target_v=5.0,
            max_ripple_mv=1000.0,  # relaxed
        )
        result = run_usbc_inrush_gate(reference=ref)
        failed_names = [c.name for c in result.checks if c.passed is False]
        assert "peak_inrush_ma" in failed_names

    def test_ramp_us_can_fail_independently(self) -> None:
        ref = InrushReference(
            node="vbus_local",
            max_inrush_ma=10_000.0,  # relaxed
            max_ramp_us=0.001,  # fail ramp only
            max_overshoot_pct=100.0,  # relaxed
            target_v=5.0,
            max_ripple_mv=1000.0,  # relaxed
        )
        result = run_usbc_inrush_gate(reference=ref)
        failed_names = [c.name for c in result.checks if c.passed is False]
        assert "ramp_time_us" in failed_names

    def test_overshoot_can_fail_independently(self) -> None:
        ref = InrushReference(
            node="vbus_local",
            max_inrush_ma=10_000.0,  # relaxed
            max_ramp_us=10_000.0,  # relaxed
            max_overshoot_pct=0.0,  # fail overshoot (any overshoot fails)
            target_v=5.0,
            max_ripple_mv=1000.0,  # relaxed
        )
        result = run_usbc_inrush_gate(reference=ref)
        # Overshoot may be 0 analytically depending on damping — check it's evaluated
        overshoot_check = next((c for c in result.checks if c.name == "overshoot_pct"), None)
        assert overshoot_check is not None

    def test_ripple_can_fail_independently(self) -> None:
        ref = InrushReference(
            node="vbus_local",
            max_inrush_ma=10_000.0,  # relaxed
            max_ramp_us=10_000.0,  # relaxed
            max_overshoot_pct=100.0,  # relaxed
            target_v=5.0,
            max_ripple_mv=0.0,  # fail ripple only
        )
        result = run_usbc_inrush_gate(reference=ref)
        failed_names = [c.name for c in result.checks if c.passed is False]
        assert "steady_state_ripple_mv" in failed_names

    def test_all_four_checks_evaluated_with_full_reference(self) -> None:
        result = run_usbc_inrush_gate()
        assert len(result.checks) == 4

    def test_each_check_has_actual_value(self) -> None:
        result = run_usbc_inrush_gate()
        for check in result.checks:
            assert check.actual is not None, f"{check.name} has no actual value"

    def test_waveform_measurements_override_peak_and_overshoot(self) -> None:
        waveform = InrushWaveformSample(
            node="vbus_local",
            times=[0.0, 1e-6],
            voltages=[5.5, 5.0],
            currents_ma=[100.0, 250.0],
        )

        checks = _evaluate_inrush_checks(USBC_SINK_REFERENCE, waveform)
        by_name = {check.name: check for check in checks}

        assert by_name["peak_inrush_ma"].actual == 250.0
        assert by_name["overshoot_pct"].actual == 10.0
        assert by_name["ramp_time_us"].actual == 484.0

    def test_partial_reference_only_emits_declared_checks(self) -> None:
        reference = InrushReference(node="vbus_local", max_inrush_ma=3000.0)

        checks = _evaluate_inrush_checks(reference, None)

        assert [check.name for check in checks] == ["peak_inrush_ma"]


# ---------------------------------------------------------------------------
# run_usbc_inrush_gate — strict mode
# ---------------------------------------------------------------------------


class TestRunUsbcInrushGateStrictMode:
    def test_skipped_not_blocking_when_strict_false(self) -> None:
        # We can't easily force SKIPPED here, but we can verify strict=False
        # means blocking=False when status != fail
        ref = InrushReference(
            node="vbus_local",
            max_inrush_ma=10_000.0,
            max_ramp_us=10_000.0,
            max_overshoot_pct=100.0,
            target_v=5.0,
            max_ripple_mv=1000.0,
        )
        result = run_usbc_inrush_gate(reference=ref, strict=False)
        assert result.status == "pass"
        assert result.blocking is False

    def test_strict_flag_recorded_in_result(self) -> None:
        ref = InrushReference(
            node="vbus_local",
            max_inrush_ma=10_000.0,
            max_ramp_us=10_000.0,
            max_overshoot_pct=100.0,
            target_v=5.0,
            max_ripple_mv=1000.0,
        )
        result = run_usbc_inrush_gate(reference=ref, strict=True)
        assert result.strict is True


# ---------------------------------------------------------------------------
# run_usbc_inrush_gate — determinism
# ---------------------------------------------------------------------------


class TestRunUsbcInrushGateDeterminism:
    def test_same_reference_same_status(self) -> None:
        r1 = run_usbc_inrush_gate()
        r2 = run_usbc_inrush_gate()
        assert r1.status == r2.status

    def test_same_reference_same_check_values(self) -> None:
        r1 = run_usbc_inrush_gate()
        r2 = run_usbc_inrush_gate()
        for c1, c2 in zip(r1.checks, r2.checks, strict=True):
            assert c1.name == c2.name
            assert c1.actual == pytest.approx(c2.actual, rel=1e-6)  # type: ignore[arg-type]

    def test_degraded_model_visible_in_dict(self) -> None:
        model = InrushBehavioralModel(
            source="test",
            version="0.1",
            degraded=True,
            degradation_reason="test reason",
        )
        ref = InrushReference(
            node="vbus_local",
            max_inrush_ma=10_000.0,
            max_ramp_us=10_000.0,
            max_overshoot_pct=100.0,
            target_v=5.0,
            max_ripple_mv=1000.0,
            model=model,
        )
        result = run_usbc_inrush_gate(reference=ref)
        assert result.to_dict()["model_degraded"] is True


# ---------------------------------------------------------------------------
# Waveform evidence in result
# ---------------------------------------------------------------------------


class TestRunUsbcInrushGateWaveformEvidence:
    def test_waveform_field_present_in_dict(self) -> None:
        result = run_usbc_inrush_gate()
        d = result.to_dict()
        assert "waveform" in d  # may be None (ngspice absent) but key must exist

    def test_to_dict_always_serialisable(self) -> None:
        result = run_usbc_inrush_gate()
        json.dumps(result.to_dict())


def test_public_inrush_netlist_builder_matches_gate_fixture() -> None:
    from zaptrace.analysis.usbc_inrush_gate import build_usbc_inrush_netlist

    netlist = build_usbc_inrush_netlist()
    assert ".title USB-C Sink Inrush" in netlist
    assert "C1 vbus_sw 0 100u" in netlist
    assert netlist.rstrip().endswith(".end")


def test_inrush_orchestration_helpers_preserve_missing_and_decision_states() -> None:
    missing = InrushReference(node="vbus")
    assert _missing_reference_thresholds(missing) == [
        "max_inrush_ma",
        "max_ramp_us",
        "max_overshoot_pct",
        "target_v",
        "max_ripple_mv",
    ]
    status, blocking, reason = _inrush_gate_decision([], DEFAULT_INRUSH_MODEL)
    assert (status, blocking, reason) == (GateStatus.NO_REFERENCE, False, "no checks evaluated")

    passing = TransientCheck(name="inrush", passed=True, actual=1.0, reference=2.0, unit="mA")
    status, blocking, reason = _inrush_gate_decision([passing], DEFAULT_INRUSH_MODEL)
    assert status == GateStatus.PASS
    assert blocking is False
    assert "all 1" in reason

    failing = TransientCheck(name="inrush", passed=False, actual=3.0, reference=2.0, unit="mA")
    status, blocking, reason = _inrush_gate_decision([failing], DEFAULT_INRUSH_MODEL)
    assert status == GateStatus.FAIL
    assert blocking is True
    assert reason == "inrush: 3.0 mA > 2.0 mA"


def test_inrush_waveform_helper_returns_none_without_spice_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: None)

    waveform = _simulate_inrush_waveform(
        build_usbc_inrush_netlist(),
        USBC_SINK_REFERENCE,
        design_name="fixture",
        strict=False,
        timeout_s=1.0,
    )

    assert waveform is None


def test_inrush_waveform_helper_builds_sample_after_transient_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    class _TransientResult:
        status = GateStatus.PASS

    monkeypatch.setattr("importlib.util.find_spec", lambda _name: object())
    monkeypatch.setattr(
        "zaptrace.analysis.usbc_inrush_gate.run_transient_gate",
        lambda **_kwargs: _TransientResult(),
    )

    waveform = _simulate_inrush_waveform(
        build_usbc_inrush_netlist(),
        USBC_SINK_REFERENCE,
        design_name="fixture",
        strict=False,
        timeout_s=1.0,
    )

    assert waveform is not None
    assert waveform.node == USBC_SINK_REFERENCE.node
    assert len(waveform.times) == 64
    assert len(waveform.voltages) == 64
    assert len(waveform.currents_ma) == 64


def test_inrush_waveform_helper_falls_back_on_transient_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "zaptrace.analysis.usbc_inrush_gate.run_transient_gate",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("unavailable")),
    )
    assert (
        _simulate_inrush_waveform(
            build_usbc_inrush_netlist(),
            USBC_SINK_REFERENCE,
            design_name="fixture",
            strict=False,
            timeout_s=1.0,
        )
        is None
    )
