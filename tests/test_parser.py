"""Tests for YAML design parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zaptrace.core.exceptions import ParseError
from zaptrace.core.models import (
    Design,
    NetClass,
)
from zaptrace.core.parser import (
    dump_file,
    dump_json,
    dump_str,
    generate_json_schema,
    parse_file,
    parse_str,
    write_json_schema,
)

_VALID_DESIGN_YAML = """
meta:
  name: TestDesign
  version: "1.0"
  author: tester
components:
  r1:
    ref: R1
    type: resistor
    value: 10k
  u1:
    ref: U1
    type: mcu
    pins:
      VCC: power
      GND: power
      TX: output
nets:
  vcc:
    name: VCC
    type: power
    nodes:
      - R1.pin1
      - U1.VCC
board:
  width_mm: 50
  height_mm: 40
  layers: 2
blocks:
  - id: b1
    name: Power
    components: [r1]
"""

_INVALID_YAML = """
meta:
  name: Bad
components: not_a_dict
"""

_EMPTY_NET_NAME = """
meta:
  name: BadNet
components:
  r1:
    ref: R1
    type: resistor
nets:
  n1:
    id: n1
    name: "  "
"""

_EXTENDED_YAML = """
meta:
  name: ExtendedDesign
components:
  c1:
    ref: C1
    type: capacitor
    dnp: true
    variants:
      v1: true
      v2: false
    lcsc_id: "C12345"
nets:
  n1:
    name: USB_D_P
    type: differential
    constraints:
      impedance_target: 90.0
      length_match_group: "usb"
      max_length_mm: 50.0
"""


class TestParseStr:
    def test_valid_design(self) -> None:
        design = parse_str(_VALID_DESIGN_YAML)
        assert isinstance(design, Design)
        assert design.meta.name == "TestDesign"
        assert len(design.components) == 2
        assert len(design.nets) == 1
        assert len(design.blocks) == 1
        assert design.board.width_mm == 50.0

    def test_component_pins_parsed(self) -> None:
        design = parse_str(_VALID_DESIGN_YAML)
        u1 = design.components["u1"]
        assert len(u1.pins) == 3
        assert u1.pins["VCC"].type.value == "power"

    def test_pin_mapping_key_is_authoritative_name(self) -> None:
        design = parse_str(
            """
meta: {name: PinNames}
components:
  u1:
    ref: U1
    type: mcu
    pins:
      VCC: {name: wrong, type: power}
"""
        )
        assert design.components["u1"].pins["VCC"].name == "VCC"

    def test_net_nodes_string_format(self) -> None:
        design = parse_str(_VALID_DESIGN_YAML)
        net = design.nets["vcc"]
        assert len(net.nodes) == 2
        assert net.nodes[0].component_ref == "R1"

    def test_invalid_yaml_syntax(self) -> None:
        with pytest.raises(ParseError, match="YAML syntax error"):
            parse_str("{{{broken", source="test")

    def test_not_a_mapping(self) -> None:
        with pytest.raises(ParseError, match="must be a YAML mapping"):
            parse_str("[1, 2, 3]", source="test")

    def test_invalid_structure(self) -> None:
        with pytest.raises(ParseError):
            parse_str(_INVALID_YAML, source="test")

    def test_empty_net_name_validation(self) -> None:
        with pytest.raises(ParseError):
            parse_str(_EMPTY_NET_NAME, source="test")

    def test_unknown_keys_ignored(self) -> None:
        yaml = _VALID_DESIGN_YAML + "extra_field: true\n"
        design = parse_str(yaml, source="test")
        assert design.meta.name == "TestDesign"

    def test_extended_fields_parsed(self) -> None:
        design = parse_str(_EXTENDED_YAML, source="test")

        c1 = design.components["c1"]
        assert c1.dnp is True
        assert c1.variants == {"v1": True, "v2": False}
        assert c1.lcsc_id == "C12345"

        n1 = design.nets["n1"]
        assert n1.constraints is not None
        assert n1.constraints.impedance_target == 90.0
        assert n1.constraints.length_match_group == "usb"
        assert n1.constraints.max_length_mm == 50.0


class TestParseFile:
    def test_file_not_found(self) -> None:
        with pytest.raises(ParseError, match="Cannot read"):
            parse_file(Path("/nonexistent/design.yaml"))

    def test_parse_valid_file(self, tmp_path: Path) -> None:
        f = tmp_path / "design.yaml"
        f.write_text(_VALID_DESIGN_YAML, encoding="utf-8")
        design = parse_file(f)
        assert design.meta.name == "TestDesign"


_SCHEMA_V1_YAML = """
meta:
  name: SchemaV1Test
  version: "1.0"
  author: tester
components:
  u1:
    ref: U1
    type: mcu
    value: ESP32-C3
    manufacturer: Espressif
    mpn: ESP32-C3-M1
    lifecycle: active
    dnp: false
    variants:
      prod: true
      test: false
    pins:
      VCC: {type: power, description: "3.3V supply"}
      GND: {type: power}
      TX: {type: output}
      RX: {type: input}
  c1:
    ref: C1
    type: capacitor
    value: 100nF
    voltage_rating: 16.0
    footprint: "0402"
    lcsc_id: "C12345"
    basic_part: true
    stock: 5000
nets:
  vcc:
    name: VCC
    type: power
    nodes:
      - U1.VCC
      - C1.pin1
  uart_tx:
    name: TX
    type: signal
    constraints:
      max_length_mm: 100.0
board:
  width_mm: 50.0
  height_mm: 40.0
  layers: 2
board_def:
  width: 50.0
  height: 40.0
  layers: 2
  outline: [[0, 0], [50, 0], [50, 40], [0, 40]]
  mounting_holes:
    - position: [2.5, 2.5]
      diameter: 3.0
      plated: true
  constraints:
    min_trace: 0.15
    min_clearance: 0.15
placement:
  u1: [10.0, 20.0]
  c1: [30.0, 20.0]
net_classes:
  vcc: power_low
  uart_tx: signal_low
"""


class TestSchemaV1:
    def test_parse_board_def(self) -> None:
        d = parse_str(_SCHEMA_V1_YAML)
        assert d.board_def is not None
        assert d.board_def.width == 50.0
        assert d.board_def.height == 40.0
        assert len(d.board_def.outline) == 4
        assert len(d.board_def.mounting_holes) == 1
        assert d.board_def.mounting_holes[0].diameter == 3.0
        assert d.board_def.constraints.min_trace == 0.15

    def test_parse_placement(self) -> None:
        d = parse_str(_SCHEMA_V1_YAML)
        assert d.placement is not None
        assert d.placement["u1"] == (10.0, 20.0)

    def test_parse_net_classes(self) -> None:
        d = parse_str(_SCHEMA_V1_YAML)
        assert d.net_classes is not None
        assert d.net_classes["vcc"] == NetClass.POWER_LOW

    def test_parse_component_extended_fields(self) -> None:
        d = parse_str(_SCHEMA_V1_YAML)
        c1 = d.components["c1"]
        assert c1.voltage_rating == 16.0
        assert c1.lcsc_id == "C12345"
        assert c1.basic_part is True
        assert c1.stock == 5000

    def test_parse_net_constraints(self) -> None:
        d = parse_str(_SCHEMA_V1_YAML)
        n = d.nets["uart_tx"]
        assert n.constraints is not None
        assert n.constraints.max_length_mm == 100.0

    def test_round_trip(self) -> None:
        d1 = parse_str(_SCHEMA_V1_YAML)
        yaml_out = dump_str(d1)
        d2 = parse_str(yaml_out)
        assert d2.meta.name == d1.meta.name
        assert len(d2.components) == len(d1.components)
        assert len(d2.nets) == len(d1.nets)
        assert d2.board_def is not None
        assert len(d2.board_def.outline) == len(d1.board_def.outline)
        assert d2.placement is not None
        assert d2.placement["u1"] == d1.placement["u1"]
        assert d2.net_classes is not None
        assert d2.net_classes["vcc"] == d1.net_classes["vcc"]

    def test_round_trip_full_v1(self, tmp_path: Path) -> None:
        f = tmp_path / "design_v1.yaml"
        f.write_text(_SCHEMA_V1_YAML, encoding="utf-8")
        d1 = parse_file(f)
        yaml_out = dump_str(d1)
        d2 = parse_str(yaml_out)
        assert d2.model_dump(exclude_none=True) == d1.model_dump(exclude_none=True)

    def test_round_trip_routing(self) -> None:
        yaml_with_routing = (
            _SCHEMA_V1_YAML
            + """
routing:
  traces:
    - layer: F.Cu
      start: [10.0, 20.0]
      end: [30.0, 20.0]
      width: 0.2
      net_id: vcc
    - layer: F.Cu
      start: [30.0, 20.0]
      end: [10.0, 20.0]
      width: 0.2
      net_id: uart_tx
  vias:
    - [15.0, 20.0, 0.45, 0.2]
    - [18.0, 21.0, 0.45, 0.2, uart_tx]
  layers_used: [F.Cu]
  total_trace_length_mm: 40.0
  net_count: 2
  routed_net_count: 2
"""
        )
        d1 = parse_str(yaml_with_routing)
        assert d1.routing is not None
        assert len(d1.routing.traces) == 2
        assert d1.routing.vias == [(15.0, 20.0, 0.45, 0.2), (18.0, 21.0, 0.45, 0.2, "uart_tx")]
        yaml_out = dump_str(d1)
        d2 = parse_str(yaml_out)
        assert d2.routing is not None
        assert len(d2.routing.traces) == len(d1.routing.traces)
        assert d2.routing.vias == d1.routing.vias

    def test_round_trip_copper_pours(self) -> None:
        yaml_with_pours = (
            _SCHEMA_V1_YAML
            + """
copper_pours:
  gnd_top:
    layer: F.Cu
    net_id: GND
    polygon: [[5, 5], [45, 5], [45, 35], [5, 35]]
"""
        )
        d1 = parse_str(yaml_with_pours)
        assert len(d1.copper_pours) == 1
        yaml_out = dump_str(d1)
        d2 = parse_str(yaml_out)
        assert len(d2.copper_pours) == 1
        pid = list(d2.copper_pours.keys())[0]
        assert len(d2.copper_pours[pid].polygon) == 4

    def test_dump_json(self) -> None:
        d = parse_str(_SCHEMA_V1_YAML)
        json_str = dump_json(d)
        data = json.loads(json_str)
        assert data["meta"]["name"] == "SchemaV1Test"
        assert "board_def" in data

    def test_generate_json_schema(self) -> None:
        schema = generate_json_schema()
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert "properties" in schema
        assert "meta" in schema["properties"]
        assert "components" in schema["properties"]
        assert "nets" in schema["properties"]
        assert "board_def" in schema["properties"]

    def test_write_json_schema(self, tmp_path: Path) -> None:
        from zaptrace.core.parser import write_json_schema

        p = tmp_path / "design-schema.json"
        write_json_schema(p)
        assert p.exists()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["title"] == "ZapTrace Design"

    def test_dump_file_round_trip(self, tmp_path: Path) -> None:
        d1 = parse_str(_SCHEMA_V1_YAML)
        p = tmp_path / "roundtrip.yaml"
        dump_file(d1, p)
        d2 = parse_file(p)
        assert d2.meta.name == d1.meta.name
        assert d2.board_def is not None

    def test_round_trip_drc_result(self) -> None:
        yaml_with_drc = (
            _SCHEMA_V1_YAML
            + """
drc_result:
  design_name: SchemaV1Test
  total_violations: 2
  errors: 1
  warnings: 1
  violations:
    - rule_id: DRC-001
      severity: error
      message: "Trace too thin"
      net_id: vcc
    - rule_id: DRC-002
      severity: warning
      message: "Silkscreen overlap"
      component_id: c1
  passed: false
"""
        )
        d1 = parse_str(yaml_with_drc)
        assert d1.drc_result is not None
        assert d1.drc_result.total_violations == 2
        assert d1.drc_result.passed is False
        yaml_out = dump_str(d1)
        d2 = parse_str(yaml_out)
        assert d2.drc_result is not None
        assert d2.drc_result.total_violations == 2

    def test_round_trip_component_symbol(self) -> None:
        yaml_with_symbol = """meta:
  name: SymTest
components:
  u1:
    ref: U1
    type: mcu
    pins:
      VCC: power
    symbol:
      pins:
        - id: "1"
          name: VCC
          position: [0, 10]
          length: 5.0
      body:
        - type: rect
          params: {x: -10, y: -10, w: 20, h: 20}
      width: 20.0
      height: 20.0
nets:
  vcc:
    name: VCC
    type: power
    nodes:
      - U1.VCC
"""
        d1 = parse_str(yaml_with_symbol)
        u1 = d1.components["u1"]
        assert u1.symbol is not None
        assert len(u1.symbol.pins) == 1
        assert u1.symbol.width == 20.0
        yaml_out = dump_str(d1)
        d2 = parse_str(yaml_out)
        u2 = d2.components["u1"]
        assert u2.symbol is not None
        assert len(u2.symbol.pins) == 1

    def test_round_trip_empty_design(self) -> None:
        d1 = parse_str("meta:\n  name: Empty\n")
        yaml_out = dump_str(d1)
        d2 = parse_str(yaml_out)
        assert d2.meta.name == "Empty"


class TestDump:
    def test_dump_str_round_trip_simple(self) -> None:
        d1 = parse_str(_VALID_DESIGN_YAML)
        s = dump_str(d1)
        d2 = parse_str(s)
        assert d2.meta.name == d1.meta.name
        assert len(d2.components) == len(d1.components)

    def test_dump_str_no_data_loss(self) -> None:
        d1 = parse_str(_EXTENDED_YAML)
        s = dump_str(d1)
        d2 = parse_str(s)
        c1 = d2.components["c1"]
        assert c1.dnp is True
        assert c1.lcsc_id == "C12345"
        n1 = d2.nets["n1"]
        assert n1.constraints is not None
        assert n1.constraints.impedance_target == 90.0

    def test_write_json_schema_ends_with_newline(self, tmp_path: Path) -> None:
        schema_path = tmp_path / "design-v1.json"

        write_json_schema(schema_path)

        assert schema_path.read_bytes().endswith(b"\n")

    def test_json_schema_file_matches_generated(self) -> None:
        import json

        schema_path = Path(__file__).parents[1] / "docs" / "schemas" / "design-v1.json"
        assert schema_path.exists(), "Committed schema file not found"
        committed = json.loads(schema_path.read_text(encoding="utf-8"))
        generated = generate_json_schema()
        assert committed == generated, "Committed schema does not match generated schema"

    def test_backward_compat_old_yaml(self) -> None:
        """Old-style YAML without field descriptions must still round-trip."""
        old_yaml = """meta:
  name: LegacyDesign
  version: "0.1.0"
components:
  r1:
    ref: R1
    type: resistor
    value: 10k
nets:
  vcc:
    name: VCC
    type: power
    nodes:
      - component_ref: r1
        pin_name: "1"
"""
        d1 = parse_str(old_yaml)
        s = dump_str(d1)
        d2 = parse_str(s)
        assert d2.meta.name == "LegacyDesign"
        assert d2.components["r1"].value == "10k"
        assert d2.nets["vcc"].name == "VCC"


def test_strict_mode_requires_zaptrace_design_signature() -> None:
    with pytest.raises(ParseError, match="kind: zaptrace.design"):
        parse_str(_VALID_DESIGN_YAML, strict=True)


def test_strict_mode_rejects_non_design_yaml() -> None:
    with pytest.raises(ParseError, match="kind: zaptrace.design"):
        parse_str("repos:\n  - repo: https://example.invalid/hooks\n", source=".pre-commit-config.yaml", strict=True)


def test_strict_mode_accepts_signed_design() -> None:
    signed = "kind: zaptrace.design\nschema_version: 1\n" + _VALID_DESIGN_YAML
    design = parse_str(signed, strict=True)
    assert design.meta.name == "TestDesign"


def test_strict_mode_rejects_unknown_top_level_keys() -> None:
    signed = "kind: zaptrace.design\nschema_version: 1\n" + _VALID_DESIGN_YAML + "extra_field: true\n"
    with pytest.raises(ParseError, match="unknown top-level keys"):
        parse_str(signed, strict=True)


def test_serialized_design_carries_signature() -> None:
    design = parse_str(_VALID_DESIGN_YAML)
    dumped = dump_str(design)
    assert "kind: zaptrace.design" in dumped
    assert "schema_version: 1" in dumped
    assert parse_str(dumped, strict=True).meta.name == "TestDesign"
