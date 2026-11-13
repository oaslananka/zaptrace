"""Fail-closed pad-owned layer and via-clearance projection, Issue #35."""

from __future__ import annotations

import math

import pytest

from zaptrace.algo.grid_router import GridPos, GridRouter, ObstacleMap
from zaptrace.algo.pad_copper import copper_layers, pad_cells, rotated_offset
from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import (
    BoardConfig,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    LayerSet,
    Net,
    NetNode,
    Pad,
    PadShape,
)
from zaptrace.ee.knowledge import KnowledgeBase


def _board(
    *pads: tuple[str, tuple[float, float], Pad],
    layers: int = 2,
) -> tuple[Design, dict[str, tuple[float, float]]]:
    design = Design(
        meta=DesignMeta(name="pad-masks"),
        board=BoardConfig(
            width_mm=40,
            height_mm=30,
            layers=layers,
        ),
    )
    locations = {}
    for ref, xy, pad in pads:
        design.components[ref] = Component(
            id=ref,
            ref=ref.upper(),
            type="connector",
            footprint_def=FootprintDef(pads=[pad], courtyard=(1.8, 1.8)),
        )
        locations[ref] = xy
    return design, locations


def _net(design: Design, name: str, *refs: str) -> None:
    design.nets[name] = Net(
        id=name,
        name=name,
        nodes=[NetNode(component_ref=ref.upper(), pin_name="1") for ref in refs],
    )


def test_smd_top_only_does_not_reserve_bottom_layer() -> None:
    design, positions = _board(
        (
            "x",
            (12, 12),
            Pad(
                id="1",
                layer=LayerSet.TOP,
                shape=PadShape.RECT,
                size=(2, 1),
            ),
        )
    )
    ctx = GridRouter(resolution_mm=0.5, pad_aware=True)._prepare_route_context(design, positions)
    top, bottom = GridPos(24, 24, 0), GridPos(24, 24, 1)
    assert not ctx.obstacles.is_free(top, net_id="foreign")
    assert ctx.obstacles.is_free(bottom, net_id="foreign")
    assert ctx.obstacles.owner(top) is None
    assert not ctx.obstacles.can_place_through_via(bottom, "foreign", 1)


def test_preexpanded_track_reservation_does_not_dilate_static_pad_masks_again() -> None:
    obs = ObstacleMap(30, 30, 1)
    obs.enforce_static_clearance = True
    obs.preexpanded_static_clearance = True
    obs.mark_pad(GridPos(10, 10), "B")
    # The static clearance raster has already reserved the one-cell halo.
    obs.mark_pad_clearance(GridPos(9, 10), "B")
    assert obs.is_free(GridPos(8, 10), "A")
    obs.block_line(GridPos(8, 10), GridPos(8, 10), radius=2, net_id="A")
    assert obs.owner(GridPos(8, 10)) == "A"
    # The clearance envelope is not materialized a second time.
    assert obs.owner(GridPos(9, 10)) is None
    # But subsequent routes still see the real dynamic track clearance.
    assert not obs.is_corridor_free(GridPos(9, 10), "B", 1)


def test_preexpanded_track_reservation_still_blocks_foreign_dynamic_copper() -> None:
    obs = ObstacleMap(30, 30, 1)
    obs.enforce_static_clearance = True
    obs.preexpanded_static_clearance = True
    obs.block_line(GridPos(10, 10), GridPos(10, 10), radius=0, net_id="B")
    with pytest.raises(ValueError, match="Copper clearance"):
        obs.block_line(GridPos(11, 10), GridPos(11, 10), radius=1, net_id="A")
    with pytest.raises(ValueError, match="Copper clearance"):
        obs.block_line(GridPos(10, 10), GridPos(10, 10), radius=0, net_id="A")


def test_preexpanded_pad_clearance_is_not_dilated_twice() -> None:
    obs = ObstacleMap(30, 30, 1)
    obs.mark_pad(GridPos(10, 10), "A")
    obs.mark_pad_clearance(GridPos(12, 10), "B")
    obs.enforce_static_clearance = True
    obs.preexpanded_static_clearance = True
    assert obs.is_corridor_free(GridPos(10, 10), "A", 1)
    assert not obs.is_corridor_free(GridPos(12, 10), "A", 1)
    assert not obs.is_corridor_free(GridPos(12, 10), "UNRELATED", 1)
    obs.block_line(GridPos(11, 10), GridPos(11, 11), net_id="B")
    assert not obs.is_corridor_free(GridPos(10, 10), "A", 1)
    clone = obs.clone()
    assert clone.preexpanded_static_clearance
    assert not clone.is_corridor_free(GridPos(10, 10), "A", 1)


def test_preexpanded_clearance_preserves_physical_obstacle_and_board_edge_margin() -> None:
    obs = ObstacleMap(30, 30, 1)
    obs.preexpanded_static_clearance = True
    obs.enforce_static_clearance = True
    obs.block(GridPos(11, 10))
    assert not obs.is_corridor_free(GridPos(10, 10), "A", 1)
    assert not obs.is_corridor_free(GridPos(0, 10), "A", 1)
    plain = ObstacleMap(30, 30, 1)
    plain.mark_pad_clearance(GridPos(11, 10), "B")
    assert not plain.is_corridor_free(GridPos(10, 10), "A", 1)


def test_wider_custom_net_class_keeps_wider_preexpanded_pad_halo() -> None:
    from zaptrace.ee.constraints.net_classes import NetClass, NetClassRule
    from zaptrace.ee.knowledge import KnowledgeBase

    d, positions = _board(
        ("a", (10, 10), Pad(id="1", size=(1, 1))),
        ("b", (25, 10), Pad(id="1", size=(1, 1))),
    )
    _net(d, "SIG", "a", "b")
    router = GridRouter(resolution_mm=0.5, pad_aware=True)
    standard = router._prepare_route_context(d, positions)
    kb = KnowledgeBase()
    kb.set_rule(
        NetClass.SIGNAL_LOW,
        NetClassRule(trace_width=1.2, clearance=0.55, max_vias=2, priority=5, description="wide custom rule"),
    )
    wide = router._prepare_route_context(d, positions, kb)
    assert standard.obstacles.preexpanded_static_clearance
    assert wide.obstacles.preexpanded_static_clearance
    assert len(wide.obstacles._pad_clearance) > len(standard.obstacles._pad_clearance)
    assert not wide.obstacles.is_free(GridPos(23, 20), "OTHER")


def test_actual_esp32_static_pad_halo_is_single_expanded_but_not_approved() -> None:
    from pathlib import Path

    from zaptrace.core.parser import parse_file
    from zaptrace.pipeline.physical_route_preflight import verified_route_candidate_safe

    source = Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml"
    d = parse_file(source)
    assert d.placement is not None
    router = GridRouter(resolution_mm=0.25, max_iterations=25_000, pad_aware=True)
    route = router.route(d, d.placement)
    assert route.routed_net_count >= 1
    assert route.routed_net_count < route.net_count
    assert all(len(via) == 5 and via[2] > via[3] > 0 for via in route.vias)
    # Partial graph routing is not complete pad/net continuity and cannot
    # be promoted to a physical source export.
    assert not verified_route_candidate_safe(d, route, d.placement)


def test_ground_without_pour_routes_two_real_ground_lands() -> None:
    """A real small GND net can use explicit pad-aware top copper, not a phantom pour."""
    from zaptrace.pipeline.physical_route_preflight import retain_verified_partial_copper

    d, pos = _board(
        ("a", (10, 10), Pad(id="1", size=(2.0, 1.5), layer=LayerSet.TOP)),
        ("b", (25, 10), Pad(id="1", size=(2.0, 1.5), layer=LayerSet.TOP)),
    )
    _net(d, "GND", "a", "b")
    d.board.copper_pour_gnd = False
    assert not canonical_board_definition(d).copper_pour_gnd
    router = GridRouter(resolution_mm=0.25, pad_aware=True, max_iterations=20_000)
    route = router.route(d, pos)
    assert route.net_count == 1
    assert route.routed_net_count == 1
    assert route.traces
    assert all(seg.net_id == "GND" and seg.layer == "layer_0" for seg in route.traces)
    safe = retain_verified_partial_copper(d, route, pos)
    assert safe.routed_net_count == 1
    assert safe.traces


def _multipad_ground_fixture(*, repeated_id: bool = False) -> tuple[Design, dict[str, tuple[float, float]]]:
    """One logical connector GND terminal with three distinct physical lands."""
    d, pos = _board(
        ("a", (10, 10), Pad(id="1", size=(2.0, 1.5), layer=LayerSet.TOP)),
        ("b", (25, 10), Pad(id="1", size=(2.0, 1.5), layer=LayerSet.TOP)),
    )
    fp = d.components["b"].footprint_def
    assert fp is not None
    fp.pads.extend(
        [
            Pad(id="1" if repeated_id else "2", position=(0, 3), size=(2.0, 1.5), layer=LayerSet.TOP),
            Pad(id="1" if repeated_id else "3", position=(0, -3), size=(2.0, 1.5), layer=LayerSet.TOP),
        ]
    )
    d.components["b"].package_pin_map = {"1": "GND", "2": "GND", "3": "GND"}
    _net(d, "GND", "a", "b")
    d.nets["GND"].nodes[1].pin_name = "GND"
    d.board.copper_pour_gnd = False
    return d, pos


@pytest.mark.parametrize("repeated_id", [False, True])
def test_ground_without_pour_connects_every_real_land_on_same_terminal(repeated_id: bool) -> None:
    """No logical terminal may hide extra disconnected physical ground contacts."""
    from zaptrace.pipeline.physical_route_preflight import retain_verified_partial_copper

    design, positions = _multipad_ground_fixture(repeated_id=repeated_id)
    router = GridRouter(resolution_mm=0.25, pad_aware=True, max_iterations=25_000)
    candidate = router.route(design, positions)
    assert candidate.net_count == 1
    assert candidate.routed_net_count == 1
    assert candidate.traces
    assert all(trace.net_id == "GND" and trace.width == 0.5 for trace in candidate.traces)
    accepted = retain_verified_partial_copper(design, candidate, positions)
    assert accepted.routed_net_count == 1
    assert accepted.traces


@pytest.mark.parametrize("repeated_id", [False, True])
def test_ground_without_pour_multipad_kicad_real_unconnected(tmp_path, repeated_id: bool) -> None:
    """Independent KiCad 10 must confirm ALL ground contacts, not only the first one."""
    import json
    import shutil
    import subprocess
    from collections import Counter

    from zaptrace.core.models import RouteResult
    from zaptrace.export.kicad import export_kicad

    if not shutil.which("kicad-cli"):
        pytest.skip("KiCad native CLI unavailable")
    version = subprocess.run(["kicad-cli", "version"], capture_output=True, text=True, timeout=10, check=True)
    if not version.stdout.strip().startswith("10."):
        pytest.skip("Independent KiCad 10 required")
    design, positions = _multipad_ground_fixture(repeated_id=repeated_id)
    routed = GridRouter(resolution_mm=0.25, pad_aware=True, max_iterations=25_000).route(design, positions)
    assert routed.routed_net_count == 1
    native = []
    for label, traces in (("before", RouteResult(net_count=1)), ("routed", routed)):
        candidate = design.model_copy(deep=True)
        candidate.placement = dict(positions)
        candidate.routing = traces
        pcb = export_kicad(candidate, tmp_path / label)["pcb"]
        report = tmp_path / f"{label}.json"
        result = subprocess.run(
            [
                "kicad-cli",
                "pcb",
                "drc",
                "--exit-code-violations",
                "--severity-all",
                "--format",
                "json",
                "--output",
                str(report),
                str(pcb),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        assert result.returncode in (0, 5), result.stderr
        native.append(json.loads(report.read_text(encoding="utf-8")))
    before, after = native
    assert len(before["unconnected_items"]) > 0
    assert len(after["unconnected_items"]) == 0
    assert Counter(v["type"] for v in before["violations"]) == Counter(v["type"] for v in after["violations"])


def test_ground_without_pour_multipad_over_limit_and_narrow_land_fail_closed() -> None:
    """Resource bounds and physical current geometry are not bypassed."""
    d, pos = _multipad_ground_fixture()
    fp = d.components["b"].footprint_def
    assert fp is not None
    router = GridRouter(resolution_mm=0.25, pad_aware=True, max_iterations=25_000)
    fp.pads[1].size = (0.45, 0.35)
    rejected = router.route(d, pos)
    assert rejected.net_count == 1 and rejected.routed_net_count == 0 and not rejected.traces
    fp.pads[1].size = (2.0, 1.5)
    # Ten distinct contacts behind one logical pin are not a small-net case.
    for index in range(4, 11):
        fp.pads.append(
            Pad(
                id=str(index),
                position=(float((index - 4) % 4) * 2.5 - 4.0, float((index - 4) // 4) * 3.0 + 4.0),
                size=(2.0, 1.5),
                layer=LayerSet.TOP,
            )
        )
        d.components["b"].package_pin_map[str(index)] = "GND"
    over_limit = router.route(d, pos)
    assert over_limit.net_count == 1 and over_limit.routed_net_count == 0 and not over_limit.traces


def _multi_vbus_footprint_fixture() -> tuple[Design, dict[str, tuple[float, float]]]:
    """A source-like USB-C four-contact VBUS has two paired physical locations."""
    d, pos = _board(
        ("a", (10, 10), Pad(id="1", size=(1.5, 1.5), layer=LayerSet.TOP)),
        ("b", (25, 10), Pad(id="A4", position=(-2, 0), size=(0.6, 1.15), layer=LayerSet.TOP)),
    )
    footprint = d.components["b"].footprint_def
    assert footprint is not None
    footprint.pads.extend(
        [
            Pad(id="A9", position=(2, 0), size=(0.6, 1.15), layer=LayerSet.TOP),
            Pad(id="B4", position=(2, 0), size=(0.6, 1.15), layer=LayerSet.TOP),
            Pad(id="B9", position=(-2, 0), size=(0.6, 1.15), layer=LayerSet.TOP),
        ]
    )
    d.components["b"].package_pin_map = {"A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS"}
    _net(d, "VCC_5V", "a", "b")
    d.nets["VCC_5V"].nodes[1].pin_name = "VBUS"
    return d, pos


def test_power_router_connects_all_four_usb_vbus_contacts() -> None:
    """A power route must touch all real USB-C contacts, not only logical VBUS."""
    from zaptrace.pipeline.physical_route_preflight import retain_verified_partial_copper

    design, positions = _multi_vbus_footprint_fixture()
    route = GridRouter(resolution_mm=0.25, pad_aware=True, max_iterations=25_000).route(design, positions)
    assert route.net_count == 1
    assert route.routed_net_count == 1
    assert route.traces
    assert all(seg.net_id == "VCC_5V" and seg.width == 0.5 for seg in route.traces)
    accepted = retain_verified_partial_copper(design, route, positions)
    assert accepted.routed_net_count == 1
    assert accepted.traces


def test_power_router_connects_off_grid_repeated_vbus_contacts_without_neckdown() -> None:
    """All real connector contacts require a legal geometric fanout, even off-grid."""
    from zaptrace.pipeline.physical_route_preflight import retain_verified_partial_copper

    design, positions = _multi_vbus_footprint_fixture()
    # With this grid pitch the 0.6 mm USB contacts sit between legal grid
    # points. First-pad-only routing or silently dropped contacts is invalid.
    positions["b"] = (25.375, 10)
    route = GridRouter(resolution_mm=0.75, pad_aware=True, max_iterations=20_000).route(design, positions)
    assert route.net_count == 1
    assert route.routed_net_count == 1
    assert route.traces
    assert all(trace.net_id == "VCC_5V" and trace.width == 0.5 for trace in route.traces)
    accepted = retain_verified_partial_copper(design, route, positions)
    assert accepted.routed_net_count == 1
    assert accepted.traces


def test_power_router_rejects_narrow_and_excess_vbus_contacts() -> None:
    """Never erase or electrically narrow an extra real VBUS pin."""
    design, positions = _multi_vbus_footprint_fixture()
    footprint = design.components["b"].footprint_def
    assert footprint is not None
    router = GridRouter(resolution_mm=0.25, pad_aware=True, max_iterations=25_000)
    footprint.pads[-1].size = (0.4, 0.35)
    narrow = router.route(design, positions)
    assert narrow.net_count == 1
    assert narrow.routed_net_count == 0 and not narrow.traces
    footprint.pads[-1].size = (0.6, 1.15)

    # A source terminal with more physical contacts than the bounded
    # router can inspect must remain incomplete, never first-pad routed.
    for offset in range(5, 13):
        name = f"P{offset}"
        footprint.pads.append(
            Pad(
                id=name,
                position=(float((offset - 5) % 4) * 2.0 - 3.0, float((offset - 5) // 4) * 2.5 + 3.0),
                size=(0.6, 1.15),
                layer=LayerSet.TOP,
            )
        )
        design.components["b"].package_pin_map[name] = "VBUS"
    too_many = router.route(design, positions)
    assert too_many.net_count == 1
    assert too_many.routed_net_count == 0 and not too_many.traces


@pytest.mark.parametrize("hidden_pad", [False, True])
def test_larger_power_net_rejects_unqualified_narrow_or_repeated_contacts(hidden_pad: bool) -> None:
    """A larger power MST cannot hide a too-narrow or extra physical pad."""
    pads = [
        (ref, (x, 15), Pad(id="1", size=(1.5, 1.5), layer=LayerSet.TOP))
        for ref, x in (("a", 5), ("b", 11), ("c", 17), ("d", 23), ("e", 29))
    ]
    design, positions = _board(*pads)
    _net(design, "VCC_3V3", "a", "b", "c", "d", "e")
    footprint = design.components["b"].footprint_def
    assert footprint is not None
    if hidden_pad:
        footprint.pads.append(Pad(id="1", position=(0, 3), size=(1.5, 1.5), layer=LayerSet.TOP))
    else:
        footprint.pads[0].size = (0.5, 0.35)
    route = GridRouter(resolution_mm=0.25, pad_aware=True, max_iterations=15_000).route(design, positions)
    assert route.net_count == 1
    assert route.routed_net_count == 0 and not route.traces


def test_real_esp32_power_nets_cannot_bypass_unqualified_source_lands() -> None:
    """Source VBUS and 3V3 remain physically unrouted until actual land/current review."""
    from pathlib import Path

    from zaptrace.core.parser import parse_file

    source = Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml"
    design = parse_file(source)
    connector_footprint = design.components["J1"].footprint_def
    assert connector_footprint is not None
    assert design.placement is not None
    vbus_pads = [
        pad for pad in connector_footprint.pads if design.components["J1"].package_pin_map.get(pad.id) == "VBUS"
    ]
    assert {pad.id for pad in vbus_pads} == {"A4", "A9", "B4", "B9"}
    assert len({pad.position for pad in vbus_pads}) == 2
    d1 = design.components["D1"].footprint_def
    u2 = design.components["U2"].footprint_def
    assert d1 is not None and u2 is not None
    assert min(d1.pads[0].size) == 0.45
    assert min(u2.pads[0].size) == 0.35
    design.nets = {key: design.nets[key] for key in ("VCC_5V", "VCC_3V3")}
    route = GridRouter(pad_aware=True, max_iterations=20_000).route(design, design.placement)
    assert route.net_count == 2
    assert route.routed_net_count == 0
    assert not route.traces and not route.vias


@pytest.mark.parametrize("offset,resolution", [(0.0, 0.25), (0.375, 0.75)])
def test_power_router_native_kicad_connects_all_vbus_contacts_without_new_drc(
    tmp_path, offset: float, resolution: float
) -> None:
    """Independent KiCad verifies all VBUS pads, including real off-grid fanout."""
    import json
    import shutil
    import subprocess
    from collections import Counter

    from zaptrace.core.models import RouteResult
    from zaptrace.export.kicad import export_kicad

    if not shutil.which("kicad-cli"):
        pytest.skip("Native KiCad unavailable")
    version = subprocess.run(["kicad-cli", "version"], capture_output=True, text=True, check=True, timeout=10)
    if not version.stdout.strip().startswith("10."):
        pytest.skip("Independent KiCad 10 required")
    design, positions = _multi_vbus_footprint_fixture()
    positions["b"] = (25 + offset, 10)
    route = GridRouter(resolution_mm=resolution, pad_aware=True, max_iterations=25_000).route(design, positions)
    assert route.routed_net_count == 1
    reports = []
    for label, copper in (("unrouted", RouteResult(net_count=1)), ("routed", route)):
        candidate = design.model_copy(deep=True)
        candidate.placement = dict(positions)
        candidate.routing = copper
        pcb = export_kicad(candidate, tmp_path / label)["pcb"]
        report_path = tmp_path / f"{label}.json"
        process = subprocess.run(
            [
                "kicad-cli",
                "pcb",
                "drc",
                "--exit-code-violations",
                "--severity-all",
                "--format",
                "json",
                "--output",
                str(report_path),
                str(pcb),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        assert process.returncode in (0, 5), process.stderr
        reports.append(json.loads(report_path.read_text(encoding="utf-8")))
    before, after = reports
    # Four USB-style VBUS pad IDs occupy two physical land positions.
    assert len(before["unconnected_items"]) == 2
    assert len(after["unconnected_items"]) == 0
    # Test-only library-footprint mismatch notices must not be suppressed.
    assert Counter(v["type"] for v in before["violations"]) == Counter(v["type"] for v in after["violations"])


def test_ground_without_pour_honors_custom_full_width_clearance() -> None:
    """Explicit GND copper must reserve the real configured trace/clearance halo."""
    from zaptrace.ee.constraints.net_classes import NetClass, NetClassRule

    d, pos = _board(
        ("a", (10, 10), Pad(id="1", size=(2.0, 1.5), layer=LayerSet.TOP)),
        ("b", (25, 10), Pad(id="1", size=(2.0, 1.5), layer=LayerSet.TOP)),
    )
    _net(d, "GND", "a", "b")
    d.board.copper_pour_gnd = False
    router = GridRouter(resolution_mm=0.5, pad_aware=True)
    standard = router._prepare_route_context(d, pos)
    kb = KnowledgeBase()
    kb.set_rule(
        NetClass.GROUND,
        NetClassRule(trace_width=1.2, clearance=0.55, max_vias=2, priority=0, description="wide ground"),
    )
    wider = router._prepare_route_context(d, pos, kb)
    assert wider.obstacles.preexpanded_static_clearance
    assert len(wider.obstacles._pad_clearance) > len(standard.obstacles._pad_clearance)


def test_ground_without_pour_rejects_narrow_physical_land_even_when_repeated() -> None:
    """Never solve a small ground net by dropping real contacts or narrowing copper."""
    d, pos = _board(
        ("a", (10, 10), Pad(id="1", size=(2.0, 1.5), layer=LayerSet.TOP)),
        ("b", (25, 10), Pad(id="1", size=(2.0, 1.5), layer=LayerSet.TOP)),
    )
    _net(d, "GND", "a", "b")
    d.board.copper_pour_gnd = False
    router = GridRouter(resolution_mm=0.25, pad_aware=True, max_iterations=20_000)
    assert router.route(d, pos).routed_net_count == 1

    footprint = d.components["b"].footprint_def
    assert footprint is not None
    footprint.pads[0].size = (0.5, 0.35)
    narrow = router.route(d, pos)
    assert narrow.net_count == 1
    assert narrow.routed_net_count == 0 and not narrow.traces

    footprint.pads[0].size = (2.0, 1.5)
    # Duplicate actual copper occurrence, despite a single logical GND pin.
    footprint.pads.append(Pad(id="1", position=(2.0, 0), size=(0.5, 0.35), layer=LayerSet.TOP))
    repeated = router.route(d, pos)
    assert repeated.net_count == 1
    assert repeated.routed_net_count == 0 and not repeated.traces


def test_ground_without_pour_does_not_use_nonphysical_legacy_router() -> None:
    """An unverified graph route cannot be used as an ersatz ground return."""
    d, pos = _board(
        ("a", (10, 10), Pad(id="1", size=(2.0, 1.5), layer=LayerSet.TOP)),
        ("b", (25, 10), Pad(id="1", size=(2.0, 1.5), layer=LayerSet.TOP)),
    )
    _net(d, "GND", "a", "b")
    d.board.copper_pour_gnd = False
    route = GridRouter(resolution_mm=0.25, pad_aware=False).route(d, pos)
    assert route.net_count == 1
    assert route.routed_net_count == 0 and not route.traces
    d.board.copper_pour_gnd = True
    pour = GridRouter(resolution_mm=0.25, pad_aware=True).route(d, pos)
    assert pour.net_count == 0
    assert pour.routed_net_count == 0 and not pour.traces


@pytest.mark.parametrize("third_contact", [False, True])
def test_ground_without_pour_native_kicad_continuity_without_new_drc(tmp_path, third_contact: bool) -> None:
    """Confirm two- or three-pad grounded copper independently in native KiCad."""
    import json
    import shutil
    import subprocess
    from collections import Counter

    from zaptrace.core.models import RouteResult
    from zaptrace.export.kicad import export_kicad

    if shutil.which("kicad-cli") is None:
        pytest.skip("Independent KiCad 10 DRC requires the native kicad-cli tool")
    version = subprocess.run(["kicad-cli", "version"], capture_output=True, text=True, check=True, timeout=10)
    if not version.stdout.strip().startswith("10."):
        pytest.skip("Independent KiCad 10 required for native GND routing evidence")
    pads = [
        ("a", (10, 10), Pad(id="1", size=(2.0, 1.5), layer=LayerSet.TOP)),
        ("b", (25, 10), Pad(id="1", size=(2.0, 1.5), layer=LayerSet.TOP)),
    ]
    if third_contact:
        pads.append(("c", (25, 20), Pad(id="1", size=(2.0, 1.5), layer=LayerSet.TOP)))
    d, pos = _board(*pads)
    _net(d, "GND", *(["a", "b", "c"] if third_contact else ["a", "b"]))
    d.board.copper_pour_gnd = False
    route = GridRouter(resolution_mm=0.25, pad_aware=True, max_iterations=20_000).route(d, pos)
    assert route.routed_net_count == 1
    reports = []
    for label, traces in (("original", RouteResult(net_count=1)), ("routed", route)):
        candidate = d.model_copy(deep=True)
        candidate.placement = dict(pos)
        candidate.routing = traces
        pcb = export_kicad(candidate, tmp_path / label)["pcb"]
        report = tmp_path / f"{label}.json"
        completed = subprocess.run(
            [
                "kicad-cli",
                "pcb",
                "drc",
                "--exit-code-violations",
                "--severity-all",
                "--format",
                "json",
                "--output",
                str(report),
                str(pcb),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        assert completed.returncode in (0, 5), completed.stderr
        reports.append(json.loads(report.read_text(encoding="utf-8")))
    before, after = reports
    assert len(before["unconnected_items"]) == (2 if third_contact else 1)
    assert len(after["unconnected_items"]) == 0
    # The test-only footprints are not in an installed KiCad library; any
    # independently reported library issues must be unchanged, not hidden.
    assert Counter(v["type"] for v in after["violations"]) == Counter(v["type"] for v in before["violations"])


def test_ground_net_is_unresolved_when_copper_pour_is_disabled() -> None:
    from copy import deepcopy
    from pathlib import Path

    from zaptrace.core.parser import parse_file

    source = Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml"
    design = parse_file(source)
    assert design.board_def is None
    assert not canonical_board_definition(design).copper_pour_gnd
    assert "GND" in design.nets
    ground_only = deepcopy(design)
    ground_only.nets = {"GND": ground_only.nets["GND"]}
    route = GridRouter(pad_aware=True).route(ground_only, ground_only.placement or {})
    assert route.net_count == 1
    assert route.routed_net_count == 0
    assert route.traces == []


def test_ground_net_is_delegated_only_when_copper_pour_is_enabled() -> None:
    from copy import deepcopy
    from pathlib import Path

    from zaptrace.core.parser import parse_file

    source = Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml"
    design = parse_file(source)
    assert design.board_def is None
    design.board.copper_pour_gnd = True
    assert canonical_board_definition(design).copper_pour_gnd
    ground_only = deepcopy(design)
    ground_only.nets = {"GND": ground_only.nets["GND"]}
    route = GridRouter(pad_aware=True).route(ground_only, ground_only.placement or {})
    assert route.net_count == 0
    assert route.routed_net_count == 0


def test_overlapping_usb_contacts_with_same_logical_pin_share_copper_owner() -> None:
    d, pos = _board(
        ("usb", (10, 10), Pad(id="A4", size=(1, 1))),
        ("other", (22, 10), Pad(id="1", size=(1, 1))),
    )
    fp = d.components["usb"].footprint_def
    assert fp is not None
    fp.pads.append(Pad(id="B9", size=(1, 1)))
    d.components["usb"].package_pin_map = {"A4": "VBUS", "B9": "VBUS"}
    d.nets["VCC"] = Net(
        id="VCC",
        name="VCC_5V",
        nodes=[
            NetNode(component_ref="USB", pin_name="VBUS"),
            NetNode(component_ref="OTHER", pin_name="1"),
        ],
    )
    obs = GridRouter(resolution_mm=0.5, pad_aware=True)._prepare_route_context(d, pos).obstacles
    center = GridPos(20, 20)
    assert center not in obs._pad_conflicts
    assert obs._pads[center] == "VCC"
    assert obs.is_free(center, "VCC")
    assert not obs.is_free(center, "OTHER")


def test_esp32_usb_duplicate_contacts_do_not_create_fake_grid_shorts() -> None:
    from pathlib import Path

    from zaptrace.core.parser import parse_file

    source = Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml"
    design = parse_file(source)
    assert design.placement is not None
    router = GridRouter(resolution_mm=0.25, pad_aware=True)
    obstacles = router._prepare_route_context(design, design.placement).obstacles
    assert obstacles._pad_conflicts == set()
    # The two net-equivalent USB-C A4/B9 pads are superimposed by the
    # supplier footprint; B9 must not become unidentified foreign copper.
    assert obstacles._pads[GridPos(310, 253)] == "VCC_5V"
    assert obstacles._pads[GridPos(307, 253)] == "GND"


def test_overlapping_pad_clearance_halos_are_not_fabricated_copper_shorts() -> None:
    d, pos = _board(
        ("a", (10, 10), Pad(id="1", size=(1, 1))),
        ("b", (11.5, 10), Pad(id="1", size=(1, 1))),
    )
    _net(d, "A", "a")
    _net(d, "B", "b")
    obs = GridRouter(resolution_mm=0.5, pad_aware=True)._prepare_route_context(d, pos).obstacles
    a, b = GridPos(20, 20), GridPos(23, 20)
    assert not obs._pad_conflicts
    assert obs._pads[a] == "A" and obs._pads[b] == "B"
    assert obs.is_free(a, "A")
    assert obs.is_free(b, "B")
    assert not obs.is_free(a, "B")
    assert not obs.is_free(b, "A")
    # The air gap is not free for a third net's copper corridor.
    assert not obs.is_free(GridPos(21, 20), "THIRD")


def test_real_foreign_pad_copper_overlap_still_blocks_both_nets() -> None:
    d, pos = _board(
        ("a", (10, 10), Pad(id="1", size=(1, 1))),
        ("b", (10, 10), Pad(id="1", size=(1, 1))),
    )
    _net(d, "A", "a")
    _net(d, "B", "b")
    obs = GridRouter(resolution_mm=0.5, pad_aware=True)._prepare_route_context(d, pos).obstacles
    center = GridPos(20, 20)
    assert center in obs._pad_conflicts
    assert not obs.is_free(center, "A")
    assert not obs.is_free(center, "B")


def test_plated_holes_and_npht_keepouts_span_all_copper_layers() -> None:
    pth = Pad(id="1", drill=0.8, layer=LayerSet.TOP, shape=PadShape.CIRCLE, size=(1.8, 1.8))
    npth = Pad(id="", drill=1.2, plated=False, layer=LayerSet.TOP, shape=PadShape.CIRCLE, size=(1.2, 1.2))
    d, pos = _board(("pth", (12, 12), pth), ("npth", (26, 12), npth), layers=4)
    _net(d, "SIG", "pth")
    router = GridRouter(pad_aware=True, resolution_mm=0.5)
    obs = router._prepare_route_context(d, pos).obstacles
    for layer in range(4):
        assert obs.is_free(GridPos(24, 24, layer), net_id="SIG")
        assert not obs.is_free(GridPos(24, 24, layer), net_id="OTHER")
        assert not obs.is_free(GridPos(52, 24, layer), net_id="SIG")
    assert copper_layers(pth, 4) == (0, 1, 2, 3)
    assert copper_layers(Pad(id="a", layer=LayerSet.INNER), 4) == (1, 2)
    assert not obs.can_place_through_via(GridPos(52, 24), "SIG", 1)


def test_component_rotation_and_local_pad_rotation_both_apply() -> None:
    pad = Pad(id="1", position=(2, 0), rotation=90, shape=PadShape.RECT, size=(3, 1))
    d, pos = _board(("a", (10, 10), pad))
    d.components["a"].properties["rotation"] = 90.0
    ctx = GridRouter(resolution_mm=0.5, pad_aware=True)._prepare_route_context(d, pos)
    assert ctx.rotation_by_ref["A"] == 90.0
    assert ctx.obstacles.is_free(GridPos(20, 16), net_id="foreign") is False
    assert ctx.obstacles.is_free(GridPos(24, 20), net_id="foreign")
    assert rotated_offset(2, 0, 90) == pytest.approx((0, -2))
    # Pad local rotation and footprint rotation follow the native KiCad convention.
    assert (23, 16) in pad_cells(pad, (10, 10), 90, 0.5, 80, 60, 0)
    assert (20, 19) not in pad_cells(pad, (10, 10), 90, 0.5, 80, 60, 0)


def test_top_only_pad_pair_routes_on_top_and_detours_around_foreign_pad() -> None:
    d, pos = _board(
        ("start", (6, 10), Pad(id="1", shape=PadShape.RECT, size=(1.5, 1))),
        ("finish", (30, 10), Pad(id="1", shape=PadShape.RECT, size=(1.5, 1))),
        ("barrier", (18, 10), Pad(id="1", shape=PadShape.RECT, size=(5, 2), rotation=90)),
    )
    _net(d, "SIGNAL_A", "start", "finish")
    _net(d, "SIGNAL_B", "barrier")
    router = GridRouter(pad_aware=True, resolution_mm=0.5)
    result = router.route(d, pos)
    assert result.net_count == 1
    assert result.routed_net_count == 1
    assert result.vias == []
    assert all(t.layer == "layer_0" for t in result.traces)
    assert result.traces[0].start == (6, 10)
    assert result.traces[-1].end == (30, 10)
    assert len(result.traces) > 1
    ctx = router._prepare_route_context(d, pos)
    for seg in result.traces:
        for x, y in [(seg.start[0], seg.start[1]), (seg.end[0], seg.end[1])]:
            p = GridPos(int(round(x * 2)), int(round(y * 2)), 0)
            assert ctx.obstacles.is_free(p, net_id="SIGNAL_A")


def test_pad_mode_connects_off_grid_centre_only_inside_real_pad_copper() -> None:
    from zaptrace.pipeline.physical_route_preflight import _physical_pad_terminal_coverage

    d, pos = _board(("a", (10.1, 10), Pad(id="1")), ("b", (20, 10), Pad(id="1")))
    _net(d, "SIG", "a", "b")
    result = GridRouter(pad_aware=True, resolution_mm=0.5).route(d, pos)
    assert result.net_count == result.routed_net_count == 1
    # Both exact centre and snapped anchor are on the same physical pad.
    # Do not draw a redundant microtrack *inside* the already connected pad.
    assert not any(segment.start == (10.1, 10) for segment in result.traces)
    assert any(segment.start == (10.0, 10.0) for segment in result.traces)
    assert _physical_pad_terminal_coverage(d, result, pos)


def test_pad_mode_offgrid_rotated_pad_emits_exact_copper_contact() -> None:
    from zaptrace.pipeline.physical_route_preflight import _physical_pad_terminal_coverage

    d, pos = _board(
        ("a", (10.1, 10), Pad(id="1", position=(1.0, 0), shape=PadShape.OVAL, size=(1.2, 0.6))),
        ("b", (20, 10), Pad(id="1")),
    )
    d.components["a"].properties["rotation"] = 90.0
    _net(d, "SIG", "a", "b")
    result = GridRouter(pad_aware=True, resolution_mm=0.5).route(d, pos)
    assert result.net_count == result.routed_net_count == 1
    # Rotated oval pad already connects the off-grid centre to the in-pad
    # grid anchor; no redundant physical copper segment is necessary.
    assert not any(segment.start == pytest.approx((10.1, 9.0)) for segment in result.traces)
    assert any(segment.start == pytest.approx((10.0, 9.0)) for segment in result.traces)
    assert _physical_pad_terminal_coverage(d, result, pos)


def test_pad_mode_rejects_nearest_grid_point_outside_real_pad_copper() -> None:
    d, pos = _board(
        ("a", (10.1, 10), Pad(id="1", size=(0.1, 0.1))),
        ("b", (20, 10), Pad(id="1")),
    )
    _net(d, "SIG", "a", "b")
    result = GridRouter(pad_aware=True, resolution_mm=0.5).route(d, pos)
    assert result.net_count == 1
    assert result.routed_net_count == 0
    assert result.traces == []


def test_pad_mode_offgrid_rounded_shape_corner_uses_explicit_geometric_stub() -> None:
    from zaptrace.pipeline.physical_route_preflight import _physical_pad_terminal_coverage

    d, pos = _board(
        ("a", (10.2, 10.2), Pad(id="1", shape=PadShape.CIRCLE, size=(0.5, 0.5))),
        ("b", (20, 10), Pad(id="1")),
    )
    _net(d, "SIG", "a", "b")
    result = GridRouter(pad_aware=True, resolution_mm=0.5).route(d, pos)
    assert result.routed_net_count == 1
    assert any(segment.start == pytest.approx((10.2, 10.2)) for segment in result.traces)
    assert _physical_pad_terminal_coverage(d, result, pos)


def test_top_bottom_smd_pair_requires_unimplemented_via_and_is_not_counted() -> None:
    d, pos = _board(
        ("top", (8, 10), Pad(id="1", layer=LayerSet.TOP)),
        ("bottom", (26, 10), Pad(id="1", layer=LayerSet.BOTTOM)),
    )
    _net(d, "SIG", "top", "bottom")
    result = GridRouter(pad_aware=True, resolution_mm=0.5).route(d, pos)
    assert result.net_count == 1
    assert result.routed_net_count == 0


def test_overlapping_foreign_pads_fail_closed_and_cannot_be_carved() -> None:
    d, pos = _board(
        ("a", (12, 12), Pad(id="1", size=(2, 2))),
        ("b", (12, 12), Pad(id="1", size=(2, 2))),
    )
    _net(d, "A", "a")
    _net(d, "B", "b")
    obs = GridRouter(pad_aware=True, resolution_mm=0.5)._prepare_route_context(d, pos).obstacles
    center = GridPos(24, 24, 0)
    assert center in obs._pad_conflicts
    for net in ("A", "B"):
        obs.open_for_net(center, net)
        assert not obs.is_free(center, net)
    assert not obs.can_place_through_via(center, "A", 0)


def test_custom_pad_and_unknown_footprint_rejected_not_treated_as_void() -> None:
    d, pos = _board(("a", (12, 12), Pad(id="1", shape=PadShape.CUSTOM)))
    with pytest.raises(ValueError, match="Custom pad"):
        GridRouter(pad_aware=True)._prepare_route_context(d, pos)
    d.components["a"].footprint_def = None
    with pytest.raises(ValueError, match="explicit footprint"):
        GridRouter(pad_aware=True)._prepare_route_context(d, pos)


def test_via_clearance_requires_all_layers_even_if_one_face_open() -> None:
    obs = ObstacleMap(20, 20, 4)
    obs.mark_pad(GridPos(10, 10, 1), "B")
    obs.enforce_static_clearance = True
    assert not obs.can_place_through_via(GridPos(10, 10), "A", 0)
    assert obs.can_place_through_via(GridPos(7, 7), "A", 1)
    obs.block(GridPos(7, 7, 3))
    assert not obs.can_place_through_via(GridPos(7, 7), "A", 1)
    assert not obs.can_place_through_via(GridPos(7, 7), "A", -1)


def test_invalid_pad_geometry_and_rotation_are_fail_closed() -> None:
    bad = Pad(id="1", size=(0, 1))
    with pytest.raises(ValueError, match="positive"):
        pad_cells(bad, (10, 10), 0, 0.25, 100, 100, 0.2)
    with pytest.raises(ValueError, match="finite"):
        pad_cells(Pad(id="1"), (10, 10), math.inf, 0.25, 100, 100, 0.2)
    with pytest.raises(ValueError, match="non-negative"):
        pad_cells(Pad(id="1"), (10, 10), 0, 0.25, 100, 100, -0.2)


def test_missing_logical_pin_pad_is_routable_debt_not_silently_ignored() -> None:
    d, pos = _board(
        ("x", (10, 10), Pad(id="1")),
        ("y", (20, 10), Pad(id="2")),
    )
    _net(d, "SIG", "x", "y")
    assert GridRouter(pad_aware=True, resolution_mm=0.5).route(d, pos).net_count == 1
    result = GridRouter(pad_aware=True, resolution_mm=0.5).route(d, pos)
    assert result.routed_net_count == 0
    assert result.traces == []


def test_foreign_pad_endpoint_is_never_displaced_to_nearest_free_grid_cell() -> None:
    d, pos = _board(
        ("x", (10, 10), Pad(id="1", size=(1.8, 1.8))),
        ("y", (25, 10), Pad(id="1", size=(1.8, 1.8))),
        ("foreign", (10, 10), Pad(id="1", size=(1.8, 1.8))),
    )
    _net(d, "SIG", "x", "y")
    _net(d, "OTHER", "foreign")
    router = GridRouter(pad_aware=True, resolution_mm=0.5)
    result = router.route(d, pos)
    assert result.net_count == 1
    assert result.routed_net_count == 0
    assert result.traces == []


def test_oval_mask_conservatively_reserves_actual_capsule_corners() -> None:
    oval = Pad(id="1", shape=PadShape.OVAL, size=(4.0, 1.0))
    shape = pad_cells(oval, (12, 12), 0, 0.5, 80, 80, 0.1)
    assert (24, 24) in shape
    assert (28, 24) in shape
    assert (24, 28) not in shape
    upright = pad_cells(oval, (12, 12), 90, 0.5, 80, 80, 0.1)
    assert (24, 28) in upright
    assert (28, 24) not in upright


def test_dnp_footprint_remains_a_real_pad_obstacle() -> None:
    d, pos = _board(("x", (10, 10), Pad(id="1", size=(2.0, 2.0))))
    d.components["x"].dnp = True
    obs = GridRouter(pad_aware=True, resolution_mm=0.5)._prepare_route_context(d, pos).obstacles
    assert not obs.is_free(GridPos(20, 20, 0), net_id="OTHER")


def test_bottom_pad_only_blocks_bottom_but_via_is_not_clear() -> None:
    d, pos = _board(("x", (10, 10), Pad(id="1", layer=LayerSet.BOTTOM)))
    _net(d, "BOTTOM_NET", "x")
    obs = GridRouter(pad_aware=True, resolution_mm=0.5)._prepare_route_context(d, pos).obstacles
    at_top = GridPos(20, 20, 0)
    assert obs.is_free(at_top, net_id="OTHER")
    assert not obs.is_free(GridPos(20, 20, 1), net_id="OTHER")
    assert not obs.can_place_through_via(at_top, "OTHER", 1)


def test_non_circular_npth_slot_and_nonfinite_pad_geometry_fail_closed() -> None:
    from zaptrace.algo.pad_copper import finished_hole_cells

    npth_slot = Pad(id="", drill=0.8, plated=False, shape=PadShape.OVAL, size=(1.8, 0.8))
    with pytest.raises(ValueError, match="Non-circular NPTH"):
        finished_hole_cells(npth_slot, (10, 10), 0, 0.5, 80, 80, 0.3)
    with pytest.raises(ValueError, match="finite"):
        pad_cells(Pad(id="1", rotation=float("nan")), (10, 10), 0, 0.5, 80, 80, 0)
    with pytest.raises(ValueError, match="outside"):
        pad_cells(Pad(id="1"), (-3, 10), 0, 0.5, 80, 80, 0)


def test_real_esp32_usb_cc_routes_use_geometric_pad_fanout_and_keep_unassigned_contacts_clear() -> None:
    from pathlib import Path

    from zaptrace.algo.pad_copper import _distance_in_local_shape
    from zaptrace.core.parser import parse_file

    source = Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml"
    design = parse_file(source)
    router = GridRouter(pad_aware=True, max_iterations=50_000)
    context = router._prepare_route_context(design, design.placement or {})
    kb = KnowledgeBase()

    for net_id in ("USB_CC1", "USB_CC2"):
        plan = router._plan_grid_net(design, design.nets[net_id], context, kb)
        assert plan.success
        assert len(plan.pad_stubs) == 2
        assert len(plan.edge_paths) == 1
        assert plan.width_mm == pytest.approx(0.2)
        connector_stub = next(stub for stub in plan.pad_stubs if stub[0][0] > 77.0)
        assert math.dist(*connector_stub) >= 0.5

        # Unassigned connector contacts remain physical obstacles.
        component = context.component_by_ref["J1"]
        assert component.footprint_def is not None
        rotation = context.rotation_by_ref["J1"]
        pos = context.ref_positions["J1"]
        for pad_id in ("B7", "B8", "A8", "A9"):
            pad = next(pad for pad in component.footprint_def.pads if str(pad.id) == pad_id)
            dx, dy = rotated_offset(*pad.position, rotation)
            center = (pos[0] + dx, pos[1] + dy)
            for step in range(21):
                ratio = step / 20
                x = connector_stub[0][0] + (connector_stub[1][0] - connector_stub[0][0]) * ratio
                y = connector_stub[0][1] + (connector_stub[1][1] - connector_stub[0][1]) * ratio
                angle = math.radians(-(float(pad.rotation) + rotation))
                px, py = x - center[0], y - center[1]
                local_x = math.cos(angle) * px + math.sin(angle) * py
                local_y = -math.sin(angle) * px + math.cos(angle) * py
                assert _distance_in_local_shape(local_x, local_y, pad) >= 0.25 - 1e-6

    # VBUS retains its full 0.50mm POWER_MED width; do not invent a neck-down.
    vbus = router._plan_grid_net(design, design.nets["VCC_5V"], context, kb)
    assert not vbus.success
    assert vbus.pad_stubs == []


def test_real_esp32_pad_fanout_improves_only_physically_proven_nets() -> None:
    from pathlib import Path

    from zaptrace.core.parser import parse_file
    from zaptrace.pipeline.physical_route_preflight import verified_route_candidate_safe

    source = Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml"
    design = parse_file(source)
    router = GridRouter(pad_aware=True, max_iterations=50_000, max_ripup_passes=2)
    result = router.route(design, design.placement or {}, KnowledgeBase())
    assert result.routed_net_count == 4
    assert result.net_count == 7
    assert {trace.net_id for trace in result.traces} == {
        "USB_CC1",
        "USB_CC2",
        "I2C_SCL",
        "I2C_SDA",
    }
    assert len(result.traces) == 44
    assert result.vias == []
    assert not verified_route_candidate_safe(design, result, design.placement or {})


def test_geometric_pad_escape_only_skips_preexpanded_pad_halo_not_dynamic_copper() -> None:
    obstacles = ObstacleMap(24, 24, layers=1)
    obstacles.enforce_static_clearance = True
    obstacles.preexpanded_static_clearance = True
    obstacles.mark_pad_clearance(GridPos(8, 8), "OTHER")
    # This option is used only after exact shape-distance validation of a
    # physical pad stub; it avoids a second raster halo rejecting that stub.
    obstacles.block_line(
        GridPos(8, 8),
        GridPos(8, 8),
        radius=0,
        net_id="SIGNAL",
        geometric_pad_escape=True,
    )
    assert obstacles.owner(GridPos(8, 8)) == "SIGNAL"

    obstacles.block_line(GridPos(12, 8), GridPos(12, 8), radius=0, net_id="POWER")
    with pytest.raises(ValueError, match="Copper clearance"):
        obstacles.block_line(
            GridPos(11, 8),
            GridPos(11, 8),
            radius=1,
            net_id="SIGNAL",
            geometric_pad_escape=True,
        )


def test_real_esp32_i2c_sda_uses_bounded_four_terminal_geometric_fanout() -> None:
    from pathlib import Path

    from zaptrace.core.parser import parse_file

    source = Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml"
    design = parse_file(source)
    net = design.nets["I2C_SDA"]
    assert len(net.nodes) == 4
    router = GridRouter(pad_aware=True, max_iterations=50_000)
    context = router._prepare_route_context(design, design.placement or {})
    plan = router._plan_grid_net(design, net, context, KnowledgeBase())
    assert plan.success
    assert len(plan.pad_stubs) == 4
    assert len(plan.edge_paths) == 3
    # Multi-terminal mode is intentionally one anchor and one MST attempt
    # per terminal; no Cartesian combination search is performed.
    assert all(math.dist(*stub) > 0 for stub in plan.pad_stubs)


def test_pad_mode_off_grid_anchor_inside_real_pad_needs_no_redundant_microtrack() -> None:
    """The pad itself connects its centre to an in-pad grid anchor."""
    from zaptrace.pipeline.physical_route_preflight import _physical_net_continuity, _physical_pad_terminal_coverage

    design, positions = _board(
        ("a", (10.01, 10.0), Pad(id="1", size=(1.0, 1.0))),
        ("b", (20.0, 10.0), Pad(id="1", size=(1.0, 1.0))),
    )
    _net(design, "SIG", "a", "b")
    routed = GridRouter(pad_aware=True, resolution_mm=0.25).route(design, positions)
    assert routed.net_count == routed.routed_net_count == 1
    assert routed.traces
    assert not any(segment.start == (10.01, 10.0) for segment in routed.traces)
    assert any(segment.start == (10.0, 10.0) or segment.end == (10.0, 10.0) for segment in routed.traces)
    assert _physical_pad_terminal_coverage(design, routed, positions)
    assert _physical_net_continuity(design, routed, positions)
