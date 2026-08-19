"""Tests for the DRC (Design Rule Check) engine."""

from __future__ import annotations

from zaptrace.core.models import (
    BoardConfig,
    BoardDefinition,
    Component,
    Design,
    DesignMeta,
    Net,
    NetClass,
    NetConstraints,
    NetNode,
    RouteResult,
    TraceSegment,
)
from zaptrace.ee.drc import DRCEngine
from zaptrace.ee.drc.engine import (
    _hole_clearance_violation,
    _routing_drilled_holes,
    _solder_mask_sliver_violation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _design(nets: dict[str, Net] | None = None) -> Design:
    return Design(
        meta=DesignMeta(name="DRCTest"),
        nets=nets or {},
        board=BoardConfig(min_clearance_mm=0.2),
    )


def _simple_design() -> Design:
    return Design(
        meta=DesignMeta(name="Simple"),
        nets={
            "vcc": Net(
                id="vcc",
                name="VCC",
                nodes=[
                    NetNode(component_ref="R1", pin_name="p1"),
                    NetNode(component_ref="C1", pin_name="p1"),
                ],
            ),
            "gnd": Net(
                id="gnd",
                name="GND",
                nodes=[
                    NetNode(component_ref="R1", pin_name="p2"),
                    NetNode(component_ref="C1", pin_name="p2"),
                ],
            ),
        },
        components={
            "r1": Component(id="r1", ref="R1", type="resistor", value="10k", footprint="0805"),
            "c1": Component(id="c1", ref="C1", type="capacitor", value="100n", footprint="0603"),
        },
        board=BoardConfig(min_clearance_mm=0.2),
    )


# ---------------------------------------------------------------------------
# ERC-001: Unconnected nets
# ---------------------------------------------------------------------------


class TestUnconnectedNets:
    def test_fully_connected_ok(self) -> None:
        d = _simple_design()
        engine = DRCEngine()
        result = engine.run(d)
        erc001 = [v for v in result.violations if v.rule_id == "ERC-001"]
        assert len(erc001) == 0, f"Got violations: {erc001}"

    def test_zero_node_net(self) -> None:
        d = _design({"floating": Net(id="floating", name="FLOATING", nodes=[])})
        engine = DRCEngine()
        result = engine.run(d)
        erc001 = [v for v in result.violations if v.rule_id == "ERC-001"]
        assert any("no connected nodes" in v.message for v in erc001)

    def test_single_node_net(self) -> None:
        d = _design(
            {
                "single": Net(
                    id="single",
                    name="SINGLE",
                    nodes=[
                        NetNode(component_ref="R1", pin_name="p1"),
                    ],
                ),
            }
        )
        engine = DRCEngine()
        result = engine.run(d)
        erc001 = [v for v in result.violations if v.rule_id == "ERC-001"]
        assert any("only 1 node" in v.message for v in erc001)


# ---------------------------------------------------------------------------
# DRC-005: Unrouted nets
# ---------------------------------------------------------------------------


class TestUnroutedNets:
    def test_no_routing_all_unrouted(self) -> None:
        d = _simple_design()
        engine = DRCEngine()
        result = engine.run(d)
        drc005 = [v for v in result.violations if v.rule_id == "DRC-005"]
        # Both nets have 2 nodes, no routing → 2 violations
        assert len(drc005) == 2

    def test_with_routing_ok(self) -> None:
        d = _simple_design()
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.2, net_id="vcc"),
                TraceSegment(layer="top", start=(0, 5), end=(10, 5), width=0.2, net_id="gnd"),
            ],
            net_count=2,
            routed_net_count=2,
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc005 = [v for v in result.violations if v.rule_id == "DRC-005"]
        assert len(drc005) == 0

    def test_ground_pour_without_connectivity_proof_remains_unrouted(self) -> None:
        d = _simple_design()
        d.routing = RouteResult(
            traces=[TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.2, net_id="vcc")],
            net_count=2,
            routed_net_count=1,
        )
        from zaptrace.core.models import CopperPourArea

        d.copper_pours["F.Cu_GND"] = CopperPourArea(
            layer="F.Cu",
            net_id="gnd",
            polygon=[(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)],
        )

        result = DRCEngine().run(d)
        drc005 = [v for v in result.violations if v.rule_id == "DRC-005"]

        assert len(drc005) == 1
        assert drc005[0].net_id == "gnd"

    def test_partially_routed(self) -> None:
        d = _simple_design()
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.2, net_id="vcc"),
            ],
            net_count=2,
            routed_net_count=1,
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc005 = [v for v in result.violations if v.rule_id == "DRC-005"]
        # Only gnd should be unrouted
        assert len(drc005) == 1
        assert drc005[0].net_id == "gnd" or "gnd" in drc005[0].message


# ---------------------------------------------------------------------------
# DRC-002: Trace width
# ---------------------------------------------------------------------------


class TestTraceWidth:
    def test_width_below_minimum(self) -> None:
        d = _simple_design()
        d.net_classes = {"vcc": NetClass.POWER_MED}
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.1, net_id="vcc"),
            ],
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc002 = [v for v in result.violations if v.rule_id == "DRC-002"]
        assert len(drc002) == 1

    def test_width_ok(self) -> None:
        d = _simple_design()
        d.net_classes = {"vcc": NetClass.SIGNAL_LOW}
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.2, net_id="vcc"),
            ],
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc002 = [v for v in result.violations if v.rule_id == "DRC-002"]
        assert len(drc002) == 0


# ---------------------------------------------------------------------------
# DRC-003: Right-angle corners
# ---------------------------------------------------------------------------


class TestRightAngle:
    def test_no_segments(self) -> None:
        d = _simple_design()
        engine = DRCEngine()
        result = engine.run(d)
        drc003 = [v for v in result.violations if v.rule_id == "DRC-003"]
        assert len(drc003) == 0

    def test_90_degree_corner_detected(self) -> None:
        d = _simple_design()
        d.routing = RouteResult(
            traces=[
                # Two segments forming a 90° corner (horizontal + vertical)
                TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.2, net_id="vcc"),
                TraceSegment(layer="top", start=(10, 0), end=(10, 10), width=0.2, net_id="vcc"),
            ],
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc003 = [v for v in result.violations if v.rule_id == "DRC-003"]
        assert len(drc003) >= 1, "Should detect 90° corner"
        assert "90" in drc003[0].message or "Right" in drc003[0].message

    def test_45_degree_ok(self) -> None:
        d = _simple_design()
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.2, net_id="vcc"),
                TraceSegment(layer="top", start=(10, 0), end=(20, 10), width=0.2, net_id="vcc"),  # ~45°
            ],
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc003 = [v for v in result.violations if v.rule_id == "DRC-003"]
        # This is actually ~45°, not 90°
        assert len(drc003) == 0

    def test_branch_junction_not_counted_as_corner(self) -> None:
        d = _simple_design()
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.2, net_id="vcc"),
                TraceSegment(layer="top", start=(10, 0), end=(10, 10), width=0.2, net_id="vcc"),
                TraceSegment(layer="top", start=(10, 0), end=(20, 0), width=0.2, net_id="vcc"),
            ],
        )
        result = DRCEngine().run(d)
        drc003 = [v for v in result.violations if v.rule_id == "DRC-003"]
        assert len(drc003) == 0


# ---------------------------------------------------------------------------
# DRC-006: Via count
# ---------------------------------------------------------------------------


class TestViaCount:
    def test_via_exceeds_limit(self) -> None:
        d = _simple_design()
        d.net_classes = {"vcc": NetClass.SIGNAL_ANALOG}  # max_vias = 1
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(5, 0), width=0.2, net_id="vcc"),
                TraceSegment(layer="top", start=(5, 0), end=(10, 0), width=0.2, net_id="vcc", via=True),
                TraceSegment(layer="top", start=(10, 0), end=(15, 0), width=0.2, net_id="vcc", via=True),
            ],
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc006 = [v for v in result.violations if v.rule_id == "DRC-006"]
        assert len(drc006) >= 1

    def test_via_under_limit_ok(self) -> None:
        d = _simple_design()
        d.net_classes = {"vcc": NetClass.SIGNAL_ANALOG}  # max_vias = 1
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.2, net_id="vcc"),
            ],
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc006 = [v for v in result.violations if v.rule_id == "DRC-006"]
        assert len(drc006) == 0


# ---------------------------------------------------------------------------
# DRC-010: Missing net class
# ---------------------------------------------------------------------------


class TestMissingNetClass:
    def test_no_net_classes(self) -> None:
        d = _simple_design()
        d.net_classes = None
        engine = DRCEngine()
        result = engine.run(d)
        drc010 = [v for v in result.violations if v.rule_id == "DRC-010"]
        # classify_design should have populated them
        assert len(drc010) == 0

    def test_all_nets_classified(self) -> None:
        d = _simple_design()
        # Classify all nets
        d.net_classes = {"vcc": NetClass.POWER_MED, "gnd": NetClass.GROUND}
        engine = DRCEngine()
        result = engine.run(d)
        drc010 = [v for v in result.violations if v.rule_id == "DRC-010"]
        assert len(drc010) == 0


# ---------------------------------------------------------------------------
# DRC-011: Component outside board
# ---------------------------------------------------------------------------


class TestComponentOutsideBoard:
    def test_components_inside_board_ok(self) -> None:
        d = _simple_design()
        d.placement = {"r1": (10.0, 10.0), "c1": (20.0, 20.0)}
        engine = DRCEngine()
        result = engine.run(d)
        drc011 = [v for v in result.violations if v.rule_id == "DRC-011"]
        assert len(drc011) == 0

    def test_component_outside_board(self) -> None:
        d = _simple_design()
        d.placement = {"r1": (200.0, 200.0)}  # way outside 100x80
        engine = DRCEngine()
        result = engine.run(d)
        drc011 = [v for v in result.violations if v.rule_id == "DRC-011"]
        assert len(drc011) >= 1
        assert "outside" in drc011[0].message


# ---------------------------------------------------------------------------
# Selective rule enablement
# ---------------------------------------------------------------------------


class TestSelectiveRules:
    def test_enabled_rules_filter(self) -> None:
        d = _simple_design()
        engine = DRCEngine(enabled_rules={"ERC-001"})
        result = engine.run(d)
        # Only ERC-001 violations should appear
        for v in result.violations:
            assert v.rule_id == "ERC-001", f"Unexpected rule {v.rule_id}"

    def test_empty_enabled_no_checks(self) -> None:
        d = _simple_design()
        engine = DRCEngine(enabled_rules=set())
        result = engine.run(d)
        assert len(result.violations) == 0


# ---------------------------------------------------------------------------
# Overall result structure
# ---------------------------------------------------------------------------


class TestResultStructure:
    def test_result_passed_on_clean(self) -> None:
        d = Design(meta=DesignMeta(name="clean"))
        engine = DRCEngine()
        result = engine.run(d)
        assert result.passed is True
        assert result.total_violations == 0

    def test_result_failed_on_violations(self) -> None:
        d = _design()
        d.nets["vcc"] = Net(id="vcc", name="VCC", nodes=[])  # unconnected
        engine = DRCEngine()
        result = engine.run(d)
        assert result.passed is True  # ERC-001 is WARNING/INFO, not error
        assert result.total_violations > 0

    def test_result_stored_on_design(self) -> None:
        d = _simple_design()
        engine = DRCEngine()
        engine.run(d)
        assert d.drc_result is not None
        assert d.drc_result.design_name == "Simple"

    def test_kb_via_count_respected(self) -> None:
        """GROUND class has max_vias=99, should never trigger."""
        d = _simple_design()
        d.net_classes = {"gnd": NetClass.GROUND}
        d.routing = RouteResult(
            traces=[
                TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.5, net_id="gnd", via=True)
                for _ in range(10)
            ],  # noqa: E501
        )
        engine = DRCEngine()
        result = engine.run(d)
        drc006 = [v for v in result.violations if v.rule_id == "DRC-006"]
        assert len(drc006) == 0  # GROUND allows 99 vias

    def test_warns_about_single_node(self) -> None:
        """Only 1 node on a net should be INFO level."""
        d = _design()
        d.nets["stub"] = Net(id="stub", name="STUB", nodes=[NetNode(component_ref="R1", pin_name="p1")])
        engine = DRCEngine()
        result = engine.run(d)
        erc001 = [v for v in result.violations if v.rule_id == "ERC-001" and "only 1 node" in v.message]
        assert len(erc001) == 1
        assert erc001[0].severity.value == "info"


class TestFabProfileDRC:
    """DRCEngine(fab_profile=...) reports fab-profile-specific violations."""

    def _thin_trace_design(self) -> Design:
        d = _design()
        # A 0.05 mm trace is below every supported fab's minimum trace width.
        d.routing = RouteResult(
            traces=[TraceSegment(layer="F.Cu", start=(0.0, 0.0), end=(10.0, 0.0), width=0.05, net_id="n1")]
        )
        return d

    def test_profile_adds_fab_specific_violations(self) -> None:
        from zaptrace.fab.profile import load_profile

        design = self._thin_trace_design()
        generic = DRCEngine().run(design)
        with_profile = DRCEngine(fab_profile=load_profile("jlcpcb-2layer")).run(design)
        # Selecting a fab profile surfaces strictly more (profile-specific) findings.
        assert with_profile.total_violations > generic.total_violations

    def test_no_profile_runs_generic_only(self) -> None:
        # Without a profile the engine behaves exactly as before (no DFM folding).
        design = self._thin_trace_design()
        result = DRCEngine().run(design)
        assert result.total_violations >= 1  # generic net-class trace-width check still fires

    def test_profile_violations_counted_and_sorted(self) -> None:
        from zaptrace.fab.profile import load_profile

        result = DRCEngine(fab_profile=load_profile("jlcpcb-2layer")).run(self._thin_trace_design())
        # Counts stay consistent after folding DFM violations in.
        assert result.total_violations == len(result.violations)
        severities = [v.severity.value for v in result.violations]
        assert severities == sorted(severities, key=lambda s: {"error": 0, "warning": 1, "info": 2}.get(s, 9))


def test_clearance_location_includes_trace_endpoints() -> None:
    d = _simple_design()
    d.routing = RouteResult(
        traces=[
            TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.2, net_id="vcc"),
            TraceSegment(layer="top", start=(0, 0.1), end=(10, 0.1), width=0.2, net_id="gnd"),
        ],
    )
    result = DRCEngine().run(d)
    drc001 = [v for v in result.violations if v.rule_id == "DRC-001"]
    assert drc001
    assert drc001[0].location is not None
    assert "vcc" in drc001[0].location
    assert "gnd" in drc001[0].location
    assert "0.00,0.00" in drc001[0].location


def test_micro_right_angle_corner_is_ignored() -> None:
    d = _simple_design()
    d.routing = RouteResult(
        traces=[
            TraceSegment(layer="top", start=(0, 0), end=(0.1, 0), width=0.2, net_id="vcc"),
            TraceSegment(layer="top", start=(0.1, 0), end=(0.1, 1.0), width=0.2, net_id="vcc"),
        ],
    )
    result = DRCEngine().run(d)
    drc003 = [v for v in result.violations if v.rule_id == "DRC-003"]
    assert len(drc003) == 0


def test_solder_mask_sliver_helper_skips_same_net_and_layer_mismatch() -> None:
    first = TraceSegment(layer="F.Cu", start=(0, 0), end=(5, 0), width=0.2, net_id="a")
    same_net = TraceSegment(layer="F.Cu", start=(0, 0.25), end=(5, 0.25), width=0.2, net_id="a")
    other_layer = TraceSegment(layer="B.Cu", start=(0, 0.25), end=(5, 0.25), width=0.2, net_id="b")
    assert _solder_mask_sliver_violation(first, same_net, min_sliver=0.1, min_copper_clearance=0.05) is None
    assert _solder_mask_sliver_violation(first, other_layer, min_sliver=0.1, min_copper_clearance=0.05) is None


def test_solder_mask_sliver_helper_preserves_clearance_window() -> None:
    first = TraceSegment(layer="F.Cu", start=(0, 0), end=(5, 0), width=0.2, net_id="a")
    second = TraceSegment(layer="F.Cu", start=(0, 0.27), end=(5, 0.27), width=0.2, net_id="b")
    violation = _solder_mask_sliver_violation(first, second, min_sliver=0.1, min_copper_clearance=0.05)
    assert violation is not None
    assert violation.rule_id == "DRC-022"
    assert violation.location == "layer=F.Cu"


def test_solder_mask_sliver_suppressed_when_copper_clearance_fails() -> None:
    d = _simple_design()
    d.routing = RouteResult(
        traces=[
            TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.2, net_id="vcc"),
            TraceSegment(layer="top", start=(0, 0.25), end=(10, 0.25), width=0.2, net_id="gnd"),
        ],
    )
    result = DRCEngine().run(d)
    assert any(v.rule_id == "DRC-001" for v in result.violations)
    assert not any(v.rule_id == "DRC-022" for v in result.violations)


def test_solder_mask_sliver_reported_when_copper_clearance_passes() -> None:
    d = _simple_design()
    d.board = BoardConfig(min_clearance_mm=0.05)
    d.routing = RouteResult(
        traces=[
            TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.2, net_id="vcc"),
            TraceSegment(layer="top", start=(0, 0.275), end=(10, 0.275), width=0.2, net_id="gnd"),
        ],
    )
    result = DRCEngine().run(d)
    assert not any(v.rule_id == "DRC-001" for v in result.violations)
    assert any(v.rule_id == "DRC-022" for v in result.violations)


def test_collinear_same_direction_segments_not_acid_trap() -> None:
    d = _simple_design()
    d.routing = RouteResult(
        traces=[
            TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.2, net_id="vcc"),
            TraceSegment(layer="top", start=(0, 0), end=(5, 0), width=0.2, net_id="vcc"),
        ],
    )
    result = DRCEngine().run(d)
    drc023 = [v for v in result.violations if v.rule_id == "DRC-023"]
    assert len(drc023) == 0


def test_duplicate_shared_endpoint_clearance_reported_once() -> None:
    d = _simple_design()
    d.routing = RouteResult(
        traces=[
            TraceSegment(layer="top", start=(0, 0), end=(0, 1), width=0.2, net_id="vcc"),
            TraceSegment(layer="top", start=(0, 0), end=(1, 0), width=0.2, net_id="gnd"),
            TraceSegment(layer="top", start=(0, 0), end=(-1, 0), width=0.2, net_id="gnd"),
        ],
    )
    result = DRCEngine().run(d)
    drc001 = [v for v in result.violations if v.rule_id == "DRC-001"]
    assert len(drc001) == 1


def test_hole_clearance_helpers_preserve_via_and_segment_semantics() -> None:
    routing = RouteResult(
        vias=[(0.0, 0.0, 0.5, 0.3, "vcc"), (2.0, 0.0, 0.5, 0.3)],
        traces=[
            TraceSegment(
                layer="F.Cu",
                start=(0.4, 0.0),
                end=(1.0, 0.0),
                width=0.2,
                net_id="sig",
                via=True,
                via_hole=0.3,
            )
        ],
    )
    holes = _routing_drilled_holes(routing)
    assert holes == [(0.0, 0.0, 0.3, "vcc"), (2.0, 0.0, 0.3, ""), (0.4, 0.0, 0.3, "sig")]

    violation = _hole_clearance_violation(holes[0], holes[2])
    assert violation is not None
    assert violation.rule_id == "DRC-013"
    assert violation.net_id == "vcc"
    assert _hole_clearance_violation(holes[0], holes[1]) is None


def test_clearance_characterization_preserves_deduplicated_finding() -> None:
    design = _simple_design()
    design.routing = RouteResult(
        traces=[
            TraceSegment(layer="top", start=(0, 0), end=(0, 1), width=0.2, net_id="vcc"),
            TraceSegment(layer="top", start=(0, 0), end=(1, 0), width=0.2, net_id="gnd"),
            TraceSegment(layer="top", start=(0, 0), end=(-1, 0), width=0.2, net_id="gnd"),
        ]
    )

    result = DRCEngine(enabled_rules={"DRC-001"}).run(design)

    assert [(v.rule_id, v.severity.value, v.message, v.location, v.net_id) for v in result.violations] == [
        (
            "DRC-001",
            "error",
            "Clearance violation: net 'vcc' and 'gnd' are -0.200mm apart (min 0.2mm)",
            "top: vcc (0.00,0.00) -> (0.00,1.00) | gnd (0.00,0.00) -> (1.00,0.00)",
            "vcc",
        )
    ]


def test_right_angle_characterization_preserves_finding() -> None:
    design = _simple_design()
    design.routing = RouteResult(
        traces=[
            TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.2, net_id="vcc"),
            TraceSegment(layer="top", start=(10, 0), end=(10, 10), width=0.2, net_id="vcc"),
        ]
    )

    result = DRCEngine(enabled_rules={"DRC-003"}).run(design)

    assert [(v.rule_id, v.severity.value, v.message, v.location, v.net_id) for v in result.violations] == [
        ("DRC-003", "warning", "Right-angle corner (90.0°) on net 'vcc' layer top", "(10.0, 0.0)", "vcc")
    ]


def test_acid_trap_characterization_preserves_finding_and_branch_suppression() -> None:
    design = _simple_design()
    design.routing = RouteResult(
        traces=[
            TraceSegment(layer="top", start=(0, 0), end=(5, 0), width=0.2, net_id="vcc"),
            TraceSegment(layer="top", start=(5, 0), end=(2.5, 2.5), width=0.2, net_id="vcc"),
        ]
    )

    result = DRCEngine(enabled_rules={"DRC-023"}).run(design)

    assert [(v.rule_id, v.severity.value, v.message, v.location, v.net_id) for v in result.violations] == [
        ("DRC-023", "error", "Acid-trap (sharp angle 45.0°) on net 'vcc' layer top", "(5.0, 0.0)", "vcc")
    ]

    design.routing.traces.append(TraceSegment(layer="top", start=(5, 0), end=(10, 0), width=0.2, net_id="vcc"))
    assert DRCEngine(enabled_rules={"DRC-023"}).run(design).violations == []


def test_high_voltage_characterization_preserves_threshold_and_pair_filters() -> None:
    design = _simple_design()
    design.net_classes = {"vcc": NetClass.POWER_HIGH, "gnd": NetClass.GROUND}
    design.routing = RouteResult(
        traces=[
            TraceSegment(layer="top", start=(0, 0), end=(5, 0), width=0.2, net_id="vcc"),
            TraceSegment(layer="top", start=(0, 0.4), end=(5, 0.4), width=0.2, net_id="gnd"),
            TraceSegment(layer="bottom", start=(0, 0.1), end=(5, 0.1), width=0.2, net_id="gnd"),
        ]
    )

    result = DRCEngine(enabled_rules={"DRC-024"}).run(design)

    assert [(v.rule_id, v.severity.value, v.message, v.location, v.net_id) for v in result.violations] == [
        (
            "DRC-024",
            "error",
            "High-voltage clearance violation: nets 'vcc' and 'gnd' are 0.200mm apart (min 0.300mm)",
            "layer=top",
            "vcc",
        )
    ]

    design.net_classes = {"vcc": NetClass.GROUND, "gnd": NetClass.GROUND}
    assert DRCEngine(enabled_rules={"DRC-024"}).run(design).violations == []


def test_component_outside_board_characterization_preserves_board_definition_message() -> None:
    design = _simple_design()
    design.board_def = BoardDefinition(
        width=100.0,
        height=80.0,
        outline=[(0.0, 0.0), (100.0, 0.0), (100.0, 80.0), (0.0, 80.0)],
    )
    design.placement = {"r1": (103.0, 40.0), "c1": (101.5, 40.0)}

    result = DRCEngine(enabled_rules={"DRC-011"}).run(design)

    assert [(v.rule_id, v.severity.value, v.message, v.component_id) for v in result.violations] == [
        ("DRC-011", "error", "Component 'R1' placed at (103.0, 40.0) outside board outline", "r1")
    ]


class TestHighCurrentTraceWidth:
    def test_explicit_high_current_width_flags_narrow_trace(self) -> None:
        design = _design(
            {
                "vbus": Net(
                    id="vbus",
                    name="VBUS",
                    constraints=NetConstraints(is_high_current=True, min_trace_width_mm=0.8),
                )
            }
        )
        design.routing = RouteResult(
            traces=[TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.4, net_id="vbus")]
        )

        result = DRCEngine(enabled_rules={"DRC-012"}).run(design)

        violations = [violation for violation in result.violations if violation.rule_id == "DRC-012"]
        assert len(violations) == 1
        assert violations[0].net_id == "vbus"
        assert "0.400mm" in violations[0].message
        assert "0.800mm" in violations[0].message

    def test_high_current_width_accepts_compliant_trace(self) -> None:
        design = _design(
            {
                "vbus": Net(
                    id="vbus",
                    name="VBUS",
                    constraints=NetConstraints(is_high_current=True, min_trace_width_mm=0.8),
                )
            }
        )
        design.routing = RouteResult(
            traces=[TraceSegment(layer="top", start=(0, 0), end=(10, 0), width=0.8, net_id="vbus")]
        )

        result = DRCEngine(enabled_rules={"DRC-012"}).run(design)

        assert [violation for violation in result.violations if violation.rule_id == "DRC-012"] == []
