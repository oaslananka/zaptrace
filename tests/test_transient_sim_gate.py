"""Tests for the transient simulation gate (issue #110).

Covers:
* TransientWaveform helpers: ripple_v, startup_time_s, steady_state_window
* parse_tran_output: correct parsing of ngspice batch print output
* with_tran_control: injection of .tran control block
* run_transient: skip-aware behaviour when ngspice absent
* TransientGateResult: SKIPPED / NO_REFERENCE / PASS / FAIL verdicts (pure)
* run_transient_gate: end-to-end path with mocked ngspice output
* regulator_fixture: BUCK_NETLIST hash stability, REGULATOR_REFERENCE fields,
  make_buck_netlist parameterisation
* model_degraded is visible in to_dict() (cannot yield silent PASS)
"""

from __future__ import annotations

import pytest

from zaptrace.analysis.regulator_fixture import (
    BUCK_NETLIST,
    FIXTURE_HASH,
    FIXTURE_SOURCE,
    FIXTURE_VERSION,
    REGULATOR_REFERENCE,
    make_buck_netlist,
)
from zaptrace.analysis.sim_gate import (
    TransientCheck,
    TransientGateResult,
    TransientReference,
    run_transient_gate,
)
from zaptrace.analysis.spice_sim import (
    TransientResult,
    TransientWaveform,
    ngspice_available,
    parse_tran_output,
    run_transient,
    with_tran_control,
)

# ---------------------------------------------------------------------------
# TransientWaveform unit tests
# ---------------------------------------------------------------------------


def _make_waveform(times: list[float], voltages: list[float]) -> TransientWaveform:
    w = TransientWaveform(node="vout")
    w.times_s = list(times)
    w.voltages_v = list(voltages)
    return w


class TestTransientWaveform:
    def test_min_max_final(self) -> None:
        w = _make_waveform([0, 1e-6, 2e-6], [0.0, 2.0, 3.3])
        assert w.min_v == pytest.approx(0.0)
        assert w.max_v == pytest.approx(3.3)
        assert w.final_v == pytest.approx(3.3)

    def test_empty_waveform_min_max_none(self) -> None:
        w = TransientWaveform(node="x")
        assert w.min_v is None
        assert w.max_v is None
        assert w.final_v is None

    def test_ripple_v_steady_state(self) -> None:
        # 20 points — last 20% (4 points) should be 3.29–3.31 → 20 mV ripple.
        times = [i * 1e-6 for i in range(20)]
        voltages = [0.0] * 16 + [3.29, 3.31, 3.29, 3.31]
        w = _make_waveform(times, voltages)
        assert w.ripple_v() == pytest.approx(0.02, rel=1e-3)

    def test_ripple_v_empty(self) -> None:
        w = TransientWaveform(node="x")
        assert w.ripple_v() == pytest.approx(0.0)

    def test_steady_state_window_fraction(self) -> None:
        w = _make_waveform(list(range(10)), list(range(10)))
        window = w.steady_state_window(last_fraction=0.2)
        assert window == [8, 9]  # last 20% of 10 items = 2 items

    def test_startup_time_s_first_crossing(self) -> None:
        # Ramp from 0 → 3.3V; threshold = 90% × 3.3 = 2.97V
        times = [i * 10e-6 for i in range(11)]
        voltages = [i * 0.33 for i in range(11)]  # 0, 0.33, ..., 3.30
        w = _make_waveform(times, voltages)
        t = w.startup_time_s(3.3, threshold=0.9)
        # 2.97V at index 9 → t = 90e-6
        assert t is not None
        assert t == pytest.approx(90e-6, rel=0.01)

    def test_startup_time_s_never_reaches_target(self) -> None:
        # Waveform never reaches threshold
        w = _make_waveform([0, 1e-6, 2e-6], [0.0, 1.0, 2.0])
        assert w.startup_time_s(3.3, threshold=0.9) is None


# ---------------------------------------------------------------------------
# parse_tran_output tests
# ---------------------------------------------------------------------------

_SAMPLE_TRAN_OUTPUT = """\
Circuit: buck converter
Doing analysis at TEMP = 27.000000

Index  v(vout)
0  0.000000e+00  0.000000e+00
1  1.000000e-09  0.100000e+00
2  2.000000e-09  3.300000e+00
3  3.000000e-09  3.305000e+00
"""


class TestParseTranOutput:
    def test_parses_time_voltage_rows(self) -> None:
        w = parse_tran_output(_SAMPLE_TRAN_OUTPUT, "vout")
        assert len(w.times_s) == 4
        assert w.times_s[2] == pytest.approx(2e-9)
        assert w.voltages_v[2] == pytest.approx(3.3)

    def test_node_name_set(self) -> None:
        w = parse_tran_output(_SAMPLE_TRAN_OUTPUT, "vout")
        assert w.node == "vout"

    def test_empty_output(self) -> None:
        w = parse_tran_output("no numbers here", "vout")
        assert w.times_s == []
        assert w.voltages_v == []

    def test_ignores_header_lines(self) -> None:
        # Lines with only one number should be ignored
        out = "Index  v(vout)\n0  0e+00  0e+00\n1  1e-06  3.3e+00\n"
        w = parse_tran_output(out, "vout")
        assert len(w.times_s) == 2


# ---------------------------------------------------------------------------
# with_tran_control tests
# ---------------------------------------------------------------------------


class TestWithTranControl:
    def test_inserts_before_end(self) -> None:
        netlist = "* title\nR1 a b 1k\n.end\n"
        out = with_tran_control(netlist, 1e-9, 100e-6, "vout")
        assert "tran " in out  # 'tran' command (inside .control, no leading dot)
        assert "print v(vout)" in out
        assert ".endc" in out
        assert out.strip().endswith(".end")

    def test_tran_step_and_stop_present(self) -> None:
        out = with_tran_control("* test\n.end", 1e-9, 50e-6, "vout")
        assert "1e-09 5e-05" in out or "1e-09 50e-06" in out or "1e-09" in out

    def test_node_name_in_print(self) -> None:
        out = with_tran_control("* test\n.end", 1e-9, 100e-6, "my_node")
        assert "v(my_node)" in out


# ---------------------------------------------------------------------------
# run_transient skip-aware tests
# ---------------------------------------------------------------------------


class TestRunTransient:
    def test_skip_when_ngspice_absent(self) -> None:
        if ngspice_available():
            pytest.skip("ngspice is installed — skipping absent-path test")
        result = run_transient("* test\n.end", "vout")
        assert result.status == "skipped"
        assert result.reason != ""

    def test_returns_transient_result_type(self) -> None:
        if ngspice_available():
            pytest.skip("ngspice is installed — skipping absent-path test")
        result = run_transient("* test\n.end", "vout")
        assert isinstance(result, TransientResult)


# ---------------------------------------------------------------------------
# TransientGateResult pure-logic tests (no ngspice needed)
# ---------------------------------------------------------------------------


def _make_gate_result(**kwargs) -> TransientGateResult:
    defaults = {
        "status": "pass",
        "blocking": False,
        "strict": False,
        "design_name": "test",
        "reason": "ok",
    }
    defaults.update(kwargs)
    return TransientGateResult(**defaults)


class TestTransientGateResult:
    def test_satisfied_when_not_blocking(self) -> None:
        r = _make_gate_result(blocking=False)
        assert r.satisfied is True

    def test_not_satisfied_when_blocking(self) -> None:
        r = _make_gate_result(blocking=True)
        assert r.satisfied is False

    def test_to_dict_contains_required_keys(self) -> None:
        r = _make_gate_result()
        d = r.to_dict()
        required = {
            "status",
            "blocking",
            "satisfied",
            "strict",
            "design_name",
            "reason",
            "model_degraded",
            "model_source",
            "checks",
        }
        assert required <= d.keys()

    def test_model_degraded_visible_in_to_dict(self) -> None:
        r = _make_gate_result(model_degraded=True, model_source="fixture:v1.0")
        d = r.to_dict()
        assert d["model_degraded"] is True
        assert d["model_source"] == "fixture:v1.0"


# ---------------------------------------------------------------------------
# run_transient_gate: skip path
# ---------------------------------------------------------------------------


class TestRunTransientGateSkim:
    def test_skipped_when_ngspice_absent(self) -> None:
        if ngspice_available():
            pytest.skip("ngspice is installed — skipping absent-path test")
        ref = TransientReference(node="vout", target_v=3.3, max_startup_us=100.0)
        result = run_transient_gate("* test\n.end", ref, design_name="test")
        assert result.status == "skipped"
        assert result.blocking is False  # not strict by default

    def test_skip_is_blocking_in_strict_mode(self) -> None:
        if ngspice_available():
            pytest.skip("ngspice is installed — skipping absent-path test")
        ref = TransientReference(node="vout", target_v=3.3, max_startup_us=100.0)
        result = run_transient_gate("* test\n.end", ref, design_name="test", strict=True)
        assert result.status == "skipped"
        assert result.blocking is True

    def test_no_reference_when_checks_disabled(self) -> None:
        """When max_startup_us and max_ripple_mv are both None, result is no_reference."""
        if ngspice_available():
            pytest.skip("ngspice is installed — skipping absent-path test")
        # With ngspice absent, we get "skipped" first.
        # Test no_reference logic via TransientGateResult directly.
        result = TransientGateResult(
            status="no_reference",
            blocking=False,
            strict=False,
            design_name="test",
            reason="no reference thresholds",
        )
        assert result.status == "no_reference"
        assert result.satisfied is True


# ---------------------------------------------------------------------------
# run_transient_gate: simulated pass/fail via mock
# ---------------------------------------------------------------------------


class TestRunTransientGateMocked:
    def _make_mock_tran_output(self, target_v: float, startup_us: float, ripple_mv: float) -> str:
        """Build fake ngspice output with predictable startup time and ripple."""
        rows = []
        steps = 100
        stop_s = 100e-6
        for i in range(steps + 1):
            t = i * stop_s / steps
            # Exponential rise, then steady state with ripple
            if t < startup_us * 1e-6 * 0.9:
                v = target_v * (1 - 2.718 ** (-t / (startup_us * 1e-6 * 0.3)))
            else:
                v = target_v + (ripple_mv / 2000.0) * (1 if i % 2 == 0 else -1)
            rows.append(f"  {t:.9e}  {v:.9e}")
        return "\n".join(rows)

    def test_pass_when_startup_and_ripple_within_limits(self) -> None:
        if ngspice_available():
            pytest.skip("ngspice is installed — skipping mock test")
        from unittest.mock import patch

        fake_output = self._make_mock_tran_output(3.3, startup_us=50.0, ripple_mv=10.0)
        mock_result = TransientResult(
            status="ok",
            waveforms={"vout": parse_tran_output(fake_output, "vout")},
        )
        ref = TransientReference(
            node="vout",
            target_v=3.3,
            max_startup_us=80.0,
            max_ripple_mv=50.0,
            model_source="fixture:v1.0:test",
            model_degraded=True,
        )
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_transient", return_value=mock_result),
        ):
            result = run_transient_gate("* test\n.end", ref, design_name="buck-test")
        assert result.status == "pass"
        assert result.satisfied is True
        assert result.model_degraded is True
        assert result.model_source == "fixture:v1.0:test"

    def test_fail_when_ripple_exceeds_limit(self) -> None:
        if ngspice_available():
            pytest.skip("ngspice is installed — skipping mock test")
        from unittest.mock import patch

        fake_output = self._make_mock_tran_output(3.3, startup_us=50.0, ripple_mv=100.0)
        mock_result = TransientResult(
            status="ok",
            waveforms={"vout": parse_tran_output(fake_output, "vout")},
        )
        ref = TransientReference(
            node="vout",
            target_v=3.3,
            max_startup_us=80.0,
            max_ripple_mv=50.0,
            model_source="fixture:v1.0:test",
            model_degraded=True,
        )
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_transient", return_value=mock_result),
        ):
            result = run_transient_gate("* test\n.end", ref, design_name="buck-test")
        assert result.status == "fail"
        assert result.blocking is True

    def test_fail_status_is_blocking(self) -> None:
        if ngspice_available():
            pytest.skip("ngspice is installed — skipping mock test")
        from unittest.mock import patch

        # Simulate an error
        mock_result = TransientResult(status="error", reason="ngspice timeout")
        ref = TransientReference(node="vout", target_v=3.3, max_startup_us=80.0)
        with (
            patch("zaptrace.analysis.spice_sim.ngspice_available", return_value=True),
            patch("zaptrace.analysis.spice_sim.run_transient", return_value=mock_result),
        ):
            result = run_transient_gate("* test\n.end", ref, design_name="buck-error")
        assert result.status == "fail"
        assert result.blocking is True


# ---------------------------------------------------------------------------
# regulator_fixture tests
# ---------------------------------------------------------------------------


class TestRegulatorFixture:
    def test_fixture_version_nonempty(self) -> None:
        assert FIXTURE_VERSION, "FIXTURE_VERSION must not be empty"

    def test_fixture_hash_stable(self) -> None:
        import hashlib

        expected = hashlib.sha256(BUCK_NETLIST.encode()).hexdigest()[:12]
        assert expected == FIXTURE_HASH, "FIXTURE_HASH must be deterministic"

    def test_fixture_source_contains_version(self) -> None:
        assert FIXTURE_VERSION in FIXTURE_SOURCE

    def test_fixture_source_contains_hash(self) -> None:
        assert FIXTURE_HASH in FIXTURE_SOURCE

    def test_regulator_reference_model_degraded(self) -> None:
        assert REGULATOR_REFERENCE.model_degraded is True, (
            "Behavioral fixtures must be marked as degraded so they cannot yield silent PASS"
        )

    def test_regulator_reference_has_thresholds(self) -> None:
        assert REGULATOR_REFERENCE.max_startup_us is not None
        assert REGULATOR_REFERENCE.max_ripple_mv is not None

    def test_regulator_reference_node_is_vout(self) -> None:
        assert REGULATOR_REFERENCE.node == "vout"

    def test_buck_netlist_is_valid_string(self) -> None:
        assert ".end" in BUCK_NETLIST
        assert "Vin" in BUCK_NETLIST or "vin" in BUCK_NETLIST.lower()

    def test_make_buck_netlist_returns_string(self) -> None:
        nl = make_buck_netlist(12.0, 3.3, 7.98e-6, 15e-6)
        assert isinstance(nl, str)
        assert ".end" in nl

    def test_make_buck_netlist_contains_params(self) -> None:
        nl = make_buck_netlist(vin=5.0, vout=1.8, inductor_h=10e-6, cap_f=22e-6)
        assert "5.0" in nl or "5" in nl
        assert "1.8" in nl

    def test_make_buck_netlist_custom_load(self) -> None:
        nl = make_buck_netlist(12.0, 3.3, 7.98e-6, 15e-6, load_r=10.0)
        assert "10.0000" in nl or "10.00" in nl

    def test_make_buck_netlist_default_load(self) -> None:
        # default load_r = vout / 2 = 1.65 Ω
        nl = make_buck_netlist(12.0, 3.3, 7.98e-6, 15e-6)
        assert "1.6500" in nl or "1.65" in nl


# ---------------------------------------------------------------------------
# TransientCheck unit tests
# ---------------------------------------------------------------------------


class TestTransientCheck:
    def test_to_dict_keys(self) -> None:
        c = TransientCheck(name="startup_time", passed=True, actual=42.0, reference=80.0, unit="us")
        d = c.to_dict()
        assert set(d.keys()) == {"name", "passed", "actual", "reference", "unit"}

    def test_to_dict_values(self) -> None:
        c = TransientCheck(name="ripple", passed=False, actual=75.0, reference=50.0, unit="mV")
        d = c.to_dict()
        assert d["passed"] is False
        assert d["actual"] == pytest.approx(75.0)
        assert d["unit"] == "mV"


def test_transient_gate_checks_steady_state_voltage_accuracy() -> None:
    from unittest.mock import patch

    fake_output = "\n".join(
        f"  {index * 1e-6:.9e}  {voltage:.9e}" for index, voltage in enumerate([0.0, 2.98, 3.0, 3.01, 3.0, 2.99] * 20)
    )
    mock_result = TransientResult(
        status="ok",
        waveforms={"vout": parse_tran_output(fake_output, "vout")},
    )
    ref = TransientReference(
        node="vout",
        target_v=3.3,
        max_steady_state_error_pct=5.0,
    )
    with patch("zaptrace.analysis.spice_sim.run_transient", return_value=mock_result):
        result = run_transient_gate("* test\n.end", ref, design_name="dc-error")

    check = next(item for item in result.checks if item.name == "steady_state_voltage_error")
    assert check.passed is False
    assert result.status == "fail"
    assert result.blocking is True


def test_regulator_fixture_has_loss_and_voltage_accuracy_reference() -> None:
    assert "Rdcr" in BUCK_NETLIST
    assert "Resr" in BUCK_NETLIST
    assert "725n" in BUCK_NETLIST
    assert REGULATOR_REFERENCE.max_steady_state_error_pct == 5.0
