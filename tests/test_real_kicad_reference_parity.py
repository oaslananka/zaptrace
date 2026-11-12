"""Real-reference netlist parity evidence contracts; no KiCad runtime required."""

from __future__ import annotations

from pathlib import Path

import pytest
from defusedxml import ElementTree
from defusedxml.common import EntitiesForbidden

from scripts.ci_real_kicad_reference_parity import (
    compare_graphs,
    connected_pin_topology,
    read_native_netlist,
    source_artifacts,
)


def test_xml_native_netlist_preserves_distinct_differential_pairs(tmp_path: Path) -> None:
    xml = tmp_path / "native.xml"
    xml.write_text(
        '<export><nets><net name="USB_D+"><node ref="U1" pin="A6"/></net>'
        '<net name="USB_D-"><node ref="U1" pin="A7"/></net></nets></export>',
        encoding="utf-8",
    )
    native = read_native_netlist(xml)
    assert native == {"USB_D+": {("U1", "A6")}, "USB_D-": {("U1", "A7")}}
    assert compare_graphs(native, native)["exact_connectivity_parity"] is True


def test_parity_does_not_accept_same_counts_with_wrong_pins() -> None:
    native = {"USB_D+": {("J1", "A6")}, "USB_D-": {("J1", "A7")}}
    imported = {"USB_D+": {("J1", "A7")}, "USB_D-": {("J1", "A6")}}
    report = compare_graphs(native, imported)
    assert report["exact_connectivity_parity"] is False
    assert report["pin_mismatch_net_count"] == 2
    assert report["native_missing_net_count"] == 0


def test_parity_does_not_accept_disjoint_names_with_equal_counts() -> None:
    report = compare_graphs({"VCC": {("U1", "1")}}, {"GND": {("U1", "1")}})
    assert report["exact_connectivity_parity"] is False
    assert report["common_net_count"] == 0
    assert report["native_missing_net_count"] == 1
    assert report["imported_extra_net_count"] == 1


def test_name_diagnostics_classify_only_identical_physical_pin_groups() -> None:
    native = {
        "/GPIO1": {("U1", "1"), ("J1", "1")},
        "IO5/Blue": {("U1", "2")},
        "Net-(D1-A)": {("D1", "1")},
        "GND": {("J1", "2"), ("U1", "4")},
        "unconnected-(U1-NC)": {("U1", "3")},
    }
    imported = {
        "GPIO1": {("U1", "1"), ("J1", "1")},
        "IO5{slash}Blue": {("U1", "2")},
        "net_b1": {("D1", "1")},
        "GND": {("J1", "2"), ("U1", "4"), ("#PWR01", "1")},
    }
    report = compare_graphs(native, imported)
    diagnostic = report["name_difference_diagnostics"]
    assert report["connected_pin_topology"]["connected_pin_topology_parity"] is True
    assert report["exact_connectivity_parity"] is False
    assert diagnostic["status"] == "classified_not_verified"
    assert diagnostic["evaluated_group_count"] == 4
    counts = diagnostic["category_counts"]
    assert counts["exact"] == 1
    assert counts["local_sheet_prefix_candidate"] == 1
    assert counts["slash_escape_candidate"] == 1
    assert counts["generated_name_mismatch"] == 1
    assert counts["unexplained_name_mismatch"] == 0


def test_name_diagnostics_classify_sheet_prefix_and_escaped_slash_without_acceptance() -> None:
    native = {"/IO5/Blue": {("J1", "1")}}
    imported = {"IO5{slash}Blue": {("J1", "1")}}
    report = compare_graphs(native, imported)
    assert report["name_difference_diagnostics"]["category_counts"]["local_sheet_and_escape_candidate"] == 1
    assert report["exact_connectivity_parity"] is False


def test_name_diagnostics_do_not_hide_signal_swap_or_open_net() -> None:
    native = {"/USB_D+": {("J1", "1")}, "/USB_D-": {("J1", "2")}}
    swapped = {"USB_D-": {("J1", "1")}, "USB_D+": {("J1", "2")}}
    swapped_report = compare_graphs(native, swapped)
    assert swapped_report["connected_pin_topology"]["connected_pin_topology_parity"] is True
    diagnostic = swapped_report["name_difference_diagnostics"]
    assert diagnostic["category_counts"]["unexplained_name_mismatch"] == 2
    assert swapped_report["exact_connectivity_parity"] is False

    disconnected = {"USB_D+": {("J1", "1")}}
    bad = compare_graphs(native, disconnected)["name_difference_diagnostics"]
    assert bad["status"] == "not_evaluated_physical_topology_mismatch"
    assert bad["evaluated_group_count"] == 0


def test_name_diagnostics_do_not_treat_arbitrary_rename_as_accepted() -> None:
    native = {"GND": {("U1", "1")}}
    imported = {"VCC": {("U1", "1")}}
    report = compare_graphs(native, imported)
    assert report["name_difference_diagnostics"]["category_counts"]["unexplained_name_mismatch"] == 1
    assert report["exact_connectivity_parity"] is False


def test_connected_pin_topology_handles_nc_and_power_annotations_without_waiving_names() -> None:
    native = {
        "GND": {("R1", "1"), ("U1", "2")},
        "unconnected-(J1-NC1)": {("J1", "NC1")},
    }
    imported = {
        "ground": {("R1", "1"), ("U1", "2"), ("#PWR01", "1"), ("#FLG01", "1")},
    }
    report = compare_graphs(native, imported)
    physical = report["connected_pin_topology"]
    assert physical["connected_pin_topology_parity"] is True
    assert physical["native_connected_pin_count"] == 2
    assert physical["native_no_connect_pin_count"] == 1
    assert physical["imported_power_annotation_pin_count"] == 1
    assert physical["imported_erc_power_flag_pin_count"] == 1
    assert physical["native_connected_topology_sha256"] == physical["imported_connected_topology_sha256"]
    assert report["exact_connectivity_parity"] is False


def test_native_and_imported_explicit_nc_groups_do_not_count_as_connected() -> None:
    native = {
        "GND": {("J1", "1")},
        "unconnected-(J1-NC-PadNC2)": {("J1", "NC2")},
    }
    imported = {
        "GND": {("J1", "1")},
        "unconnected-(J1-NC-PadNC2)": {("J1", "NC2")},
    }
    report = compare_graphs(native, imported)
    topo = report["connected_pin_topology"]
    assert topo["connected_pin_topology_parity"] is True
    assert topo["native_connected_pin_count"] == 1
    assert topo["imported_connected_pin_count"] == 1
    assert topo["native_no_connect_pin_count"] == 1
    assert topo["imported_no_connect_pin_count"] == 1
    assert report["exact_connectivity_parity"] is True
    assert report["name_difference_diagnostics"]["evaluated_group_count"] == 1

    # The connected-only diagnostic is intentionally weaker than exact graph.
    without_explicit_nc = compare_graphs(native, {"GND": {("J1", "1")}})
    assert without_explicit_nc["connected_pin_topology"]["connected_pin_topology_parity"] is True
    assert without_explicit_nc["exact_connectivity_parity"] is False


def test_connected_pin_topology_detects_both_open_and_short() -> None:
    native = {
        "/USB_D+": {("J1", "A6"), ("U1", "5")},
        "/USB_D-": {("J1", "A7"), ("U1", "6")},
    }
    missing = {
        "/USB_D+": {("J1", "A6")},
        "/USB_D-": {("J1", "A7"), ("U1", "6")},
    }
    short = {"/USB": {("J1", "A6"), ("U1", "5"), ("J1", "A7"), ("U1", "6")}}
    assert connected_pin_topology(native, missing)["missing_connected_pin_count"] == 1
    assert connected_pin_topology(native, missing)["connected_pin_topology_parity"] is False
    assert connected_pin_topology(native, short)["connected_pin_topology_parity"] is False


def test_connected_pin_topology_rejects_duplicate_or_unexpected_physical_pins() -> None:
    native = {"A": {("R1", "1")}, "B": {("R2", "1")}}
    duplicated = {"A": {("R1", "1")}, "B": {("R1", "1"), ("R2", "1")}}
    extra = {"A": {("R1", "1")}, "B": {("R2", "1"), ("R3", "1")}}
    assert connected_pin_topology(native, duplicated)["connected_pin_topology_parity"] is False
    assert connected_pin_topology(native, extra)["extra_connected_pin_count"] == 1
    assert connected_pin_topology(native, extra)["connected_pin_topology_parity"] is False


def test_physical_topology_is_not_named_signal_equivalence() -> None:
    native = {"USB_D+": {("J1", "A6")}, "USB_D-": {("J1", "A7")}}
    swapped = {"USB_D+": {("J1", "A7")}, "USB_D-": {("J1", "A6")}}
    report = compare_graphs(native, swapped)
    assert report["connected_pin_topology"]["connected_pin_topology_parity"] is True
    assert report["exact_connectivity_parity"] is False


def test_malformed_nc_group_cannot_be_ignored_as_parity() -> None:
    native = {"unconnected-invalid": {("J1", "A8"), ("J1", "B8")}}
    assert connected_pin_topology(native, {})["connected_pin_topology_parity"] is False


def test_missing_native_nets_is_not_a_valid_oracle(tmp_path: Path) -> None:
    path = tmp_path / "empty.xml"
    path.write_text("<export><nets/></export>", encoding="utf-8")
    with pytest.raises(ValueError, match="no nets"):
        read_native_netlist(path)


def test_native_duplicate_names_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.xml"
    path.write_text('<export><nets><net name="VCC"/><net name="VCC"/></nets></export>', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        read_native_netlist(path)


def test_invalid_native_xml_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "bad.xml"
    path.write_text("<export><nets>", encoding="utf-8")
    with pytest.raises(ElementTree.ParseError):
        read_native_netlist(path)


def test_manifest_pinned_real_reference_bytes() -> None:
    import json

    repo = Path(__file__).resolve().parents[1]
    manifest = json.loads((repo / "benchmarks/human-reference-corpus/manifest.json").read_text())
    record = next(r for r in manifest["references"] if r["reference_id"] == "mitayi-pico-d1")
    source, schematic, identity = source_artifacts(repo, record)
    assert source.is_dir()
    assert schematic.name == "Mitayi-Pico-D1.kicad_sch"
    assert len(identity) == 3


def test_reference_only_board_is_explicitly_not_run() -> None:
    from scripts.ci_real_kicad_reference_parity import measure_reference

    record = {
        "reference_id": "not-vendored-board",
        "upstream_commit": "0" * 40,
        "source_verification": "reference-only-hash-pinned",
    }
    result = measure_reference(Path(__file__).parents[1], record, tool="kicad-cli")
    assert result["status"] == "not_run"
    assert "reference-only" in result["reason"]


def test_missing_native_tool_does_not_claim_verification() -> None:
    import json

    from scripts.ci_real_kicad_reference_parity import measure_reference

    repo = Path(__file__).resolve().parents[1]
    manifest = json.loads((repo / "benchmarks/human-reference-corpus/manifest.json").read_text())
    record = next(r for r in manifest["references"] if r["reference_id"] == "mitayi-pico-d1")
    result = measure_reference(repo, record, tool="a_nonexistent_kicad_cli")
    assert result["status"] == "not_run"
    assert result["source_artifact_sha256"]
    assert result["reason"] == "native KiCad CLI unavailable"


def test_manifest_hash_mismatch_blocks_before_execution() -> None:
    import copy
    import json

    from scripts.ci_real_kicad_reference_parity import measure_reference

    repo = Path(__file__).resolve().parents[1]
    manifest = json.loads((repo / "benchmarks/human-reference-corpus/manifest.json").read_text())
    record = copy.deepcopy(next(r for r in manifest["references"] if r["reference_id"] == "mitayi-pico-d1"))
    record["artifacts"][0]["sha256"] = "0" * 64
    result = measure_reference(repo, record, tool="kicad-cli")
    assert result["status"] == "blocked"
    assert "Source identity mismatch" in result["reason"]


def test_strict_mode_rejects_blocked_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import ci_real_kicad_reference_parity as runner

    monkeypatch.setattr(
        runner, "build_report", lambda: {"status": "blocked", "measured": 2, "verified": 0, "blocked": 2, "not_run": 4}
    )
    output = tmp_path / "report.json"
    assert runner.main(["--output", str(output), "--strict"]) == 1
    assert output.is_file()
    assert runner.main(["--output", str(output)]) == 0


def test_native_xml_entities_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "entity.xml"
    path.write_text(
        '<!DOCTYPE export [<!ENTITY injected SYSTEM "file:///etc/passwd">]>'
        '<export><nets><net name="X"><node ref="U1" pin="&injected;"/></net></nets></export>',
        encoding="utf-8",
    )
    with pytest.raises(EntitiesForbidden):
        read_native_netlist(path)


@pytest.mark.parametrize(
    ("reference_id", "expected_nets", "expected_pins"),
    [
        ("jkc-9v-battery-indicator", 9, 24),
        ("jkc-hidden-wire-detector", 7, 16),
        ("jkc-light-activated-switch", 5, 13),
        ("jkc-astable-multivibrator", 6, 24),
        ("jkc-automatic-hand-sanitizer", 5, 12),
        ("jkc-clap-switch", 7, 22),
        ("jkc-obstacle-detector", 6, 18),
        ("jkc-temperature-fan", 4, 11),
        ("jkc-touch-sensor", 4, 10),
        ("jkc-water-level-indicator", 17, 41),
        ("atomic14-basic-esp32s3-dev-board", 47, 132),
    ],
)
def test_new_original_licensed_corpus_native_kicad_netlist(
    reference_id: str, expected_nets: int, expected_pins: int, tmp_path: Path
) -> None:
    """Independently prove KiCad 10 can open original reference bytes.

    This is source/CLI interoperability ONLY; importer parity, electrical
    correctness, DRC and independent human review are separate gates.
    """
    import hashlib
    import json
    import shutil
    import subprocess

    kicad = shutil.which("kicad-cli")
    if kicad is None:
        pytest.skip("KiCad 10 native CLI not installed; no independent netlist evidence")
    version = subprocess.run([kicad, "version"], check=False, capture_output=True, text=True, timeout=15)
    if version.returncode or not version.stdout.strip().startswith("10."):
        pytest.skip("KiCad 10 required; other versions cannot attest the reference corpus")

    manifest = json.loads((Path(__file__).parents[1] / "benchmarks/human-reference-corpus/manifest.json").read_text())
    record = next(r for r in manifest["references"] if r["reference_id"] == reference_id)
    origin = Path(__file__).parents[1] / "benchmarks" / "external" / reference_id / "source"
    for artifact in record["artifacts"]:
        source = origin / artifact["path"]
        raw = source.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]
        destination = tmp_path / source.name
        destination.write_bytes(raw)

    schematic = next(tmp_path.glob("*.kicad_sch"))
    xml = tmp_path / "native.xml"
    run = subprocess.run(
        [kicad, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(xml), str(schematic)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr[-500:]
    actual = read_native_netlist(xml)
    assert len(actual) == expected_nets
    assert sum(len(nodes) for nodes in actual.values()) == expected_pins
    assert all(nodes for nodes in actual.values())
    # Verify that native KiCad never edits the source repository originals.
    for artifact in record["artifacts"]:
        source = origin / artifact["path"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == artifact["sha256"]


def test_atomic14_esp32s3_direct_led_anodes_match_independent_native_kicad(
    tmp_path: Path,
) -> None:
    """Real upstream project includes three zero-wire direct LED/resistor contacts."""
    import shutil
    import subprocess

    from scripts.ci_real_kicad_reference_parity import (
        compare_graphs,
        read_imported_netlist,
    )

    cli = shutil.which("kicad-cli")
    if cli is None:
        pytest.skip("Native KiCad CLI required")
    version = subprocess.run([cli, "version"], capture_output=True, text=True, timeout=15, check=False)
    if version.returncode or not version.stdout.strip().startswith("10."):
        pytest.skip("Independent native KiCad 10 required")
    source_dir = Path(__file__).parents[1] / "benchmarks/external/atomic14-basic-esp32s3-dev-board/source"
    for suffix in ("pro", "sch", "pcb"):
        source = next(source_dir.glob(f"*.kicad_{suffix}"))
        (tmp_path / source.name).write_bytes(source.read_bytes())
    schematic = next(tmp_path.glob("*.kicad_sch"))
    project = next(tmp_path.glob("*.kicad_pro"))
    xml = tmp_path / "native.xml"
    completed = subprocess.run(
        [cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(xml), str(schematic)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-500:]
    native = read_native_netlist(xml)
    imported, metadata = read_imported_netlist(project)
    expected = {
        "Net-(D1-A)": {("D1", "2"), ("R4", "2")},
        "Net-(D2-A)": {("D2", "2"), ("R5", "2")},
        "Net-(D3-A)": {("D3", "2"), ("R6", "2")},
    }
    for name, connected_nodes in expected.items():
        assert native[name] == connected_nodes
        assert imported[name] == connected_nodes
    assert len(native) == len(imported) == 47
    assert sum(map(len, native.values())) == sum(map(len, imported.values())) == 132
    assert compare_graphs(native, imported)["exact_connectivity_parity"] is True
    # Full G0 acceptance remains blocked by unsupported constructs/PCB findings.
    assert metadata["finding_kinds"]["unsupported_construct"] > 0


def test_atomic14_native_kicad_excludes_embedded_power_symbols_from_physical_parts(
    tmp_path: Path,
) -> None:
    """Independent KiCad 10 netlist confirms original #PWR refs are annotations."""
    import shutil
    import subprocess

    cli = shutil.which("kicad-cli")
    if cli is None:
        pytest.skip("independent native KiCad CLI unavailable")
    version = subprocess.run([cli, "version"], capture_output=True, text=True, timeout=15, check=False)
    if version.returncode or not version.stdout.strip().startswith("10."):
        pytest.skip("KiCad 10 is needed for independent original-source evidence")

    source = Path(__file__).parents[1] / "benchmarks/external/atomic14-basic-esp32s3-dev-board/source"
    for original in source.glob("*.kicad_*"):
        (tmp_path / original.name).write_bytes(original.read_bytes())
    schematic = next(tmp_path.glob("*.kicad_sch"))
    xml_path = tmp_path / "native.xml"
    run = subprocess.run(
        [cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(xml_path), str(schematic)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr[-500:]
    tree = ElementTree.parse(xml_path)
    refs = {node.attrib["ref"] for node in tree.findall("./components/comp")}
    assert len(refs) == 21
    assert {"D1", "R4", "R5", "R6", "U2"} <= refs
    assert all(not ref.startswith("#PWR") for ref in refs)
