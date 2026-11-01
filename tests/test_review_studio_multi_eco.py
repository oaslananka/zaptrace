"""Hermetic multi-footprint state/evidence checks; optional real KiCad smoke."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from review_studio_change_diff import check_native_board_transition  # noqa: E402


def sample() -> tuple[dict, dict, dict]:
    before = {
        "origin": [0, 0],
        "size": [50, 35],
        "zones": 0,
        "tracks": 0,
        "copper": [],
        "kicad": "10.0.7",
        "footprints": [],
        "pads": [],
    }
    for ref, x in (("R1", 20.0), ("R2", 35.0)):
        before["footprints"].append(
            {"ref": ref, "value": "1k", "footprint": "R_0805", "pad_count": 2, "x": x, "y": 20.0}
        )
        for pin, offset in (("1", -0.825), ("2", 0.825)):
            before["pads"].append(
                {
                    "ref": ref,
                    "pad": pin,
                    "net": "(no net)",
                    "size": [0.8, 0.95],
                    "x": x + offset,
                    "y": 20.0,
                }
            )
    after = copy.deepcopy(before)
    translations = {"R1": (1.0, 0.5), "R2": (-1.0, -0.5)}
    for item in after["footprints"] + after["pads"]:
        dx, dy = translations[item["ref"]]
        item["x"] += dx
        item["y"] += dy
    steps = [
        {
            "ref": ref,
            "dx_mm": dx,
            "dy_mm": dy,
            "source_sha256": source,
            "working_sha256": dest,
            "old_mm": [x, 20.0],
            "new_mm": [x + dx, 20.0 + dy],
            "native_drc": {"new_drc_rules": 0},
        }
        for ref, x, dx, dy, source, dest in (
            ("R1", 20.0, 1.0, 0.5, "a" * 64, "c" * 64),
            ("R2", 35.0, -1.0, -0.5, "c" * 64, "b" * 64),
        )
    ]
    proof = {
        "type": "PCB_UNROUTED_MULTI_FOOTPRINT_PLACEMENT_ECO",
        "status": "native_drc_verified_copy_not_original",
        "source_sha256": "a" * 64,
        "working_sha256": "b" * 64,
        "moves": [{k: item[k] for k in ("ref", "old_mm", "new_mm")} for item in steps],
        "steps": steps,
        "fabApproved": False,
        "electricallyApproved": False,
    }
    return before, after, proof


def test_two_distinct_pad_sets_are_source_matched() -> None:
    before, after, proof = sample()
    changes = check_native_board_transition(before, after, proof, "a" * 64, "b" * 64)
    assert [item["ref"] for item in changes] == ["R1", "R2"]
    assert [item["pad_count"] for item in changes] == [2, 2]


@pytest.mark.parametrize(
    "tamper",
    [
        "net",
        "pad",
        "manifest",
        "duplicate",
        "chain",
        "endpoint",
        "approval",
        "copper",
        "drc",
        "missing",
        "unplanned",
    ],
)
def test_reject_forged_multi_evidence_or_copper(tamper: str) -> None:
    before, after, proof = sample()
    if tamper == "net":
        after["pads"][0]["net"] = "VCC"
    elif tamper == "pad":
        after["pads"][0]["x"] += 0.1
    elif tamper == "manifest":
        proof["moves"][0]["new_mm"] = [0.0, 0.0]
    elif tamper == "duplicate":
        proof["moves"][1]["ref"] = "R1"
    elif tamper == "chain":
        proof["steps"][1]["source_sha256"] = "0" * 64
    elif tamper == "endpoint":
        proof["steps"][1]["working_sha256"] = "0" * 64
    elif tamper == "approval":
        proof["fabApproved"] = True
    elif tamper == "copper":
        after["tracks"] = 1
    elif tamper == "drc":
        proof["steps"][0]["native_drc"]["new_drc_rules"] = 1
    elif tamper == "missing":
        after["footprints"].pop()
    else:
        proof["moves"].append(copy.deepcopy(proof["moves"][0]))
    with pytest.raises(ValueError):
        check_native_board_transition(before, after, proof, "a" * 64, "b" * 64)


def test_multi_selection_and_old_single_decision_contracts_remain_visible() -> None:
    html = (Path(__file__).resolve().parents[1] / "scripts/review_studio_change_diff_template.html").read_text()
    for term in (
        "pcbChangePicker",
        "pcbSelectedDetail",
        "focusedRef",
        "DATA.changed",
        "importDecision(file)",
        "Approve / fabricate (unavailable)",
    ):
        assert term in html


@pytest.mark.skipif(
    not Path("build/qa-033-multieco/eco-dual/ECO_EVIDENCE.json").is_file(),
    reason="Real KiCad acceptance fixture is local ignored QA evidence",
)
def test_real_kicad_copy_matches_native_manifest_when_local_evidence_present() -> None:
    path = Path("build/qa-033-multieco/eco-dual/ECO_EVIDENCE.json")
    manifest = json.loads(path.read_text())
    script = (
        "import json,sys;sys.path.insert(0,'scripts');"
        "from review_studio_native_kicad import _read_kicad;"
        "from pathlib import Path;"
        "print(json.dumps([_read_kicad(Path(sys.argv[1])),_read_kicad(Path(sys.argv[2]))]))"
    )
    result = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            "-c",
            script,
            "build/qa-029-rule-state/native/source/sensor.kicad_pcb",
            "build/qa-033-multieco/eco-dual/source.kicad_pcb",
        ],
        capture_output=True,
        text=True,
        timeout=35,
        check=True,
    )
    before, after = json.loads(result.stdout)
    changes = check_native_board_transition(
        before, after, manifest, manifest["source_sha256"], manifest["working_sha256"]
    )
    assert {change["ref"] for change in changes} == {"R1", "R2"}
