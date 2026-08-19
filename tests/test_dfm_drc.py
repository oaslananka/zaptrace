from zaptrace.core.models import (
    BoardConfig,
    BoardConstraints,
    BoardDefinition,
    CopperPourArea,
    Design,
    DesignMeta,
    Net,
    NetClass,
    NetNode,
    RouteResult,
    TraceSegment,
)
from zaptrace.ee.drc.engine import DRCEngine


def _simple_design() -> Design:
    d = Design(meta=DesignMeta(name="Simple"))
    d.nets["vcc"] = Net(
        id="vcc",
        name="VCC",
        nodes=[NetNode(component_ref="r1", pin_name="1"), NetNode(component_ref="c1", pin_name="1")],
    )
    d.nets["gnd"] = Net(
        id="gnd",
        name="GND",
        nodes=[NetNode(component_ref="r1", pin_name="2"), NetNode(component_ref="c1", pin_name="2")],
    )
    d.board_def = BoardDefinition(
        width=100.0,
        height=80.0,
        outline=[(0.0, 0.0), (100.0, 0.0), (100.0, 80.0), (0.0, 80.0)],
        constraints=BoardConstraints(
            min_annular_ring=0.13,
            min_solder_mask_sliver=0.1,
            min_clearance_high_voltage=0.3,
        ),
        copper_pour_gnd=True,
    )
    return d


class TestAnnularRing:
    def test_annular_ring_pass(self) -> None:
        d = _simple_design()
        d.routing = RouteResult(
            traces=[
                TraceSegment(
                    layer="top",
                    start=(0, 0),
                    end=(5, 0),
                    width=0.2,
                    net_id="vcc",
                    via=True,
                    via_diameter=0.6,
                    via_hole=0.3,
                ),
            ]
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc020 = [v for v in result.violations if v.rule_id == "DRC-020"]
        assert len(drc020) == 0

    def test_annular_ring_fail(self) -> None:
        d = _simple_design()
        d.routing = RouteResult(
            traces=[
                # annular ring = (0.4 - 0.3)/2 = 0.05 < 0.13
                TraceSegment(
                    layer="top",
                    start=(0, 0),
                    end=(5, 0),
                    width=0.2,
                    net_id="vcc",
                    via=True,
                    via_diameter=0.4,
                    via_hole=0.3,
                ),
            ]
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc020 = [v for v in result.violations if v.rule_id == "DRC-020"]
        assert len(drc020) == 1


class TestBoardEdgeClearance:
    def test_board_edge_pass(self) -> None:
        d = _simple_design()
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(50, 40), end=(60, 40), width=0.2, net_id="vcc"),
            ]
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc021 = [v for v in result.violations if v.rule_id == "DRC-021"]
        assert len(drc021) == 0

    def test_board_edge_fail(self) -> None:
        d = _simple_design()
        d.routing = RouteResult(
            traces=[
                # near edge y=0
                TraceSegment(layer="top", start=(50, 0.1), end=(60, 0.1), width=0.2, net_id="vcc"),
            ]
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc021 = [v for v in result.violations if v.rule_id == "DRC-021"]
        assert len(drc021) == 1


class TestSolderMaskSliver:
    def test_solder_mask_sliver_pass(self) -> None:
        d = _simple_design()
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(5, 0), width=0.2, net_id="vcc"),
                TraceSegment(layer="top", start=(0, 1), end=(5, 1), width=0.2, net_id="gnd"),
            ]
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc022 = [v for v in result.violations if v.rule_id == "DRC-022"]
        assert len(drc022) == 0

    def test_solder_mask_sliver_fail(self) -> None:
        d = _simple_design()
        d.board = BoardConfig(min_clearance_mm=0.05)
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(5, 0), width=0.2, net_id="vcc"),
                # dist = 0.28. copper clearance = 0.08mm, so copper clearance passes
                # while the remaining solder-mask web is still below the 0.10mm sliver rule.
                TraceSegment(layer="top", start=(0, 0.28), end=(5, 0.28), width=0.2, net_id="gnd"),
            ]
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc022 = [v for v in result.violations if v.rule_id == "DRC-022"]
        assert len(drc022) >= 1


class TestAcidTrap:
    def test_acid_trap_pass(self) -> None:
        d = _simple_design()
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(5, 0), width=0.2, net_id="vcc"),
                TraceSegment(layer="top", start=(5, 0), end=(5, 5), width=0.2, net_id="vcc"),  # 90 degrees
            ]
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc023 = [v for v in result.violations if v.rule_id == "DRC-023"]
        assert len(drc023) == 0

    def test_acid_trap_fail(self) -> None:
        d = _simple_design()
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(5, 0), width=0.2, net_id="vcc"),
                # 45 degrees acute angle from (5,0) going back towards (0,5)
                TraceSegment(layer="top", start=(5, 0), end=(2.5, 2.5), width=0.2, net_id="vcc"),
            ]
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc023 = [v for v in result.violations if v.rule_id == "DRC-023"]
        assert len(drc023) >= 1


class TestHighVoltageClearance:
    def test_hv_clearance_pass(self) -> None:
        d = _simple_design()
        d.net_classes = {"vcc": NetClass.POWER_HIGH, "gnd": NetClass.GROUND}
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(5, 0), width=0.2, net_id="vcc"),
                TraceSegment(layer="top", start=(0, 1), end=(5, 1), width=0.2, net_id="gnd"),  # dist=1.0 > 0.3
            ]
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc024 = [v for v in result.violations if v.rule_id == "DRC-024"]
        assert len(drc024) == 0

    def test_hv_clearance_fail(self) -> None:
        d = _simple_design()
        d.net_classes = {"vcc": NetClass.POWER_HIGH, "gnd": NetClass.GROUND}
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(5, 0), width=0.2, net_id="vcc"),
                # dist=0.4. clearance = 0.4 - 0.1 - 0.1 = 0.2 < 0.3
                TraceSegment(layer="top", start=(0, 0.4), end=(5, 0.4), width=0.2, net_id="gnd"),
            ]
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc024 = [v for v in result.violations if v.rule_id == "DRC-024"]
        assert len(drc024) >= 1


class TestCopperBalance:
    def test_copper_balance_pass(self) -> None:
        d = _simple_design()
        d.copper_pours = {"gnd_pour": CopperPourArea(layer="top", net_id="gnd")}
        engine = DRCEngine()
        result = engine.run(d)
        drc025 = [v for v in result.violations if v.rule_id == "DRC-025"]
        assert len(drc025) == 0

    def test_copper_balance_fail(self) -> None:
        d = _simple_design()
        d.copper_pours = {}
        engine = DRCEngine()
        result = engine.run(d)
        drc025 = [v for v in result.violations if v.rule_id == "DRC-025"]
        assert len(drc025) == 1
