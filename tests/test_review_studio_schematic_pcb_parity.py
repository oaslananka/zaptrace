"""Real KiCad 10 source-only schematic-to-PCB association review; never F8."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE / "scripts/review_studio_schematic_pcb_parity.py"
SCH = SOURCE / "build/source-reference-readonly/ESP32_I2C_Sensor_Board.kicad_sch"
PCB = SOURCE / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"


def invoke(schematic: Path, board: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            str(SCRIPT),
            "--schematic",
            str(schematic),
            "--board",
            str(board),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=115,
        check=False,
    )


@pytest.mark.skipif(not shutil.which("kicad-cli") or not PCB.exists(), reason="Native KiCad 10 real project fixture")
def test_actual_esp32_source_identity_differences_are_reported_not_silently_synced(tmp_path: Path) -> None:
    original = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (SCH, PCB)}
    report = tmp_path / "project-audit.json"
    run = invoke(SCH, PCB, report)
    assert run.returncode == 0, run.stderr
    finding = json.loads(report.read_text())
    assert finding["source_sha256"] == {"schematic": original[SCH], "pcb": original[PCB]}
    assert finding["component_counts"] == {"schematic": 14, "pcb": 14, "shared_references": 14}
    assert finding["schematic_net_count"] == 7
    issues = [(x["reference"], x["field"]) for x in finding["component_field_discrepancies"]]
    assert issues == [(ref, "value") for ref in ("J1", "TP1", "TP2", "U2", "U3")]
    assert finding["component_fields_match"] is False
    assert finding["repeated_pcb_pad_numbers"] is True
    pin = finding["native_pin_net_evidence"]
    assert pin["schematic_connected_pin_identifiers"] == 37
    assert pin["pcb_physical_pads"] == 112
    assert pin["unique_pcb_pad_identifiers"] == 86
    assert pin["matching_pin_identifiers_by_reference"] == 0
    assert pin["schematic_pin_identifiers_missing_from_pcb"] == 37
    assert pin["pcb_pad_identifiers_missing_from_schematic"] == 86
    assert pin["native_net_label_differences_for_matching_pin_ids"] == 0
    assert pin["conflicting_nets_on_duplicate_pcb_pad_numbers"] == 0
    assert pin["issue_count"] == 123
    assert len(pin["issue_samples"]) == 24
    assert any(x["reference"] == "R1" and x["schematic_pin"] == "P1" for x in pin["issue_samples"])
    assert finding["pin_net_correspondence"].startswith("not_verified_")
    assert finding["linkage_uuid_verified"] is False
    assert finding["automatic_sync_authorized"] is False
    assert finding["electricallyApproved"] is False
    assert finding["fabApproved"] is False
    assert finding["source_files_modified"] is False
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == value for p, value in original.items())
    assert report.stat().st_mode & 0o777 == 0o600
    again = invoke(SCH, PCB, report)
    assert again.returncode == 2
    assert report.read_text() == json.dumps(finding, indent=2, ensure_ascii=False) + "\n"


@pytest.mark.skipif(not shutil.which("kicad-cli") or not PCB.exists(), reason="Native KiCad 10 real project fixture")
def test_actual_esp32_modified_pcb_value_is_reported_and_originals_protected(tmp_path: Path) -> None:
    copied = tmp_path / "source.kicad_pcb"
    original = PCB.read_bytes()
    native = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            "-c",
            "import pcbnew as p,sys; b=p.LoadBoard(sys.argv[1]);"
            "b.FindFootprintByReference('R1').SetValue('DANGEROUS_DIFFERENCE');p.SaveBoard(sys.argv[2],b)",
            str(PCB),
            str(copied),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert native.returncode == 0, native.stderr
    report = tmp_path / "detected.json"
    result = invoke(SCH, copied, report)
    assert result.returncode == 0, result.stderr
    findings = json.loads(report.read_text())["component_field_discrepancies"]
    assert any(
        x["reference"] == "R1" and x["field"] == "value" and x["pcb"] == "DANGEROUS_DIFFERENCE" for x in findings
    )
    assert PCB.read_bytes() == original


@pytest.mark.parametrize("invalid", ["not-a-board.kicad_pcb", "wrong-extension.txt"])
def test_invalid_native_source_fails_without_publishing(tmp_path: Path, invalid: str) -> None:
    source = tmp_path / invalid
    source.write_text("not a KiCad board" * 15)
    report = tmp_path / "must-not-exist.json"
    run = invoke(SCH, source, report)
    assert run.returncode != 0
    assert not report.exists()


def linked_native_copy(tmp_path: Path, mode: str) -> Path:
    """Use KiCad's own kicadxml netlist and pcbnew KIID_PATH to build a real board copy."""
    source = tmp_path / "actual-netlist.xml"
    run = subprocess.run(
        [
            "kicad-cli",
            "sch",
            "export",
            "netlist",
            "--format",
            "kicadxml",
            "--output",
            str(source),
            str(SCH),
        ],
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    target = tmp_path / "linked-board.kicad_pcb"
    created = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            "-c",
            """
import pcbnew as pcb,sys,xml.etree.ElementTree as ET
root=ET.parse(sys.argv[1]).getroot()
paths={c.get("ref"):c.findtext("tstamps") for c in root.findall("./components/comp")}
board=pcb.LoadBoard(sys.argv[2])
mode=sys.argv[4]
for fp in board.GetFootprints():
    ref=fp.GetReference()
    uuid=paths[ref]
    if mode=="swapped" and ref in ("R1","R2"):
        uuid=paths[{"R1":"R2","R2":"R1"}[ref]]
    if mode=="duplicate" and ref=="R2":
        uuid=paths["R1"]
    if mode=="missing" and ref=="R2":
        continue
    if mode=="bad" and ref=="R1":
        uuid="00000000-0000-4000-8000-000000000001"
    if mode=="bad-format" and ref=="R1":
        continue
    path=pcb.KIID_PATH()
    if mode=="unexpected-sheet" and ref=="R1":
        path.push_back(pcb.KIID("00000000-0000-4000-8000-000000000002"))
    path.push_back(pcb.KIID(uuid))
    fp.SetPath(path)
    if mode=="same-number-different-net" and ref=="R1":
        # Deliberately change a COPY's pad label to a real schematic
        # pin number, leaving its native PCB net name unchanged.
        for pad in fp.Pads():
            if pad.GetNumber()=="1":
                pad.SetNumber("P1")
                break
    if mode=="contradictory-repeated-pad" and ref=="U3":
        seen=set()
        for pad in fp.Pads():
            if pad.GetNumber()=="2":
                if "2" in seen:
                    pad.SetNetCode(0)
                    break
                seen.add("2")
pcb.SaveBoard(sys.argv[3],board)
""",
            str(source),
            str(PCB),
            str(target),
            mode,
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert created.returncode == 0, created.stderr
    return target


@pytest.mark.parametrize(
    "mode,expected_issue",
    [
        ("swapped", "schematic_footprint_uuid_path_mismatch"),
        ("duplicate", "duplicate_pcb_footprint_uuid_path"),
        ("missing", "pcb_footprint_uuid_path_missing"),
        ("bad", "schematic_footprint_uuid_path_mismatch"),
        ("unexpected-sheet", "schematic_footprint_uuid_path_mismatch"),
    ],
)
@pytest.mark.skipif(not shutil.which("kicad-cli") or not PCB.exists(), reason="Native KiCad real PCB required")
def test_kicad_uuid_linkage_fails_closed_on_incorrect_native_paths(
    tmp_path: Path, mode: str, expected_issue: str
) -> None:
    board = linked_native_copy(tmp_path, mode)
    raw = board.read_bytes()
    report_path = tmp_path / "linkage-report.json"
    run = invoke(SCH, board, report_path)
    assert run.returncode == 0, run.stderr
    evidence = json.loads(report_path.read_text())
    assert evidence["linkage_uuid_verified"] is False
    assert evidence["native_uuid_linkage"]["status"] == "not_verified_native_uuid_paths"
    assert any(item["issue"] == expected_issue for item in evidence["native_uuid_linkage"]["findings"])
    assert evidence["automatic_sync_authorized"] is False
    assert evidence["fabApproved"] is False
    assert board.read_bytes() == raw


@pytest.mark.skipif(not shutil.which("kicad-cli") or not PCB.exists(), reason="Native KiCad real PCB required")
def test_kicad_real_native_uuid_paths_verified_but_pin_net_sync_still_blocked(tmp_path: Path) -> None:
    board = linked_native_copy(tmp_path, "valid")
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (SCH, PCB, board)}
    report_path = tmp_path / "verified-uuid-only.json"
    run = invoke(SCH, board, report_path)
    assert run.returncode == 0, run.stderr
    evidence = json.loads(report_path.read_text())
    assert evidence["component_counts"]["shared_references"] == 14
    assert evidence["native_uuid_linkage"]["status"] == "fully_linked_native_uuid_paths"
    assert evidence["native_uuid_linkage"]["verified_reference_count"] == 14
    assert evidence["native_uuid_linkage"]["findings"] == []
    assert evidence["linkage_uuid_verified"] is True
    # This establishes *only* KiCad symbol-to-footprint identity, never
    # physical pad net correspondence, ERC/DRC or the authority to synchronize.
    assert evidence["pin_net_correspondence"].startswith("not_verified_")
    assert len(evidence["component_field_discrepancies"]) == 5
    assert evidence["automatic_sync_authorized"] is False
    assert evidence["electricallyApproved"] is False
    assert evidence["fabApproved"] is False
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == value for p, value in before.items())


def test_kicad_uuid_path_parser_handles_hierarchical_multi_unit_and_fails_closed() -> None:
    """A hierarchy is sheet-instance UUID(s) plus exactly one native symbol UUID."""
    native = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            "-c",
            """
import sys,json,xml.etree.ElementTree as ET
sys.path.insert(0,sys.argv[1])
from review_studio_schematic_pcb_parity import expected_symbol_paths,verify_uuid_paths
a='AAA00000-1111-4222-8333-444444444444'
b='BBB00000-1111-4222-8333-444444444444'
u='CCC00000-1111-4222-8333-444444444444'
v='DDD00000-1111-4222-8333-444444444444'
def one(sheet,ids):
    item=ET.Element('comp',ref='U1')
    ET.SubElement(item,'sheetpath',tstamps=sheet)
    ET.SubElement(item,'tstamps').text=ids
    return expected_symbol_paths(item)
paths=one('/'+a+'/'+b,u+' '+v)
assert paths==frozenset({'/'+a.lower()+'/'+b.lower()+'/'+u.lower(),
                         '/'+a.lower()+'/'+b.lower()+'/'+v.lower()})
assert one('/'+a,u+' '+u)==frozenset()
assert one('/not-a-uuid',u)==frozenset()
assert one('//'+a,u)==frozenset()
assert one('/'+a,'invalid')==frozenset()
yes=verify_uuid_paths({'U1':paths},{'U1':'/'+a.lower()+'/'+b.lower()+'/'+v.lower()})
assert yes['verified'] is True and yes['verified_reference_count']==1
no=verify_uuid_paths({'U1':paths},{'U1':'/'+b.lower()+'/'+a.lower()+'/'+v.lower()})
assert no['verified'] is False and no['findings'][0]['issue']=='schematic_footprint_uuid_path_mismatch'
collision=verify_uuid_paths({'U1':paths,'U2':paths},{
    'U1':'/'+a.lower()+'/'+b.lower()+'/'+u.lower(),
    'U2':'/'+a.lower()+'/'+b.lower()+'/'+v.lower()
})
assert collision['verified'] is False
assert any(x['issue']=='duplicate_schematic_symbol_uuid_path' for x in collision['findings'])
print(json.dumps({'hierarchical_multisymbol_kicad_path': 'PASS','wrong_sheet_order':'REJECTED',
                  'duplicate_multiunit_uuid':'REJECTED', 'duplicate_schematic_paths':'REJECTED'}))
""",
            str(SOURCE / "scripts"),
        ],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert native.returncode == 0, native.stderr
    assert json.loads(native.stdout)["wrong_sheet_order"] == "REJECTED"


@pytest.mark.skipif(not shutil.which("kicad-cli") or not PCB.exists(), reason="Native KiCad real PCB required")
def test_native_pin_number_matching_does_not_misstate_net_equality(tmp_path: Path) -> None:
    native = linked_native_copy(tmp_path, "same-number-different-net")
    result = tmp_path / "native-net-disagreement.json"
    run = invoke(SCH, native, result)
    assert run.returncode == 0, run.stderr
    proof = json.loads(result.read_text())
    assert proof["linkage_uuid_verified"] is True
    pin = proof["native_pin_net_evidence"]
    assert pin["matching_pin_identifiers_by_reference"] == 1
    assert pin["native_net_label_differences_for_matching_pin_ids"] == 1
    assert any(
        row["reference"] == "R1"
        and row.get("pin") == "P1"
        and row["issue"] == "same_pin_number_but_native_net_labels_differ"
        for row in pin["issue_samples"]
    )
    assert proof["pin_net_correspondence"].startswith("not_verified_")
    assert proof["automatic_sync_authorized"] is False
    assert proof["fabApproved"] is False


@pytest.mark.skipif(not shutil.which("kicad-cli") or not PCB.exists(), reason="Native KiCad real PCB required")
def test_repeated_native_pad_number_conflicting_nets_never_prove_electrical_parity(tmp_path: Path) -> None:
    native = linked_native_copy(tmp_path, "contradictory-repeated-pad")
    result = tmp_path / "native-repeated-pad-net-disagreement.json"
    run = invoke(SCH, native, result)
    assert run.returncode == 0, run.stderr
    proof = json.loads(result.read_text())
    assert proof["linkage_uuid_verified"] is True
    assert proof["native_pin_net_evidence"]["conflicting_nets_on_duplicate_pcb_pad_numbers"] >= 1
    assert proof["native_pin_net_evidence"]["duplicate_pcb_pad_numbers"] is True
    assert proof["pin_net_correspondence"].startswith("not_verified_")
    assert proof["automatic_sync_authorized"] is False
