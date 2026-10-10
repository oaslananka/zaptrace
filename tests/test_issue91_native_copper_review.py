"""Fail-closed partial copper paths must connect authentic pad centers and nets."""

from __future__ import annotations

from pathlib import Path

from scripts.issue91_native_copper_review import ROUTES, _violations
from zaptrace.core.parser import parse_file

_DESIGN = Path(__file__).resolve().parents[1] / "examples" / "esp32_i2c_sensor_node" / "design.yaml"


def test_native_copper_review_has_only_verified_complete_net_terminal_endpoints() -> None:
    design = parse_file(_DESIGN)
    assert design.placement is not None
    assert len(ROUTES) == 14
    assert sum(len(route.points) - 1 for route in ROUTES) == 30
    for route in ROUTES:
        assert route.net in design.nets
        assert route.points[0] == route.source[2]
        assert route.points[-1] == route.target[2]
        assert len(route.points) >= 2
        for component_ref, pin_number, expected in (route.source, route.target):
            component = design.components[component_ref]
            assert component.footprint_def is not None
            pads = [pad for pad in component.footprint_def.pads if pad.id == pin_number]
            assert pads
            origin_x, origin_y = design.placement[component_ref]
            assert any(
                abs(origin_x + pad.position[0] - expected[0]) < 1e-6
                and abs(origin_y + pad.position[1] - expected[1]) < 1e-6
                for pad in pads
            )
            connected_pin = component.package_pin_map.get(pin_number, pin_number)
            assert component.pins[connected_pin].net == route.net


def test_native_drc_result_cannot_hide_new_finding_classes() -> None:
    sample = (
        "[drill_out_of_range]: 0.20 mm\n"
        "[drill_out_of_range]: 0.20 mm\n"
        "[hole_clearance]: 0.1944 mm\n"
        "[unconnected_items]: gap\n"
        "[shorting_items]: dangerous\n"
    )
    result = _violations(sample)
    assert result == {
        "drill_out_of_range": 2,
        "hole_clearance": 1,
        "unconnected_items": 1,
        "shorting_items": 1,
    }
