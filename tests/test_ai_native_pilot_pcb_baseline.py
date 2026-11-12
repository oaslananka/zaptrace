"""Whole-pilot KiCad placement: source-bound, unrouted and never production approved."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.ai_native_candidate_pilot import write_local_candidate
from scripts.ai_native_pilot_pcb_baseline import create_baseline

NATIVE_KICAD_PYTHON = (
    "/usr/local/bin/kicad-python" if os.environ.get("ZAPTRACE_KICAD_PYTHON") == "appimage" else "/usr/bin/python3"
)


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
    assert summary["native_pad_objects"] == 101
    assert summary["non_copper_stencil_only"] == 1
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
    assert len({pad["uuid"] for pad in all_pads}) == 101
    art = native["usb_c_manufacturer_art"]
    assert art["source_sha256"] == "db924af7ac6b9ed7b16df1f598a56268c6a32ec33583557b6e5d8aa5056e3b2c"
    assert art["graphical_items"] == 7
    assert art["three_d_model_qualified"] is False
    assert art["manufacturer_mating_approved"] is False
    passive = native["passive_source_courtyards"]
    assert passive["refs"] == ["C1", "C2", "C3", "R1", "R2", "R3", "R4", "R5"]
    assert passive["courtyard_mm"] == [2.0, 1.5]
    assert passive["min_pad_edge_margin_mm"] == 0.15
    assert passive["fabrication_approved"] is False
    sensor = next(fp for fp in native["footprints"] if fp["ref"] == "U3")
    assert len(sensor["pads"]) == 10
    paste_only = [p for p in sensor["pads"] if p["number"] == ""]
    assert len(paste_only) == 1
    assert paste_only[0]["net"] == ""
    assert paste_only[0]["front_paste"] is True
    thermal_pad = next(p for p in sensor["pads"] if p["number"] == "9")
    assert thermal_pad["front_paste"] is False
    assert thermal_pad["back_paste"] is False
    mcu = next(fp for fp in native["footprints"] if fp["ref"] == "U2")
    assert mcu["footprint"] == "ZapTrace:LQFP-48_7x7mm_P0.5mm"
    for number in ("5", "6"):
        physical = [p for p in mcu["pads"] if p["number"] == number]
        assert len(physical) == 1 and physical[0]["net"] == ""
    regulator = next(fp for fp in native["footprints"] if fp["ref"] == "U1")
    assert regulator["footprint"] == "ZapTrace:SOT-23-5"
    resistor = next(fp for fp in native["footprints"] if fp["ref"] == "R1")
    assert all(p["front_paste"] is True for p in resistor["pads"])
    assert len(native["s1_four_separate_uuid_net_associations"]) == 4
    assert {pad["net"] for pad in native["s1_four_separate_uuid_net_associations"]} == {"GND"}
    assert native["drc_cli_exit"] != 0
    assert native["fabrication_approved"] is False
    assert (dest / "SynthesizedBoard.kicad_pcb").stat().st_size > 10_000
    assert (dest / "SynthesizedBoard.kicad_sch").stat().st_size > 10_000
    assert (dest / "fp-lib-table").is_file()
    assert len(list((dest / "ZapTracePilot.pretty").glob("*.kicad_mod"))) == 9
    assert len(list((dest / "ZapTrace.pretty").glob("*.kicad_mod"))) == 3
    for ref in passive["refs"]:
        local = (dest / "ZapTracePilot.pretty" / f"ZT_{ref}.kicad_mod").read_text()
        assert local.count('(layer "F.CrtYd")') == 1
        assert "(start -1 -0.75) (end 1 0.75)" in local
    assert (dest / "native-pcb-drc.json").is_file()
    for name, expected in report["artifact_sha256"].items():
        assert hashlib.sha256((dest / name).read_bytes()).hexdigest() == expected
    for name, expected in original.items():
        assert hashlib.sha256((candidate / name).read_bytes()).hexdigest() == expected


def test_u3_native_oracle_rejects_stencil_loss_and_copper_shape_tampering(tmp_path: Path) -> None:
    """Adversarially alter an actual KiCad board *in memory* after successful export."""
    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    dest = tmp_path / "native-placement"
    create_baseline(candidate, dest)
    python_code = """
import pcbnew as pcb
from pathlib import Path
from scripts.ai_native_pilot_pcb_native import assert_native_u3_manufacturer_geometry

board_path = Path(__import__("sys").argv[1]).resolve()
board = pcb.LoadBoard(str(board_path))
u3 = next(fp for fp in board.GetFootprints() if fp.GetReference() == "U3")
assert_native_u3_manufacturer_geometry(u3)

stencil = next(p for p in u3.Pads() if p.GetNumber() == "")
u3.Remove(stencil)
try:
    assert_native_u3_manufacturer_geometry(u3)
except ValueError as exc:
    assert "stencil pad" in str(exc)
else:
    raise AssertionError("Missing manufacturer paste-only stencil pad was accepted")

board = pcb.LoadBoard(str(board_path))
u3 = next(fp for fp in board.GetFootprints() if fp.GetReference() == "U3")
thermal = next(p for p in u3.Pads() if p.GetNumber() == "9")
thermal.SetShape(pcb.PAD_SHAPE_RECT)
try:
    assert_native_u3_manufacturer_geometry(u3)
except ValueError as exc:
    assert "polygon" in str(exc)
else:
    raise AssertionError("Modified SHT31 thermal copper primitive was accepted")
print("U3_STENCIL_AND_COPPER_MUTATION_REJECTED")
"""
    result = subprocess.run(
        [NATIVE_KICAD_PYTHON, "-B", "-c", python_code, str(dest / "SynthesizedBoard.kicad_pcb")],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-1200:]
    assert "U3_STENCIL_AND_COPPER_MUTATION_REJECTED" in result.stdout


def test_mcu_unmodeled_crystal_pads_cannot_be_assigned_a_fabricated_net(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    source = candidate / "design.json"
    design = json.loads(source.read_text())
    assert design["components"]["U2"]["package_pin_map"]["5"] == "PD0"
    assert design["components"]["U2"]["package_pin_map"]["6"] == "PD1"
    design["nets"]["GND"]["nodes"].append({"component_ref": "U2", "pin_name": "PD0"})
    source.write_text(json.dumps(design))
    manifest = json.loads((candidate / "manifest.json").read_text())
    manifest["files_sha256"]["design.json"] = hashlib.sha256(source.read_bytes()).hexdigest()
    (candidate / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Unmodeled U2 PD0/PD1 pins must remain electrically unconnected"):
        create_baseline(candidate, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


@pytest.mark.parametrize("modification", ["undersized_courtyard", "changed_copper"])
def test_passive_0402_source_courtyard_contract_rejects_mutation(tmp_path: Path, modification: str) -> None:
    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    source = candidate / "design.json"
    design = json.loads(source.read_text())
    footprint = design["components"]["R1"]["footprint_def"]
    if modification == "undersized_courtyard":
        footprint["courtyard"] = [1.7, 1.5]
    else:
        footprint["pads"][0]["size"][0] += 0.01
    source.write_text(json.dumps(design))
    manifest = json.loads((candidate / "manifest.json").read_text())
    manifest["files_sha256"]["design.json"] = hashlib.sha256(source.read_bytes()).hexdigest()
    (candidate / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="0402"):
        create_baseline(candidate, tmp_path / "must-not-exist")
    assert not (tmp_path / "must-not-exist").exists()


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


@pytest.mark.parametrize("side", ["candidate_ancestor", "output_ancestor", "output_parent_reference"])
def test_baseline_refuses_indirect_symlink_paths(tmp_path: Path, side: str) -> None:
    """Never read a different source or write to an aliased output location."""
    safe = tmp_path / "safe"
    safe.mkdir()
    candidate = safe / "candidate"
    candidate.mkdir()
    protected = tmp_path / "outside"
    protected.mkdir()
    (protected / "user-data.txt").write_text("do not touch")
    output = safe / "result"
    if side == "candidate_ancestor":
        alias = tmp_path / "candidate-alias"
        alias.symlink_to(safe, target_is_directory=True)
        candidate = alias / "candidate"
        expected = "Unsafe candidate path"
    elif side == "output_ancestor":
        alias = tmp_path / "output-alias"
        alias.symlink_to(protected, target_is_directory=True)
        output = alias / "result"
        expected = "Unsafe output path"
    else:
        output = safe / "temp" / ".." / "result"
        (safe / "temp").mkdir()
        expected = "Unsafe output path"

    with pytest.raises(ValueError, match=expected):
        create_baseline(candidate, output)
    assert (protected / "user-data.txt").read_text() == "do not touch"
    assert not (safe / "result").exists()


def test_baseline_rejects_indirect_manifest_file(tmp_path: Path) -> None:
    """Do not follow a manifest symlink before checking source integrity."""
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    external_manifest = tmp_path / "other-users-manifest.json"
    external_manifest.write_text('{"fabrication_approved":false}')
    (candidate / "manifest.json").symlink_to(external_manifest)
    with pytest.raises(ValueError, match="Unsafe candidate manifest"):
        create_baseline(candidate, tmp_path / "result")
    assert external_manifest.read_text() == '{"fabrication_approved":false}'
    assert not (tmp_path / "result").exists()


@pytest.mark.parametrize("changed_name", ["design.json", "candidate-report.json", "manifest.json"])
def test_pilot_fails_closed_if_candidate_changes_during_native_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_name: str
) -> None:
    """Never publish 'source-bound' evidence for a different candidate revision."""
    from scripts import ai_native_pilot_pcb_baseline as baseline

    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    original = {p.name: p.read_bytes() for p in candidate.iterdir()}
    dest = tmp_path / "native-placement"
    selected = candidate / changed_name

    def mutation_after_native_staging(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[-1].startswith(str(tmp_path))
        stage = Path(command[-1])
        assert (stage / "placed-design.json").is_file()
        selected.write_bytes(original[changed_name] + b"\n")
        (stage / "native-placement-audit.json").write_text('{"summary":{"drc_findings":4}}')
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(baseline.subprocess, "run", mutation_after_native_staging)
    with pytest.raises(ValueError, match="Candidate source changed during native verification"):
        create_baseline(candidate, dest)
    assert not dest.exists()
    assert selected.read_bytes() == original[changed_name] + b"\n"
    for name, original_bytes in original.items():
        if name != changed_name:
            assert (candidate / name).read_bytes() == original_bytes


def test_pilot_rechecks_output_ancestor_before_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Do not publish into a parent directory redirected by another local process."""
    from scripts import ai_native_pilot_pcb_baseline as baseline

    candidate = tmp_path / "candidate"
    write_local_candidate(INTENT, candidate)
    parent = tmp_path / "requested"
    parent.mkdir()
    user_folder = tmp_path / "different-user-folder"
    user_folder.mkdir()
    (user_folder / "personal-notes.txt").write_text("DO NOT ALTER")
    destination = parent / "result"

    def redirect_parent_during_native_stage(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        stage = Path(command[-1])
        (stage / "native-placement-audit.json").write_text('{"summary":{}}')
        parent.rename(tmp_path / "original-parent-moved")
        parent.symlink_to(user_folder, target_is_directory=True)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(baseline.subprocess, "run", redirect_parent_during_native_stage)
    with pytest.raises((ValueError, OSError), match="Unsafe output path|symbolic link|Refusing|No such file"):
        create_baseline(candidate, destination)
    assert not (user_folder / "result").exists()
    assert (user_folder / "personal-notes.txt").read_text() == "DO NOT ALTER"
