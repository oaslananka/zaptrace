"""Exact KiCad native pin-number, pad-number and named-net crossprobe; never global approval."""

from __future__ import annotations

import copy
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from review_studio_pin_net_crossprobe import scoped_pin_net_crossprobe  # noqa: E402


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict, dict]:
    root = ET.Element("export", {"version": "E"})
    components = ET.SubElement(root, "components")
    nets = ET.SubElement(root, "nets")
    for ref in ("R1", "R2"):
        comp = ET.SubElement(components, "comp", {"ref": ref})
        units = ET.SubElement(comp, "units")
        unit = ET.SubElement(units, "unit")
        pins = ET.SubElement(unit, "pins")
        for number in ("P1", "P2"):
            ET.SubElement(pins, "pin", {"num": number})
    named_nets = [
        ("/VCC_3V3", (("R1", "P1"), ("R2", "P1"))),
        ("/I2C_SDA", (("R1", "P2"),)),
        ("/I2C_SCL", (("R2", "P2"),)),
    ]
    for i, (name, nodes) in enumerate(named_nets, 1):
        net = ET.SubElement(nets, "net", {"code": str(i), "name": name})
        for ref, pin in nodes:
            ET.SubElement(net, "node", {"ref": ref, "pin": pin})
    source = tmp_path / "original.xml"
    proposal = tmp_path / "proposed.xml"
    ET.ElementTree(root).write(source, encoding="unicode")
    proposal.write_bytes(source.read_bytes())
    pcb = {
        "footprints": [
            {"ref": "R1", "pad_count": 2},
            {"ref": "R2", "pad_count": 2},
        ],
        "pads": [
            {"ref": "R1", "pad": "P1", "net": "/VCC_3V3"},
            {"ref": "R1", "pad": "P2", "net": "/I2C_SDA"},
            {"ref": "R2", "pad": "P1", "net": "/VCC_3V3"},
            {"ref": "R2", "pad": "P2", "net": "/I2C_SCL"},
        ],
    }
    return source, proposal, pcb, copy.deepcopy(pcb)


def _check(tmp_path: Path, *, mutation=None) -> dict:
    source, proposed, before, after = _fixture(tmp_path)
    if mutation is not None:
        mutation(source, proposed, before, after)
    return scoped_pin_net_crossprobe(source, proposed, before, after, ["R1", "R2"], project_rules_crosslinked=True)


def test_two_realistic_components_in_both_states_match_only_scoped_pins(tmp_path: Path) -> None:
    result = _check(tmp_path)
    assert result["totals"] == {"matched": 8, "mismatch": 0, "unverifiable": 0}
    assert result["scoped_pin_net_consistent"] is True
    assert result["full_project_covered"] is False
    assert result["pcb_schematic_parity_verified"] is False
    assert result["electrically_approved"] is False


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("new_net", "native_net_name_conflict"),
        ("no_net", "unnamed_or_unconnected_net"),
        ("different_pin", "schematic_pin_missing_for_pcb_pad"),
        ("missing_pad", "pcb_pad_missing_for_schematic_pin"),
        ("missing_schematic", "schematic_pin_missing_for_pcb_pad"),
    ],
)
def test_conflicts_are_explicit_and_fail_closed(tmp_path: Path, mutation: str, expected: str) -> None:
    source, proposal, before, after = _fixture(tmp_path)
    if mutation == "new_net":
        after["pads"][0]["net"] = "/WRONG"
    elif mutation == "no_net":
        before["pads"][0]["net"] = "(no net)"
    elif mutation == "different_pin":
        after["pads"][0]["pad"] = "1"
    elif mutation == "missing_pad":
        after["pads"].pop()
        after["footprints"][1]["pad_count"] = 1
    else:
        text = proposal.read_text()
        text = text.replace('ref="R2"', 'ref="R3"')
        proposal.write_text(text)
    result = scoped_pin_net_crossprobe(source, proposal, before, after, ["R1", "R2"], project_rules_crosslinked=True)
    assert expected in result["reasons_when_unverified"]
    assert result["scoped_pin_net_consistent"] is False
    assert result["pcb_schematic_parity_verified"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_pad",
        "duplicate_sch_pin",
        "same_pin_two_nets",
        "missing_comp_ref",
        "duplicate_net",
        "unknown_component",
    ],
)
def test_ambiguous_native_inputs_are_rejected(tmp_path: Path, mutation: str) -> None:
    source, proposal, before, after = _fixture(tmp_path)
    if mutation == "duplicate_pad":
        after["pads"].append(copy.deepcopy(after["pads"][0]))
    else:
        tree = ET.parse(source)
        root = tree.getroot()
        if mutation == "duplicate_sch_pin":
            pins = root.find("./components/comp/units/unit/pins")
            ET.SubElement(pins, "pin", {"num": "P1"})
        elif mutation == "same_pin_two_nets":
            net = root.find("./nets/net[@name='/I2C_SDA']")
            ET.SubElement(net, "node", {"ref": "R1", "pin": "P1"})
        elif mutation == "missing_comp_ref":
            root.find("./components/comp").attrib.pop("ref")
        elif mutation == "duplicate_net":
            ET.SubElement(root.find("nets"), "net", {"name": "/VCC_3V3"})
        else:
            net = root.find("./nets/net")
            ET.SubElement(net, "node", {"ref": "NONEXISTENT", "pin": "1"})
        tree.write(source, encoding="unicode")
    with pytest.raises(ValueError):
        scoped_pin_net_crossprobe(source, proposal, before, after, ["R1", "R2"], project_rules_crosslinked=True)


def test_duplicate_moved_reference_is_rejected(tmp_path: Path) -> None:
    source, proposed, before, after = _fixture(tmp_path)
    with pytest.raises(ValueError, match="unique"):
        scoped_pin_net_crossprobe(source, proposed, before, after, ["R1", "R1"], project_rules_crosslinked=True)


def test_crossprobe_ui_does_not_claim_global_authority() -> None:
    html = (Path(__file__).resolve().parents[1] / "scripts/review_studio_change_diff_template.html").read_text()
    for key in (
        "pinNetPanel",
        "pinNetStatus",
        "pinNetResults",
        "pinNetSelected",
        "initPinNetCrossprobe",
        "Full PCB/schematic parity",
    ):
        assert key in html
    assert "NOT VERIFIED" in html


def test_identical_pin_and_net_names_without_project_rules_are_not_verified(tmp_path: Path) -> None:
    source, proposal, before, after = _fixture(tmp_path)
    result = scoped_pin_net_crossprobe(source, proposal, before, after, ["R1", "R2"], project_rules_crosslinked=False)
    assert result["totals"]["matched"] == 8
    assert result["scoped_pin_net_consistent"] is False
    assert result["project_rule_context_crosslinked"] is False
    assert "project_rule_context_not_crosslinked" in result["reasons_when_unverified"]


def test_crossprobe_native_records_are_available_for_explicit_audit_evidence(tmp_path: Path) -> None:
    from review_studio_change_diff import evidence_catalog

    result = _check(tmp_path)
    document = {"changed": [], "drc": {"before_rules": 0, "after_rules": 0}, "schematic": None, "crossprobe": result}
    catalog = evidence_catalog(document)
    options = {item["id"]: item for item in catalog}
    assert "pin-net:summary" in options
    assert options["pin-net:1"]["ref"] == "R1"
    assert options["pin-net:1"]["rule"] == "exact_pin_and_named_net"
    assert options["pin-net:1"]["kind"] == "native_pin_pad_net_scoped_diagnostics"
    assert len(options) == len(catalog)
    assert (
        "pin-net:"
        in (Path(__file__).resolve().parents[1] / "scripts/review_studio_change_diff_template.html").read_text()
    )
