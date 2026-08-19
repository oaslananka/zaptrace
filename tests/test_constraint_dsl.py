from __future__ import annotations

from zaptrace.core.models import (
    ConstraintSet,
    ManufacturingIntent,
    PlacementIntent,
    RoutingIntent,
    VoltageDomainConstraint,
)
from zaptrace.core.parser import dump_str, parse_str


def test_constraint_dsl_model_accepts_core_intents() -> None:
    constraints = ConstraintSet(
        voltage_domains=[VoltageDomainConstraint(id="VDD_3V3", nominal="3.3V", tolerance="5%")],
        placement=[PlacementIntent(component="J1", edge="left", reason="USB connector on edge")],
        routing=[RoutingIntent(net="USB_D*", differential_pair=True, impedance_ohm=90, length_match_mm=0.5)],
        manufacturing=ManufacturingIntent(profile="jlcpcb-2layer", min_trace_mm="profile", min_space_mm="profile"),
    )
    assert constraints.voltage_domains[0].id == "VDD_3V3"
    assert constraints.placement[0].edge == "left"
    assert constraints.routing[0].differential_pair
    assert constraints.manufacturing.profile == "jlcpcb-2layer"


def test_constraint_dsl_yaml_round_trip() -> None:
    design = parse_str(
        """
kind: zaptrace.design
schema_version: 1
meta:
  name: ConstraintDemo
components:
  j1:
    ref: J1
    type: usb-c
nets:
  gnd:
    name: GND
    nodes: []
constraints:
  voltage_domains:
    - id: VDD_3V3
      nominal: 3.3V
      tolerance: 5%
  placement:
    - component: J1
      edge: left
      reason: connector must be on board edge
  routing:
    - net: GND
      copper_pour: true
      stitching_vias: true
  manufacturing:
    profile: jlcpcb-2layer
    min_trace_mm: profile
""",
        strict=True,
    )
    assert design.constraints.placement[0].component == "J1"
    assert design.constraints.routing[0].copper_pour
    dumped = dump_str(design)
    assert "constraints:" in dumped
    assert parse_str(dumped, strict=True).constraints.manufacturing.profile == "jlcpcb-2layer"
