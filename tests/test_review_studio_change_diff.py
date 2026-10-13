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


def test_rule_context_defaults_are_bound_without_inventing_custom_rules(tmp_path: Path) -> None:
    before, after = (tmp_path / name / "source.kicad_pcb" for name in ("original", "proposed"))
    for board in (before, after):
        board.parent.mkdir()
        board.write_text("(kicad_pcb)\n")
    claim = {
        "rule_context": {
            "mode": "defaults_without_project",
            "project_sha256": None,
            "custom_rules_sha256": None,
            "custom_rule_loader_probe_passed": False,
            "effective_rules_independently_verified": False,
        }
    }
    context = change.verified_rule_context(before, after, claim)
    assert context["mode"] == "defaults_without_project"
    assert context["production_rule_approval"] is False
    (after.with_suffix(".kicad_pro")).write_text("altered native KiCad rules")
    with pytest.raises(ValueError, match="Unexpected native KiCad project-rule"):
        change.verified_rule_context(before, after, claim)


@pytest.mark.parametrize("mode", ["project", "project_with_custom_rules"])
def test_rule_bytes_are_bound_on_both_original_and_proposed_native_pcb(tmp_path: Path, mode: str) -> None:
    import hashlib

    first, second = (tmp_path / name / "source.kicad_pcb" for name in ("original", "proposed"))
    for board in (first, second):
        board.parent.mkdir()
        board.write_text("(kicad_pcb)\n")
        board.with_suffix(".kicad_pro").write_bytes(b'{"board": {"design_settings": "original"}}')
        if mode == "project_with_custom_rules":
            board.with_suffix(".kicad_dru").write_bytes(b"(version 1)\n(rule clearance)\n")

    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    context = {
        "mode": mode,
        "project_sha256": sha(first.with_suffix(".kicad_pro")),
        "custom_rules_sha256": sha(first.with_suffix(".kicad_dru")) if mode == "project_with_custom_rules" else None,
        "custom_rule_loader_probe_passed": mode == "project_with_custom_rules",
        "effective_rules_independently_verified": False,
    }
    proof = {"rule_context": context}
    assert change.verified_rule_context(first, second, proof)["project_sha256"] == context["project_sha256"]
    for side in (first, second):
        change.verified_rule_context(first, second, proof)
        project = side.with_suffix(".kicad_pro")
        project.write_bytes(project.read_bytes() + b"changed rule")
        with pytest.raises(ValueError, match="Stale or altered native KiCad project-rule"):
            change.verified_rule_context(first, second, proof)
        project.write_bytes(b'{"board": {"design_settings": "original"}}')
    if mode == "project_with_custom_rules":
        rules = second.with_suffix(".kicad_dru")
        rules.write_bytes(rules.read_bytes() + b"(rule unexpected)\n")
        with pytest.raises(ValueError, match="Stale or altered native KiCad project-rule"):
            change.verified_rule_context(first, second, proof)
        rules.unlink()
        with pytest.raises(ValueError, match="Stale or altered native KiCad project-rule"):
            change.verified_rule_context(first, second, proof)


@pytest.mark.parametrize("corrupt", ["missing", "loader", "approval", "extra", "mode"])
def test_forged_project_rule_claims_fail_closed(tmp_path: Path, corrupt: str) -> None:
    import hashlib

    before, after = (tmp_path / name / "source.kicad_pcb" for name in ("old", "new"))
    for board in (before, after):
        board.parent.mkdir()
        board.write_text("(kicad_pcb)\n")
        board.with_suffix(".kicad_pro").write_bytes(b"project")
    context = {
        "mode": "project",
        "project_sha256": hashlib.sha256(b"project").hexdigest(),
        "custom_rules_sha256": None,
        "custom_rule_loader_probe_passed": False,
        "effective_rules_independently_verified": False,
    }
    if corrupt == "missing":
        context.pop("project_sha256")
    elif corrupt == "loader":
        context["custom_rule_loader_probe_passed"] = True
    elif corrupt == "approval":
        context["effective_rules_independently_verified"] = True
    elif corrupt == "extra":
        context["signed_approval"] = True
    else:
        context["mode"] = "project_with_custom_rules"
    with pytest.raises(ValueError, match="native KiCad|Native KiCad"):
        change.verified_rule_context(before, after, {"rule_context": context})


def test_rule_context_screens_make_hashes_visible_but_never_approve() -> None:
    screen = change.TEMPLATE.read_text()
    for evidence in ("projectDigest", "rulesDigest", "ruleProbe", "DATA.rule_context"):
        assert evidence in screen
    assert "Approve / fabricate (unavailable)" in screen
    assert "does not independently certify all effective KiCad rules" in screen


def test_native_schematic_diff_rejects_unpaired_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Both native schematic"):
        change.create_review(
            tmp_path / "source.kicad_pcb",
            tmp_path / "after.kicad_pcb",
            tmp_path / "evidence.json",
            tmp_path / "review.html",
            schematic_source=tmp_path / "before.kicad_sch",
        )


def test_schematic_semantic_screen_exposes_limitations_without_approving() -> None:
    screen = change.TEMPLATE.read_text()
    for required in (
        'id="schErc"',
        'id="schChanges"',
        "sch.erc_before.errors",
        "sch.erc_after.errors",
        "sch.changed_nets",
        "sch.changed_values",
        "PCB parity not verified",
        "No native schematic source",
    ):
        assert required in screen
    assert "Approve / fabricate (unavailable)" in screen


def test_native_schematic_comparison_real_value_delta_and_erc(tmp_path: Path) -> None:
    import hashlib
    import shutil

    if not shutil.which("kicad-cli"):
        pytest.skip("Native KiCad 10 required for real schematic/erc acceptance")
    from review_studio_schematic_eco import propose

    fixture = ROOT / "tests/fixtures/review_studio_native_eco_sensor.kicad_sch"
    before = tmp_path / "a" / "sensor.kicad_sch"
    after = tmp_path / "b" / "sensor.kicad_sch"
    for file in (before, after):
        file.parent.mkdir()
        file.write_bytes(fixture.read_bytes())
    revision, original = propose(before.read_text(), "R1", "10k")
    assert original == "4.7k"
    after.write_text(revision)
    start = (hashlib.sha256(before.read_bytes()).hexdigest(), hashlib.sha256(after.read_bytes()).hexdigest())
    result = change.native_schematic_comparison(before, after, tmp_path / "review.html")
    assert (result["source_sha256"], result["proposed_sha256"]) == start
    assert result["changed_values"] == [{"ref": "R1", "before": "4.7k", "after": "10k"}]
    assert result["changed_nets"] == []
    assert result["added_components"] == result["removed_components"] == []
    assert result["changed_metadata_refs"] == []
    assert result["erc_before"] == result["erc_after"]
    assert result["pcb_schematic_parity_verified"] is False
    assert result["electrical_approval"] is False
    assert len(result["native_export_sha256"]) == 4
    assert before.read_bytes() == fixture.read_bytes()
    assert (hashlib.sha256(before.read_bytes()).hexdigest(), hashlib.sha256(after.read_bytes()).hexdigest()) == start


@pytest.mark.parametrize("variant", ["project_drift", "symlink", "oversized"])
def test_native_schematic_rule_context_fails_closed(tmp_path: Path, variant: str) -> None:
    from review_studio_schematic_eco import propose

    fixture = ROOT / "tests/fixtures/review_studio_native_eco_sensor.kicad_sch"
    before = tmp_path / "a" / "sensor.kicad_sch"
    after = tmp_path / "b" / "sensor.kicad_sch"
    for file in (before, after):
        file.parent.mkdir()
        file.write_bytes(fixture.read_bytes())
    after.write_text(propose(after.read_text(), "R1", "10k")[0])
    before.with_suffix(".kicad_pro").write_bytes(b"first")
    if variant == "project_drift":
        after.with_suffix(".kicad_pro").write_bytes(b"different")
        error = "project-rule bytes differ"
    elif variant == "symlink":
        after.with_suffix(".kicad_pro").symlink_to(before.with_suffix(".kicad_pro"))
        error = "Unsafe native schematic"
    else:
        after.with_suffix(".kicad_pro").write_bytes(b"x" * 3_000_001)
        error = "Oversized native schematic"
    with pytest.raises(ValueError, match=error):
        change.native_schematic_comparison(before, after, tmp_path / "review.html")
    assert not (tmp_path / "review.sch-before-netlist.xml").exists()
