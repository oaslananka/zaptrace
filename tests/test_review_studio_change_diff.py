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


def test_accessible_offline_report_keeps_hash_based_content_security_policy() -> None:
    """Visible explanation/skip link must not require weakening offline CSP."""
    from review_studio_local_csp import apply_offline_csp

    html = change.TEMPLATE.read_text()
    assert html.count("__CHANGE_DATA__") == 1
    rendered = apply_offline_csp(html.replace("__CHANGE_DATA__", "{}"))
    assert "__CSP__" not in rendered
    assert "style-src 'sha256-" in rendered
    assert "script-src 'sha256-" in rendered
    assert "unsafe-inline" not in rendered
    assert 'href="#reviewMain"' in rendered
    assert 'id="approvalBlockReason"' in rendered


def test_source_bound_decision_overview_links_actual_evidence_and_unsigned_outcome() -> None:
    """The first screen must explain the decision without inventing signoff."""
    from html.parser import HTMLParser

    class BriefParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.ids: set[str] = set()
            self.links: list[str] = []
            self.inside_brief = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            properties = dict(attrs)
            if properties.get("id") == "decisionBriefTitle":
                self.inside_brief = True
            if properties.get("id"):
                assert properties["id"] not in self.ids
                self.ids.add(str(properties["id"]))
            if tag == "a" and self.inside_brief:
                self.links.append(str(properties.get("href")))

        def handle_endtag(self, tag: str) -> None:
            if tag == "nav" and self.inside_brief:
                self.inside_brief = False

    template = change.TEMPLATE.read_text()
    parser = BriefParser()
    parser.feed(template)
    assert {
        "briefChange",
        "briefRisk",
        "briefEvidence",
        "briefNext",
        "briefStateHash",
        "decisionBriefTitle",
        "briefStatus",
    } <= parser.ids
    assert parser.links == ["#changeTitle", "#verificationTitle", "#reviewDecisionTitle"]
    assert all(anchor[1:] in parser.ids for anchor in parser.links)
    assert '<nav class="brief-links" aria-label="Review this exact design state">' in template
    assert "FABRICATION BLOCKED" in template
    assert 'Schematic/ERC: "+(sch?"REPORTED (not full parity)":"NOT CHECKED")' in template
    assert 'Pin/net crossprobe: "+crossprobe' in template
    assert '$("briefStateHash").textContent=DATA.state_hash;' in template
    assert 'if(cp.scoped_pin_net_consistent)crossprobe="SCOPED MATCH ONLY";' in template
    assert "A local decision never authorizes fabrication." in template
    assert "initDecisionBrief();" in template
    assert template.count("__CHANGE_DATA__") == 1


def test_native_drc_findings_preserve_source_rule_and_severity_with_bounded_evidence() -> None:
    """Do not turn native KiCad warnings into approvals or generic green status."""
    rows = [{"type": f"rule_{i}", "severity": "warning", "description": f"Actual finding {i}"} for i in range(11)]
    findings, omitted = change.native_reported_findings({"violations": rows})
    assert len(findings) == 8
    assert omitted == 3
    assert findings[0] == {"rule": "rule_0", "severity": "warning", "description": "Actual finding 0"}
    record = {
        "changed": [{"ref": "R1"}],
        "drc": {"before_rules": 11, "after_rules": 11, "reported_findings": findings},
        "schematic": None,
    }
    catalog = change.evidence_catalog(record)
    assert len([item for item in catalog if item["kind"] == "native_pcb_drc_finding"]) == 8
    assert catalog[2]["id"] == "pcb-drc:finding:0"
    assert catalog[2]["rule"] == "rule_0"
    assert catalog[2]["summary"] == "WARNING: Actual finding 0"
    altered = deepcopy(record)
    altered["drc"]["reported_findings"][0]["description"] = "Different native rule evidence"
    assert change.canonical_decision_hash(record) != change.canonical_decision_hash(altered)
    template = change.TEMPLATE.read_text()
    assert 'id="drcFindings"' in template
    assert 'id="drcFindingSummary"' in template
    assert '"pcb-drc:finding:"+index' in template
    assert '" Native finding: "+first.severity.toUpperCase()' in template
    assert "selection is not inspection or approval." in template


def test_native_pin_net_verdict_is_screen_reader_announced_without_implying_approval() -> None:
    """Current, mismatch and unverifiable findings must be text, not color only."""
    html = change.TEMPLATE.read_text()
    assert 'id="pinNetStatus" role="status" aria-live="polite"' in html
    assert '"Exact native pin/pad/net crossprobe: "+status.toUpperCase()' in html
    assert '"Blocking reasons: "+cp.reasons_when_unverified.join(", ")' in html
    assert "Full PCB/schematic parity: NOT VERIFIED." in html


def test_offline_review_has_keyboard_skip_link_to_main_landmark() -> None:
    """The offline comparison remains navigable before all engineering controls."""
    from html.parser import HTMLParser

    class LandmarkParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.skip_link: dict[str, str | None] | None = None
            self.main: dict[str, str | None] | None = None
            self.ordered: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            properties = dict(attrs)
            if tag == "a" and properties.get("class") == "skip-to-content":
                self.skip_link = properties
                self.ordered.append("skip")
            if tag == "main":
                self.main = properties
                self.ordered.append("main")

    html = change.TEMPLATE.read_text()
    parser = LandmarkParser()
    parser.feed(html)
    assert parser.ordered[:2] == ["skip", "main"]
    assert parser.skip_link is not None
    assert parser.main is not None
    assert parser.skip_link["href"] == "#" + str(parser.main["id"])
    assert parser.main["tabindex"] == "-1"
    assert ".skip-to-content:focus-visible{transform:none;" in html


def test_disabled_fabrication_action_has_visible_accessible_block_reason() -> None:
    """Missing production authorization must not be disclosed by tooltip alone."""
    from html.parser import HTMLParser

    class ApprovalSemantics(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.button_attributes: dict[str, str | None] = {}
            self.block_reason_attributes: dict[str, str | None] = {}
            self.reason_text: list[str] = []
            self.in_reason = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            properties = dict(attrs)
            if tag == "button" and properties.get("aria-describedby") == "approvalBlockReason":
                self.button_attributes = properties
            if tag == "p" and properties.get("id") == "approvalBlockReason":
                self.block_reason_attributes = properties
                self.in_reason = True

        def handle_endtag(self, tag: str) -> None:
            if tag == "p" and self.in_reason:
                self.in_reason = False

        def handle_data(self, data: str) -> None:
            if self.in_reason:
                self.reason_text.append(data)

    parser = ApprovalSemantics()
    parser.feed(change.TEMPLATE.read_text())
    assert parser.button_attributes.get("disabled") is None
    assert "disabled" in parser.button_attributes
    assert parser.button_attributes["aria-describedby"] == parser.block_reason_attributes["id"]
    assert "hidden" not in parser.block_reason_attributes
    reason = " ".join(parser.reason_text)
    assert "verified reviewer identity" in reason
    assert "electrical/DFM" in reason
    assert "signed authorization workflow" in reason
    assert "cannot authorize fabrication" in reason


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


def test_review_output_cannot_escape_native_candidate_workspace(tmp_path: Path) -> None:
    source = tmp_path / "original.kicad_pcb"
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    candidate = candidate_dir / "candidate.kicad_pcb"
    evidence = tmp_path / "evidence.json"
    for file in (source, candidate, evidence):
        file.write_bytes(b"test source, not valid KiCad geometry")

    other = tmp_path / "outside"
    other.mkdir()
    protected = other / "review.html"
    protected.write_text("protected")

    for invalid in (protected, tmp_path / "review.html", candidate_dir / "not-html.txt"):
        with pytest.raises(ValueError, match="output must be an HTML child"):
            change.create_review(source, candidate, evidence, invalid)
    assert protected.read_text() == "protected"
    assert not (tmp_path / "review.html").exists()


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


def test_decision_hash_ignores_volatile_native_render_export_but_not_semantics() -> None:
    from copy import deepcopy

    base = {
        "schema_version": 1,
        "source_sha256": "s" * 64,
        "proposed_sha256": "p" * 64,
        "evidence_sha256": "e" * 64,
        "decision_hash_contract": "native_source_and_semantic_evidence_v2",
        "rule_context": {"project_sha256": "a" * 64},
        "drc": {"before_rules": 1, "after_rules": 1},
        "native_svg": {"current": {"uri": "time 01"}, "proposed": {"uri": "time 01"}},
        "schematic": {
            "source_sha256": "b" * 64,
            "proposed_sha256": "c" * 64,
            "erc_before": {"warnings": 28},
            "erc_after": {"warnings": 28},
            "erc_findings_after": [{"ref": "R1", "rule": "lib_symbol_issues"}],
            "svg": {"current": {"sha256": "fresh export 01"}},
            "native_export_sha256": {"erc_before": "timestamp 01"},
        },
    }
    first = change.canonical_decision_hash(base)
    another = deepcopy(base)
    another["native_svg"]["current"]["uri"] = "time 02"
    another["schematic"]["svg"]["current"]["sha256"] = "fresh export 02"
    another["schematic"]["native_export_sha256"]["erc_before"] = "timestamp 02"
    assert change.canonical_decision_hash(another) == first
    for field, payload in (
        ("rule", "b" * 64),
        ("erc", 29),
        ("source", "d" * 64),
        ("evidence", "f" * 64),
    ):
        modified = deepcopy(another)
        if field == "rule":
            modified["rule_context"]["project_sha256"] = payload
        elif field == "erc":
            modified["schematic"]["erc_after"]["warnings"] = payload
        elif field == "source":
            modified["schematic"]["source_sha256"] = payload
        else:
            modified["evidence_sha256"] = payload
        assert change.canonical_decision_hash(modified) != first


def test_native_erc_finding_links_verified_reference_and_rule_only() -> None:
    report = """ERC report (2026, Encoding UTF8)
***** Sheet /
[lib_symbol_issues]: Library unresolved
    ; warning
    @(317.50 mm, 50.80 mm): Symbol R1 [ZapTrace_R1]
** ERC messages: 1 Errors 0 Warnings 1
"""
    result = change.erc_findings(report, {"R1"}, 1)
    assert result == [
        {
            "rule": "lib_symbol_issues",
            "message": "Library unresolved",
            "severity": "warning",
            "ref": "R1",
            "coordinate_mm": [317.5, 50.8],
        }
    ]
    assert change.erc_findings(report, {"R2"}, 1)[0]["ref"] is None
    with pytest.raises(ValueError, match="count"):
        change.erc_findings(report, {"R1"}, 2)
    with pytest.raises(ValueError, match="Unsupported"):
        change.erc_findings(report.replace("; warning", "; unknown"), {"R1"}, 1)


@pytest.mark.parametrize("bad", ["<script/>", '<image href="https://attacker.example/test" />'])
def test_native_schematic_svg_does_not_embed_active_or_remote_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    import subprocess

    def generate(argv, **kwargs):
        output = Path(argv[argv.index("--output") + 1])
        (output / "preview.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10">{bad}</svg>'
        )
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(change.subprocess, "run", generate)
    target = tmp_path / "result.svg"
    with pytest.raises(ValueError, match="unsupported active"):
        change.native_schematic_svg("kicad-cli", tmp_path / "source.kicad_sch", target)
    assert not target.exists()


def test_schematic_symbol_navigation_requires_source_and_native_plot_provenance() -> None:
    template = change.TEMPLATE.read_text()
    for term in (
        'id="schAnchorCurrent"',
        'id="schAnchorProposed"',
        'id="schJumpToSymbol"',
        "sch.symbol_anchors?.proposed?.[ref]",
        "highlightNativeSymbol(side,ref)",
        "PCB schematic electrical parity: NOT VERIFIED",
    ):
        assert term in template


def test_native_svg_target_symlink_is_rejected_without_touching_owner_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    def generate(argv, **kwargs):
        directory = Path(argv[argv.index("--output") + 1])
        (directory / "native.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10"/>'
        )
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(change.subprocess, "run", generate)
    user_data = tmp_path / "protected.txt"
    user_data.write_text("unchanged")
    target = tmp_path / "review.svg"
    target.symlink_to(user_data)
    with pytest.raises(ValueError, match="Unsafe native schematic SVG target"):
        change.native_schematic_svg("kicad-cli", tmp_path / "source.kicad_sch", target)
    assert user_data.read_text() == "unchanged"
