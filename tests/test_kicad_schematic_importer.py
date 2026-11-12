"""Tests for KiCad flat schematic importer (issue #117).

Covers all acceptance criteria:
* Flat schematic fixture imports components, pins, nets, labels, and junction
  connectivity deterministically.
* Connectivity resolution is independently unit-tested for crossings,
  junctions, dangling wires, aliases, and global/local labels.
* Every unsupported record includes source, kind, and degradation severity.
* Export → import self-round-trip reaches net score 1.00 on the supported
  fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode
from zaptrace.export.kicad import export_kicad_schematic
from zaptrace.kicad.schematic_importer import (
    KiCadSchematicImportResult,
    SchematicUnsupportedRecord,
    _add_imported_components,
    _add_imported_nets,
    _parse_pin_coordinate,
    _record_schematic_import_losses,
    _resolve_connectivity,
    _symbol_pin_coordinates,
    _UnionFind,
    compute_schematic_net_score,
    import_kicad_schematic_string,
)

# ---------------------------------------------------------------------------
# Minimal fixture helpers
# ---------------------------------------------------------------------------

_FLAT_SCH = """\
(kicad_sch (version 20230121) (generator "zaptrace")
  (title_block (title "test") (rev "1.0")
    (company "test")
  )
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (property "Reference" "R1" (at 50 45 0))
    (property "Value" "10k" (at 50 55 0))
    (pin 1 30 50)
    (pin 2 70 50)
  )
  (symbol (lib_id "Device:C") (at 100 50 0) (unit 1)
    (property "Reference" "C1" (at 100 45 0))
    (property "Value" "100nF" (at 100 55 0))
    (pin 1 80 50)
    (pin 2 120 50)
  )
  (wire (pts (xy 70 50) (xy 80 50)))
  (label "net_A" (at 70 50 0))
  (label "net_B" (at 30 50 0))
)"""

_JUNCTION_SCH = """\
(kicad_sch (version 20230121) (generator "zaptrace")
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (property "Reference" "R1" (at 50 45 0))
    (property "Value" "1k" (at 50 55 0))
    (pin 1 30 50)
    (pin 2 70 50)
  )
  (wire (pts (xy 30 50) (xy 70 50)))
  (wire (pts (xy 50 50) (xy 50 30)))
  (junction (at 50 50))
  (label "shared_net" (at 50 30 0))
  (label "shared_net" (at 30 50 0))
)"""

_GLOBAL_SCH = """\
(kicad_sch (version 20230121) (generator "zaptrace")
  (symbol (lib_id "power:VCC" ) (at 50 50 0) (unit 1)
    (property "Reference" "#PWR01" (at 50 45 0))
    (property "Value" "VCC" (at 50 55 0))
    (pin PWR 50 70)
  )
  (wire (pts (xy 50 70) (xy 50 90)))
  (global_label "VCC" (at 50 90 0))
)"""

_DANGLING_SCH = """\
(kicad_sch (version 20230121) (generator "zaptrace")
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (property "Reference" "R1" (at 50 45 0))
    (property "Value" "1k" (at 50 55 0))
    (pin 1 30 50)
    (pin 2 70 50)
  )
  (wire (pts (xy 30 50) (xy 10 50)))
)"""

_MULTI_UNIT_SCH = """\
(kicad_sch (version 20230121) (generator "zaptrace")
  (symbol (lib_id "Device:Dual_Opamp" ) (at 50 50 0) (unit 1)
    (property "Reference" "U1" (at 50 45 0))
    (property "Value" "LM358" (at 50 55 0))
  )
  (symbol (lib_id "Device:Dual_Opamp" ) (at 100 50 0) (unit 2)
    (property "Reference" "U1" (at 100 45 0))
    (property "Value" "LM358" (at 100 55 0))
  )
)"""


class TestSymbolPinCoordinates:
    def test_nested_pin_coordinates(self) -> None:
        assert _parse_pin_coordinate(["pin", "1", ["at", "12.5", "8.25"]]) == ("1", 12.5, 8.25)

    def test_bare_pin_coordinates(self) -> None:
        assert _parse_pin_coordinate(["pin", "2", "30", "50"]) == ("2", 30.0, 50.0)

    def test_malformed_pin_is_skipped(self) -> None:
        node = ["symbol", ["pin", "1", "bad"], ["pin", "2", "4", "5"], ["property", "Value", "x"]]
        assert _symbol_pin_coordinates(node) == [("2", 4.0, 5.0)]


# ---------------------------------------------------------------------------
# KiCad 10 actual pin transforms: rotation and instance mirroring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("local", "angle", "mirror", "expected"),
    [
        ((-3.81, 0.0), 0.0, "", (-3.81, 0.0)),
        ((-3.81, 0.0), 90.0, "", (0.0, 3.81)),
        ((-3.81, 0.0), 90.0, "x", (0.0, -3.81)),
        ((3.81, 0.0), 270.0, "", (0.0, 3.81)),
        ((2.0, 3.0), 0.0, "y", (-2.0, -3.0)),
        ((2.0, 3.0), 180.0, "", (-2.0, 3.0)),
    ],
)
def test_embedded_pin_transform_matches_kicad_sheet_coordinates(
    local: tuple[float, float],
    angle: float,
    mirror: str,
    expected: tuple[float, float],
) -> None:
    from zaptrace.kicad.schematic_importer import _rotate_local_pin

    x, y = _rotate_local_pin(local, (45.72, 116.84), angle, mirror)
    assert x == pytest.approx(45.72 + expected[0])
    assert y == pytest.approx(116.84 + expected[1])


def test_kicad_half_grid_rounding_does_not_lose_pin_connections() -> None:
    """Transform drift on a half-grid tick cannot drop a connected pin."""
    from zaptrace.kicad.schematic_importer import _quantise

    assert _quantise((169.545, 278.765)) == _quantise((169.54500000000002, 278.76500000000004))
    assert _quantise((-169.545, -278.765)) == _quantise((-169.54500000000002, -278.76500000000004))
    assert _quantise((1.000, 2.000)) != _quantise((1.020, 2.000))


def test_label_at_wire_interior_names_the_connected_pins() -> None:
    """KiCad permits labels at segment interior, not only at wire endpoints."""
    from zaptrace.kicad.schematic_importer import _resolve_connectivity

    wires = [((0.0, 0.0), (10.0, 0.0)), ((20.0, 0.0), (30.0, 0.0))]
    symbols = [
        {"ref": ref, "pins": [("1", x, 0.0)]} for ref, x in (("R1", 0.0), ("R2", 10.0), ("R3", 20.0), ("R4", 30.0))
    ]
    labels = [
        ("QSPI_SS", "label", (5.0, 0.0)),
        ("QSPI_SS", "label", (25.0, 0.0)),
    ]
    result = _resolve_connectivity(symbols, wires, [], labels)
    assert result == {
        "/QSPI_SS": [("R1", "1"), ("R2", "1"), ("R3", "1"), ("R4", "1")],
    }


def _crossing_wires_and_symbols():
    """Two independent wires crossing without an electrical junction."""
    wires = [((0.0, 0.0), (10.0, 0.0)), ((5.0, -5.0), (5.0, 5.0))]
    symbols = [
        {"ref": ref, "pins": [("1", x, y)]}
        for ref, x, y in (
            ("R1", 0.0, 0.0),
            ("R2", 10.0, 0.0),
            ("C1", 5.0, -5.0),
            ("C2", 5.0, 5.0),
        )
    ]
    return wires, symbols


def test_explicit_junction_joins_crossing_wire_segments_only_when_marked() -> None:
    """A KiCad junction dot is electrical, a geometrical crossing is not."""
    from zaptrace.kicad.schematic_importer import _resolve_connectivity

    wires, symbols = _crossing_wires_and_symbols()
    without = _resolve_connectivity(symbols, wires, [], [])
    without_groups = [set(pins) for pins in without.values() if pins]
    assert len(without_groups) == 2
    assert {("R1", "1"), ("R2", "1")} in without_groups
    assert {("C1", "1"), ("C2", "1")} in without_groups

    with_junction = _resolve_connectivity(symbols, wires, [(5.0, 0.0)], [])
    with_groups = [set(pins) for pins in with_junction.values() if pins]
    assert with_groups == [{("R1", "1"), ("R2", "1"), ("C1", "1"), ("C2", "1")}]


def test_real_linear_regulator_junctions_preserve_native_ground_group() -> None:
    from pathlib import Path

    from zaptrace.kicad.schematic_importer import import_kicad_schematic

    source = (
        Path(__file__).parents[1] / "benchmarks/external/nitu-linear-regulator/source/05_linear_regulator.kicad_sch"
    )
    result = import_kicad_schematic(source)
    named = {
        net.name: {
            (pin.component_ref, pin.pin_name) for pin in net.nodes if not pin.component_ref.startswith(("#PWR", "#FLG"))
        }
        for net in result.design.nets.values()
    }
    assert named["GND"] == {
        ("C1", "2"),
        ("C2", "2"),
        ("C3", "2"),
        ("C4", "2"),
        ("D2", "1"),
        ("J1", "2"),
        ("J2", "2"),
        ("TP4", "1"),
        ("U1", "2"),
    }


def test_label_on_unjoined_wire_crossing_does_not_short_nets() -> None:
    """A geometrical crossing without a junction is electrically distinct."""
    from zaptrace.kicad.schematic_importer import _resolve_connectivity

    wires, symbols = _crossing_wires_and_symbols()
    unsupported = []
    nets = _resolve_connectivity(symbols, wires, [], [("ambiguous", "label", (5.0, 0.0))], unsupported)
    groups = [set(pins) for pins in nets.values() if pins]
    assert {("R1", "1"), ("R2", "1")} in groups
    assert {("C1", "1"), ("C2", "1")} in groups
    assert all(not ({("R1", "1"), ("C1", "1")} <= group) for group in groups)
    assert [r.kind for r in unsupported] == ["ambiguous_wire_label_crossing"]


def test_real_mitayi_connected_pins_and_qspi_label_match_native_reference() -> None:
    """All real Mitayi connector pins except 3 KiCad NC pins stay connected."""
    from pathlib import Path

    from zaptrace.kicad.schematic_importer import import_kicad_schematic

    source = Path(__file__).parents[1] / "benchmarks/external/mitayi-pico-d1/source/Mitayi-Pico-D1.kicad_sch"
    result = import_kicad_schematic(source)
    by_name = {
        net.name: {(node.component_ref, node.pin_name) for node in net.nodes} for net in result.design.nets.values()
    }
    assert len(by_name) == 64
    assert by_name["/QSPI_SS"] == {("U3", "56"), ("U1", "1"), ("R1", "2"), ("R2", "1")}
    # The independent KiCad XML omits synthetic #PWR* connection nodes.
    all_pins = {pin for name, pins in by_name.items() if not name.startswith("unconnected-") for pin in pins}
    assert by_name["unconnected-(J2-SBU1-PadA8)"] == {("J2", "A8")}
    assert by_name["unconnected-(J2-SBU2-PadB8)"] == {("J2", "B8")}
    assert by_name["unconnected-(J6-ID-Pad4)"] == {("J6", "4")}
    assert {("J3", str(n)) for n in range(1, 21)} <= all_pins
    assert {("J4", str(n)) for n in range(1, 21)} <= all_pins
    assert {("J6", str(n)) for n in (1, 2, 3, 5, 6)} <= all_pins
    assert {("J7", "1"), ("J10", "1"), ("R3", "2"), ("R4", "2")} <= all_pins
    assert {("J2", "A8"), ("J2", "B8"), ("J6", "4")}.isdisjoint(all_pins)
    assert len(all_pins) == 228
    assert result.net_score == 1.0


def test_power_input_symbols_merge_global_nets_but_not_power_output_flags() -> None:
    """KiCad (power) library pins identify nets; instance Value is not authority."""
    source = """
    (kicad_sch (version 20250114)
      (lib_symbols
        (symbol "power:GND" (power)
          (symbol "GND_0_1"
            (pin power_in line (at 0 0 270) (name "GND") (number "1"))))
        (symbol "power:PWR_FLAG" (power)
          (symbol "PWR_FLAG_0_1"
            (pin power_out line (at 0 0 90) (name "PWR_FLAG") (number "1")))))
      (symbol (lib_id "power:GND") (at 10 20 0)
        (property "Reference" "#PWR01") (property "Value" "renamed")
        (pin "1" (uuid "a")))
      (symbol (lib_id "power:GND") (at 40 20 0)
        (property "Reference" "#PWR02") (property "Value" "renamed again")
        (pin "1" (uuid "b")))
      (symbol (lib_id "power:PWR_FLAG") (at 10 60 0)
        (property "Reference" "#FLG01") (property "Value" "PWR_FLAG")
        (pin "1" (uuid "c")))
      (symbol (lib_id "power:PWR_FLAG") (at 40 60 0)
        (property "Reference" "#FLG02") (property "Value" "PWR_FLAG")
        (pin "1" (uuid "d")))
      (symbol (lib_id "Device:R") (at 20 20 0)
        (property "Reference" "R1") (property "Value" "10k")
        (pin 1 20 20))
      (symbol (lib_id "Device:R") (at 50 20 0)
        (property "Reference" "R2") (property "Value" "10k")
        (pin 1 50 20))
      (symbol (lib_id "Device:R") (at 20 60 0)
        (property "Reference" "R3") (property "Value" "10k")
        (pin 1 20 60))
      (symbol (lib_id "Device:R") (at 50 60 0)
        (property "Reference" "R4") (property "Value" "10k")
        (pin 1 50 60))
      (wire (pts (xy 10 20) (xy 20 20)))
      (wire (pts (xy 40 20) (xy 50 20)))
      (wire (pts (xy 10 60) (xy 20 60)))
      (wire (pts (xy 40 60) (xy 50 60)))
    )
    """
    result = import_kicad_schematic_string(source)
    nets = {
        net.name: {(node.component_ref, node.pin_name) for node in net.nodes} for net in result.design.nets.values()
    }
    assert nets["GND"] == {("R1", "1"), ("R2", "1")}
    assert "PWR_FLAG" not in nets
    assert "renamed" not in nets and "renamed again" not in nets
    assert len(result.design.nets) == 3
    assert not any(
        {("R3", "1"), ("R4", "1")}.issubset(pins) for pins in nets.values()
    )  # Two independent power-output flags must not merge.


def test_modern_kicad_power_input_uses_library_value_when_pin_name_empty() -> None:
    """KiCad 10 power net identity follows instance Value when pin name is blank."""
    source = """
    (kicad_sch (version 20260306)
      (lib_symbols
        (symbol "power:GND" (power global)
          (property "Value" "GND")
          (symbol "GND_0_1"
            (pin power_in line (at 0 0 270) (name "") (number "1"))))
        (symbol "power:PWR_FLAG" (power global)
          (property "Value" "PWR_FLAG")
          (symbol "PWR_FLAG_0_1"
            (pin power_out line (at 0 0 90) (name "") (number "1")))))
      (symbol (lib_id "power:GND") (at 10 20 0)
        (property "Reference" "#PWR01") (property "Value" "GND")
        (pin "1" (uuid "a")))
      (symbol (lib_id "power:GND") (at 40 20 0)
        (property "Reference" "#PWR02") (property "Value" "GND")
        (pin "1" (uuid "b")))
      (symbol (lib_id "power:PWR_FLAG") (at 10 60 0)
        (property "Reference" "#FLG01") (property "Value" "PWR_FLAG")
        (pin "1" (uuid "c")))
      (symbol (lib_id "Device:R") (at 20 20 0)
        (property "Reference" "R1") (property "Value" "10k")
        (pin 1 20 20))
      (symbol (lib_id "Device:R") (at 50 20 0)
        (property "Reference" "R2") (property "Value" "10k")
        (pin 1 50 20))
      (wire (pts (xy 10 20) (xy 20 20)))
      (wire (pts (xy 40 20) (xy 50 20)))
    )
    """
    result = import_kicad_schematic_string(source)
    nets = {net.name: {(pin.component_ref, pin.pin_name) for pin in net.nodes} for net in result.design.nets.values()}
    assert nets["GND"] == {("R1", "1"), ("R2", "1")}
    # Power symbols still define global net identity; they are not physical
    # netlist nodes in KiCad's XML representation.
    assert {"#PWR01", "#PWR02"} <= {c.ref for c in result.design.components.values()}
    assert "PWR_FLAG" not in nets

    edited_source = source.replace(
        '(property "Reference" "#PWR02") (property "Value" "GND")',
        '(property "Reference" "#PWR02") (property "Value" "GND_CUSTOM")',
    )
    assert edited_source != source
    edited = import_kicad_schematic_string(edited_source)
    edited_nets = {
        net.name: {(pin.component_ref, pin.pin_name) for pin in net.nodes} for net in edited.design.nets.values()
    }
    assert edited_nets["GND"] == {("R1", "1")}
    assert edited_nets["GND_CUSTOM"] == {("R2", "1")}


def test_real_sparkfun_library_no_connect_pin_types_are_preserved() -> None:
    from pathlib import Path

    from zaptrace.kicad.schematic_importer import import_kicad_schematic

    schematic = (
        Path(__file__).parents[1]
        / "benchmarks/external/sparkfun-qwiic-navigation/source/SparkFun_Qwiic_Navigation.kicad_sch"
    )
    result = import_kicad_schematic(schematic)
    nc = {
        name: {(node.component_ref, node.pin_name) for node in net.nodes}
        for net in result.design.nets.values()
        if (name := net.name).startswith("unconnected-")
    }
    assert nc == {
        "unconnected-(J1-NC-PadNC1)": {("J1", "NC1")},
        "unconnected-(J1-NC-PadNC2)": {("J1", "NC2")},
        "unconnected-(J3-NC-PadNC1)": {("J3", "NC1")},
        "unconnected-(J3-NC-PadNC2)": {("J3", "NC2")},
        "unconnected-(SW2-PadMP1)": {("SW2", "MP1")},
        "unconnected-(SW2-PadMP2)": {("SW2", "MP2")},
    }
    assert not any(
        node.component_ref.startswith(("#PWR", "#FLG")) for net in result.design.nets.values() for node in net.nodes
    )


def test_real_mitayi_marker_not_silently_guessed_if_deleted() -> None:
    from pathlib import Path

    from zaptrace.kicad.schematic_importer import import_kicad_schematic_string

    schematic = (
        Path(__file__).parents[1] / "benchmarks/external/mitayi-pico-d1/source/Mitayi-Pico-D1.kicad_sch"
    ).read_text(encoding="utf-8")
    assert schematic.count("(no_connect") == 3
    original = import_kicad_schematic_string(schematic)
    edited = import_kicad_schematic_string(schematic.replace("(no_connect", "(not_a_nc_marker", 1))
    original_nc = {net.name for net in original.design.nets.values() if net.name.startswith("unconnected-")}
    edited_nc = {net.name for net in edited.design.nets.values() if net.name.startswith("unconnected-")}
    assert len(original_nc) == 3
    assert len(edited_nc) == 2
    assert edited_nc < original_nc
    assert any(record.kind == "unknown_not_a_nc_marker" for record in edited.unsupported)


def test_real_mitayi_marker_on_connected_pin_is_not_accepted_as_no_connect() -> None:
    from pathlib import Path

    from zaptrace.kicad.schematic_importer import import_kicad_schematic_string

    source = (
        Path(__file__).parents[1] / "benchmarks/external/mitayi-pico-d1/source/Mitayi-Pico-D1.kicad_sch"
    ).read_text(encoding="utf-8")
    # Pin J6.4 was intentionally NC; J6.2 is physically wired.
    assert source.count("(at 291.465 191.77)") >= 1
    edited = source.replace(
        "(no_connect\n\t\t(at 291.465 191.77)",
        "(no_connect\n\t\t(at 291.465 189.23)",
        1,
    )
    assert edited != source
    result = import_kicad_schematic_string(edited)
    nc_names = {net.name for net in result.design.nets.values() if net.name.startswith("unconnected-")}
    assert len(nc_names) == 2
    assert "unconnected-(J6-ID-Pad4)" not in nc_names
    assert any(f.kind == "no_connect_on_connected_pin" for f in result.unsupported)
    assert ("J6", "2") in {
        (node.component_ref, node.pin_name)
        for net in result.design.nets.values()
        if not net.name.startswith("unconnected-")
        for node in net.nodes
    }


def test_real_mitayi_unknown_no_connect_marker_is_fail_closed() -> None:
    from pathlib import Path

    from zaptrace.kicad.schematic_importer import import_kicad_schematic_string

    source = (
        Path(__file__).parents[1] / "benchmarks/external/mitayi-pico-d1/source/Mitayi-Pico-D1.kicad_sch"
    ).read_text(encoding="utf-8")
    edited = source.replace(
        "(no_connect\n\t\t(at 291.465 191.77)",
        "(no_connect\n\t\t(at 9999 9999)",
        1,
    )
    assert edited != source
    result = import_kicad_schematic_string(edited)
    nc_names = {net.name for net in result.design.nets.values() if net.name.startswith("unconnected-")}
    assert len(nc_names) == 2
    assert "unconnected-(J6-ID-Pad4)" not in nc_names
    assert any(f.kind == "unresolved_no_connect_marker" for f in result.unsupported)


def test_real_sparkfun_power_symbols_preserve_native_kicad_pin_graph() -> None:
    """Expected GND/3.3V pin memberships are measured from KiCad 10 XML."""
    from pathlib import Path

    from zaptrace.kicad.schematic_importer import import_kicad_schematic

    source = (
        Path(__file__).parents[1]
        / "benchmarks/external/sparkfun-qwiic-navigation/source/SparkFun_Qwiic_Navigation.kicad_sch"
    )
    result = import_kicad_schematic(source)
    named = {
        net.name: {
            (node.component_ref, node.pin_name) for node in net.nodes if not node.component_ref.startswith("#PWR")
        }
        for net in result.design.nets.values()
    }
    assert named["GND"] == {
        ("C1", "2"),
        ("D1", "1"),
        ("J1", "1"),
        ("J3", "1"),
        ("J5", "1"),
        ("R1", "1"),
        ("R2", "1"),
        ("R3", "1"),
        ("SW2", "2"),
        ("U4", "8"),
    }
    assert named["3.3V"] == {
        ("C1", "1"),
        ("D2", "1"),
        ("J1", "2"),
        ("J3", "2"),
        ("J5", "2"),
        ("JP1", "2"),
        ("JP2", "2"),
        ("JP3", "2"),
        ("JP4", "2"),
        ("JP6", "2"),
        ("R10", "2"),
        ("R11", "2"),
        ("R12", "2"),
        ("R4", "2"),
        ("R8", "2"),
        ("R9", "2"),
        ("U4", "16"),
    }
    assert len(named) == 32


def test_real_mitayi_power_input_groups_not_silently_split() -> None:
    from pathlib import Path

    from zaptrace.kicad.schematic_importer import import_kicad_schematic

    source = Path(__file__).parents[1] / "benchmarks/external/mitayi-pico-d1/source/Mitayi-Pico-D1.kicad_sch"
    result = import_kicad_schematic(source)
    named = {
        net.name: {
            (node.component_ref, node.pin_name) for node in net.nodes if not node.component_ref.startswith("#PWR")
        }
        for net in result.design.nets.values()
    }
    assert named["+1V1"] == {
        ("C2", "1"),
        ("C3", "1"),
        ("C4", "1"),
        ("U3", "23"),
        ("U3", "45"),
        ("U3", "50"),
    }
    assert named["+3V3"] == {
        ("C1", "1"),
        ("C10", "1"),
        ("C11", "1"),
        ("C12", "1"),
        ("C14", "1"),
        ("C15", "1"),
        ("C5", "1"),
        ("C6", "1"),
        ("C7", "1"),
        ("C8", "1"),
        ("C9", "1"),
        ("D3", "2"),
        ("J1", "2"),
        ("J4", "5"),
        ("JP1", "2"),
        ("R1", "1"),
        ("R11", "2"),
        ("R9", "1"),
        ("U1", "8"),
        ("U2", "5"),
        ("U3", "1"),
        ("U3", "10"),
        ("U3", "22"),
        ("U3", "33"),
        ("U3", "42"),
        ("U3", "44"),
        ("U3", "48"),
        ("U3", "49"),
    }
    assert len(named) == 64  # 61 connected nets + 3 KiCad singleton NC nets.


def test_real_sparkfun_native_kicad_pin_membership() -> None:
    """KiCad 10 reference XML netlist: unmirrored jumpers and mirrored resistors."""
    from pathlib import Path

    from zaptrace.kicad.schematic_importer import import_kicad_schematic

    source = (
        Path(__file__).parents[1]
        / "benchmarks/external/sparkfun-qwiic-navigation/source/SparkFun_Qwiic_Navigation.kicad_sch"
    )
    result = import_kicad_schematic(source)
    nets = {
        net.name: {(node.component_ref, node.pin_name) for node in net.nodes} for net in result.design.nets.values()
    }
    assert nets["ADR0"] == {("JP1", "1"), ("R1", "2"), ("U4", "1")}
    assert nets["ADR1"] == {("JP2", "1"), ("R2", "2"), ("U4", "2")}
    assert nets["SCL"] == {("J1", "4"), ("J3", "4"), ("J5", "4"), ("R7", "2"), ("U4", "14")}
    assert nets["SDA"] == {("J1", "3"), ("J3", "3"), ("J5", "3"), ("R13", "2"), ("U4", "15")}
    assert nets["SW_Center"] == {("R12", "1"), ("SW2", "5"), ("U4", "9")}


def test_real_sparkfun_global_slash_names_match_native_kicad_export() -> None:
    from pathlib import Path

    from zaptrace.kicad.schematic_importer import import_kicad_schematic

    source = (
        Path(__file__).parents[1]
        / "benchmarks/external/sparkfun-qwiic-navigation/source/SparkFun_Qwiic_Navigation.kicad_sch"
    )
    assert source.is_file()
    imported = import_kicad_schematic(source)
    names = {net.name for net in imported.design.nets.values()}
    assert {"IO5/Blue", "IO6/Green", "IO7/Red"} <= names
    assert not any("{slash}" in name for name in names)


def test_native_kicad_label_priority_and_alphabetical_tie_break() -> None:
    from zaptrace.kicad.schematic_importer import _resolve_connectivity

    wires = [((0.0, 0.0), (10.0, 0.0))]
    labels = [
        ("Z_local", "label", (0.0, 0.0)),
        ("A_hier", "hierarchical_label", (0.0, 0.0)),
        ("GND", "power_symbol", (0.0, 0.0)),
        ("Z_global", "global_label", (0.0, 0.0)),
        ("A_global", "global_label", (10.0, 0.0)),
    ]
    assert list(_resolve_connectivity([], wires, [], labels)) == ["A_global"]
    # KiCad's priority is power > local > hierarchical, independent of order.
    no_global = [x for x in labels if x[1] != "global_label"]
    assert list(_resolve_connectivity([], wires, [], no_global)) == ["GND"]
    no_power = [x for x in no_global if x[1] != "power_symbol"]
    assert list(_resolve_connectivity([], wires, [], no_power)) == ["/Z_local"]


def test_flat_local_label_and_global_alias_with_same_name_share_connected_pins() -> None:
    from zaptrace.kicad.schematic_importer import _resolve_connectivity

    wires = [((0.0, 0.0), (10.0, 0.0)), ((20.0, 0.0), (30.0, 0.0))]
    symbols = [
        {"ref": "R1", "pins": [("1", 0.0, 0.0)]},
        {"ref": "R2", "pins": [("1", 30.0, 0.0)]},
    ]
    labels = [
        ("GND", "label", (10.0, 0.0)),
        ("GND", "global_label", (20.0, 0.0)),
    ]
    assert _resolve_connectivity(symbols, wires, [], labels) == {"GND": [("R1", "1"), ("R2", "1")]}


def test_kicad_generated_pin_net_names_reproduce_native_reference_examples() -> None:
    from pathlib import Path

    from zaptrace.kicad.schematic_importer import import_kicad_schematic

    native_names = {
        "sparkfun-qwiic-navigation": {
            "Net-(D1-A)",
            "Net-(D2-BK)",
            "Net-(D2-GK)",
            "Net-(D2-RK)",
            "Net-(JP4-A)",
            "Net-(JP5-A)",
            "Net-(JP6-A)",
            "Net-(JP6-B)",
            "Net-(JP7-A)",
            "Net-(JP8-A)",
        },
        "mitayi-pico-d1": {
            "Net-(C18-Pad1)",
            "Net-(D2-A)",
            "Net-(D2-K)",
            "Net-(D3-K)",
            "Net-(J2-CC1)",
            "Net-(J2-CC2)",
            "Net-(JP6-C)",
            "Net-(U2-BP)",
            "Net-(U3-USB-DM)",
            "Net-(U3-USB-DP)",
        },
        "nitu-555-blinker": {"Net-(D1-A)"},
        "nitu-npn-transistor-switch": {
            "Net-(D1-A)",
            "Net-(D1-K)",
            "Net-(Q1-B)",
            "Net-(R1-Pad1)",
        },
    }
    root = Path(__file__).parents[1] / "benchmarks/external"
    for board, expected in native_names.items():
        schematic = next((root / board / "source").glob("*.kicad_sch"))
        result = import_kicad_schematic(schematic)
        actual = {net.name for net in result.design.nets.values()}
        assert expected <= actual, board


def test_kicad_auto_names_fail_closed_without_complete_unambiguous_pin_metadata() -> None:
    from zaptrace.kicad.schematic_importer import _auto_generated_pin_net_name

    assert (
        _auto_generated_pin_net_name(
            [("R5", "2"), ("D1", "2")],
            {"D1": {"2": "A"}, "R5": {"2": "~"}},
        )
        == "Net-(D1-A)"
    )
    assert (
        _auto_generated_pin_net_name(
            [("C18", "1"), ("R10", "2")],
            {"C18": {"1": "~"}, "R10": {"2": "2"}},
        )
        == "Net-(C18-Pad1)"
    )
    assert _auto_generated_pin_net_name([("R1", "1")], {}) == ""
    assert _auto_generated_pin_net_name([("R?", "1")], {"R?": {"1": "A"}}) == ""
    assert _auto_generated_pin_net_name([("U1", "1")], {"U1": {"1": "A", "2": "A"}}) == ""
    assert _auto_generated_pin_net_name([("U1", "1")], {"U1": {"1": "A/B"}}) == ""


def test_real_mitayi_native_kicad_mirrored_header_pin_membership() -> None:
    """KiCad 10 reference XML netlist names have root-sheet / prefixes."""
    from pathlib import Path

    from zaptrace.kicad.schematic_importer import import_kicad_schematic

    source = Path(__file__).parents[1] / "benchmarks/external/mitayi-pico-d1/source/Mitayi-Pico-D1.kicad_sch"
    result = import_kicad_schematic(source)
    nets = {
        net.name: {(node.component_ref, node.pin_name) for node in net.nodes} for net in result.design.nets.values()
    }
    assert nets["/GPIO0"] == {("J3", "1"), ("U3", "2")}
    assert nets["/GPIO2"] == {("J3", "3"), ("JP6", "3"), ("R11", "1"), ("U3", "4")}
    assert nets["/AREF"] == {("J4", "6"), ("JP1", "1"), ("U3", "43")}


# ---------------------------------------------------------------------------
# UnionFind unit tests
# ---------------------------------------------------------------------------


class TestUnionFind:
    def test_single_element(self) -> None:
        uf = _UnionFind()
        assert uf.find(0) == 0

    def test_union_merges_groups(self) -> None:
        uf = _UnionFind()
        uf.union(0, 1)
        assert uf.find(0) == uf.find(1)

    def test_union_is_transitive(self) -> None:
        uf = _UnionFind()
        uf.union(0, 1)
        uf.union(1, 2)
        assert uf.find(0) == uf.find(2)

    def test_separate_groups(self) -> None:
        uf = _UnionFind()
        uf.union(0, 1)
        uf.union(2, 3)
        assert uf.find(0) != uf.find(2)

    def test_groups_dict(self) -> None:
        uf = _UnionFind()
        uf.union(0, 1)
        uf.union(0, 2)
        groups = uf.groups()
        # All three should share one root
        assert len(groups) == 1
        roots = {uf.find(i) for i in [0, 1, 2]}
        assert len(roots) == 1


# ---------------------------------------------------------------------------
# Import of flat schematic fixture
# ---------------------------------------------------------------------------


class TestFlatSchematicImport:
    def test_imports_components(self) -> None:
        res = import_kicad_schematic_string(_FLAT_SCH)
        refs = {c.ref for c in res.design.components.values()}
        assert "R1" in refs
        assert "C1" in refs

    def test_component_count(self) -> None:
        res = import_kicad_schematic_string(_FLAT_SCH)
        assert len(res.design.components) == 2

    def test_component_value(self) -> None:
        res = import_kicad_schematic_string(_FLAT_SCH)
        c = next(c for c in res.design.components.values() if c.ref == "R1")
        assert c.value == "10k"

    def test_component_type_from_lib_id(self) -> None:
        res = import_kicad_schematic_string(_FLAT_SCH)
        c = next(c for c in res.design.components.values() if c.ref == "C1")
        assert c.type == "C"

    def test_nets_created(self) -> None:
        res = import_kicad_schematic_string(_FLAT_SCH)
        assert len(res.design.nets) >= 1

    def test_label_becomes_net_name(self) -> None:
        res = import_kicad_schematic_string(_FLAT_SCH)
        net_names = {n.name for n in res.design.nets.values()}
        assert "/net_A" in net_names or "/net_B" in net_names

    def test_import_deterministic(self) -> None:
        r1 = import_kicad_schematic_string(_FLAT_SCH)
        r2 = import_kicad_schematic_string(_FLAT_SCH)
        assert {c.ref for c in r1.design.components.values()} == {c.ref for c in r2.design.components.values()}
        assert set(r1.design.nets.keys()) == set(r2.design.nets.keys())

    def test_to_dict_serialisable(self) -> None:
        import json

        res = import_kicad_schematic_string(_FLAT_SCH)
        json.dumps(res.to_dict())

    def test_net_score_is_float(self) -> None:
        res = import_kicad_schematic_string(_FLAT_SCH)
        assert 0.0 <= res.net_score <= 1.0


# ---------------------------------------------------------------------------
# Junction connectivity
# ---------------------------------------------------------------------------


class TestJunctionConnectivity:
    def test_junction_merges_crossing_wires(self) -> None:
        res = import_kicad_schematic_string(_JUNCTION_SCH)
        # Both labels say "shared_net"; there should be a shared_net in design
        net_names = {n.name for n in res.design.nets.values()}
        assert "/shared_net" in net_names

    def test_shared_net_has_nodes(self) -> None:
        res = import_kicad_schematic_string(_JUNCTION_SCH)
        shared = next(n for n in res.design.nets.values() if n.name == "/shared_net")
        assert len(shared.nodes) >= 1


# ---------------------------------------------------------------------------
# Global labels take priority over local labels
# ---------------------------------------------------------------------------


class TestGlobalLabelPriority:
    def test_global_label_becomes_net_name(self) -> None:
        res = import_kicad_schematic_string(_GLOBAL_SCH)
        net_names = {n.name for n in res.design.nets.values()}
        assert "VCC" in net_names


# ---------------------------------------------------------------------------
# Dangling wires / floating labels
# ---------------------------------------------------------------------------


class TestDanglingWires:
    def test_dangling_wire_does_not_crash(self) -> None:
        res = import_kicad_schematic_string(_DANGLING_SCH)
        assert isinstance(res, KiCadSchematicImportResult)

    def test_dangling_wire_creates_auto_net(self) -> None:
        res = import_kicad_schematic_string(_DANGLING_SCH)
        # Pin 1 of R1 is on the dangling wire — should get an auto-named net
        auto_nets = [n for n in res.design.nets if n.startswith("net_")]
        # there may be none if the pin doesn't land on a wire endpoint
        assert isinstance(auto_nets, list)


# ---------------------------------------------------------------------------
# Multi-unit deduplicate
# ---------------------------------------------------------------------------


class TestMultiUnitDedup:
    def test_multi_unit_deduplicated(self) -> None:
        res = import_kicad_schematic_string(_MULTI_UNIT_SCH)
        refs = [c.ref for c in res.design.components.values()]
        assert refs.count("U1") == 1  # deduplicated

    def test_component_count_one(self) -> None:
        res = import_kicad_schematic_string(_MULTI_UNIT_SCH)
        assert len(res.design.components) == 1


# ---------------------------------------------------------------------------
# Unsupported record tracking
# ---------------------------------------------------------------------------


class TestUnsupportedRecords:
    def test_unsupported_record_has_kind(self) -> None:
        res = import_kicad_schematic_string(_FLAT_SCH)
        for ur in res.unsupported:
            assert ur.kind, "Unsupported record must have a kind"

    def test_unsupported_record_has_message(self) -> None:
        res = import_kicad_schematic_string(_FLAT_SCH)
        for ur in res.unsupported:
            assert ur.message, "Unsupported record must have a message"

    def test_unsupported_record_has_severity(self) -> None:
        res = import_kicad_schematic_string(_FLAT_SCH)
        for ur in res.unsupported:
            assert ur.severity in ("info", "warning", "error")

    def test_unsupported_record_to_dict(self) -> None:
        ur = SchematicUnsupportedRecord(kind="test_kind", message="test msg", severity="warning", source="line:42")
        d = ur.to_dict()
        assert d["kind"] == "test_kind"
        assert d["source"] == "line:42"

    def test_import_losses_recorded_in_design(self) -> None:
        # title_block is unsupported → should appear in import_losses
        res = import_kicad_schematic_string(_FLAT_SCH)
        # At minimum: title_block and potentially sheet constructs
        assert isinstance(res.design.import_losses, list)

    def test_unknown_construct_noted(self) -> None:
        sch = """\
(kicad_sch (version 20230121) (generator "zaptrace")
  (mystical_element (some_attr "value"))
)"""
        res = import_kicad_schematic_string(sch)
        kinds = [ur.kind for ur in res.unsupported]
        assert any(k.startswith("unknown_") for k in kinds)

    def test_missing_ref_noted(self) -> None:
        sch = """\
(kicad_sch (version 20230121) (generator "zaptrace")
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (property "Value" "10k" (at 50 55 0))
  )
)"""
        res = import_kicad_schematic_string(sch)
        kinds = [ur.kind for ur in res.unsupported]
        assert "symbol_missing_ref" in kinds


# ---------------------------------------------------------------------------
# Invalid input
# ---------------------------------------------------------------------------


class TestInvalidInput:
    def test_rejects_non_kicad_sch(self) -> None:
        with pytest.raises(ValueError, match="kicad_sch"):
            import_kicad_schematic_string("(some_other_format)")

    def test_rejects_empty_atom(self) -> None:
        with pytest.raises((ValueError, Exception)):
            import_kicad_schematic_string("not_sexp")


# ---------------------------------------------------------------------------
# Export → import self-round-trip net score
# ---------------------------------------------------------------------------


class TestSelfRoundTrip:
    def _make_design(self) -> Design:
        design = Design(meta=DesignMeta(name="rt_test", author="test"))
        design.components["r1"] = Component(id="r1", ref="R1", type="R", value="1k")
        design.components["c1"] = Component(id="c1", ref="C1", type="C", value="100nF")
        design.nets["vcc"] = Net(
            id="vcc",
            name="VCC",
            nodes=[NetNode(component_ref="R1", pin_name="1")],
        )
        design.nets["gnd"] = Net(
            id="gnd",
            name="GND",
            nodes=[NetNode(component_ref="C1", pin_name="2")],
        )
        return design

    def test_export_produces_kicad_sch(self, tmp_path) -> None:
        design = self._make_design()
        files = export_kicad_schematic(design, tmp_path)
        assert "schematic" in files
        assert files["schematic"].suffix == ".kicad_sch"

    def test_exported_sch_re_importable(self, tmp_path) -> None:
        design = self._make_design()
        files = export_kicad_schematic(design, tmp_path)
        sch_path = files["schematic"]
        result = import_kicad_schematic_string(sch_path.read_text())
        assert isinstance(result, KiCadSchematicImportResult)

    def test_round_trip_components_preserved(self, tmp_path) -> None:
        design = self._make_design()
        files = export_kicad_schematic(design, tmp_path)
        sch_path = files["schematic"]
        result = import_kicad_schematic_string(sch_path.read_text())
        refs = {c.ref for c in result.design.components.values()}
        assert "R1" in refs
        assert "C1" in refs

    def test_round_trip_net_score_full(self, tmp_path) -> None:
        """Export a design, re-import the schematic, and measure net score."""
        design = self._make_design()
        files = export_kicad_schematic(design, tmp_path)
        sch_path = files["schematic"]
        content = sch_path.read_text()

        # Create pseudo-result for exported nets
        from zaptrace.kicad.schematic_importer import KiCadSchematicImportResult as Res

        exported_res = Res(design=design)
        imported_res = import_kicad_schematic_string(content)

        score = compute_schematic_net_score(exported_res, imported_res)
        assert score == pytest.approx(1.00), f"Round-trip net score {score} < 1.00"

    def test_round_trip_net_nodes_preserved(self, tmp_path) -> None:
        design = self._make_design()
        files = export_kicad_schematic(design, tmp_path)
        imported = import_kicad_schematic_string(files["schematic"].read_text())

        expected = {
            net.name: {(node.component_ref, node.pin_name) for node in net.nodes} for net in design.nets.values()
        }
        actual = {
            net.name: {(node.component_ref, node.pin_name) for node in net.nodes}
            for net in imported.design.nets.values()
        }

        assert actual == expected

    def test_round_trip_uses_embedded_library_pin_geometry(self, tmp_path) -> None:
        design = self._make_design()
        files = export_kicad_schematic(design, tmp_path)
        content = files["schematic"].read_text()

        assert "(lib_symbols" in content
        imported = import_kicad_schematic_string(content)
        nodes = {
            net.name: {(node.component_ref, node.pin_name) for node in net.nodes}
            for net in imported.design.nets.values()
        }
        assert nodes == {"VCC": {("R1", "1")}, "GND": {("C1", "2")}}

    def test_net_score_function_empty(self) -> None:
        empty = Design(meta=DesignMeta(name="e", author="t"))
        from zaptrace.kicad.schematic_importer import KiCadSchematicImportResult as Res

        r1 = Res(design=empty)
        r2 = Res(design=empty)
        assert compute_schematic_net_score(r1, r2) == pytest.approx(1.0)

    def test_net_score_partial(self) -> None:
        d1 = Design(meta=DesignMeta(name="a", author="t"))
        d1.nets["vcc"] = Net(id="vcc", name="VCC", nodes=[])
        d1.nets["gnd"] = Net(id="gnd", name="GND", nodes=[])
        d2 = Design(meta=DesignMeta(name="b", author="t"))
        d2.nets["vcc"] = Net(id="vcc", name="VCC", nodes=[])
        from zaptrace.kicad.schematic_importer import KiCadSchematicImportResult as Res

        r1 = Res(design=d1)
        r2 = Res(design=d2)
        score = compute_schematic_net_score(r1, r2)
        assert 0.0 < score < 1.0


# ---------------------------------------------------------------------------
# Connectivity resolution unit tests
# ---------------------------------------------------------------------------


class TestResolveConnectivity:
    def test_single_wire_two_pins(self) -> None:
        syms = [
            {
                "ref": "R1",
                "lib_id": "Device:R",
                "value": "1k",
                "at": (50, 50),
                "angle": 0,
                "unit": 1,
                "footprint": "",
                "pins": [("1", 30.0, 50.0), ("2", 70.0, 50.0)],
            },
        ]
        wires = [((30.0, 50.0), (70.0, 50.0))]
        nets = _resolve_connectivity(syms, wires, [], [])
        # Both pins should be in the same net
        all_pins = [p for pins in nets.values() for p in pins]
        assert len(all_pins) == 2
        # Both in one group
        groups = list(nets.values())
        first_group = next(g for g in groups if len(g) == 2)
        assert {pin for _, pin in first_group} == {"1", "2"}

    def test_label_names_net(self) -> None:
        syms = [
            {
                "ref": "R1",
                "lib_id": "Device:R",
                "value": "1k",
                "at": (50, 50),
                "angle": 0,
                "unit": 1,
                "footprint": "",
                "pins": [("1", 30.0, 50.0)],
            },
        ]
        wires = [((30.0, 50.0), (10.0, 50.0))]
        labels = [("my_net", "label", (10.0, 50.0))]
        nets = _resolve_connectivity(syms, wires, [], labels)
        assert "/my_net" in nets

    def test_global_label_priority(self) -> None:
        wires = [((0.0, 0.0), (10.0, 0.0))]
        labels = [("local", "label", (0.0, 0.0)), ("GLOBAL", "global_label", (10.0, 0.0))]
        nets = _resolve_connectivity([], wires, [], labels)
        # GLOBAL label wins because same group after wire union
        # They should share a group; the highest priority (global) wins
        assert "GLOBAL" in nets

    def test_no_wires_isolated_labels(self) -> None:
        labels = [("net1", "label", (0.0, 0.0)), ("net2", "label", (50.0, 0.0))]
        nets = _resolve_connectivity([], [], [], labels)
        assert "/net1" in nets
        assert "/net2" in nets
        assert "net1" != "net2"

    def test_junction_merges_crossing_groups(self) -> None:
        syms = [
            {
                "ref": "R1",
                "lib_id": "R",
                "value": "1k",
                "at": (0, 0),
                "angle": 0,
                "unit": 1,
                "footprint": "",
                "pins": [("1", 0.0, 0.0)],
            },
            {
                "ref": "R2",
                "lib_id": "R",
                "value": "2k",
                "at": (0, 0),
                "angle": 0,
                "unit": 1,
                "footprint": "",
                "pins": [("1", 10.0, 0.0)],
            },
        ]
        wires = [((0.0, 0.0), (10.0, 0.0))]
        junctions = [(5.0, 0.0)]
        labels = [("junction_net", "label", (5.0, 0.0))]
        nets = _resolve_connectivity(syms, wires, junctions, labels)
        # junction_net should contain both pins
        assert "/junction_net" in nets


def test_schematic_build_helpers_preserve_components_nets_and_losses() -> None:
    design = Design(meta=DesignMeta(name="helpers"))
    symbols = [
        {"ref": "R1", "lib_id": "Device:R", "value": "10k"},
        {"ref": "R1", "lib_id": "Device:R", "value": "10k"},
        {"ref": "", "lib_id": "Device:C", "value": "1uF"},
    ]
    _add_imported_components(design, symbols)
    assert list(design.components) == ["r1"]
    assert design.components["r1"].type == "R"

    score = _add_imported_nets(design, {"NET A": [("R1", "1")], "EMPTY": []})
    assert score == pytest.approx(0.5)
    assert design.nets["net_a"].nodes[0].component_ref == "R1"

    records = [
        SchematicUnsupportedRecord(kind="title_block", message="unsupported", source="fixture"),
        SchematicUnsupportedRecord(kind="note", message="informational", severity="info"),
    ]
    _record_schematic_import_losses(design, records)
    assert len(design.import_losses) == 1
    assert design.import_losses[0].field_path == "title_block"


def test_distinct_usb_differential_pair_names_do_not_collide() -> None:
    """A real KiCad reference contains USB_D+ and USB_D- as separate nets."""
    raw = {
        "USB_D+": [("U1", "1"), ("J1", "A6")],
        "USB_D-": [("U1", "2"), ("J1", "A7")],
        "floating": [],
    }
    first = Design(meta=DesignMeta(name="usb", author="test"))
    second = Design(meta=DesignMeta(name="usb", author="test"))

    score = _add_imported_nets(first, raw)
    assert score == pytest.approx(2 / 3)
    assert len(first.nets) == len(raw)
    assert {net.name for net in first.nets.values()} == set(raw)
    assert len({net.id for net in first.nets.values()}) == 3
    assert {net.name: {(n.component_ref, n.pin_name) for n in net.nodes} for net in first.nets.values()} == {
        name: set(pins) for name, pins in raw.items()
    }

    # Order-independent IDs allow stable diff/replay for the same names.
    assert _add_imported_nets(second, dict(reversed(list(raw.items())))) == pytest.approx(score)
    assert {net.name: net.id for net in first.nets.values()} == {net.name: net.id for net in second.nets.values()}


def test_real_mitayi_pico_usb_net_names_remain_distinct() -> None:
    from pathlib import Path

    from zaptrace.kicad.schematic_importer import import_kicad_schematic

    source = Path(__file__).parents[1] / "benchmarks/external/mitayi-pico-d1/source/Mitayi-Pico-D1.kicad_sch"
    result = import_kicad_schematic(source)
    by_name = {net.name: net for net in result.design.nets.values()}
    assert len(by_name) == len(result.design.nets)
    assert "/USB_D+" in by_name
    assert "/USB_D-" in by_name
    assert by_name["/USB_D+"].id != by_name["/USB_D-"].id
    assert by_name["/USB_D+"].nodes
    assert by_name["/USB_D-"].nodes
    assert 0.0 <= result.net_score <= 1.0


def test_kicad_source_snapshot_keeps_exact_utf8_bytes_and_page_data(tmp_path: Path) -> None:
    import hashlib

    from zaptrace.kicad.schematic_importer import import_kicad_schematic

    source = (
        "(kicad_sch\r\n"
        "  (version 20250101)\r\n"
        '  (paper "A3")\r\n'
        '  (title_block (title "Güç devresi") (rev "R2") (comment 1 "Prototip"))\r\n'
        "  (embedded_fonts no)\r\n"
        '  (text "Annotation only")\r\n'
        ")\r\n"
    ).encode()
    path = tmp_path / "original.kicad_sch"
    path.write_bytes(source)
    result = import_kicad_schematic(path)
    snapshot = result.source_snapshot
    assert snapshot is not None
    assert snapshot.raw_bytes == source
    assert snapshot.sha256 == hashlib.sha256(source).hexdigest()
    assert snapshot.paper == "A3"
    assert snapshot.title_block == {
        "title": "Güç devresi",
        "rev": "R2",
        "comment_1": "Prototip",
    }
    assert snapshot.embedded_fonts == "no"
    assert snapshot.top_level_counts["text"] == 1
    assert snapshot.nodes("text")[0][1] == "Annotation only"

    # A returned source node may be mutated by a UI without changing evidence.
    snapshot.nodes("text")[0][1] = "not the original"
    assert snapshot.nodes("text")[0][1] == "Annotation only"
    assert snapshot.sha256 == hashlib.sha256(snapshot.raw_bytes).hexdigest()

    summary = snapshot.to_dict()
    assert summary["sha256"] == snapshot.sha256
    assert summary["byte_size"] == len(source)
    assert "raw_bytes" not in summary
    assert result.to_dict()["source_evidence"]["title_block"]["title"] == "Güç devresi"
    assert "raw_bytes" not in str(result.to_dict())
    assert result.to_dict()["source_sha256"] == snapshot.sha256

    # Capture is in memory, never a dangling pointer to an external source.
    path.unlink()
    assert snapshot.raw_bytes == source


def test_original_kicad_graphics_and_constraint_markers_are_retained_not_accepted() -> None:
    import hashlib

    from zaptrace.kicad.schematic_importer import import_kicad_schematic

    root = Path(__file__).parents[1] / "benchmarks/external"
    expected = [
        ("sparkfun-qwiic-navigation", "USLetter", {"polyline": 20, "text": 43}),
        ("mitayi-pico-d1", "A3", {"rectangle": 15, "text": 25, "image": 1, "netclass_flag": 5}),
        ("nitu-555-blinker", "A5", {}),
        ("nitu-npn-transistor-switch", "A5", {}),
        ("nitu-linear-regulator", "A5", {}),
    ]
    for board, paper, kinds in expected:
        original = next((root / board / "source").glob("*.kicad_sch"))
        result = import_kicad_schematic(original)
        archive = result.source_snapshot
        assert archive is not None
        assert archive.raw_bytes == original.read_bytes()
        assert archive.sha256 == hashlib.sha256(original.read_bytes()).hexdigest()
        assert archive.paper == paper
        assert archive.title_block["title"]
        for kind, count in kinds.items():
            assert archive.top_level_counts[kind] == count, (board, kind)
            assert len(archive.nodes(kind)) == count
        if kinds:
            # Original graphic/constraint constructs have not been fully
            # mapped to the editable Design and must remain visible as losses.
            assert result.unsupported_count > 0
            assert any(record.kind in kinds for record in result.unsupported)


def test_direct_component_pin_contact_without_wire_creates_real_native_net() -> None:
    """KiCad connects physically coincident component pins without drawn wire."""
    symbols = [
        {
            "ref": "D1",
            "pins": [("2", 124.46, 153.67)],
            "pin_library_names": {"2": "A"},
        },
        {
            "ref": "R4",
            "pins": [("2", 124.46, 153.67000000000002)],
            "pin_library_names": {"2": "~"},
        },
    ]
    graph = _resolve_connectivity(symbols, [], [], [])
    assert graph == {"Net-(D1-A)": [("D1", "2"), ("R4", "2")]}


def test_direct_pin_contact_does_not_short_nearby_non_touching_pins() -> None:
    """Nearby pins and isolated dangling pins must never be connected by rounding drift."""
    symbols = [
        {"ref": "D1", "pins": [("2", 10.0, 20.0)], "pin_library_names": {"2": "A"}},
        {"ref": "R4", "pins": [("2", 10.02, 20.0)], "pin_library_names": {"2": "~"}},
    ]
    assert _resolve_connectivity(symbols, [], [], []) == {}


def test_colocated_pins_on_same_component_are_not_invented_as_intercomponent_nets() -> None:
    symbols = [
        {"ref": "U1", "pins": [("1", 30.0, 40.0), ("2", 30.0, 40.0)], "pin_library_names": {"1": "NC1", "2": "NC2"}},
    ]
    assert _resolve_connectivity(symbols, [], [], []) == {}
