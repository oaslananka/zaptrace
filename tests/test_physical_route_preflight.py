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


def test_two_separate_stubs_touch_all_pads_but_are_not_one_net() -> None:
    design, positions = _contact_design()
    routed = RouteResult(
        traces=[
            TraceSegment(layer="F.Cu", start=(10, 10), end=(12, 10), net_id="n"),
            TraceSegment(layer="F.Cu", start=(18, 10), end=(20, 10), net_id="n"),
        ],
        net_count=1,
        routed_net_count=1,
    )
    from zaptrace.pipeline.physical_route_preflight import _physical_pad_terminal_coverage

    assert _physical_pad_terminal_coverage(design, routed, positions)
    assert not verified_route_candidate_safe(design, routed, positions)


def test_touching_segments_connect_real_pads_without_approving_fabrication() -> None:
    design, positions = _contact_design()
    routed = RouteResult(
        traces=[
            TraceSegment(layer="F.Cu", start=(10, 10), end=(15, 10), net_id="n"),
            TraceSegment(layer="F.Cu", start=(15, 10), end=(20, 10), net_id="n"),
        ],
        net_count=1,
        routed_net_count=1,
    )
    assert verified_route_candidate_safe(design, routed, positions)


def test_pad_connected_net_with_extra_isolated_copper_is_not_complete() -> None:
    design, positions = _contact_design()
    routed = RouteResult(
        traces=[
            TraceSegment(layer="F.Cu", start=(10, 10), end=(20, 10), net_id="n"),
            TraceSegment(layer="F.Cu", start=(25, 15), end=(26, 15), net_id="n"),
        ],
        net_count=1,
        routed_net_count=1,
    )
    assert not verified_route_candidate_safe(design, routed, positions)


def test_two_layers_at_same_xy_are_not_joined_without_a_real_via() -> None:
    from zaptrace.core.models import LayerSet

    design, positions = _contact_design()
    left = design.components["R1"].footprint_def
    right = design.components["R2"].footprint_def
    assert left is not None and right is not None
    right.pads[0].layer = LayerSet.BOTTOM
    routed = RouteResult(
        traces=[
            TraceSegment(layer="F.Cu", start=(10, 10), end=(15, 10), net_id="n"),
            TraceSegment(layer="B.Cu", start=(15, 10), end=(20, 10), net_id="n"),
        ],
        net_count=1,
        routed_net_count=1,
    )
    assert not verified_route_candidate_safe(design, routed, positions)
    routed.vias = [(15, 10, 0.7, 0.3, "n")]
    assert verified_route_candidate_safe(design, routed, positions)


def test_via_on_different_net_or_without_ownership_does_not_bridge_layers() -> None:
    from zaptrace.core.models import LayerSet

    design, positions = _contact_design()
    right = design.components["R2"].footprint_def
    assert right is not None
    right.pads[0].layer = LayerSet.BOTTOM
    routed = RouteResult(
        traces=[
            TraceSegment(layer="F.Cu", start=(10, 10), end=(15, 10), net_id="n"),
            TraceSegment(layer="B.Cu", start=(15, 10), end=(20, 10), net_id="n"),
        ],
        net_count=1,
        routed_net_count=1,
        vias=[(15, 10, 0.7, 0.3, "foreign")],
    )
    assert not verified_route_candidate_safe(design, routed, positions)
    routed.vias = [(15, 10, 0.7, 0.3)]
    assert not verified_route_candidate_safe(design, routed, positions)
    routed.vias = [(15, 10, 0.3, 0.3, "n")]
    assert not verified_route_candidate_safe(design, routed, positions)


def test_rotated_footprint_pad_requires_real_board_space_contact() -> None:
    design, positions = _contact_design()
    footprint = design.components["R1"].footprint_def
    assert footprint is not None
    pad = footprint.pads[0]
    pad.position = (1.0, 0.0)
    pad.size = (0.6, 0.6)
    design.components["R1"].properties["rotation"] = 90.0

    routed = RouteResult(
        traces=[TraceSegment(layer="F.Cu", start=(10.0, 9.0), end=(20.0, 10.0), net_id="n")],
        net_count=1,
        routed_net_count=1,
    )
    assert verified_route_candidate_safe(design, routed, positions)

    # The unrotated pad location is not copper after the footprint rotates.
    routed.traces[0].start = (11.0, 10.0)
    assert not verified_route_candidate_safe(design, routed, positions)


def test_rounded_pad_bounding_box_corner_does_not_count_as_contact() -> None:
    from zaptrace.core.models import PadShape

    design, positions = _contact_design()
    footprint = design.components["R1"].footprint_def
    assert footprint is not None
    footprint.pads[0].shape = PadShape.CIRCLE
    routed = RouteResult(
        traces=[TraceSegment(layer="F.Cu", start=(10.49, 10.49), end=(20.0, 10.0), net_id="n")],
        net_count=1,
        routed_net_count=1,
    )
    # (0.49, 0.49) is within the one-millimetre pad's bounding square,
    # but outside the actual 0.5 mm-radius round pad.
    assert not verified_route_candidate_safe(design, routed, positions)
    routed.traces[0].start = (10.3, 10.3)
    assert verified_route_candidate_safe(design, routed, positions)


def test_rotated_oval_pad_contact_checks_copper_in_local_axes() -> None:
    from zaptrace.core.models import PadShape

    design, positions = _contact_design()
    footprint = design.components["R1"].footprint_def
    assert footprint is not None
    pad = footprint.pads[0]
    pad.shape = PadShape.OVAL
    pad.size = (2.0, 0.4)
    pad.rotation = 90.0
    routed = RouteResult(
        traces=[TraceSegment(layer="F.Cu", start=(10.0, 10.75), end=(20.0, 10.0), net_id="n")],
        net_count=1,
        routed_net_count=1,
    )
    assert verified_route_candidate_safe(design, routed, positions)
    routed.traces[0].start = (10.75, 10.0)
    assert not verified_route_candidate_safe(design, routed, positions)


def test_roundrect_corner_without_copper_is_not_a_pad_contact() -> None:
    from zaptrace.core.models import PadShape

    design, positions = _contact_design()
    footprint = design.components["R1"].footprint_def
    assert footprint is not None
    pad = footprint.pads[0]
    pad.shape = PadShape.ROUNDRECT
    pad.roundrect_rratio = 0.5
    routed = RouteResult(
        traces=[TraceSegment(layer="F.Cu", start=(10.49, 10.49), end=(20.0, 10.0), net_id="n")],
        net_count=1,
        routed_net_count=1,
    )
    assert not verified_route_candidate_safe(design, routed, positions)
    routed.traces[0].start = (10.0, 10.3)
    assert verified_route_candidate_safe(design, routed, positions)


def test_actual_usb_c_demo_graph_routing_is_rejected_before_export() -> None:
    design = parse_file(Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml")
    assert design.placement is not None
    candidate = GridRouter().route(design, design.placement)
    assert candidate.routed_net_count > 0
    assert candidate.traces
    assert not verified_route_candidate_safe(design, candidate, design.placement)
