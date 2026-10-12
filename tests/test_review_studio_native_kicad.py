"""Local native KiCad Review Studio: parse/provenance/fail-closed invariants."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/review_studio_native_kicad.py"
TEMPLATE = SCRIPT.with_name("review_studio_native_template.html")
spec = importlib.util.spec_from_file_location("local_kicad_review", SCRIPT)
assert spec is not None and spec.loader is not None
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


REPORT = """** Drc report for example.kicad_pcb **
** Found 1 DRC violations **
[hole_clearance]: Measured 0.1944 mm versus minimum 0.25 mm
    Rule: board setup constraints; error
    @(77.1100 mm, 64.3950 mm): Hole of footprint J1
    @(76.8000 mm, 63.3200 mm): Pad A1 [GND] of J1 on F.Cu
** Found 1 unconnected pads **
[unconnected_items]: Missing connection between items
    Local override; error
    @(30.0000 mm, 34.0000 mm): Pad 1 [GND] of U1 on F.Cu
    @(45.0000 mm, 46.0000 mm): Pad 1 [GND] of C1 on F.Cu
** Found 0 Footprint errors **
** End of Report **
"""


def test_native_report_parses_actual_pad_coordinates() -> None:
    parsed = native.parse_native_drc(REPORT)
    assert len(parsed) == 2
    assert parsed[0]["rule"] == "hole_clearance"
    assert parsed[0]["severity"] == "error"
    assert parsed[0]["x"] == pytest.approx(77.11)
    assert parsed[0]["y"] == pytest.approx(64.395)
    assert "Pad A1" in " ".join(parsed[0]["objects"])
    assert parsed[1]["severity"] == "error"
    assert parsed[1]["rule"] == "unconnected_items"


def test_report_counters_match_parsed_physical_findings() -> None:
    assert len(native.validated_native_drc(REPORT)) == 2


@pytest.mark.parametrize(
    "report",
    [
        REPORT.replace("Found 1 DRC violations", "Found 2 DRC violations"),
        REPORT.replace("Found 1 unconnected pads", "Found 3 unconnected pads"),
        REPORT.replace("** Found 1 unconnected pads **", "** Malformed report **"),
        REPORT.replace("[hole_clearance]", "(hole_clearance)"),
        "No counters or findings; pretend everything passed",
    ],
)
def test_native_rule_mismatch_fails_closed(report: str) -> None:
    with pytest.raises(RuntimeError):
        native.validated_native_drc(report)


def test_known_empty_report_is_distinct_from_no_oracle() -> None:
    text = "** Found 0 DRC violations **\n** Found 0 unconnected pads **\n** End of Report **\n"
    assert native.validated_native_drc(text) == []


def test_native_erc_summary_uses_actual_rule_counts() -> None:
    report = "ERC report\n***** Sheet /\n ** ERC messages: 0  Errors 0  Warnings 0\n"
    assert native.native_erc_summary(report) == (0, 0, 0)
    report = "ERC report\n***** Sheet /\n ** ERC messages: 2  Errors 1  Warnings 1\n"
    assert native.native_erc_summary(report) == (2, 1, 1)


@pytest.mark.parametrize("report", ["", "PASS", "** ERC messages: 2 Errors 0 Warnings 0"])
def test_unknown_or_inconsistent_erc_report_is_blocked(report: str) -> None:
    with pytest.raises(RuntimeError):
        native.native_erc_summary(report)


def test_inline_json_blocks_html_script_breakout() -> None:
    hazard = '</script><script>alert("hi")</script>'
    safe = native.safe_inline_json({"name": hazard, "net": "A&B < GND"})
    assert "</script>" not in safe
    assert "\\u003c" in safe
    assert json.loads(safe) == {"name": hazard, "net": "A&B < GND"}


def test_html_template_is_read_only_and_uses_real_layers() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "__NATIVE_DATA__" in source
    assert "Native KiCad" in source
    assert "NOT FABRICATION APPROVED" in source
    assert "Human approval required" in source
    assert "source_sha256" in source
    assert "DATA.layers" in source
    assert "DATA.board.pads" in source
    assert "data-tab" in source
    assert "modeSch" in source
    assert "enabled-rule findings" in source
    assert 'id="ercBadge"' in source
    assert 'id="netParityBadge"' in source
    assert "pins unverified" in source
    assert "addRuleGuidance" in source
    assert "Do not silently relax board rules" in source
    assert "Do not approve fabrication" in source
    assert "DATA.board.copper" in source
    assert "crossprobe_refs" in source
    assert 'data-tab="pins"' in source
    assert "Unmapped / not qualified" in source
    assert "PIN MAPPING BLOCKER" in source
    assert 'data-tab="opens"' in source
    assert "inspection-only airwire" in source
    assert "NOT a clearance-safe route" in source
    assert "<script src=" not in source
    assert "fetch(" not in source


def test_local_original_and_readable_schematic_have_identical_native_pin_netlist() -> None:
    """Original vs candidate Eeschema netlist parity, not a PCB pad-number parity claim."""
    import xml.etree.ElementTree as ET

    root = Path(__file__).resolve().parents[1]
    original = root / "build/native-review-original/native-schematic-netlist.xml"
    candidate = root / "build/new-schematic-issue91-layout/candidate-netlist.xml"
    if not (original.is_file() and candidate.is_file()):
        pytest.skip("Local native KiCad schematic exports were not generated")

    def extract(path: Path) -> tuple:
        source = path.read_bytes()
        assert b"<!DOCTYPE" not in source and b"<!ENTITY" not in source
        xml = ET.fromstring(source)
        return tuple(
            sorted(
                (
                    net.attrib["name"],
                    tuple(sorted((node.attrib["ref"], node.attrib["pin"]) for node in net.findall("node"))),
                )
                for net in xml.findall("./nets/net")
            )
        )

    baseline, proposed = extract(original), extract(candidate)
    assert proposed == baseline
    assert len(proposed) == 7
    assert sum(len(pin_nodes) for _, pin_nodes in proposed) == 37


def test_explicit_paper_sizing_for_fourteen_real_components() -> None:
    from zaptrace.export.kicad import _schematic_page_layout

    assert _schematic_page_layout(14, 7)[0:2] == ("A3", 4)
    assert _schematic_page_layout(2, 2)[0] == "A4"


def test_invalid_board_name_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r".kicad_pcb"):
        native.build(tmp_path / "no-board.txt", tmp_path / "out", TEMPLATE)


def test_root_schematic_symbols_exclude_library_templates() -> None:
    source = (
        """"""
        """(kicad_sch
  (lib_symbols
    (symbol "Demo:U1" (property "Reference" "U" (at 0 0 0)))
  )
  (symbol
    (lib_id "Demo:U1")
    (at 406.4 51.2 90)
    (property "Reference" "J1" (at 401.5 49.2 0))
    (property "Value" "USB-C (test)" (at 401.5 61.2 0))
  )
)"""
        """"""
    )
    locations = native.schematic_symbols(source)
    assert locations == {"J1": {"ref": "J1", "x": 406.4, "y": 51.2, "rotation": 90.0}}


def test_repeated_schematic_reference_fails_closed() -> None:
    part = (
        """"""
        """  (symbol
    (lib_id "Demo:R")
    (at 20 30 0)
    (property "Reference" "R1" (at 20 27 0))
  )
"""
        """"""
    )
    with pytest.raises(RuntimeError, match="Ambiguous repeated schematic reference"):
        native.schematic_symbols("(kicad_sch\n" + part + part + ")")


def test_schematic_unbalanced_instances_are_refused() -> None:
    with pytest.raises(RuntimeError, match="Malformed native schematic"):
        native.schematic_symbols(
            """"""
            """(kicad_sch
  (symbol
    (at 10 20 0)
    (property "Reference" "U1" (at 1 2 0))
"""
            """"""
        )


def test_real_local_board_and_schematic_consistent_with_native_kicad(tmp_path: Path) -> None:
    import shutil
    import subprocess

    project = Path(__file__).resolve().parents[1]
    board = project / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"
    sch = project / "build/source-reference-readonly/ESP32_I2C_Sensor_Board.kicad_sch"
    if not board.is_file() or not sch.is_file() or not shutil.which("kicad-cli"):
        pytest.skip("Requires an actual user-provided local KiCad project reference")
    probe = subprocess.run(
        ["/usr/bin/python3", "-c", "import pcbnew"],
        capture_output=True,
        check=False,
    )
    if probe.returncode:
        pytest.skip("Native distro pcbnew is not installed")
    from hashlib import sha256

    source_hashes = (sha256(board.read_bytes()).hexdigest(), sha256(sch.read_bytes()).hexdigest())
    output = tmp_path / "native-local"
    output.mkdir()
    created = subprocess.run(
        ["/usr/bin/python3", str(SCRIPT), "--board", str(board), "--schematic", str(sch), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert created.returncode == 0, created.stderr
    evidence = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["source_sha256"] == source_hashes[0]
    assert evidence["schematic_meta"]["source_sha256"] == source_hashes[1]
    assert evidence["board"]["tracks"] == len(evidence["board"]["copper"]) == 61
    assert len(evidence["board"]["pads"]) == 112
    assert len(evidence["board"]["footprints"]) == 14
    assert evidence["schematic_meta"]["display_page_expanded"] is True
    assert evidence["schematic_meta"]["viewbox"][0] > 590
    assert len(evidence["schematic_meta"]["crossprobe_refs"]) == 14
    assert evidence["erc"]["count"] == 0
    assert evidence["net_parity"]["state"] == "names_match"
    assert len(evidence["net_parity"]["common"]) == 7
    assert evidence["net_parity"]["refs_match"] is True
    assert "NOT verified" in evidence["net_parity"]["scope"]
    assert {
        name: sum(f["rule"] == name for f in evidence["findings"])
        for name in (
            "drill_out_of_range",
            "hole_clearance",
            "unconnected_items",
        )
    } == {"drill_out_of_range": 12, "hole_clearance": 4, "unconnected_items": 12}
    assert (sha256(board.read_bytes()).hexdigest(), sha256(sch.read_bytes()).hexdigest()) == source_hashes


def test_bad_native_schematic_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r".kicad_sch"):
        native._export_schematic("kicad-cli", tmp_path / "missing.sch", tmp_path / "out")


def _local_pin_parity_sources() -> tuple[dict, dict, Path]:
    root = Path(__file__).resolve().parents[1]
    evidence = root / "build/native-review/evidence.json"
    design = root / "build/source-reference-readonly/issue91-design.yaml"
    if not evidence.is_file() or not design.is_file():
        pytest.skip("No local native KiCad evidence and canonical pin map")
    data = json.loads(evidence.read_text(encoding="utf-8"))
    return data["board"], data["schematic_meta"], design


def test_native_physical_pad_mapping_is_exact_and_scoped() -> None:
    board, schematic, design = _local_pin_parity_sources()
    report = native.physical_pin_parity(board, schematic, design)
    assert report["state"] == "mapped_net_consistent"
    assert report["mismatch_count"] == 0
    assert report["mapped_pad_instances"] == 69
    assert report["unmapped_pad_instances"] == 43
    assert report["total_pad_instances"] == 112
    assert report["schematic_logical_pin_nodes"] == 47
    assert report["unique_canonical_logical_functions"] == 37
    assert report["native_physical_pin_number_links"] == 47
    assert len(report["pad_links"]) == 69
    assert len({item["pad_index"] for item in report["pad_links"]}) == 69
    assert "no datasheet qualification" in report["scope"]
    assert report["design_sha256"]


def test_usb_c_repeated_function_maps_only_exact_physical_vbus_pad_numbers() -> None:
    board, schematic, design = _local_pin_parity_sources()
    parity = native.physical_pin_parity(board, schematic, design)
    assert parity["state"] == "mapped_net_consistent"
    pad_links = {(item["ref"], item["pad"]): item for item in parity["pad_links"]}
    vbus = [pin for pin in schematic["pin_anchors"] if pin["ref"] == "J1" and pin["canonical_pin"] == "VBUS"]
    assert {pin["physical_pin"] for pin in vbus} == {"A4", "A9", "B4", "B9"}
    assert {pin["logical_pin"] for pin in vbus} == {"VBUS_A4", "VBUS_A9", "VBUS_B4", "VBUS_B9"}
    for pin in vbus:
        link = pad_links[("J1", pin["physical_pin"])]
        assert link["logical_pin"] == pin["canonical_pin"] == "VBUS"
        assert link["net"] == pin["net"] == "VCC_5V"
    # A repeated canonical function never supplies authority for a different pin.
    assert len({(pin["ref"], pin["physical_pin"]) for pin in vbus}) == 4


def test_wrong_physical_pad_net_is_not_silently_approved() -> None:
    from copy import deepcopy

    board, schematic, design = _local_pin_parity_sources()
    broken = deepcopy(board)
    pad = next(p for p in broken["pads"] if p["ref"] == "J1" and p["pad"] == "A5")
    assert pad["net"] == "USB_CC1"
    pad["net"] = "GND"
    report = native.physical_pin_parity(broken, schematic, design)
    assert report["state"] == "mismatch"
    assert any(issue["reason"] == "physical-pad-versus-schematic-net" for issue in report["mismatches"])


def test_unmapped_pad_with_a_net_is_not_silently_approved() -> None:
    from copy import deepcopy

    board, schematic, design = _local_pin_parity_sources()
    broken = deepcopy(board)
    pad = next(p for p in broken["pads"] if p["ref"] == "J1" and p["pad"] == "A6")
    assert pad["net"] == "(no net)"
    pad["net"] = "VCC_3V3"
    report = native.physical_pin_parity(broken, schematic, design)
    assert report["state"] == "mismatch"
    assert any(issue["reason"] == "unmapped-but-connected-pad" for issue in report["mismatches"])


def test_canonical_pin_rewire_is_visible_as_a_mismatch(tmp_path: Path) -> None:
    board, schematic, design = _local_pin_parity_sources()
    altered = design.read_text(encoding="utf-8").replace(
        'GPIO21: {type: "bidirectional", net: "I2C_SDA"}',
        'GPIO21: {type: "bidirectional", net: "GND"}',
        1,
    )
    assert altered != design.read_text(encoding="utf-8")
    path = tmp_path / "altered.yaml"
    path.write_text(altered, encoding="utf-8")
    report = native.physical_pin_parity(board, schematic, path)
    assert report["state"] == "mismatch"
    assert any(x["reason"] == "canonical-versus-schematic-net" for x in report["mismatches"])


def test_schematic_added_unmapped_pin_is_not_silently_approved() -> None:
    from copy import deepcopy

    board, schematic, design = _local_pin_parity_sources()
    broken = deepcopy(schematic)
    broken["logical_nodes"].append({"ref": "U1", "pin": "DUMMY", "net": "GND"})
    report = native.physical_pin_parity(board, broken, design)
    assert report["state"] == "mismatch"
    assert any(x["reason"] == "native-schematic-pin-not-in-canonical-design" for x in report["mismatches"])


def test_bad_design_references_fail_closed(tmp_path: Path) -> None:
    board, schematic, design = _local_pin_parity_sources()
    altered = design.read_text(encoding="utf-8").replace('ref: "U1"', 'ref: "UX"', 1)
    assert altered != design.read_text(encoding="utf-8")
    path = tmp_path / "bad.yaml"
    path.write_text(altered, encoding="utf-8")
    with pytest.raises(ValueError, match="references do not match"):
        native.physical_pin_parity(board, schematic, path)


def test_real_native_schematic_pin_endpoint_geometry_and_xml_parity() -> None:
    board, schematic, _design = _local_pin_parity_sources()
    assert board["tracks"] == 61
    anchors = schematic["pin_anchors"]
    assert len(anchors) == 47
    assert len({(p["ref"], p["logical_pin"]) for p in anchors}) == 47
    assert len({(p["ref"], p["physical_pin"]) for p in anchors}) == 47
    assert len({(p["ref"], p["canonical_pin"]) for p in anchors}) == 37
    gnd = [p for p in anchors if p["ref"] == "U1" and p["canonical_pin"] == "GND"]
    assert {p["physical_pin"] for p in gnd} == {"1", "15", "38", "39"}
    assert {p["net"] for p in gnd} == {"GND"}
    assert all(p["logical_pin"].startswith("GND_") for p in gnd)
    assert next(p for p in anchors if p["ref"] == "U1" and p["physical_pin"] == "2")["canonical_pin"] == "VCC"
    assert {(p["ref"], p["logical_pin"], p["net"]) for p in anchors} == {
        (p["ref"], p["pin"], p["net"]) for p in schematic["logical_nodes"]
    }
    match = next(p for p in anchors if p["ref"] == "U1" and p["logical_pin"] == "GPIO21")
    assert match["net"] == "I2C_SDA"
    assert match["x"] == pytest.approx(34.29)
    assert match["y"] == pytest.approx(58.42)


def test_kicad_native_xml_physical_pin_numbers_come_from_embedded_symbol(tmp_path: Path) -> None:
    import shutil
    from copy import deepcopy

    if not shutil.which("kicad-cli"):
        pytest.skip("Native KiCad CLI not installed")
    root = Path(__file__).resolve().parents[1]
    source = root / "build/new-schematic-issue91-layout/kicad/ESP32_I2C_Sensor_Board.kicad_sch"
    if not source.is_file():
        pytest.skip("Generated native KiCad schematic not available")
    report = native._read_schematic_netlist("kicad-cli", source, tmp_path)
    symbols = native.schematic_symbols(source.read_text())
    original_nodes = report["logical_nodes"]
    anchors = native.schematic_pin_anchors(source.read_text(), symbols, original_nodes)
    assert len(anchors) == len(original_nodes) == 47
    assert len({(x["ref"], x["physical_pin"]) for x in anchors}) == 47
    assert len({(x["ref"], x["canonical_pin"]) for x in anchors}) == 37
    assert next(x for x in anchors if x["ref"] == "U1" and x["physical_pin"] == "33")["canonical_pin"] == "GPIO21"
    assert next(x for x in anchors if x["ref"] == "U1" and x["physical_pin"] == "2")["net"] == "VCC_3V3"
    assert all(x["source"].startswith("embedded KiCad library pin name/number") for x in anchors)
    wrong_function = deepcopy(original_nodes)
    pin = next(x for x in wrong_function if x["ref"] == "U1" and x["pin"] == "2")
    pin["pinfunction"] = "GPIO21_2"
    with pytest.raises(RuntimeError, match="pinfunction disagrees"):
        native.schematic_pin_anchors(source.read_text(), symbols, wrong_function)
    wrong_number = deepcopy(original_nodes)
    pin = next(x for x in wrong_number if x["ref"] == "U1" and x["pin"] == "2")
    pin["pin"] = "999"
    with pytest.raises(RuntimeError, match="physical pin U1.2"):
        native.schematic_pin_anchors(source.read_text(), symbols, wrong_number)


def test_native_repeated_logical_grounds_cannot_disagree_on_physical_net() -> None:
    from copy import deepcopy

    board, schematic, design = _local_pin_parity_sources()
    wrong = deepcopy(schematic)
    real = next(x for x in wrong["logical_nodes"] if x["ref"] == "U1" and x.get("physical_pin") == "38")
    real["net"] = "VCC_3V3"
    report = native.physical_pin_parity(board, wrong, design)
    assert report["state"] == "mismatch"
    assert any(x["reason"] == "native-logical-pin-has-conflicting-physical-nets" for x in report["mismatches"])


def test_schematic_physical_pin_function_number_crosswalk_rejects_wrong_pad_identity() -> None:
    from copy import deepcopy

    board, schematic, design = _local_pin_parity_sources()
    wrong = deepcopy(schematic)
    real = next(x for x in wrong["logical_nodes"] if x["ref"] == "U1" and x.get("physical_pin") == "2")
    real["canonical_pin"] = "GPIO21"
    report = native.physical_pin_parity(board, wrong, design)
    assert report["state"] == "mismatch"
    assert any(x["reason"] == "native-physical-pin-number-name-mismatch" for x in report["mismatches"])


def test_unsupported_schematic_rotation_refuses_pin_overlay() -> None:
    from copy import deepcopy

    root = Path(__file__).resolve().parents[1]
    source = root / "build/new-schematic-issue91-layout/kicad/ESP32_I2C_Sensor_Board.kicad_sch"
    if not source.is_file():
        pytest.skip("Native local Eeschema fixture missing")
    _board, schematic, _design = _local_pin_parity_sources()
    symbols = {s["ref"]: deepcopy(s) for s in schematic["symbols"]}
    symbols["U1"]["rotation"] = 90
    with pytest.raises(RuntimeError, match="Rotated native schematic"):
        native.schematic_pin_anchors(source.read_text(), symbols, schematic["logical_nodes"])


def test_native_drc_open_connection_pairs_are_geometry_verified() -> None:
    from copy import deepcopy

    root = Path(__file__).resolve().parents[1]
    evidence = json.loads((root / "build/native-review/evidence.json").read_text())
    board = evidence["board"]
    pairs = native.native_open_connection_pairs(board, evidence["findings"])
    assert len(pairs) == 12
    assert sum(len(pair["endpoints"]) for pair in pairs) == 24
    assert {pair["net"] for pair in pairs} == {"GND", "VCC_3V3", "VCC_5V", "I2C_SCL"}
    assert all(pair["straight_line_mm"] > 0 for pair in pairs)
    assert all("not a routed path" in pair["scope"] for pair in pairs)
    assert all(end["kind"] in {"pad", "track"} for p in pairs for end in p["endpoints"])
    broken = deepcopy(board)
    pad = next(p for p in broken["pads"] if p["ref"] == "J1" and p["pad"] == "A1")
    pad["x"] += 0.2
    with pytest.raises(RuntimeError, match="ambiguous or unavailable"):
        native.native_open_connection_pairs(broken, evidence["findings"])


def test_native_drc_open_connection_track_net_conflict_is_blocked() -> None:
    from copy import deepcopy

    root = Path(__file__).resolve().parents[1]
    evidence = json.loads((root / "build/native-review/evidence.json").read_text())
    broken = deepcopy(evidence["findings"])
    issue = next(f for f in broken if f["rule"] == "unconnected_items")
    issue["objects"][0] = issue["objects"][0].replace("[GND]", "[VCC_5V]")
    with pytest.raises(RuntimeError, match="ambiguous or unavailable"):
        native.native_open_connection_pairs(evidence["board"], broken)


def test_local_review_report_contains_exact_blocked_engineering_evidence() -> None:
    root = Path(__file__).resolve().parents[1]
    evidence_file = root / "build/native-review/evidence.json"
    report_file = root / "build/native-review/REVIEW_REPORT.md"
    if not evidence_file.is_file() or not report_file.is_file():
        pytest.skip("Native KiCad local source evidence not built")
    x = json.loads(evidence_file.read_text())
    assert native.native_review_report({**x, "schematic": x["schematic_meta"]}) == report_file.read_text()
    text = report_file.read_text()
    assert x["source_sha256"] in text
    assert x["schematic_meta"]["source_sha256"] in text
    assert x["pin_parity"]["design_sha256"] in text
    assert "16 non-open findings" in text
    assert "12 native open items" in text
    assert "69/112 pad instances; 0 mismatches" in text
    assert "AIRWIRE ONLY" in text and "NOT FABRICATION APPROVED" in text
    assert "fabricator DFM" in text
    assert text.count("| GND |") >= 2


def test_report_cannot_claim_clean_if_oracles_not_run() -> None:
    from copy import deepcopy

    root = Path(__file__).resolve().parents[1]
    path = root / "build/native-review/evidence.json"
    if not path.is_file():
        pytest.skip("Native KiCad evidence unavailable")
    data = json.loads(path.read_text())
    broken = deepcopy(data)
    broken["drc_state"] = "not_run"
    broken["findings"] = []
    broken["open_pairs"] = []
    broken["erc"] = {"state": "not_run", "count": None}
    broken["schematic"] = None
    review = native.native_review_report(broken)
    assert "native DRC not executed" in review
    assert "not checked" in review
    assert "no DRC violations" not in review.lower()
    assert "FABRICATION BLOCKED" in review


def test_html_has_real_pad_distance_tool_with_nonclaim() -> None:
    src = TEMPLATE.read_text()
    assert 'id="measure"' in src
    assert 'id="clearMeasure"' in src
    assert 'id="measureReadout"' in src
    assert "Math.hypot(dx,dy)" in src
    assert "DATA.board.pads[index]" in src
    assert "NOT copper-to-copper clearance" in src
    assert 'href="REVIEW_REPORT.html"' in src


def test_professional_workspace_uses_real_metrics_and_operable_local_controls() -> None:
    template = TEMPLATE.read_text()
    for control in (
        "quickDrc",
        "quickOpen",
        "quickErc",
        "quickPins",
        "focusMode",
        "showHelp",
        "closeHelp",
        "shortcutBackdrop",
        "kpiDrc",
        "kpiOpens",
        "kpiErc",
        "kpiPins",
    ):
        assert template.count(f'id="{control}"') == 1
    assert "function setFocusMode(next)" in template
    assert "function bindShortcuts()" in template
    assert "DATA.drc_state==='not_run'?'—'" in template
    assert "DATA.erc.state==='not_run'?'—'" in template
    assert 'data-tab="opens"' in template
    assert "Local workspace" in template
    assert "Fabrication blocked" in template


def test_locally_rendered_evidence_report_is_static_styled_and_deterministic() -> None:
    from copy import deepcopy

    root = Path(__file__).resolve().parents[1]
    evidence = root / "build/native-review/evidence.json"
    html_file = root / "build/native-review/REVIEW_REPORT.html"
    if not evidence.is_file() or not html_file.is_file():
        pytest.skip("Native local evidence and styled report must be built")
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["schematic"] = payload["schematic_meta"]
    generated = native.native_review_report_html(payload)
    assert generated == html_file.read_text(encoding="utf-8")
    assert "default-src 'none'; style-src 'unsafe-inline'" in generated
    assert "<script" not in generated.lower()
    assert "NOT FABRICATION APPROVED" in generated
    assert "16 violations" in generated and "12 pairs" in generated
    assert payload["source_sha256"] in generated
    assert payload["schematic"]["source_sha256"] in generated
    assert payload["pin_parity"]["design_sha256"] in generated
    mutated = deepcopy(payload)
    mutated["findings"][0]["message"] = '<img src=x onerror="alert(1)">'
    escaped = native.native_review_report_html(mutated)
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in escaped
    assert "<img src=x" not in escaped


def test_offline_html_report_does_not_call_unrun_oracles_clean() -> None:
    from copy import deepcopy

    root = Path(__file__).resolve().parents[1]
    evidence = root / "build/native-review/evidence.json"
    if not evidence.is_file():
        pytest.skip("Native local evidence must be built")
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload = deepcopy(payload)
    payload["schematic"] = None
    payload["drc_state"] = "not_run"
    payload["findings"] = []
    payload["open_pairs"] = []
    payload["erc"] = {"state": "not_run", "count": None}
    payload["pin_parity"]["state"] = "not_checked"
    payload["pin_parity"]["mapped_pad_instances"] = None
    rendered = native.native_review_report_html(payload)
    assert "KiCad DRC was NOT RUN" in rendered
    assert "NOT RUN" in rendered
    assert "Fabrication remains blocked" in rendered
    assert "NOT FABRICATION APPROVED" in rendered
    assert "0 violations" not in rendered


def test_global_native_search_and_marker_visibility_stay_review_only() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    assert source.count('id="commandBackdrop"') == 1
    assert source.count('id="commandInput"') == 1
    assert source.count('id="commandResults"') == 1
    assert source.count('id="searchWorkspace"') == 1
    assert source.count('id="searchCanvas"') == 1
    assert "function buildCommandItems()" in source
    assert "function executeCommand(index)" in source
    assert "if(DATA.drc_state!=='not_run')" in source
    assert "if(DATA.schematic)" in source
    assert "No matching native objects" in source
    assert "focus({preventScroll:true})" in source
    for field in ("showPadMarkers", "showFaultMarkers", "showFootprintMarkers"):
        assert source.count(f'id="{field}"') == 1
    assert "#stage.hide-fault-markers .fault" in source
    assert "#stage.hide-pad-markers .pad-hit" in source
    assert "#stage.hide-footprint-markers .fp-hit" in source
    assert "Hide or show interactive markers" not in source or "Native geometry" in source
    assert "DRC evidence and fabrication blockers remain unchanged" in source
    assert "@media(max-width:1070px) and (min-width:751px)" in source


def test_dockable_review_workspace_has_keyboard_and_source_safe_queue() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    for control in ("leftSplitter", "rightSplitter", "reviewQueue", "reviewQueueStatus", "reviewPrev", "reviewNext"):
        assert source.count(f'id="{control}"') == 1
    assert 'role="separator"' in source
    assert 'aria-valuenow="290"' in source
    assert 'aria-valuenow="346"' in source
    assert "function bindPanelSplitters()" in source
    assert "function advanceReview(direction)" in source
    assert "function getReviewQueue()" in source
    assert "DATA.drc_state==='not_run'" in source
    assert "pair.finding_index" in source
    assert "450" in source  # Keep board canvas visible when resizing side panels.
    assert "aria-valuetext" in source
    assert "k==='j'||k==='k'" in source
    assert "' · filtered'" in source
    assert "@media(max-width:750px){.app{--left-width:0px" in source
    assert "app.style.removeProperty('--left-width')" in source
    assert "app.style.removeProperty('--right-width')" in source
    assert "max-width:950px" in source
    assert "function updateReviewQueue()" in source
    assert " · filtered" in source


def test_projects_backlink_is_optional_source_scoped_viewer_ui() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    assert source.count("__WORKSPACE_LINK__") == 1
    assert 'id="workspaceHome"' not in source
    assert "function readPreferences()" in source
    assert "function restorePreferences()" in source
    assert "function resetPreferences()" in source
    assert "zaptrace.review.layout.v1." in source
    assert "DATA.source_sha256" in source
    assert "source unchanged" in source


def test_native_multi_sheet_selector_shows_real_pages_without_child_pin_claims() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    assert source.count('id="schematicPagePicker"') == 1
    assert source.count('id="schematicPageNav"') == 1
    assert "DATA.schematic.pages" in source
    assert "function setSchematicPage(index)" in source
    assert "root_only_crossprobe" in SCRIPT.read_text(encoding="utf-8")
    assert "root_only_not_verified" in SCRIPT.read_text(encoding="utf-8")
    assert "schematicStage.querySelectorAll('.sch-hit,.sch-pin-hit')" in source
    assert "Root-only PCB cross-probe disabled on child pages" in source
    assert "setSchematicPage(0)" in source
    assert "schematicPageIndex" in source
    assert "page:schematicPageIndex" in source


def test_native_schematic_gallery_uses_only_real_kicad_svg_pages_and_refuses_child_crossprobe() -> None:
    """Presentation-only controls cannot fabricate schematic or approval evidence."""
    template = (Path(__file__).resolve().parents[1] / "scripts/review_studio_native_template.html").read_text()
    for item in (
        'id="schematicThumbnails"',
        'id="schematicSheetDock" hidden',
        'id="schematicPrevious"',
        'id="schematicNext"',
        'id="schematicFocusSymbols"',
        'class="sheet-thumb"',
    ):
        # Class sheet-thumb is created at runtime from actual KiCad pages.
        assert item in template if item != 'class="sheet-thumb"' else "node('button','sheet-thumb')" in template
    assert "image.src=page.src" in template
    assert "DATA.schematic.pages.forEach((page,index)" in template
    assert "btn.hidden=index!==0" in template
    assert "Root-only PCB cross-probe disabled on child pages." in template
    assert "schematicFocusSymbols').disabled=index!==0" in template
    assert "focusNativeRootSymbols()" in template
    assert "DATA.schematic.symbols||[]" in template
    assert "k===']'&&mode==='schematic'" in template
    assert "k==='['&&mode==='schematic'" in template
    assert "NOT FABRICATION APPROVED" in template
