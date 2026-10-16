"""Real USB4105 oval slot evidence: geometry, nets and NC drill preservation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from zaptrace.core.models import Pad
from zaptrace.core.parser import parse_file
from zaptrace.export.excellon import generate_composite_drill, generate_excellon
from zaptrace.export.kicad import export_kicad_pcb
from zaptrace.kicad.importer import import_kicad_pcb
from zaptrace.kicad.verified_vendor import resolve_verified_footprint, verified_footprint_bytes

_ROOT = Path(__file__).resolve().parents[1]
_DESIGN = _ROOT / "examples" / "esp32_i2c_sensor_node" / "design.yaml"


def test_real_connector_preserves_four_routed_slots_and_two_npth_locating_holes() -> None:
    footprint = resolve_verified_footprint("usb4105-16p")
    assert len(footprint.pads) == 22
    assert sum(pad.id == "" and not pad.plated and pad.drill == 0.65 for pad in footprint.pads) == 2
    slots = [pad for pad in footprint.pads if pad.drill_slot is not None]
    assert len(slots) == 4
    assert [pad.drill_slot for pad in slots] == [(0.6, 1.7), (0.6, 1.4), (0.6, 1.7), (0.6, 1.4)]
    assert all(pad.id == "S1" and pad.plated and pad.drill is None for pad in slots)
    assert {pad.id for pad in footprint.pads if pad.id and pad.drill_slot is None} == {
        "A1",
        "A4",
        "A5",
        "A6",
        "A7",
        "A8",
        "A9",
        "A12",
        "B1",
        "B4",
        "B5",
        "B6",
        "B7",
        "B8",
        "B9",
        "B12",
    }


def test_exported_connector_keeps_contact_nets_slots_and_npth_pegs(tmp_path: Path) -> None:
    design = parse_file(_DESIGN)
    design.placement = {"J1": (22.0, 18.0)}
    exported = export_kicad_pcb(design, tmp_path)
    pcb = Path(exported["pcb"]).read_text(encoding="utf-8")
    j1 = next(block for block in pcb.split("\n  (footprint ") if '(property "Reference" "J1"' in block)

    assert j1.count('(pad "S1" thru_hole oval') == 4
    assert j1.count("(drill oval 0.6 1.7)") == 2
    assert j1.count("(drill oval 0.6 1.4)") == 2
    assert j1.count('(pad "" np_thru_hole circle') == 2
    assert j1.count("(drill 0.65)") == 2

    for pad, net in {
        "A1": "GND",
        "B1": "GND",
        "A12": "GND",
        "B12": "GND",
        "A4": "VCC_5V",
        "B4": "VCC_5V",
        "A9": "VCC_5V",
        "B9": "VCC_5V",
        "A5": "USB_CC1",
        "B5": "USB_CC2",
    }.items():
        match = re.search(
            rf'\(pad "{pad}" smd[\s\S]*?\(net \d+ "([^"]+)"\)',
            j1,
        )
        assert match is not None, pad
        assert match.group(1) == net

    # The connector's metal-shell stakes have no automatically invented GND net.
    assert not re.search(
        r'\(pad "S1" thru_hole[\s\S]*?\(net \d+ ', j1.split('(pad "S1" thru_hole')[1].split("  (uuid ")[0]
    )

    filename, content = verified_footprint_bytes("usb4105-16p")
    assert (tmp_path / "ZapTrace.pretty" / filename).read_bytes() == content


def test_excellon_preserves_four_real_slots_with_separate_plated_drill_tools() -> None:
    design = parse_file(_DESIGN)
    design.components["J1"].position = (22.0, 18.0)
    drills = generate_excellon(design, prefix="usb4105")
    plated = str(drills["plated"])
    non_plated = str(drills["non_plated"])
    composite = str(generate_composite_drill(design, prefix="usb4105"))

    assert plated.count("G85") == 4
    assert plated.count("G05") == 4
    assert "T01C0.6000" in plated
    assert composite.count("G85") == 4
    assert "G85" not in non_plated
    assert non_plated.count("X") == 2
    assert "T01C0.6500" in non_plated
    # Real slot centerlines: length minus cutter diameter is the routed distance.
    assert "X17680000Y14345000G85X17680000Y15445000" in plated
    assert "X26320000Y18675000G85X26320000Y19475000" in plated


def test_kicad_roundtrip_recovers_plated_slots_and_anonymous_npth(tmp_path: Path) -> None:
    design = parse_file(_DESIGN)
    design.placement = {"J1": (22.0, 18.0)}
    pcb = export_kicad_pcb(design, tmp_path)["pcb"]
    imported = import_kicad_pcb(pcb)
    component = next(c for c in imported.design.components.values() if c.ref == "J1")
    assert component.footprint_def is not None
    pads = component.footprint_def.pads
    assert len(pads) == 22
    assert [pad.drill_slot for pad in pads if pad.drill_slot] == [(0.6, 1.7), (0.6, 1.4), (0.6, 1.7), (0.6, 1.4)]
    assert sum(pad.id == "" and not pad.plated for pad in pads) == 2


@pytest.mark.parametrize(
    "slot",
    [(0, 1), (-0.6, 1.7), (0.6, 0.6), (float("nan"), 1.7), (float("inf"), 1.7)],
)
def test_invalid_oval_drill_parameters_fail_closed(slot: tuple[float, float]) -> None:
    with pytest.raises(ValidationError, match="Oval drill"):
        Pad(id="S1", drill_slot=slot)
