"""Whole-pilot KiCad placement: source-bound, unrouted and never production approved."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.ai_native_candidate_pilot import write_local_candidate
from scripts.ai_native_pilot_pcb_baseline import create_baseline

INTENT = "USB-C powered STM32 MCU board, 3.3V rail at 100 mA, I2C temperature sensor"


def test_real_native_full_placement_has_all_source_uuid_pads_and_blocking_drc(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    original = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in candidate.iterdir()}
    dest = tmp_path / "native-placement"
    report = create_baseline(candidate, dest)
    native = report["native"]
    assert report["fabrication_approved"] is False
    assert report["source_netlist_unmodified"] is True
    assert report["source_candidate_pcb_not_previously_present"] is True
    assert report["routing_status"] == "not_routed"
    summary = native["summary"]
    assert summary["footprints"] == 12
    assert summary["physical_pads"] == 100
    assert summary["nets"] == 8
    assert summary["named_net_pads"] == 55
    assert summary["tracks"] == summary["zones"] == 0
    assert summary["unconnected"] > 0
    # The four manufacturer-pattern hole-clearance violations still block PCB acceptance.
    # All library/instance mismatches must instead be resolved at their source.
    assert summary["drc_findings"] == 4
    assert native["drc_violations_by_type"] == {"hole_clearance": 4}
    assert all(
        native["drc_violations_by_type"].get(rule, 0) == 0
        for rule in ("shorting_items", "clearance", "solder_mask_bridge")
    )
    assert summary["unconnected"] >= 40
    assert native["schematic_connected_pin_net_subset_verified"]
    assert native["all_physical_nets_verified_against_source"]
    assert native["uuid_path_parity"]["verified"]
    assert len(native["footprints"]) == 12
    assert len({f["uuid"] for f in native["footprints"]}) == 12
    all_pads = [pad for fp in native["footprints"] for pad in fp["pads"]]
    assert len({pad["uuid"] for pad in all_pads}) == 100
    art = native["usb_c_manufacturer_art"]
    assert art["source_sha256"] == "db924af7ac6b9ed7b16df1f598a56268c6a32ec33583557b6e5d8aa5056e3b2c"
    assert art["graphical_items"] == 7
    assert art["three_d_model_qualified"] is False
    assert art["manufacturer_mating_approved"] is False
    sensor = next(fp for fp in native["footprints"] if fp["ref"] == "U3")
    thermal_pad = next(p for p in sensor["pads"] if p["number"] == "9")
    assert thermal_pad["front_paste"] is False
    assert thermal_pad["back_paste"] is False
    resistor = next(fp for fp in native["footprints"] if fp["ref"] == "R1")
    assert all(p["front_paste"] is True for p in resistor["pads"])
    assert len(native["s1_four_separate_uuid_net_associations"]) == 4
    assert {pad["net"] for pad in native["s1_four_separate_uuid_net_associations"]} == {"GND"}
    assert native["drc_cli_exit"] != 0
    assert native["fabrication_approved"] is False
    assert (dest / "SynthesizedBoard.kicad_pcb").stat().st_size > 10_000
    assert (dest / "SynthesizedBoard.kicad_sch").stat().st_size > 10_000
    assert (dest / "fp-lib-table").is_file()
    assert len(list((dest / "ZapTracePilot.pretty").glob("*.kicad_mod"))) == 12
    assert (dest / "native-pcb-drc.json").is_file()
    for name, expected in report["artifact_sha256"].items():
        assert hashlib.sha256((dest / name).read_bytes()).hexdigest() == expected
    for name, expected in original.items():
        assert hashlib.sha256((candidate / name).read_bytes()).hexdigest() == expected


def test_placement_rejects_source_tampering_and_existing_destination(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    exists = tmp_path / "preserve"
    exists.mkdir()
    (exists / "keep").write_text("USER DATA")
    with pytest.raises(ValueError, match="Source must be real and output directory new"):
        create_baseline(candidate, exists)
    assert (exists / "keep").read_text() == "USER DATA"
    (candidate / "design.json").write_text('{"tampered":true}')
    with pytest.raises(ValueError, match="Tampered candidate source artifact"):
        create_baseline(candidate, tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()


def test_placement_rejects_forged_gct_geometry_even_with_new_manifest_sha(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    design_path = candidate / "design.json"
    design = json.loads(design_path.read_text())
    pad = next(p for p in design["components"]["J1"]["footprint_def"]["pads"] if p["id"] == "S1")
    pad["size"][0] += 0.5
    design_path.write_text(json.dumps(design))
    manifest = json.loads((candidate / "manifest.json").read_text())
    manifest["files_sha256"]["design.json"] = hashlib.sha256(design_path.read_bytes()).hexdigest()
    (candidate / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="USB-C geometry does not match"):
        create_baseline(candidate, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()
