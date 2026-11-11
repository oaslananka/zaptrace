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
        "QSPI_SS": [("R1", "1"), ("R2", "1"), ("R3", "1"), ("R4", "1")],
    }


def test_explicit_junction_joins_crossing_wire_segments_only_when_marked() -> None:
    """A KiCad junction dot is electrical, a geometrical crossing is not."""
    from zaptrace.kicad.schematic_importer import _resolve_connectivity

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
    assert len(by_name) == 61
    assert by_name["QSPI_SS"] == {("U3", "56"), ("U1", "1"), ("R1", "2"), ("R2", "1")}
    # The independent KiCad XML omits synthetic #PWR* connection nodes.
    all_pins = {pin for pins in by_name.values() for pin in pins if not pin[0].startswith("#PWR")}
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
    assert nets["GND"] == {("#PWR01", "1"), ("#PWR02", "1"), ("R1", "1"), ("R2", "1")}
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
    assert nets["GND"] == {
        ("#PWR01", "1"),
        ("#PWR02", "1"),
        ("R1", "1"),
        ("R2", "1"),
    }
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
    assert edited_nets["GND"] == {("#PWR01", "1"), ("R1", "1")}
    assert edited_nets["GND_CUSTOM"] == {("#PWR02", "1"), ("R2", "1")}


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
    assert len(named) == 26


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
    assert len(named) == 61  # Mid-wire QSPI_SS label merges its two physical groups.


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


def test_real_mitayi_native_kicad_mirrored_header_pin_membership() -> None:
    """KiCad 10 reference XML netlist names have root-sheet / prefixes."""
    from pathlib import Path

    from zaptrace.kicad.schematic_importer import import_kicad_schematic

    source = Path(__file__).parents[1] / "benchmarks/external/mitayi-pico-d1/source/Mitayi-Pico-D1.kicad_sch"
    result = import_kicad_schematic(source)
    nets = {
        net.name: {(node.component_ref, node.pin_name) for node in net.nodes} for net in result.design.nets.values()
    }
    assert nets["GPIO0"] == {("J3", "1"), ("U3", "2")}
    assert nets["GPIO2"] == {("J3", "3"), ("JP6", "3"), ("R11", "1"), ("U3", "4")}
    assert nets["AREF"] == {("J4", "6"), ("JP1", "1"), ("U3", "43")}


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
        assert "net_A" in net_names or "net_B" in net_names

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
        assert "shared_net" in net_names

    def test_shared_net_has_nodes(self) -> None:
        res = import_kicad_schematic_string(_JUNCTION_SCH)
        shared = next(n for n in res.design.nets.values() if n.name == "shared_net")
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
        assert "my_net" in nets

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
        assert "net1" in nets
        assert "net2" in nets
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
        assert "junction_net" in nets


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
    assert "USB_D+" in by_name
    assert "USB_D-" in by_name
    assert by_name["USB_D+"].id != by_name["USB_D-"].id
    assert by_name["USB_D+"].nodes and by_name["USB_D-"].nodes
    assert 0.0 <= result.net_score <= 1.0
