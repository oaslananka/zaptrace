"""Tests for signal-integrity timing helpers."""

from __future__ import annotations

import pytest

from zaptrace.analysis.signal_integrity import (
    critical_length_mm,
    delay_for_length_ps,
    length_match_tolerance_mm,
    microstrip_eff_dielectric,
    propagation_delay_ps_per_mm,
)


def test_propagation_delay_vacuum_is_speed_of_light() -> None:
    # eeff = 1 -> ~3.336 ps/mm (speed of light)
    assert propagation_delay_ps_per_mm(1.0) == pytest.approx(3.3356, abs=0.001)


def test_propagation_delay_fr4_stripline() -> None:
    # eeff ~= 4.3 (FR-4 stripline) -> ~6.9 ps/mm
    assert propagation_delay_ps_per_mm(4.3) == pytest.approx(6.917, abs=0.01)


def test_microstrip_eff_dielectric() -> None:
    eeff = microstrip_eff_dielectric(4.3, 2.0)
    assert 1.0 < eeff < 4.3  # always between air and bulk
    assert eeff == pytest.approx(3.27, abs=0.05)


def test_critical_length() -> None:
    # 1 ns rise time on FR-4 -> ~24 mm before it's a transmission line (1/6 rule)
    length = critical_length_mm(1000.0, 4.3, divisor=6.0)
    assert length == pytest.approx(24.1, abs=0.5)


def test_critical_length_divisor_two_is_longer() -> None:
    assert critical_length_mm(1000.0, 4.3, divisor=2.0) > critical_length_mm(1000.0, 4.3, divisor=6.0)


def test_length_match_tolerance() -> None:
    # 10 ps skew on FR-4 (~6.9 ps/mm) -> ~1.45 mm tolerance
    assert length_match_tolerance_mm(10.0, 4.3) == pytest.approx(1.446, abs=0.01)


def test_delay_for_length_round_trips() -> None:
    eeff = 4.3
    delay = delay_for_length_ps(10.0, eeff)
    assert delay == pytest.approx(10.0 * propagation_delay_ps_per_mm(eeff))


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        propagation_delay_ps_per_mm(0.5)  # eeff < 1
    with pytest.raises(ValueError):
        critical_length_mm(0.0, 4.3)
    with pytest.raises(ValueError):
        microstrip_eff_dielectric(4.3, 0.0)


class TestCrosstalkHeuristic:
    def test_close_traces_high_risk(self) -> None:
        from zaptrace.analysis.signal_integrity import crosstalk_coupling_fraction, crosstalk_risk_label

        # Very close separation: s=0.05mm on 0.2mm substrate → k ≈ 0.052 > 0.05
        k = crosstalk_coupling_fraction(0.15, 0.15, trace_separation_mm=0.05, substrate_height_mm=0.2)
        assert k > 0.05
        assert crosstalk_risk_label(k) == "high"

    def test_well_separated_traces_low_risk(self) -> None:
        from zaptrace.analysis.signal_integrity import crosstalk_coupling_fraction, crosstalk_risk_label

        k = crosstalk_coupling_fraction(0.15, 0.15, trace_separation_mm=1.0, substrate_height_mm=0.2)
        assert k < 0.01
        assert crosstalk_risk_label(k) == "low"

    def test_zero_separation_valid(self) -> None:
        from zaptrace.analysis.signal_integrity import crosstalk_coupling_fraction

        k = crosstalk_coupling_fraction(0.15, 0.15, trace_separation_mm=0.0, substrate_height_mm=0.2)
        assert k == pytest.approx(0.25, rel=1e-3)  # maximum coupling


class TestReturnPathChecker:
    def test_high_current_net_without_hint_is_high_risk(self) -> None:
        from zaptrace.analysis.signal_integrity import check_return_path_hints
        from zaptrace.core.models import Net, NetConstraints, NetType

        net = Net(
            id="pwr",
            name="VCC",
            type=NetType.POWER,
            constraints=NetConstraints(is_high_current=True),
        )
        results = check_return_path_hints({"pwr": net})
        assert len(results) == 1
        assert results[0].risk == "high"
        assert not results[0].has_return_path_hint

    def test_net_with_return_path_is_low_risk(self) -> None:
        from zaptrace.analysis.signal_integrity import check_return_path_hints
        from zaptrace.core.models import Net, NetConstraints, NetType

        net = Net(
            id="pwr",
            name="VCC",
            type=NetType.POWER,
            constraints=NetConstraints(is_high_current=True, return_path_net="GND"),
        )
        results = check_return_path_hints({"pwr": net})
        assert results[0].risk == "low"
        assert results[0].return_path_net == "GND"

    def test_plain_signal_net_not_evaluated(self) -> None:
        from zaptrace.analysis.signal_integrity import check_return_path_hints
        from zaptrace.core.models import Net, NetType

        net = Net(id="sig", name="MOSI", type=NetType.SIGNAL)
        results = check_return_path_hints({"sig": net})
        assert results == []


class TestImpedanceReturnPathReport:
    def test_report_makes_impedance_assumptions_explicit(self) -> None:
        from zaptrace.analysis.signal_integrity import build_impedance_return_path_report
        from zaptrace.core.models import Design, DesignMeta, Net, NetConstraints, NetType

        design = Design(
            meta=DesignMeta(name="si-risk"),
            nets={
                "usb_dp": Net(
                    id="usb_dp",
                    name="USB_DP",
                    type=NetType.DIFFERENTIAL,
                    constraints=NetConstraints(impedance_target=90.0, return_path_net="GND"),
                )
            },
        )

        report = build_impedance_return_path_report(design)

        assert report.assumption_count == 1
        assert report.assumptions[0].target_ohms == 90.0
        assert report.assumptions[0].assumed_er == 4.2
        assert report.diagnostics[0].risk == "low"
        assert report.human_review_required is False
        assert report.blocked is False

    def test_missing_return_path_requires_human_review(self) -> None:
        from zaptrace.analysis.signal_integrity import SiRiskStatus, build_impedance_return_path_report
        from zaptrace.core.models import Design, DesignMeta, Net, NetConstraints, NetType

        design = Design(
            meta=DesignMeta(name="si-risk"),
            nets={
                "hs": Net(
                    id="hs",
                    name="HS_DATA",
                    type=NetType.SIGNAL,
                    constraints=NetConstraints(impedance_target=50.0),
                )
            },
        )

        report = build_impedance_return_path_report(design)

        assert report.blocked is False
        assert report.human_review_required is True
        assert report.diagnostics[0].status == SiRiskStatus.HUMAN_REVIEW_REQUIRED
        assert "No return-path net assigned" in report.diagnostics[0].message
        assert report.limitations
