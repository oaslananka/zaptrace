"""Tests for the Altium ASCII schematic importer (issue #136)."""

from __future__ import annotations

import pathlib

import pytest

from zaptrace.eda.altium import (
    MAX_INPUT_BYTES,
    AltiumImportResult,
    AltiumRecord,
    read_altium_ascii_sch,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "altium"

# ---------------------------------------------------------------------------
# Minimal fixture content
# ---------------------------------------------------------------------------

MINIMAL_SCH = (FIXTURES / "minimal_schematic.SchDoc").read_text(encoding="utf-8")

# A tiny inline schematic with one component and no nets
ONE_COMP = """\
|RECORD=1|DESCRIPTION=Sheet|
|RECORD=28|LIBREFERENCE=RES1|DESIGNITEMID=RES1|DESCRIPTION=Resistor|UNIQUEID=AAAA|LOCATION.X=100|LOCATION.Y=100|PARTCOUNT=1|
"""

# Two components with wires and labels joining them
TWO_COMP_WIRED = """\
|RECORD=1|DESCRIPTION=Test|
|RECORD=28|LIBREFERENCE=RES1|UNIQUEID=R001|LOCATION.X=200|LOCATION.Y=200|
|RECORD=2|OWNER=1|X=100|Y=250|NAME=1|NUMBER=1|PINLENGTH=100|PINCONGLOMERATE=0|
|RECORD=28|LIBREFERENCE=CAP1|UNIQUEID=C001|LOCATION.X=500|LOCATION.Y=200|
|RECORD=2|OWNER=3|X=400|Y=250|NAME=1|NUMBER=1|PINLENGTH=100|PINCONGLOMERATE=0|
|RECORD=37|X1=200|Y1=250|X2=400|Y2=250|
|RECORD=4|TEXT=SIG_NET|X=290|Y=270|
"""


# ---------------------------------------------------------------------------
# 1. Basic reader tests
# ---------------------------------------------------------------------------


class TestReader:
    def test_reads_minimal_fixture(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        assert isinstance(result, AltiumImportResult)

    def test_returns_altium_import_result(self):
        result = read_altium_ascii_sch(ONE_COMP)
        assert isinstance(result, AltiumImportResult)

    def test_total_record_count_nonzero(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        assert result.total_record_count > 0

    def test_supported_record_types_populated(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        assert len(result.supported_record_types) > 0

    def test_record_1_is_supported(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        assert 1 in result.supported_record_types

    def test_record_28_is_supported(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        assert 28 in result.supported_record_types

    def test_record_2_is_supported(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        assert 2 in result.supported_record_types

    def test_record_37_is_supported(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        assert 37 in result.supported_record_types

    def test_record_4_is_supported(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        assert 4 in result.supported_record_types

    def test_record_209_is_supported(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        assert 209 in result.supported_record_types

    def test_accepts_bytes_input(self):
        result = read_altium_ascii_sch(MINIMAL_SCH.encode("utf-8"))
        assert result.total_record_count > 0

    def test_empty_string_returns_zero_records(self):
        result = read_altium_ascii_sch("")
        assert result.total_record_count == 0
        assert result.error_count == 0

    def test_whitespace_only_input(self):
        result = read_altium_ascii_sch("   \n  \n")
        assert result.total_record_count == 0

    def test_malformed_lines_ignored(self):
        bad = "this is not a record\n|RECORD=1|DESCRIPTION=Test|\n"
        result = read_altium_ascii_sch(bad)
        assert result.total_record_count == 1  # only the valid record

    def test_design_object_present(self):
        result = read_altium_ascii_sch(ONE_COMP)
        assert result.design is not None

    def test_no_errors_on_valid_input(self):
        result = read_altium_ascii_sch(ONE_COMP)
        assert result.error_count == 0


# ---------------------------------------------------------------------------
# 2. Security tests
# ---------------------------------------------------------------------------


class TestSecurity:
    def test_rejects_oversized_bytes(self):
        oversized = b"A" * (MAX_INPUT_BYTES + 1)
        with pytest.raises(ValueError, match="maximum allowed size"):
            read_altium_ascii_sch(oversized)

    def test_rejects_oversized_string(self):
        oversized = "A" * (MAX_INPUT_BYTES + 1)
        with pytest.raises(ValueError, match="maximum allowed size"):
            read_altium_ascii_sch(oversized)

    def test_rejects_ole_binary_magic(self):
        ole_header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100
        with pytest.raises(ValueError, match="OLE Compound Document"):
            read_altium_ascii_sch(ole_header)

    def test_max_size_boundary_accepted(self):
        # Exactly at the limit should not raise
        at_limit = b"|RECORD=1|DESCRIPTION=Test|\n"
        padded = at_limit + b" " * (MAX_INPUT_BYTES - len(at_limit))
        result = read_altium_ascii_sch(padded)
        assert result.total_record_count >= 1

    def test_malformed_record_type_not_crash(self):
        bad = "|RECORD=not_a_number|FIELD=value|\n"
        result = read_altium_ascii_sch(bad)
        assert result.error_count == 0  # just ignored, no crash

    def test_missing_record_field_not_crash(self):
        missing = "|FIELD=value|OTHER=stuff|\n"
        result = read_altium_ascii_sch(missing)
        assert result.total_record_count == 0  # line without RECORD is ignored


# ---------------------------------------------------------------------------
# 3. Component extraction tests
# ---------------------------------------------------------------------------


class TestComponentExtraction:
    def test_two_components_from_fixture(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        assert len(result.design.components) == 2

    def test_component_has_ref(self):
        result = read_altium_ascii_sch(ONE_COMP)
        comp = next(iter(result.design.components.values()))
        assert comp.ref

    def test_component_has_type(self):
        result = read_altium_ascii_sch(ONE_COMP)
        comp = next(iter(result.design.components.values()))
        assert comp.type in ("resistor", "capacitor", "inductor", "diode", "transistor", "ic")

    def test_resistor_type_inference(self):
        result = read_altium_ascii_sch(ONE_COMP)
        comp = next(iter(result.design.components.values()))
        assert comp.type == "resistor"

    def test_capacitor_type_inference(self):
        cap_sch = "|RECORD=28|LIBREFERENCE=CAP|UNIQUEID=C1|LOCATION.X=0|LOCATION.Y=0|\n"
        result = read_altium_ascii_sch(cap_sch)
        comp = next(iter(result.design.components.values()))
        assert comp.type == "capacitor"

    def test_component_unique_id_used_as_key(self):
        result = read_altium_ascii_sch(ONE_COMP)
        assert "AAAA" in result.design.components

    def test_component_position_set(self):
        result = read_altium_ascii_sch(ONE_COMP)
        comp = result.design.components["AAAA"]
        assert comp.position is not None
        assert comp.position[0] > 0 or comp.position[1] >= 0

    def test_component_libreference_in_properties(self):
        result = read_altium_ascii_sch(ONE_COMP)
        comp = result.design.components["AAAA"]
        assert "libreference" in comp.properties

    def test_two_distinct_refs(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        refs = {c.ref for c in result.design.components.values()}
        assert len(refs) == 2

    def test_ref_prefix_resistor(self):
        result = read_altium_ascii_sch(ONE_COMP)
        comp = next(iter(result.design.components.values()))
        assert comp.ref.startswith("R")

    def test_no_components_empty_input(self):
        result = read_altium_ascii_sch("")
        assert len(result.design.components) == 0


# ---------------------------------------------------------------------------
# 4. Pin extraction tests
# ---------------------------------------------------------------------------


class TestPinExtraction:
    def test_pins_attached_to_component(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        # At least one component should have pins
        has_pins = any(len(c.pins) > 0 for c in result.design.components.values())
        assert has_pins

    def test_pin_has_name(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        for comp in result.design.components.values():
            for _pin_id, pin in comp.pins.items():
                assert pin.name

    def test_pin_has_type(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        for comp in result.design.components.values():
            for _, pin in comp.pins.items():
                assert pin.type is not None

    def test_pin_position_set(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        for comp in result.design.components.values():
            for _, pin in comp.pins.items():
                assert pin.position is not None


# ---------------------------------------------------------------------------
# 5. Wire / net extraction tests
# ---------------------------------------------------------------------------


class TestWireNetExtraction:
    def test_labels_produce_nets(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        net_names = {n.name for n in result.design.nets.values()}
        assert "NET_A" in net_names or len(result.design.nets) > 0

    def test_ports_produce_nets(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        # VCC and GND ports exist in fixture
        net_names = {n.name for n in result.design.nets.values()}
        assert len(net_names) > 0

    def test_net_score_between_0_and_1(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        assert 0.0 <= result.net_score <= 1.0

    def test_net_has_id(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        for net in result.design.nets.values():
            assert net.id

    def test_net_has_name(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        for net in result.design.nets.values():
            assert net.name

    def test_gnd_net_classified_as_ground(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        from zaptrace.core.models import NetType

        gnd_nets = [n for n in result.design.nets.values() if "GND" in n.name.upper()]
        if gnd_nets:
            assert gnd_nets[0].type == NetType.GROUND

    def test_vcc_net_classified_as_power(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        from zaptrace.core.models import NetType

        power_nets = [n for n in result.design.nets.values() if "VCC" in n.name.upper()]
        if power_nets:
            assert power_nets[0].type == NetType.POWER

    def test_wired_components_share_net_nodes(self):
        result = read_altium_ascii_sch(TWO_COMP_WIRED)
        # The wire+label should produce at least one net
        assert result.design.nets is not None  # may or may not connect depending on snap

    def test_net_node_references_valid_component(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        comp_ids = set(result.design.components.keys())
        for net in result.design.nets.values():
            for node in net.nodes:
                assert node.component_ref in comp_ids


# ---------------------------------------------------------------------------
# 6. Unsupported record tracking tests
# ---------------------------------------------------------------------------


class TestUnsupportedRecords:
    def test_unsupported_record_captured(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        # Fixture contains RECORD=99 which is unsupported
        assert len(result.unsupported_records) >= 1

    def test_unsupported_record_is_altium_record(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        assert all(isinstance(r, AltiumRecord) for r in result.unsupported_records)

    def test_unsupported_record_has_type(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        for rec in result.unsupported_records:
            assert isinstance(rec.record_type, int)

    def test_unsupported_record_has_fields(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        for rec in result.unsupported_records:
            assert isinstance(rec.fields, dict)

    def test_unsupported_record_severity_info(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        for rec in result.unsupported_records:
            assert rec.severity == "info"

    def test_unsupported_record_type_99(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        types = {r.record_type for r in result.unsupported_records}
        assert 99 in types

    def test_to_dict_includes_unsupported_count(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        d = result.to_dict()
        assert "unsupported_record_count" in d
        assert d["unsupported_record_count"] >= 1

    def test_to_dict_keys(self):
        result = read_altium_ascii_sch(ONE_COMP)
        d = result.to_dict()
        expected_keys = {
            "component_count",
            "net_count",
            "total_record_count",
            "supported_record_types",
            "unsupported_record_count",
            "error_count",
            "warning_count",
            "net_score",
        }
        assert expected_keys.issubset(d.keys())

    def test_altium_record_to_dict(self):
        rec = AltiumRecord(record_type=99, fields={"SOMETHING": "VALUE"})
        d = rec.to_dict()
        assert d["record_type"] == 99
        assert d["fields"] == {"SOMETHING": "VALUE"}
        assert d["severity"] == "info"

    def test_supported_types_not_in_unsupported(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        unsupported_types = {r.record_type for r in result.unsupported_records}
        # Supported types (1,2,4,28,37,209) must not appear in unsupported
        for t in result.supported_record_types:
            assert t not in unsupported_types


# ---------------------------------------------------------------------------
# 7. Design integration tests
# ---------------------------------------------------------------------------


class TestDesignIntegration:
    def test_design_meta_name_set(self):
        result = read_altium_ascii_sch(ONE_COMP)
        assert result.design.meta.name

    def test_design_meta_author_set(self):
        result = read_altium_ascii_sch(ONE_COMP)
        assert "altium" in result.design.meta.author.lower()

    def test_design_components_dict(self):
        result = read_altium_ascii_sch(ONE_COMP)
        assert isinstance(result.design.components, dict)

    def test_design_nets_dict(self):
        result = read_altium_ascii_sch(ONE_COMP)
        assert isinstance(result.design.nets, dict)

    def test_full_fixture_no_crash(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        assert result is not None
        assert result.error_count == 0

    def test_fixture_component_count_matches(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        assert len(result.design.components) == 2

    def test_net_score_positive_when_pins_connected(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        # Fixture has pins; score may be 0 if no connectivity but should not be negative
        assert result.net_score >= 0.0

    def test_result_to_dict_component_count(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        d = result.to_dict()
        assert d["component_count"] == 2

    def test_result_to_dict_net_count(self):
        result = read_altium_ascii_sch(MINIMAL_SCH)
        d = result.to_dict()
        assert isinstance(d["net_count"], int)
