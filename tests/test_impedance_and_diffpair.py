"""Tests for impedance calculation, differential pair routing, and length matching."""

from __future__ import annotations

import math

from zaptrace.core.models import TraceSegment
from zaptrace.ee.routing import (
    STANDARD_STACKUPS,
    ImpedanceResult,
    SkewReport,
    analyze_diff_pair_skew,
    compute_microstrip_diff,
    compute_microstrip_se,
    generate_meander_segments,
    signal_propagation_delay_ps_per_mm,
)


class TestImpedanceCalculators:
    """Test IPC-2141 microstrip single-ended and differential impedance formulas."""

    def test_single_ended_50_ohm_4layer(self) -> None:
        stackup = STANDARD_STACKUPS["4-layer-jlc04161h"]
        h = stackup.outer_dielectric_h_mm
        t = stackup.outer_copper_t_mm
        er = stackup.dielectric_er

        result = compute_microstrip_se(target_z=50.0, h=h, t=t, er=er)
        assert isinstance(result, ImpedanceResult)
        assert not result.is_diff
        assert result.trace_width > 0.1
        assert abs(result.actual_z - 50.0) < 3.0  # Within 3 ohms

    def test_diff_pair_90_ohm_usb(self) -> None:
        stackup = STANDARD_STACKUPS["4-layer-jlc04161h"]
        result = compute_microstrip_diff(
            target_z=90.0,
            h=stackup.outer_dielectric_h_mm,
            t=stackup.outer_copper_t_mm,
            er=stackup.dielectric_er,
            min_gap=0.15,
        )
        assert result.is_diff
        assert result.trace_width > 0.05
        assert result.gap is not None
        assert result.gap >= 0.15
        assert abs(result.actual_z - 90.0) < 5.0

    def test_diff_pair_100_ohm_ethernet(self) -> None:
        stackup = STANDARD_STACKUPS["4-layer-jlc04161h"]
        result = compute_microstrip_diff(
            target_z=100.0,
            h=stackup.outer_dielectric_h_mm,
            t=stackup.outer_copper_t_mm,
            er=stackup.dielectric_er,
        )
        assert result.is_diff
        assert abs(result.actual_z - 100.0) < 5.0


class TestLengthMatchingAndSkew:
    """Test propagation delay, skew analysis, and meander snake generation."""

    def test_propagation_delay_fr4(self) -> None:
        delay = signal_propagation_delay_ps_per_mm(er=4.2)
        # FR-4 propagation delay is typically ~6.5 - 7.0 ps/mm
        assert 5.5 < delay < 8.0

    def test_diff_pair_skew_passing(self) -> None:
        # Equal length traces (10mm each) -> 0 skew
        traces_p = [TraceSegment(layer="F.Cu", start=(0.0, 0.0), end=(10.0, 0.0), width=0.2, net_id="USB_D_P")]
        traces_n = [TraceSegment(layer="F.Cu", start=(0.0, 0.5), end=(10.0, 0.5), width=0.2, net_id="USB_D_N")]

        report = analyze_diff_pair_skew(traces_p, traces_n, max_skew_ps=5.0)
        assert isinstance(report, SkewReport)
        assert report.passed
        assert report.delta_length_mm == 0.0
        assert report.skew_ps == 0.0

    def test_diff_pair_skew_failing(self) -> None:
        # P trace is 10mm, N trace is 15mm (5mm delta -> ~33 ps skew > 5ps)
        traces_p = [TraceSegment(layer="F.Cu", start=(0.0, 0.0), end=(10.0, 0.0), width=0.2, net_id="ETH_TX_P")]
        traces_n = [TraceSegment(layer="F.Cu", start=(0.0, 0.5), end=(15.0, 0.5), width=0.2, net_id="ETH_TX_N")]

        report = analyze_diff_pair_skew(traces_p, traces_n, max_skew_ps=5.0)
        assert not report.passed
        assert report.delta_length_mm == 5.0
        assert report.skew_ps > 20.0

    def test_meander_generation_increases_length(self) -> None:
        start = (0.0, 0.0)
        end = (10.0, 0.0)
        direct_dist = 10.0
        target_len = 16.0

        meanders = generate_meander_segments(
            start=start,
            end=end,
            target_length_mm=target_len,
            amplitude_mm=1.5,
            pitch_mm=1.0,
            net_id="MATCHED_NET",
        )
        assert len(meanders) > 1

        total_meander_len = sum(math.hypot(s.end[0] - s.start[0], s.end[1] - s.start[1]) for s in meanders)
        assert total_meander_len > direct_dist
        assert abs(total_meander_len - target_len) < 2.0
