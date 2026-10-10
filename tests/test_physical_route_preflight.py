"""Verified land patterns require physical pad contact and clean source DRC."""

from __future__ import annotations

from pathlib import Path

from zaptrace.algo.grid_router import GridRouter
from zaptrace.core.models import (
    BoardConfig,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    Net,
    NetNode,
    Pad,
    Pin,
    PinType,
    RouteResult,
    TraceSegment,
)
from zaptrace.core.parser import parse_file
from zaptrace.pipeline.physical_route_preflight import verified_route_candidate_safe


def _contact_design() -> tuple[Design, dict[str, tuple[float, float]]]:
    def component(ref: str, x: float) -> Component:
        return Component(
            id=ref,
            ref=ref,
            type="resistor",
            footprint_asset="r-0402",
            footprint_def=FootprintDef(pads=[Pad(id="1", size=(1.0, 1.0))]),
            pins={"P1": Pin(name="P1", type=PinType.PASSIVE, net="n")},
            package_pin_map={"1": "P1"},
            position=(x, 10.0),
        )

    positions = {"R1": (10.0, 10.0), "R2": (20.0, 10.0)}
    design = Design(
        meta=DesignMeta(name="Physical Contact Gate"),
        board=BoardConfig(width_mm=40.0, height_mm=20.0),
        components={"R1": component("R1", 10.0), "R2": component("R2", 20.0)},
        nets={
            "n": Net(
                id="n",
                name="SIGNAL",
                nodes=[
                    NetNode(component_ref="R1", pin_name="P1"),
                    NetNode(component_ref="R2", pin_name="P1"),
                ],
            )
        },
    )
    return design, positions


def test_valid_source_trace_contacts_both_real_pads() -> None:
    design, positions = _contact_design()
    routed = RouteResult(
        traces=[TraceSegment(layer="F.Cu", start=(10.0, 10.0), end=(20.0, 10.0), net_id="n")],
        net_count=1,
        routed_net_count=1,
    )
    assert verified_route_candidate_safe(design, routed, positions)


def test_route_graph_success_does_not_count_if_one_real_pad_is_unconnected() -> None:
    design, positions = _contact_design()
    routed = RouteResult(
        traces=[TraceSegment(layer="F.Cu", start=(12.0, 10.0), end=(20.0, 10.0), net_id="n")],
        net_count=1,
        routed_net_count=1,
    )
    assert not verified_route_candidate_safe(design, routed, positions)


def test_route_graph_success_does_not_count_if_wrong_layer() -> None:
    design, positions = _contact_design()
    routed = RouteResult(
        traces=[TraceSegment(layer="B.Cu", start=(10.0, 10.0), end=(20.0, 10.0), net_id="n")],
        net_count=1,
        routed_net_count=1,
    )
    assert not verified_route_candidate_safe(design, routed, positions)


def test_actual_usb_c_demo_graph_routing_is_rejected_before_export() -> None:
    design = parse_file(Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml")
    assert design.placement is not None
    candidate = GridRouter().route(design, design.placement)
    assert candidate.routed_net_count > 0
    assert candidate.traces
    assert not verified_route_candidate_safe(design, candidate, design.placement)
