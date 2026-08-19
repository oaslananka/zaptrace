from __future__ import annotations

from zaptrace.algo.grid_router import GridRouter
from zaptrace.algo.router import route_design_smart
from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode, RouteResult, TraceSegment
from zaptrace.core.net_identity import (
    _normalize_trace_net_ids,
    _normalize_via_net_ids,
    canonical_net_id,
    canonical_routing_net_ids,
    voltage_from_net_name,
)
from zaptrace.ee.drc import DRCEngine
from zaptrace.proof.checker import ProofRunner
from zaptrace.proof.manifest import CheckDefinition


def _design() -> Design:
    design = Design(meta=DesignMeta(name="net-id-test"))
    design.components["u1"] = Component(id="u1", ref="U1", type="ic")
    design.components["r1"] = Component(id="r1", ref="R1", type="resistor")
    design.nets["net-001"] = Net(
        id="net-001",
        name="VCC_3V3",
        nodes=[
            NetNode(component_ref="U1", pin_name="VCC"),
            NetNode(component_ref="R1", pin_name="1"),
        ],
    )
    return design


def test_canonical_net_id_accepts_id_and_unique_legacy_name() -> None:
    design = _design()
    assert canonical_net_id(design, "net-001") == "net-001"
    assert canonical_net_id(design, "VCC_3V3") == "net-001"
    assert canonical_net_id(design, "missing") is None


def test_routing_outputs_machine_net_ids_not_human_names() -> None:
    design = _design()
    _, route, _sc = route_design_smart(design, {"u1": (10.0, 10.0), "r1": (30.0, 10.0)})
    assert route.traces
    assert {trace.net_id for trace in route.traces} == {"net-001"}
    assert "VCC_3V3" not in {trace.net_id for trace in route.traces}


def test_grid_router_outputs_machine_net_ids() -> None:
    design = _design()
    route = GridRouter(resolution_mm=1.0).route(design, {"u1": (10.0, 10.0), "r1": (30.0, 10.0)})
    assert route.traces
    assert {trace.net_id for trace in route.traces} == {"net-001"}


def test_legacy_name_routing_is_normalized_before_drc_and_proof() -> None:
    design = _design()
    design.routing = RouteResult(
        traces=[TraceSegment(layer="top", start=(0, 0), end=(5, 0), width=0.3, net_id="VCC_3V3")],
        net_count=1,
        routed_net_count=1,
    )

    report = canonical_routing_net_ids(design, design.routing)
    assert report.changed_trace_count == 1
    assert report.ok
    assert design.routing.traces[0].net_id == "net-001"

    drc = DRCEngine().run(design)
    assert not [violation for violation in drc.violations if violation.rule_id == "DRC-005"]

    checker = ProofRunner(design)
    result = checker.run_checks([CheckDefinition(name="all routed", type="routed")])[0]
    assert result.passed


def test_trace_normalizer_preserves_unknown_and_counts_aliases() -> None:
    design = _design()
    traces = [
        TraceSegment(layer="top", start=(0, 0), end=(1, 0), net_id="VCC_3V3"),
        TraceSegment(layer="top", start=(1, 0), end=(2, 0), net_id="missing"),
        TraceSegment(layer="top", start=(2, 0), end=(3, 0), net_id="net-001"),
    ]

    normalized, changed, unknown = _normalize_trace_net_ids(design, traces)

    assert [trace.net_id for trace in normalized] == ["net-001", "missing", "net-001"]
    assert changed == 1
    assert unknown == ["missing"]
    assert traces[0].net_id == "VCC_3V3"


def test_via_normalizer_preserves_short_vias_and_unknown_refs() -> None:
    design = _design()
    vias = [
        (1.0, 2.0, 0.6, 0.3),
        (2.0, 3.0, 0.6, 0.3, "VCC_3V3"),
        (3.0, 4.0, 0.6, 0.3, "missing"),
        (4.0, 5.0, 0.6, 0.3, "net-001"),
    ]

    normalized, changed, unknown = _normalize_via_net_ids(design, vias)

    assert normalized == [
        vias[0],
        (2.0, 3.0, 0.6, 0.3, "net-001"),
        vias[2],
        vias[3],
    ]
    assert changed == 1
    assert unknown == ["missing"]


def test_voltage_from_net_name_uses_bounded_engineering_formats() -> None:
    assert voltage_from_net_name("VCC 3.3V") == 3.3
    assert voltage_from_net_name("3V3") == 3.3
    assert voltage_from_net_name("12V") == 12.0
    assert voltage_from_net_name("9" * 100_000 + ".3V") is None
