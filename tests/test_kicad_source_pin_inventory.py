"""A user can inspect real KiCad symbol pins and nets in the editable Design."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from defusedxml import ElementTree

from zaptrace.core.models import PinType
from zaptrace.kicad.schematic_importer import import_kicad_schematic, import_kicad_schematic_string

SOURCE = Path(__file__).parents[1] / "benchmarks/external/atomic14-basic-esp32s3-dev-board/source"


def _component(design, ref: str):
    return next(c for c in design.components.values() if c.ref == ref)


def test_real_esp32_schematic_import_preserves_library_pin_names_types_and_net_ids() -> None:
    """Original ESP32, LED and resistor pins must be queryable for AI design review."""
    schematic = next(SOURCE.glob("*.kicad_sch"))
    imported = import_kicad_schematic(schematic)
    design = imported.design
    r4, d1, u2 = (_component(design, ref) for ref in ("R4", "D1", "U2"))
    native_net = next(net for net in design.nets.values() if net.name == "Net-(D1-A)")

    assert {"1", "2"} <= set(r4.pins)
    assert r4.pins["2"].name == "2"  # KiCad's '~' is not a real pin label
    assert r4.pins["2"].type == PinType.PASSIVE
    assert r4.pins["2"].position == pytest.approx((124.46, 153.67))
    assert r4.pins["2"].net == native_net.id
    serialized = design.model_dump(mode="json")
    assert serialized["components"]["r4"]["pins"]["2"]["net"] == native_net.id
    assert serialized["components"]["r4"]["properties"]["kicad_original_pin_types"]["2"] == "passive"
    assert d1.pins["2"].name == "A"
    assert d1.pins["2"].net == native_net.id
    assert u2.pins["3"].name == "EN"
    assert u2.pins["3"].type == PinType.INPUT
    assert u2.pins["2"].type == PinType.POWER
    assert u2.pins["2"].current_domain == "POWER_IN"
    assert _component(design, "#PWR05").pins == {}  # annotation, not a physical component


def test_every_populated_pin_net_points_to_same_original_net_graph() -> None:
    imported = import_kicad_schematic(next(SOURCE.glob("*.kicad_sch")))
    connected = {
        (node.component_ref, node.pin_name): net.id for net in imported.design.nets.values() for node in net.nodes
    }
    matched = 0
    for component in imported.design.components.values():
        for number, pin in component.pins.items():
            if pin.net is not None:
                assert connected[(component.ref, number)] == pin.net
                matched += 1
    assert matched >= 100


def test_one_unmapped_kicad_electrical_type_is_visible_not_guessed() -> None:
    source = """(kicad_sch
      (lib_symbols (symbol "Device:Test"
        (symbol "Test_1_1"
          (pin unspecified line (at 0 0 0) (length 2.54)
            (name "MYSTERY") (number "7")))))
      (symbol (lib_id "Device:Test") (at 20 20 0)
        (property "Reference" "U1") (property "Value" "X")
        (pin "7" (uuid "11111111-1111-4111-8111-111111111111")))
    )"""
    result = import_kicad_schematic_string(source)
    u1 = _component(result.design, "U1")
    assert "7" not in u1.pins
    assert any(issue.kind == "unmapped_pin_electrical_type" and issue.source == "U1:7" for issue in result.unsupported)


def test_genuinely_empty_library_pin_evidence_does_not_fabricate_pin_schema() -> None:
    source = """(kicad_sch
      (symbol (lib_id "Unknown:Part") (at 10 10 0)
        (property "Reference" "U1") (property "Value" "X")
        (pin "1" (at 10 10 0)))
    )"""
    result = import_kicad_schematic_string(source)
    assert _component(result.design, "U1").pins == {}


def test_independent_kicad_10_original_native_net_nodes_agree_with_imported_pin_nets(tmp_path: Path) -> None:
    cli = shutil.which("kicad-cli")
    if cli is None:
        pytest.skip("Independent original netlist evidence requires native KiCad 10 CLI")
    v = subprocess.run([cli, "version"], capture_output=True, text=True, timeout=15, check=False)
    if v.returncode != 0 or not v.stdout.strip().startswith("10."):
        pytest.skip("Only native KiCad 10 is accepted as the independent oracle")
    for name in ("*.kicad_sch", "*.kicad_pro"):
        for file in SOURCE.glob(name):
            (tmp_path / file.name).write_bytes(file.read_bytes())
    schematic = next(tmp_path.glob("*.kicad_sch"))
    xml = tmp_path / "native.xml"
    result = subprocess.run(
        [cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(xml), str(schematic)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-500:]
    native = ElementTree.parse(xml).getroot()
    native_nodes = {
        (str(n.attrib["ref"]), str(n.attrib["pin"])): str(net.attrib["name"])
        for net in native.findall("./nets/net")
        for n in net.findall("node")
    }
    design = import_kicad_schematic(schematic).design
    for component in design.components.values():
        for pin_number, pin in component.pins.items():
            if pin.net is not None:
                assert (component.ref, pin_number) in native_nodes
                assert design.nets[pin.net].name == native_nodes[(component.ref, pin_number)]
    assert len(design.nets) == 47
    assert sum(len(net.nodes) for net in design.nets.values()) == 132


def test_source_verified_multiunit_pins_join_same_component_without_dropping_units() -> None:
    source = """(kicad_sch
      (lib_symbols (symbol "Device:Multi"
        (symbol "Multi_1_1"
          (pin input line (at 0 0 0) (length 2.54)
            (name "IN") (number "1"))
          (pin output line (at 5 0 0) (length 2.54)
            (name "OUT") (number "2")))))
      (symbol (lib_id "Device:Multi") (at 30 40 0) (unit 1)
        (property "Reference" "U1") (property "Value" "Device")
        (pin "1" (uuid "11111111-1111-4111-8111-111111111111")))
      (symbol (lib_id "Device:Multi") (at 50 60 0) (unit 2)
        (property "Reference" "U1") (property "Value" "Device")
        (pin "2" (uuid "22222222-2222-4222-8222-222222222222")))
    )"""
    result = import_kicad_schematic_string(source)
    u1 = _component(result.design, "U1")
    assert set(u1.pins) == {"1", "2"}
    assert u1.pins["1"].type == PinType.INPUT
    assert u1.pins["2"].type == PinType.OUTPUT
    assert u1.pins["2"].position == pytest.approx((55.0, 60.0))


def test_conflicting_source_units_do_not_silently_choose_one_pin_coordinate() -> None:
    source = """(kicad_sch
      (lib_symbols (symbol "Device:Multi"
        (symbol "Multi_1_1"
          (pin passive line (at 0 0 0) (length 2.54)
            (name "P") (number "1")))))
      (symbol (lib_id "Device:Multi") (at 10 20 0)
        (property "Reference" "U1") (property "Value" "Device")
        (pin "1" (uuid "11111111-1111-4111-8111-111111111111")))
      (symbol (lib_id "Device:Multi") (at 30 40 0)
        (property "Reference" "U1") (property "Value" "Device")
        (pin "1" (uuid "22222222-2222-4222-8222-222222222222")))
    )"""
    result = import_kicad_schematic_string(source)
    assert _component(result.design, "U1").pins == {}
    assert any(f.kind == "ambiguous_source_pin_instance" and f.source == "U1:1" for f in result.unsupported)
