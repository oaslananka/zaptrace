"""Fail-closed semantic KiCad PCB proposal review: no fabricated approvals."""

from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("review_change_diff", ROOT / "scripts/review_studio_change_diff.py")
assert spec and spec.loader
change = importlib.util.module_from_spec(spec)
spec.loader.exec_module(change)


def fixture_data() -> tuple[dict, dict, dict]:
    original = {
        "origin": [0, 0],
        "size": [50, 35],
        "zones": 0,
        "tracks": 0,
        "copper": [],
        "kicad": "10.0.7",
        "footprints": [{"ref": "R1", "value": "1k", "footprint": "Resistor", "pad_count": 2, "x": 20.0, "y": 20.0}],
        "pads": [
            {"ref": "R1", "pad": str(i), "net": net, "size": [1.0, 1.0], "x": x, "y": 20.0}
            for i, net, x in ((1, "GND", 19.0), (2, "SIG", 21.0))
        ],
    }
    proposed = deepcopy(original)
    proposed["footprints"][0].update(x=21.0, y=20.5)
    for pad in proposed["pads"]:
        pad["x"] += 1
        pad["y"] += 0.5
    proof = {
        "type": "PCB_UNROUTED_FOOTPRINT_PLACEMENT_ECO",
        "status": "native_drc_verified_copy_not_original",
        "source_sha256": "s" * 64,
        "working_sha256": "p" * 64,
        "ref": "R1",
        "old_mm": [20.0, 20.0],
        "new_mm": [21.0, 20.5],
        "fabApproved": False,
        "electricallyApproved": False,
    }
    return original, proposed, proof


def test_actual_footprint_translation_and_native_state_contract() -> None:
    source, target, proof = fixture_data()
    assert change.check_native_board_transition(source, target, proof, "s" * 64, "p" * 64) == [
        {
            "ref": "R1",
            "old_mm": [20.0, 20.0],
            "new_mm": [21.0, 20.5],
            "delta_mm": [1.0, 0.5],
            "pad_count": 2,
            "risk": "human_review_required",
        }
    ]


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("source", "state hash"),
        ("approved", "cannot authorize"),
        ("net", "net or dimensions"),
        ("pad", "rotation"),
        ("copper", "Copper"),
        ("footprint", "identity"),
        ("add", "identity"),
        ("manifest", "positions differ"),
        ("zone", "Copper"),
    ],
)
def test_changed_or_forged_design_fails_closed(mutation: str, expected: str) -> None:
    before, after, proof = fixture_data()
    if mutation == "source":
        proof["source_sha256"] = "b" * 64
    elif mutation == "approved":
        proof["fabApproved"] = True
    elif mutation == "net":
        after["pads"][0]["net"] = "VCC"
    elif mutation == "pad":
        after["pads"][0]["x"] += 0.2
    elif mutation == "copper":
        after["copper"] = [{"net": "GND", "layer": "F.Cu"}]
    elif mutation == "footprint":
        after["footprints"][0]["footprint"] = "ModifiedFootprint"
    elif mutation == "add":
        after["footprints"].append(dict(after["footprints"][0], ref="R2"))
    elif mutation == "manifest":
        proof["new_mm"] = [21.0, 20.6]
    elif mutation == "zone":
        after["zones"] += 1
    with pytest.raises(ValueError, match=expected):
        change.check_native_board_transition(before, after, proof, "s" * 64, "p" * 64)


def test_offline_view_explicitly_blocks_fabrication_and_shows_mode_options() -> None:
    template = change.TEMPLATE.read_text()
    assert template.count("__CHANGE_DATA__") == 1
    for label in (
        'data-view="current"',
        'data-view="proposed"',
        'data-view="overlay"',
        'data-view="changed"',
        "Approve / fabricate (unavailable)",
        "disabled",
        "Stale source/target state",
        "importDecision(file)",
        "schema_version:1",
    ):
        assert label in template


def test_decision_export_is_not_a_signed_approval_or_drc_waiver() -> None:
    js = change.TEMPLATE.read_text()
    assert "fabrication_approved:false,electrically_approved:false,source_modified:false" in js
    assert "raw.source_sha256!==DATA.source_sha256" in js
    assert "raw.proposed_sha256!==DATA.proposed_sha256" in js
    assert "raw.state_hash!==DATA.state_hash" in js
    assert "Object.keys(raw).sort().join" in js
