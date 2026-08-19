"""Tests for impedance computation and reporting."""

from __future__ import annotations

from zaptrace.core.models import Design, DesignMeta, Net, NetConstraints
from zaptrace.ee.knowledge import KnowledgeBase
from zaptrace.ee.routing.impedance import (
    ImpedanceResult,
    compute_microstrip_diff,
    compute_microstrip_se,
)


class TestImpedanceEngine:
    def test_compute_microstrip_se(self) -> None:
        """Test single-ended IPC-2141 microstrip calculation."""
        # 100 ohm target, h=1.53, t=0.035, er=4.5
        result = compute_microstrip_se(100.0, 1.53, 0.035, 4.5)
        assert isinstance(result, ImpedanceResult)
        assert not result.is_diff
        assert result.gap is None
        assert result.target_z == 100.0
        # Check actual_z matches target_z within 1% tolerance
        assert result.tolerance_pct < 1.0

    def test_compute_microstrip_diff(self) -> None:
        """Test differential IPC-2141 microstrip calculation."""
        # 90 ohm diff target, h=0.1, t=0.035, er=4.5
        result = compute_microstrip_diff(90.0, 0.1, 0.035, 4.5)
        assert isinstance(result, ImpedanceResult)
        assert result.is_diff
        assert result.gap is not None
        assert result.target_z == 90.0
        # Check actual_z matches target_z within 5% tolerance
        assert result.tolerance_pct < 5.0

    def test_resolve_net_geometry_se(self) -> None:
        kb = KnowledgeBase(preset_name="4layer_standard")
        net = Net(id="n1", name="ETH_TX", constraints=NetConstraints(impedance_target=100.0))
        geom = kb.resolve_net_geometry(net)
        assert isinstance(geom, ImpedanceResult)
        assert not geom.is_diff
        assert geom.target_z == 100.0

    def test_resolve_net_geometry_diff(self) -> None:
        kb = KnowledgeBase(preset_name="4layer_standard")
        net = Net(id="n2", name="USB_D_P", constraints=NetConstraints(impedance_target=90.0))
        geom = kb.resolve_net_geometry(net)
        assert isinstance(geom, ImpedanceResult)
        assert geom.is_diff
        assert geom.gap is not None
        assert geom.target_z == 90.0

    def test_resolve_net_geometry_fallback(self) -> None:
        kb = KnowledgeBase(preset_name="4layer_standard")
        net = Net(id="n3", name="GPIO1", constraints=None)
        geom = kb.resolve_net_geometry(net)
        assert isinstance(geom, dict)
        assert "trace_width" in geom

    def test_generate_impedance_report(self) -> None:
        kb = KnowledgeBase(preset_name="4layer_standard")
        design = Design(
            meta=DesignMeta(name="Test"),
            nets={
                "n1": Net(id="n1", name="USB_D_P", constraints=NetConstraints(impedance_target=90.0)),
                "n2": Net(id="n2", name="USB_D_N", constraints=NetConstraints(impedance_target=90.0)),
                "n3": Net(id="n3", name="ETH_TX", constraints=NetConstraints(impedance_target=100.0)),
                "n4": Net(id="n4", name="GPIO", constraints=None),
            },
        )
        report = kb.generate_impedance_report(design)
        assert "Impedance Report" in report
        assert "USB_D_P" in report
        assert "USB_D_N" in report
        assert "ETH_TX" in report
        assert "GPIO" not in report

        # Check diff/SE formatting
        assert "Diff" in report
        assert "SE" in report
