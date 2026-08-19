"""Tests for the DC operating-point simulation gate."""

from __future__ import annotations

import pytest

from zaptrace.analysis.sim_gate import (
    GateStatus,
    _gate_verdict,
    _rail_net_to_volts,
    expected_rail_voltages,
    run_simulation_gate,
)
from zaptrace.synthesis.architecture import build_architecture_design
from zaptrace.synthesis.requirements import parse_requirements


class TestVerdictMapping:
    def test_skip_is_recorded_not_passed(self) -> None:
        status, blocking, _ = _gate_verdict("skipped", True, False, strict=False)
        assert status is GateStatus.SKIPPED  # never PASS
        assert blocking is False

    def test_skip_blocks_in_strict_mode(self) -> None:
        status, blocking, _ = _gate_verdict("skipped", True, True, strict=True)
        assert status is GateStatus.SKIPPED
        assert blocking is True

    def test_error_always_fails_and_blocks(self) -> None:
        for strict in (False, True):
            status, blocking, _ = _gate_verdict("error", True, True, strict=strict)
            assert status is GateStatus.FAIL
            assert blocking is True

    def test_pass_only_when_checks_ran_and_passed(self) -> None:
        status, blocking, _ = _gate_verdict("ok", True, True, strict=False)
        assert status is GateStatus.PASS
        assert blocking is False

    def test_no_checks_is_no_reference_not_pass(self) -> None:
        status, blocking, _ = _gate_verdict("ok", True, False, strict=False)
        assert status is GateStatus.NO_REFERENCE
        assert blocking is False
        # ...and strict mode refuses to accept an unchecked run
        status_strict, blocking_strict, _ = _gate_verdict("ok", True, False, strict=True)
        assert status_strict is GateStatus.NO_REFERENCE
        assert blocking_strict is True

    def test_out_of_tolerance_fails(self) -> None:
        status, blocking, _ = _gate_verdict("ok", False, True, strict=False)
        assert status is GateStatus.FAIL
        assert blocking is True


class TestRailReferences:
    @pytest.mark.parametrize(
        ("net", "volts"),
        [("VDD_3V3", 3.3), ("VDD_5", 5.0), ("VDD_1V8", 1.8), ("VDD_12", 12.0), ("SDA", None)],
    )
    def test_rail_net_to_volts(self, net: str, volts: float | None) -> None:
        assert _rail_net_to_volts(net) == volts

    def test_expected_rail_voltages_from_synthesized_board(self) -> None:
        design, _, _ = build_architecture_design(parse_requirements("USB-C powered board, 3.3V rail, I2C sensor"))
        refs = expected_rail_voltages(design)
        assert refs.get("VDD_3V3") == 3.3
        assert all(v == 0.0 for k, v in refs.items() if k == "GND")


class TestGateOnSynthesizedBoard:
    def _design(self):
        d, _, _ = build_architecture_design(parse_requirements("USB-C powered board, 3.3V rail, I2C sensor"))
        return d

    def test_skip_is_non_blocking_by_default(self) -> None:
        # ngspice is not installed in the test environment: expect a recorded skip.
        result = run_simulation_gate(self._design(), strict=False)
        assert result.status is GateStatus.SKIPPED
        assert result.satisfied is True
        assert result.status is not GateStatus.PASS

    def test_skip_blocks_under_strict(self) -> None:
        result = run_simulation_gate(self._design(), strict=True)
        assert result.status is GateStatus.SKIPPED
        assert result.blocking is True
        assert result.satisfied is False

    def test_to_dict_shape(self) -> None:
        data = run_simulation_gate(self._design()).to_dict()
        assert set(data) == {
            "status",
            "blocking",
            "satisfied",
            "strict",
            "design_name",
            "reason",
            "checks",
            "node_voltages",
        }
