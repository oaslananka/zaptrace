"""Real user result: source-backed physical pad contacts join schematic nets, without dedup."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from zaptrace.kicad.project_importer import import_kicad_project

SOURCE = Path(__file__).parents[1] / "benchmarks/external/atomic14-basic-esp32s3-dev-board/source"


def _component(result, ref: str):
    return next(component for component in result.design.components.values() if component.ref == ref)


def _clone_project(tmp_path: Path) -> Path:
    for path in SOURCE.glob("*.kicad_*"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    return next(tmp_path.glob("*.kicad_pro"))


def _change_r4_pad_two_net(path: Path, target_net: str, target_id: int) -> None:
    pcb_path = next(path.glob("*.kicad_pcb"))
    original = pcb_path.read_text()
    footprint_ref = original.index('(property "Reference" "R4"')
    pad_two = original.index('(pad "2"', footprint_ref)
    native = '(net 45 "Net-(D1-A)")'
    pos = original.index(native, pad_two)
    pcb_path.write_text(original[:pos] + f'(net {target_id} "{target_net}")' + original[pos + len(native) :])


def test_real_original_board_keeps_145_physical_contact_instances_and_real_nets() -> None:
    result = import_kicad_project(next(SOURCE.glob("*.kicad_pro")))
    design = result.design
    assert sum(len(c.pcb_pad_contacts) for c in design.components.values()) == 145
    u2 = _component(result, "U2")
    assert len(u2.pcb_pad_contacts) == 51
    assert len([pad for pad in u2.pcb_pad_contacts if pad.number == "41"]) == 11
    assert len([pad for pad in _component(result, "U3").pcb_pad_contacts if pad.number == "2"]) == 2
    j1 = _component(result, "J1")
    assert len([pad for pad in j1.pcb_pad_contacts if pad.number == ""]) == 2
    assert all(pad.schematic_net_id is None for pad in j1.pcb_pad_contacts if not pad.number)
    r4 = _component(result, "R4")
    d1 = _component(result, "D1")
    r4_contact = next(p for p in r4.pcb_pad_contacts if p.number == "2")
    d1_contact = next(p for p in d1.pcb_pad_contacts if p.number == "2")
    assert r4_contact.board_net_name == "Net-(D1-A)" == d1_contact.board_net_name
    assert r4_contact.schematic_net_id == r4.pins["2"].net == d1.pins["2"].net
    assert r4_contact.position_in_footprint_mm == pytest.approx((0.825, 0.0))
    assert r4_contact.size_mm == pytest.approx((0.8, 0.95))
    assert r4_contact.shape == "roundrect"
    assert r4_contact.kind == "smd"
    assert r4_contact.source_uuid
    assert not any(f.kind == "pcb_pad_net_mismatch" for f in result.findings)
    dumped = design.model_dump(mode="json")
    assert len(dumped["components"][r4.id]["pcb_pad_contacts"]) == 2
    assert dumped["components"][r4.id]["pcb_pad_contacts"][1]["schematic_net_id"] in design.nets


def test_real_original_board_mismatched_copper_net_reports_finding_not_silent_update(
    tmp_path: Path,
) -> None:
    project = _clone_project(tmp_path)
    _change_r4_pad_two_net(tmp_path, "+5V", 3)
    result = import_kicad_project(project)
    r4 = _component(result, "R4")
    pad_two = next(p for p in r4.pcb_pad_contacts if p.number == "2")
    assert pad_two.board_net_name == "+5V"
    assert pad_two.schematic_net_id == next(net.id for net in result.design.nets.values() if net.name == "+5V")
    assert pad_two.schematic_net_id != r4.pins["2"].net
    assert any(f.kind == "pcb_pad_net_mismatch" and "R4" in f.message for f in result.findings)
    assert r4.pins["2"].net == next(net.id for net in result.design.nets.values() if net.name == "Net-(D1-A)")


def test_unknown_board_net_never_invents_a_canonical_connection(tmp_path: Path) -> None:
    project = _clone_project(tmp_path)
    _change_r4_pad_two_net(tmp_path, "Ghost-net-not-in-schematic", 45)
    result = import_kicad_project(project)
    r4 = _component(result, "R4")
    pad = next(p for p in r4.pcb_pad_contacts if p.number == "2")
    assert pad.board_net_name == "Ghost-net-not-in-schematic"
    assert pad.schematic_net_id is None
    assert any(f.kind == "pcb_pad_unknown_net" for f in result.findings)


def test_independent_native_pcbnew_original_pad_instances_match_source_contacts() -> None:
    """KiCad 10 PCB API oracle for local positions, numbers and nets, not a synthetic fixture."""
    if shutil.which("kicad-cli") is None:
        pytest.skip("native KiCad 10 required")
    script = """
import json, pcbnew as k, sys
b = k.LoadBoard(sys.argv[1])
out = [[f.GetReference(),p.GetNumber(),p.GetNetname(),
        [p.GetFPRelativePosition().x/1000000, p.GetFPRelativePosition().y/1000000]]
       for f in b.GetFootprints() for p in f.Pads()]
print(json.dumps({"version":k.GetBuildVersion(), "contacts":out}))
"""
    pcb = next(SOURCE.glob("*.kicad_pcb"))
    run = subprocess.run(["/usr/bin/python3", "-c", script, str(pcb)], capture_output=True, text=True, timeout=60)
    if run.returncode and ("No module named" in run.stderr or "not found" in run.stderr):
        pytest.skip("native KiCad pcbnew Python binding unavailable")
    assert run.returncode == 0, run.stderr[-400:]
    native = json.loads(run.stdout)
    if not str(native["version"]).startswith("10."):
        pytest.skip("independent native KiCad 10 PCB required")
    src = import_kicad_project(next(SOURCE.glob("*.kicad_pro")))
    expected = Counter(
        (
            component.ref,
            contact.number,
            contact.board_net_name,
            tuple(round(v, 6) for v in contact.position_in_footprint_mm),
        )
        for component in src.design.components.values()
        for contact in component.pcb_pad_contacts
    )
    actual = Counter(
        (ref, num, name, tuple(round(x, 6) for x in relative)) for ref, num, name, relative in native["contacts"]
    )
    assert sum(expected.values()) == sum(actual.values()) == 145
    assert expected == actual


def test_duplicate_board_footprint_reference_does_not_assign_pads_to_arbitrary_component(
    tmp_path: Path,
) -> None:
    project = _clone_project(tmp_path)
    pcb = next(tmp_path.glob("*.kicad_pcb"))
    source = pcb.read_text()
    original = '(property "Reference" "D1"'
    assert source.count(original) == 1
    pcb.write_text(source.replace(original, '(property "Reference" "R4"', 1))
    result = import_kicad_project(project)
    assert _component(result, "R4").pcb_pad_contacts == []
    assert _component(result, "D1").pcb_pad_contacts == []
    assert any(f.kind == "pcb_pad_ambiguous_reference" for f in result.findings)


def test_missing_original_physical_pad_geometry_never_generates_a_fake_contact(
    tmp_path: Path,
) -> None:
    project = _clone_project(tmp_path)
    pcb = next(tmp_path.glob("*.kicad_pcb"))
    source = pcb.read_text()
    ref_index = source.index('(property "Reference" "R4"')
    pad_index = source.index('(pad "2"', ref_index)
    size = "(size 0.8 0.95)"
    size_index = source.index(size, pad_index)
    pcb.write_text(source[:size_index] + source[size_index + len(size) :])
    result = import_kicad_project(project)
    r4 = _component(result, "R4")
    assert len(r4.pcb_pad_contacts) == 1
    assert any(f.kind == "pcb_pad_unmapped_geometry" for f in result.findings)
