"""Tests for AC gain and phase checks with explicit model degradation (issue #111).

Covers:
* with_ac_control: control block injection (with and without .end in netlist)
* parse_ac_output: nominal two/three-column rows, optional index column,
  zero-magnitude rows, empty text, out-of-order rows (sorted ascending)
* AcResult helpers: frequencies_hz, magnitudes_db, phases_deg,
  gain_at_hz (in-range, out-of-range, interpolation),
  crossover_hz (descending edge, never crosses),
  phase_margin_deg (with and without phase data)
* run_ac: skipped (ngspice absent), error, success (mocked)
* AcCheck / AcReference dataclasses
* AcGateResult: to_dict keys, satisfied, model_degraded always present
* run_ac_gate: all four status branches
  - skipped (non-strict → not blocking; strict → blocking)
  - error (ngspice fail)
  - pass (all checks pass)
  - fail (at least one check fails)
  - no_reference (no thresholds provided)
* Individual check types: min_gain, max_gain, phase_margin,
  min_crossover, max_crossover
* Model degradation is visible in to_dict() even on PASS
"""

from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from zaptrace.analysis.sim_gate import (
    AcCheck,
    AcGateResult,
    AcReference,
    run_ac_gate,
)
from zaptrace.analysis.spice_sim import (
    AcResult,
    AcSample,
    parse_ac_output,
    with_ac_control,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIMPLE_NETLIST = """\
* Simple RC low-pass filter
Vin in 0 AC 1
R1 in out 1k
C1 out 0 1u
.end
"""


def _make_ac_result(
    *,
    freqs: list[float],
    mags_db: list[float],
    phases: list[float | None] | None = None,
    status: str = "ok",
) -> AcResult:
    """Build an AcResult from explicit lists."""
    if phases is None:
        phases_list: list[float | None] = [None] * len(freqs)
    else:
        phases_list = phases
    samples = [
        AcSample(freq_hz=f, magnitude_db=m, phase_deg=p) for f, m, p in zip(freqs, mags_db, phases_list, strict=True)
    ]
    return AcResult(status=status, samples=samples, node="vout")


def _pass_ac_result() -> AcResult:
    """AC result with +6 dB at 1 kHz, crossover at ~100 kHz, +45° phase margin."""
    freqs = [1e1, 1e2, 1e3, 1e4, 1e5, 1e6]
    # Gains: high at low freq, crossing 0 dB around 1e5
    mags = [20.0, 15.0, 6.0, -6.0, 0.0, -20.0]
    phases = [-10.0, -30.0, -60.0, -120.0, -135.0, -160.0]
    return _make_ac_result(freqs=freqs, mags_db=mags, phases=phases)


def _mock_run_ac_pass() -> AcResult:
    return _pass_ac_result()


def _mock_run_ac_skipped() -> AcResult:
    return AcResult(status="skipped", node="vout", reason="ngspice not installed")


def _mock_run_ac_error() -> AcResult:
    return AcResult(status="error", node="vout", reason="ngspice exited 1")


# ---------------------------------------------------------------------------
# with_ac_control
# ---------------------------------------------------------------------------


class TestWithAcControl:
    def test_injects_control_block(self) -> None:
        result = with_ac_control(_SIMPLE_NETLIST)
        assert ".control" in result
        assert "ac dec" in result
        assert "print vm(vout) vp(vout)" in result
        assert ".endc" in result

    def test_placed_before_end(self) -> None:
        result = with_ac_control(_SIMPLE_NETLIST)
        lines = [ln.strip().lower() for ln in result.splitlines()]
        control_idx = next(i for i, ln in enumerate(lines) if ln == ".control")
        end_idx = next(i for i, ln in enumerate(lines) if ln == ".end")
        assert control_idx < end_idx

    def test_appends_end_when_missing(self) -> None:
        no_end = "* netlist\nR1 in out 1k"
        result = with_ac_control(no_end, node="vout")
        assert result.endswith(".end\n")
        assert ".control" in result

    def test_custom_node(self) -> None:
        result = with_ac_control(_SIMPLE_NETLIST, node="mynet")
        assert "vm(mynet)" in result
        assert "vp(mynet)" in result

    def test_custom_sweep_params(self) -> None:
        result = with_ac_control(
            _SIMPLE_NETLIST,
            variation="lin",
            points_per_decade=100,
            start_hz=100.0,
            stop_hz=1e5,
        )
        assert "ac lin 100 100 100000" in result

    def test_default_sweep_range(self) -> None:
        result = with_ac_control(_SIMPLE_NETLIST)
        assert "1 10000000" in result or "1.0 1e+07" in result or "1 1e+07" in result


# ---------------------------------------------------------------------------
# parse_ac_output
# ---------------------------------------------------------------------------


class TestParseAcOutput:
    def test_parses_three_column_rows(self) -> None:
        text = "1.000000e+02   3.162278e+00   -45.000000\n1.000000e+03   1.000000e+00   -90.000000\n"
        samples = parse_ac_output(text, "vout")
        assert len(samples) == 2
        assert samples[0].freq_hz == pytest.approx(100.0)
        assert samples[0].phase_deg == pytest.approx(-45.0)
        assert samples[1].freq_hz == pytest.approx(1000.0)
        assert samples[1].phase_deg == pytest.approx(-90.0)

    def test_parses_two_column_rows(self) -> None:
        text = "1.000000e+03   1.000000e+00\n"
        samples = parse_ac_output(text, "vout")
        assert len(samples) == 1
        assert samples[0].phase_deg is None

    def test_magnitude_converted_to_db(self) -> None:
        text = "1.000000e+03   1.000000e+00   0.0\n"
        samples = parse_ac_output(text, "vout")
        # linear 1.0 → 0 dB
        assert samples[0].magnitude_db == pytest.approx(0.0, abs=1e-6)

    def test_magnitude_2_is_6db(self) -> None:
        text = "1.000000e+03   1.995262e+00   0.0\n"
        samples = parse_ac_output(text, "vout")
        assert samples[0].magnitude_db == pytest.approx(6.0, abs=0.1)

    def test_zero_magnitude_is_minus_inf(self) -> None:
        text = "1.000000e+03   0.000000e+00   0.0\n"
        samples = parse_ac_output(text, "vout")
        assert samples[0].magnitude_db == float("-inf")

    def test_optional_index_column(self) -> None:
        text = "0  1.000000e+02   1.000000e+00   -10.0\n"
        samples = parse_ac_output(text, "vout")
        assert len(samples) == 1
        assert samples[0].freq_hz == pytest.approx(100.0)

    def test_sorted_ascending_by_freq(self) -> None:
        text = (
            "1.000000e+04   0.500000e+00   -80.0\n"
            "1.000000e+02   2.000000e+00   -10.0\n"
            "1.000000e+03   1.000000e+00   -45.0\n"
        )
        samples = parse_ac_output(text, "vout")
        freqs = [s.freq_hz for s in samples]
        assert freqs == sorted(freqs)

    def test_empty_text_returns_empty(self) -> None:
        assert parse_ac_output("", "vout") == []

    def test_non_numeric_lines_skipped(self) -> None:
        text = "ngspice version 37\n1.000000e+03   1.000000e+00   -45.0\nCircuit: AC test\n"
        samples = parse_ac_output(text, "vout")
        assert len(samples) == 1

    def test_negative_frequency_skipped(self) -> None:
        text = "-1.000000e+02   1.000000e+00   0.0\n"
        samples = parse_ac_output(text, "vout")
        assert samples == []


# ---------------------------------------------------------------------------
# AcResult helpers
# ---------------------------------------------------------------------------


class TestAcResultHelpers:
    def test_frequencies_hz(self) -> None:
        r = _make_ac_result(freqs=[100.0, 1000.0, 10000.0], mags_db=[6.0, 0.0, -6.0])
        assert r.frequencies_hz == [100.0, 1000.0, 10000.0]

    def test_magnitudes_db(self) -> None:
        r = _make_ac_result(freqs=[1e3], mags_db=[3.0])
        assert r.magnitudes_db == [3.0]

    def test_phases_deg(self) -> None:
        r = _make_ac_result(freqs=[1e3], mags_db=[0.0], phases=[-45.0])
        assert r.phases_deg == [-45.0]

    def test_phases_deg_none_when_absent(self) -> None:
        r = _make_ac_result(freqs=[1e3], mags_db=[0.0])
        assert r.phases_deg == [None]


class TestGainAtHz:
    def test_exact_match(self) -> None:
        r = _make_ac_result(freqs=[1e3, 1e4], mags_db=[6.0, 0.0])
        assert r.gain_at_hz(1e3) == pytest.approx(6.0)

    def test_below_range_returns_none(self) -> None:
        r = _make_ac_result(freqs=[1e3, 1e4], mags_db=[6.0, 0.0])
        assert r.gain_at_hz(100.0) is None

    def test_above_range_returns_none(self) -> None:
        r = _make_ac_result(freqs=[1e3, 1e4], mags_db=[6.0, 0.0])
        assert r.gain_at_hz(1e5) is None

    def test_interpolated_midpoint(self) -> None:
        # At geometric mean of 1e3 and 1e4 → midpoint in log space
        r = _make_ac_result(freqs=[1e3, 1e4], mags_db=[6.0, 0.0])
        mid_freq = math.sqrt(1e3 * 1e4)  # geometric mean
        result = r.gain_at_hz(mid_freq)
        assert result is not None
        assert result == pytest.approx(3.0, abs=0.1)

    def test_fewer_than_two_samples_returns_none(self) -> None:
        r = _make_ac_result(freqs=[1e3], mags_db=[6.0])
        assert r.gain_at_hz(1e3) is None  # single sample, < 2 → always None
        assert r.gain_at_hz(900.0) is None  # out of range


class TestCrossoverHz:
    def test_finds_crossover(self) -> None:
        r = _make_ac_result(freqs=[1e3, 1e4, 1e5], mags_db=[10.0, 0.0, -10.0])
        fc = r.crossover_hz()
        assert fc is not None
        # Crossover should be at or near 1e4 (already at 0 dB)
        assert 1e3 < fc < 1e5

    def test_never_crosses_returns_none(self) -> None:
        r = _make_ac_result(freqs=[1e3, 1e4], mags_db=[-6.0, -12.0])
        assert r.crossover_hz() is None

    def test_always_above_returns_none(self) -> None:
        r = _make_ac_result(freqs=[1e3, 1e4], mags_db=[6.0, 3.0])
        assert r.crossover_hz() is None


class TestPhaseMarginDeg:
    def test_45_degree_phase_margin(self) -> None:
        # Gain crosses 0 dB at 1e4; phase is -135° there → margin = 45°
        r = _make_ac_result(
            freqs=[1e3, 1e4, 1e5],
            mags_db=[6.0, 0.0, -6.0],
            phases=[-90.0, -135.0, -160.0],
        )
        pm = r.phase_margin_deg()
        assert pm is not None
        assert pm == pytest.approx(45.0, abs=5.0)

    def test_no_crossover_returns_none(self) -> None:
        r = _make_ac_result(freqs=[1e3, 1e4], mags_db=[-6.0, -12.0], phases=[-45.0, -90.0])
        assert r.phase_margin_deg() is None

    def test_no_phase_data_returns_none(self) -> None:
        r = _make_ac_result(freqs=[1e3, 1e4, 1e5], mags_db=[6.0, 0.0, -6.0])
        # All phase_deg are None → phase_margin returns None
        assert r.phase_margin_deg() is None


# ---------------------------------------------------------------------------
# AcCheck dataclass
# ---------------------------------------------------------------------------


class TestAcCheck:
    def test_to_dict_keys(self) -> None:
        check = AcCheck(name="min_gain", passed=True, actual=6.0, reference=0.0, unit="dB")
        d = check.to_dict()
        assert set(d.keys()) == {"name", "passed", "actual", "reference", "unit"}

    def test_to_dict_values(self) -> None:
        check = AcCheck(name="phase_margin", passed=False, actual=20.0, reference=45.0, unit="deg")
        d = check.to_dict()
        assert d["passed"] is False
        assert d["actual"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# AcGateResult
# ---------------------------------------------------------------------------


class TestAcGateResult:
    def _make_result(self, *, status: str = "pass", model_degraded: bool = False) -> AcGateResult:
        return AcGateResult(
            status=status,
            blocking=False,
            strict=False,
            design_name="test_design",
            reason="ok",
            node="vout",
            model_degraded=model_degraded,
            model_source="fixture:v1.0",
        )

    def test_to_dict_has_required_keys(self) -> None:
        result = self._make_result()
        d = result.to_dict()
        required = {
            "status",
            "blocking",
            "satisfied",
            "strict",
            "design_name",
            "reason",
            "node",
            "model_degraded",
            "model_source",
            "checks",
        }
        assert required <= d.keys()

    def test_model_degraded_always_in_dict(self) -> None:
        result = self._make_result(model_degraded=True)
        assert result.to_dict()["model_degraded"] is True

    def test_satisfied_is_not_blocking(self) -> None:
        result = self._make_result(status="pass")
        assert result.satisfied is True

    def test_blocking_is_not_satisfied(self) -> None:
        result = AcGateResult(
            status="fail",
            blocking=True,
            strict=False,
            design_name="x",
            reason="fail",
            node="vout",
        )
        assert result.satisfied is False


# ---------------------------------------------------------------------------
# run_ac_gate — all status branches
# ---------------------------------------------------------------------------


class TestRunAcGateSkipped:
    def test_non_strict_not_blocking(self) -> None:
        ref = AcReference(node="vout", min_gain_db=0.0)
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=False),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref, design_name="test")
        assert result.status == "skipped"
        assert result.blocking is False

    def test_strict_is_blocking(self) -> None:
        ref = AcReference(node="vout", min_gain_db=0.0)
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=False),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref, design_name="test", strict=True)
        assert result.status == "skipped"
        assert result.blocking is True

    def test_model_degraded_visible_on_skip(self) -> None:
        ref = AcReference(node="vout", model_degraded=True)
        with patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=False):
            result = run_ac_gate(_SIMPLE_NETLIST, ref)
        assert result.to_dict()["model_degraded"] is True


class TestRunAcGateError:
    def test_error_is_blocking_fail(self) -> None:
        ref = AcReference(node="vout", min_gain_db=0.0)
        error_result = AcResult(status="error", node="vout", reason="ngspice exited 1")
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=error_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref, design_name="test")
        assert result.status == "fail"
        assert result.blocking is True


class TestRunAcGateNoReference:
    def test_no_thresholds_returns_no_reference(self) -> None:
        ref = AcReference(node="vout")  # no thresholds set
        ok_result = _pass_ac_result()
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=ok_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref)
        assert result.status == "no_reference"

    def test_no_reference_non_strict_not_blocking(self) -> None:
        ref = AcReference(node="vout")
        ok_result = _pass_ac_result()
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=ok_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref, strict=False)
        assert result.blocking is False

    def test_no_reference_strict_is_blocking(self) -> None:
        ref = AcReference(node="vout")
        ok_result = _pass_ac_result()
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=ok_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref, strict=True)
        assert result.blocking is True


class TestRunAcGatePass:
    def test_min_gain_pass(self) -> None:
        # _pass_ac_result has +6 dB at 1 kHz
        ref = AcReference(node="vout", min_gain_db=0.0, gain_check_hz=1e3)
        ok_result = _pass_ac_result()
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=ok_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref)
        assert result.status == "pass"
        assert result.blocking is False
        assert len(result.checks) == 1
        assert result.checks[0].name == "min_gain"
        assert result.checks[0].passed is True

    def test_phase_margin_pass(self) -> None:
        # _pass_ac_result: crossover near 1e5, phase -135 → margin 45°
        ref = AcReference(node="vout", min_phase_margin_deg=30.0)
        ok_result = _pass_ac_result()
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=ok_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref)
        assert result.status == "pass"

    def test_model_degraded_visible_on_pass(self) -> None:
        ref = AcReference(node="vout", min_gain_db=0.0, model_degraded=True)
        ok_result = _pass_ac_result()
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=ok_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref)
        assert result.to_dict()["model_degraded"] is True

    def test_multiple_checks_all_pass(self) -> None:
        ref = AcReference(
            node="vout",
            min_gain_db=0.0,
            gain_check_hz=1e3,
            min_phase_margin_deg=30.0,
        )
        ok_result = _pass_ac_result()
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=ok_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref)
        assert result.status == "pass"
        assert all(c.passed is True for c in result.checks)


class TestRunAcGateFail:
    def test_min_gain_fail(self) -> None:
        # Gain at 1 kHz is +6 dB; require >= +20 dB → fail
        ref = AcReference(node="vout", min_gain_db=20.0, gain_check_hz=1e3)
        ok_result = _pass_ac_result()
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=ok_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref)
        assert result.status == "fail"
        assert result.blocking is True
        assert result.checks[0].name == "min_gain"
        assert result.checks[0].passed is False

    def test_max_gain_fail(self) -> None:
        # Gain at 1 kHz is +6 dB; require <= +3 dB → fail
        ref = AcReference(node="vout", max_gain_db=3.0, gain_check_hz=1e3)
        ok_result = _pass_ac_result()
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=ok_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref)
        assert result.status == "fail"

    def test_phase_margin_fail(self) -> None:
        # _pass_ac_result: crossover ~3162 Hz, nearest sample 1kHz has phase=-60°
        # margin = -60 + 180 = 120°; require >= 150° → fail
        ref = AcReference(node="vout", min_phase_margin_deg=150.0)
        ok_result = _pass_ac_result()
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=ok_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref)
        assert result.status == "fail"

    def test_crossover_below_minimum_fails(self) -> None:
        # crossover at ~1e5; require >= 1e6 → fail
        ref = AcReference(node="vout", min_crossover_hz=1e6)
        ok_result = _pass_ac_result()
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=ok_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref)
        assert result.status == "fail"
        assert any(c.name == "min_crossover" for c in result.checks)

    def test_crossover_above_maximum_fails(self) -> None:
        # crossover at ~1e5; require <= 1e3 → fail
        ref = AcReference(node="vout", max_crossover_hz=1e3)
        ok_result = _pass_ac_result()
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=ok_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref)
        assert result.status == "fail"

    def test_fail_reason_contains_check_name(self) -> None:
        ref = AcReference(node="vout", min_gain_db=100.0)
        ok_result = _pass_ac_result()
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=ok_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref)
        assert "min_gain" in result.reason


class TestRunAcGateMalformedOutput:
    def test_no_samples_parsed_is_no_reference_effectively_fail(self) -> None:
        """If AC ran but no samples parsed, gain checks will use gain_at_hz → None → fail."""
        empty_result = AcResult(status="ok", samples=[], node="vout")
        ref = AcReference(node="vout", min_gain_db=0.0)
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=empty_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref)
        # gain_at_hz returns None for empty sweep → passed = False
        assert result.status == "fail"

    def test_phase_margin_no_crossover_returns_none_check_fails(self) -> None:
        # Gain is always negative → no crossover → phase_margin_deg = None → check fails
        no_cross_result = _make_ac_result(
            freqs=[1e3, 1e4],
            mags_db=[-6.0, -12.0],
            phases=[-45.0, -90.0],
        )
        ref = AcReference(node="vout", min_phase_margin_deg=45.0)
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_ac", return_value=no_cross_result),
        ):
            result = run_ac_gate(_SIMPLE_NETLIST, ref)
        assert result.status == "fail"
        pm_check = next(c for c in result.checks if c.name == "phase_margin")
        assert pm_check.actual is None
        assert pm_check.passed is False
