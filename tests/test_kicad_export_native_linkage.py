"""Native KiCad 10 proof of physical-pin and root schematic/PCB UUID identity."""

from __future__ import annotations

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from zaptrace.core.parser import parse_file
from zaptrace.export.kicad import export_kicad

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "build/source-reference-readonly/issue91-design.yaml"
AUDIT = ROOT / "scripts/review_studio_schematic_pcb_parity.py"

pytestmark = pytest.mark.skipif(
    not shutil.which("kicad-cli") or not Path("/usr/lib/python3/dist-packages/pcbnew.py").exists(),
    reason="Native KiCad and pcbnew required for native linkage proof",
)


def native_evidence(tmp_path: Path, design_source: Path = SRC) -> tuple[dict, ET.Element, dict[str, Path]]:
    design = parse_file(design_source)
    artifacts = export_kicad(design, tmp_path)
    output = {
        "schematic": Path(artifacts["schematic"]),
        "pcb": Path(artifacts["pcb"]),
        "netlist": tmp_path / "authentic.xml",
        "audit": tmp_path / "audit.json",
    }
    net = subprocess.run(
        [
            "kicad-cli",
            "sch",
            "export",
            "netlist",
            "--format",
            "kicadxml",
            "--output",
            str(output["netlist"]),
            str(output["schematic"]),
        ],
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    assert net.returncode == 0, net.stderr
    run = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            str(AUDIT),
            "--schematic",
            str(output["schematic"]),
            "--board",
            str(output["pcb"]),
            "--output",
            str(output["audit"]),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(output["audit"].read_text()), ET.parse(output["netlist"]).getroot(), output


def test_generated_esp32_native_kiid_and_full_connected_pad_subset(tmp_path: Path) -> None:
    original = SRC.read_bytes()
    report, netlist, output = native_evidence(tmp_path)
    assert report["component_counts"] == {"schematic": 14, "pcb": 14, "shared_references": 14}
    assert report["linkage_uuid_verified"] is True
    assert report["native_uuid_linkage"]["verified_reference_count"] == 14
    assert report["native_uuid_linkage"]["findings"] == []
    assert report["component_field_discrepancies"] == []
    pins = report["native_pin_net_evidence"]
    assert pins["schematic_connected_pin_identifiers"] == 47
    assert pins["matching_pin_identifiers_by_reference"] == 47
    assert pins["schematic_pin_identifiers_missing_from_pcb"] == 0
    assert pins["native_root_sheet_proven"] is True
    assert pins["native_root_scope_slash_pattern_not_parity"] == 0
    assert pins["native_unexplained_net_label_disagreements"] == 0
    assert pins["native_net_label_differences_for_matching_pin_ids"] == 0
    assert pins["native_unexplained_net_label_disagreements"] == 0
    assert pins["connected_schematic_pin_net_subset_verified"] is True
    # Genuine vendor J1 includes two anonymous NPTH locating pegs,
    # represented by one unique (J1, '') mechanical pad identifier.
    assert pins["pcb_pad_identifiers_missing_from_schematic"] == 39
    assert pins["conflicting_nets_on_duplicate_pcb_pad_numbers"] == 0
    assert report["automatic_sync_authorized"] is False
    assert report["electricallyApproved"] is False
    assert report["fabApproved"] is False
    component_ids = {x.get("ref"): x.findtext("tstamps") for x in netlist.findall("./components/comp")}
    assert len(component_ids) == 14
    assert all(component_ids.values())
    native_pcb = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            "-c",
            "import pcbnew as p,json,sys;"
            "b=p.LoadBoard(sys.argv[1]);"
            "print(json.dumps({x.GetReference():x.GetPath().AsString() for x in b.GetFootprints()}))",
            str(output["pcb"]),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert native_pcb.returncode == 0, native_pcb.stderr
    assert json.loads(native_pcb.stdout) == {ref: "/" + (value or "") for ref, value in component_ids.items()}
    assert SRC.read_bytes() == original


def test_native_schematic_root_mapping_uses_physical_numbers_not_logical_labels(tmp_path: Path) -> None:
    report, netlist, _output = native_evidence(tmp_path)
    by_net = {
        name: {(node.get("ref"), node.get("pin")) for node in entries.findall("node")}
        for entries in netlist.findall("./nets/net")
        if (name := entries.get("name"))
    }
    assert ("R1", "1") in by_net["VCC_3V3"]
    assert ("R1", "2") in by_net["I2C_SDA"]
    assert ("U1", "33") in by_net["I2C_SDA"]
    assert ("U1", "36") in by_net["I2C_SCL"]
    assert {("J1", "A1"), ("J1", "B12"), ("U1", "1"), ("U1", "39")} <= by_net["GND"]
    assert all(pin not in {"P1", "P2", "GPIO21", "GPIO22"} for pins in by_net.values() for _ref, pin in pins)
    assert report["native_pin_net_evidence"]["connected_schematic_pin_net_subset_verified"] is True


def test_native_export_deterministic_schematic_pcb_copied_twice(tmp_path: Path) -> None:
    first, _, files1 = native_evidence(tmp_path / "once")
    second, _, files2 = native_evidence(tmp_path / "twice")
    assert first["component_counts"] == second["component_counts"]
    assert first["native_uuid_linkage"] == second["native_uuid_linkage"]
    assert files1["schematic"].read_bytes() == files2["schematic"].read_bytes()
    assert files1["pcb"].read_bytes() == files2["pcb"].read_bytes()


def test_generated_real_pcb_wrong_net_is_never_accepted_as_root_scope_alias(tmp_path: Path) -> None:
    _report, _netlist, files = native_evidence(tmp_path)
    mutated = tmp_path / "native-wrong-net.kicad_pcb"
    process = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            "-c",
            "import pcbnew as p,sys; b=p.LoadBoard(sys.argv[1]);"
            "f=b.FindFootprintByReference('R1');"
            "n=next(q for q in f.Pads() if q.GetNumber()=='1');"
            "n.SetNetCode(0);p.SaveBoard(sys.argv[2],b)",
            str(files["pcb"]),
            str(mutated),
        ],
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    report_path = tmp_path / "different-native-net.json"
    run = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            str(AUDIT),
            "--schematic",
            str(files["schematic"]),
            "--board",
            str(mutated),
            "--output",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=80,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    review = json.loads(report_path.read_text())
    evidence = review["native_pin_net_evidence"]
    assert review["linkage_uuid_verified"] is True
    assert evidence["matching_pin_identifiers_by_reference"] == 47
    assert evidence["native_root_scope_slash_pattern_not_parity"] == 0
    assert evidence["native_unexplained_net_label_disagreements"] == 1
    assert evidence["connected_schematic_pin_net_subset_verified"] is False
    assert any(
        row["reference"] == "R1"
        and row.get("pin") == "1"
        and row.get("pcb_net") == ""
        and row["issue"] == "same_pin_number_but_native_net_labels_differ"
        for row in evidence["issue_samples"]
    )
    assert review["automatic_sync_authorized"] is False
    assert review["fabApproved"] is False


def test_missing_authoritative_logical_to_physical_map_fails_closed(tmp_path: Path) -> None:
    source = parse_file(SRC)
    # Physical resistor pad 1 still exists. Removing its authoritative
    # P1-to-pad1 relation must never silently infer a replacement.
    source.components["R1"].package_pin_map.pop("1")
    artifacts = export_kicad(source, tmp_path)
    output = tmp_path / "unmapped-native-linkage.json"
    run = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            str(AUDIT),
            "--schematic",
            str(artifacts["schematic"]),
            "--board",
            str(artifacts["pcb"]),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=80,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    report = json.loads(output.read_text())
    assert report["linkage_uuid_verified"] is True
    evidence = report["native_pin_net_evidence"]
    assert evidence["connected_schematic_pin_net_subset_verified"] is False
    assert evidence["schematic_pin_identifiers_missing_from_pcb"] > 0
    assert evidence["matching_pin_identifiers_by_reference"] < 47
    assert report["automatic_sync_authorized"] is False
    assert report["fabApproved"] is False


def test_native_kicad_drc_schematic_parity_is_clean_without_misreporting_routing(tmp_path: Path) -> None:
    """Independent KiCad 10 F8-equivalent comparison; not routed-board signoff."""
    evidence, _netlist, artifacts = native_evidence(tmp_path)
    assert evidence["native_pin_net_evidence"]["connected_schematic_pin_net_subset_verified"] is True
    parity_path = tmp_path / "independent-kicad10-schematic-parity.json"
    native = subprocess.run(
        [
            "kicad-cli",
            "pcb",
            "drc",
            "--schematic-parity",
            "--severity-all",
            "--format",
            "json",
            "--output",
            str(parity_path),
            str(artifacts["pcb"]),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert native.returncode == 0, native.stderr
    native_report = json.loads(parity_path.read_text())
    assert native_report["kicad_version"].startswith("10.")
    assert native_report["schematic_parity"] == []
    # The exact pinned supplier art replaces fake pads-only library redraws
    # and retains real oval holes; never waive the remaining physical DRC.
    from collections import Counter

    kinds = Counter(item["type"] for item in native_report["violations"])
    assert kinds == {"drill_out_of_range": 12, "hole_clearance": 4}
    assert len(native_report["violations"]) == 16
    assert len(native_report["unconnected_items"]) == 37
    assert "lib_footprint_mismatch" not in kinds
    assert "through_hole_pad_without_hole" not in kinds
    assert "silk_over_copper" not in kinds
    assert evidence["automatic_sync_authorized"] is False
    assert evidence["electricallyApproved"] is False
    assert evidence["fabApproved"] is False


def test_native_local_root_labels_conflict_with_pcb_global_net_names(tmp_path: Path) -> None:
    """A visual '/GND' vs 'GND' prefix is NOT KiCad native net parity."""
    verified, _netlist, files = native_evidence(tmp_path)
    assert verified["native_pin_net_evidence"]["connected_schematic_pin_net_subset_verified"] is True
    local_sch = tmp_path / "locally-labeled.kicad_sch"
    raw = files["schematic"].read_text()
    assert raw.count('  (global_label "') == 47
    # Schematic-only legacy conversion; KiCad itself determines the resulting
    # slash-prefixed root-sheet net names. Never mutate the baseline source.
    raw = raw.replace('  (global_label "', '  (label "').replace(" (shape passive) (at ", " (at ")
    local_sch.write_text(raw)
    dest = tmp_path / "local-versus-pcb.json"
    run = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            str(AUDIT),
            "--schematic",
            str(local_sch),
            "--board",
            str(files["pcb"]),
            "--output",
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=80,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    parity = json.loads(dest.read_text())
    evidence = parity["native_pin_net_evidence"]
    assert parity["linkage_uuid_verified"] is True
    assert evidence["matching_pin_identifiers_by_reference"] == 47
    assert evidence["native_root_sheet_proven"] is True
    assert evidence["native_root_scope_slash_pattern_not_parity"] == 47
    assert evidence["native_unexplained_net_label_disagreements"] == 47
    assert evidence["connected_schematic_pin_net_subset_verified"] is False
    assert evidence["issue_count"] >= 47
    assert parity["automatic_sync_authorized"] is False
    assert parity["electricallyApproved"] is False
    assert parity["fabApproved"] is False


def test_generated_esp32_native_erc_preserves_explicit_incomplete_board_status(tmp_path: Path) -> None:
    """Native KiCad ERC is clean while fabrication and physical DRC remain separate."""
    audit, _netlist, artifacts = native_evidence(tmp_path)
    report_path = tmp_path / "native-erc.json"
    run = subprocess.run(
        [
            "kicad-cli",
            "sch",
            "erc",
            "--severity-all",
            "--format",
            "json",
            "--output",
            str(report_path),
            str(artifacts["schematic"]),
        ],
        capture_output=True,
        text=True,
        timeout=50,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    body = json.loads(report_path.read_text())
    assert body["kicad_version"].startswith("10.")
    assert sum(len(x.get("violations", [])) for x in body["sheets"]) == 0
    assert audit["linkage_uuid_verified"] is True
    assert audit["native_pin_net_evidence"]["connected_schematic_pin_net_subset_verified"] is True
    assert audit["automatic_sync_authorized"] is False
    assert audit["electricallyApproved"] is False
    assert audit["fabApproved"] is False
