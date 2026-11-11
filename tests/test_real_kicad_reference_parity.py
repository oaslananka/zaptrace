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
