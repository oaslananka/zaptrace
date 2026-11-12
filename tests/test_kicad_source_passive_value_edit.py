"""A real passive value edit must preserve original KiCad electrical topology."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from defusedxml import ElementTree

from zaptrace.io.sexp import parse
from zaptrace.kicad.schematic_importer import (
    KiCadSchematicSourceSnapshot,
    import_kicad_schematic,
    import_kicad_schematic_string,
)
from zaptrace.kicad.source_edit import replace_kicad_source_passive_value

RESISTOR = "11111111-1111-4111-8111-111111111111"
CAPACITOR = "22222222-2222-4222-8222-222222222222"
POWER = "33333333-3333-4333-8333-333333333333"
TEXT = (
    "(kicad_sch\r\n"
    ' (symbol (lib_id "Device:R") (property "Reference" "R1" (at 0 0 0))'
    f' (property "Value" "10k" (at 0 1 0)) (uuid "{RESISTOR}"))\r\n'
    f' (symbol (lib_id "Device:C") (property "Reference" "C1") (property "Value" "100nF") (uuid "{CAPACITOR}"))\r\n'
    f' (symbol (lib_id "power:GND") (property "Reference" "#PWR01") (property "Value" "GND") (uuid "{POWER}"))\r\n'
    " ;; preserve this comment and every other source byte\r\n"
    ' (netclass_flag "" (property "Netclass" "VBUS"))\r\n'
    ")\r\n"
)


def _snapshot(raw: str = TEXT) -> KiCadSchematicSourceSnapshot:
    return KiCadSchematicSourceSnapshot(
        raw_bytes=raw.encode("utf-8"),
        sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        paper=None,
        title_block={},
        embedded_fonts=None,
        top_level_counts={},
    )


def test_passive_value_edits_only_expected_uuid_field_in_exact_original_bytes() -> None:
    snap = _snapshot()
    changed = replace_kicad_source_passive_value(snap, RESISTOR, "R1", "10k", "4.7k Ω", expected_sha256=snap.sha256)
    assert changed == snap.raw_bytes.replace(b'"Value" "10k"', '"Value" "4.7k Ω"'.encode(), 1)
    assert snap.raw_bytes == TEXT.encode()
    old, new = parse(TEXT), parse(changed.decode())
    assert isinstance(old, list) and isinstance(new, list)
    assert old[1] != new[1]
    assert old[2:] == new[2:]  # other component, power, netclass and comment unaffected


def test_passive_value_rejects_unexpected_or_ambiguous_edits() -> None:
    snap = _snapshot()
    valid = dict(expected_sha256=snap.sha256)
    with pytest.raises(ValueError, match="SHA"):
        replace_kicad_source_passive_value(snap, RESISTOR, "R1", "10k", "4.7k", expected_sha256="a" * 64)
    with pytest.raises(ValueError, match="expected"):
        replace_kicad_source_passive_value(snap, RESISTOR, "R1", "100k", "4.7k", **valid)
    with pytest.raises(ValueError, match="reference"):
        replace_kicad_source_passive_value(snap, RESISTOR, "R2", "10k", "4.7k", **valid)
    with pytest.raises(ValueError, match="passive"):
        replace_kicad_source_passive_value(snap, POWER, "#PWR01", "GND", "VCC", **valid)
    with pytest.raises(ValueError, match="value"):
        replace_kicad_source_passive_value(snap, RESISTOR, "R1", "10k", "", **valid)
    with pytest.raises(ValueError, match="control"):
        replace_kicad_source_passive_value(snap, RESISTOR, "R1", "10k", "10k\ninjected", **valid)
    duplicated = TEXT.replace(CAPACITOR, RESISTOR)
    duplicate = _snapshot(duplicated)
    with pytest.raises(ValueError, match="unique"):
        replace_kicad_source_passive_value(duplicate, RESISTOR, "R1", "10k", "4.7k", expected_sha256=duplicate.sha256)


def test_symbol_library_must_match_generic_passive_type() -> None:
    for lib_id in ("SparkFun-Resistor:2.2k_0603", "Vendor:Fixed_R", "Device:C"):
        modified = TEXT.replace('(lib_id "Device:R")', f'(lib_id "{lib_id}")', 1)
        snap = _snapshot(modified)
        with pytest.raises(ValueError, match="library|symbol"):
            replace_kicad_source_passive_value(snap, RESISTOR, "R1", "10k", "4.7k", expected_sha256=snap.sha256)


def test_symbol_library_must_be_present_and_unique() -> None:
    for altered in (
        TEXT.replace('(lib_id "Device:R")', "", 1),
        TEXT.replace('(lib_id "Device:R")', '(lib_id "Device:R") (lib_id "Device:R")', 1),
    ):
        snap = _snapshot(altered)
        with pytest.raises(ValueError, match="library|symbol"):
            replace_kicad_source_passive_value(snap, RESISTOR, "R1", "10k", "4.7k", expected_sha256=snap.sha256)


def test_value_edit_must_change_the_old_value() -> None:
    snap = _snapshot()
    with pytest.raises(ValueError, match="unchanged|different"):
        replace_kicad_source_passive_value(snap, RESISTOR, "R1", "10k", "10k", expected_sha256=snap.sha256)


def test_fixed_value_original_sparkfun_symbol_is_not_editable() -> None:
    source = next(
        (Path(__file__).parents[1] / "benchmarks/external/sparkfun-qwiic-navigation/source").glob("*.kicad_sch")
    )
    snap = import_kicad_schematic(source).source_snapshot
    assert snap is not None
    symbol = next(
        node
        for node in snap.nodes("symbol")
        if any(isinstance(child, list) and child[:3] == ["property", "Reference", "R14"] for child in node)
    )
    uid = next(entry[1] for entry in symbol if isinstance(entry, list) and entry[0] == "uuid")
    with pytest.raises(ValueError, match="library|symbol"):
        replace_kicad_source_passive_value(snap, str(uid), "R14", "2.2k", "4.7k", expected_sha256=snap.sha256)


@pytest.mark.parametrize(
    ("name", "ref", "old_value", "new_value"),
    [
        ("nitu-npn-transistor-switch", "R1", "390", "470"),
        ("mitayi-pico-d1", "C17", "30pF", "33pF"),
        ("nitu-555-blinker", "R1", "4.7k", "5.1k"),
        ("nitu-linear-regulator", "R1", "330", "470"),
    ],
)
def test_real_original_source_passive_value_edit_retains_imported_nets(
    name: str, ref: str, old_value: str, new_value: str
) -> None:
    source = next((Path(__file__).parents[1] / "benchmarks/external" / name / "source").glob("*.kicad_sch"))
    before = import_kicad_schematic(source)
    snap = before.source_snapshot
    assert snap is not None
    symbol = next(
        node
        for node in snap.nodes("symbol")
        if any(isinstance(child, list) and child[:3] == ["property", "Reference", ref] for child in node)
    )
    uuid_node = next(e for e in symbol if isinstance(e, list) and e and e[0] == "uuid")
    changed = replace_kicad_source_passive_value(
        snap, str(uuid_node[1]), ref, old_value, new_value, expected_sha256=snap.sha256
    )
    after = import_kicad_schematic_string(changed.decode(), source_path=source)
    assert before.design.nets == after.design.nets
    assert after.unsupported_count == before.unsupported_count
    assert after.source_snapshot is not None
    assert after.source_snapshot.nodes("netclass_flag") == snap.nodes("netclass_flag")
    assert changed != source.read_bytes()
    assert snap.raw_bytes == source.read_bytes()


@pytest.mark.parametrize(
    ("name", "reference", "old_value", "new_value"),
    [
        ("mitayi-pico-d1", "C17", "30pF", "33pF"),
        ("nitu-555-blinker", "R1", "4.7k", "5.1k"),
        ("nitu-npn-transistor-switch", "R1", "390", "470"),
        ("nitu-linear-regulator", "R1", "330", "470"),
    ],
)
def test_native_kicad_cli_preserves_all_net_nodes_and_erc_findings_after_passive_edit(
    tmp_path: Path, name: str, reference: str, old_value: str, new_value: str
) -> None:
    """KiCad 10 is an independent oracle. Skip explicitly if native CLI is unavailable."""
    cli = shutil.which("kicad-cli")
    if cli is None:
        pytest.skip("native KiCad CLI unavailable: not an independent pass")
    version = subprocess.run([cli, "version"], capture_output=True, text=True, timeout=15)
    if version.returncode != 0 or not version.stdout.strip().startswith("10."):
        pytest.skip("requires installed KiCad 10 for independent native oracle")

    source = next((Path(__file__).parents[1] / "benchmarks/external" / name / "source").glob("*.kicad_sch"))
    snapshot = import_kicad_schematic(source).source_snapshot
    assert snapshot is not None
    symbol = next(
        n
        for n in snapshot.nodes("symbol")
        if any(isinstance(e, list) and e[:3] == ["property", "Reference", reference] for e in n)
    )
    uid = next(str(e[1]) for e in symbol if isinstance(e, list) and e[0] == "uuid")
    altered = replace_kicad_source_passive_value(
        snapshot, uid, reference, old_value, new_value, expected_sha256=snapshot.sha256
    )

    artifacts = []
    for name_suffix, payload in (("original", snapshot.raw_bytes), ("edited", altered)):
        folder = tmp_path / name_suffix
        folder.mkdir()
        sch = folder / "review.kicad_sch"
        sch.write_bytes(payload)
        netxml = folder / "net.xml"
        ercjson = folder / "erc.json"
        for command in (
            [cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(netxml), str(sch)],
            [cli, "sch", "erc", "--format", "json", "--severity-all", "-o", str(ercjson), str(sch)],
        ):
            result = subprocess.run(command, capture_output=True, text=True, timeout=50)
            assert result.returncode == 0, result.stderr

        net = ElementTree.parse(netxml).getroot()
        graph = {
            n.get("name"): tuple(sorted((x.get("ref"), x.get("pin")) for x in n.findall("node")))
            for n in net.findall("./nets/net")
        }
        values = [c.findtext("value") for c in net.findall("./components/comp") if c.get("ref") == reference]
        erc = json.loads(ercjson.read_text())
        findings = sorted(
            (
                entry.get("type"),
                entry.get("severity"),
                tuple(sorted((item.get("uuid"), repr(item.get("pos"))) for item in entry.get("items", []))),
            )
            for sheet in erc["sheets"]
            for entry in sheet["violations"]
        )
        artifacts.append((graph, values, findings))

    assert artifacts[0][0] == artifacts[1][0]
    assert artifacts[0][1] == [old_value]
    assert artifacts[1][1] == [new_value]
    assert artifacts[0][2] == artifacts[1][2]
    assert source.read_bytes() == snapshot.raw_bytes
