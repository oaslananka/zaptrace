from __future__ import annotations

import json
from pathlib import Path

from zaptrace.core.models import Component, Design, DesignMeta
from zaptrace.synthesis.repair import Patch, RepairResult, repair_design, synthesize_and_repair
from zaptrace.synthesis.repair_evidence import build_repair_proposal_report, write_repair_proposal_report


def _design_with(component: Component) -> Design:
    design = Design(meta=DesignMeta(name="repair-evidence"))
    design.components[component.ref] = component
    return design


def test_repair_proposal_report_contains_problem_alternatives_selection_and_verification() -> None:
    design = _design_with(Component(id="R1", ref="R1", type="resistor", value="10k"))
    repair = repair_design(design)

    report = build_repair_proposal_report(repair)
    proposal = report.proposals[0]

    assert report.proposal_count == 1
    assert report.verified_count == 1
    assert report.blocked is False
    assert proposal.problem.startswith("ERC020 on R1")
    assert {alt.label for alt in proposal.alternatives} == {"leave-for-human-review", "apply-selected-patch"}
    assert any(alt.selected for alt in proposal.alternatives)
    assert proposal.selected_change == "Set R1.footprint from '' to '0402'"
    assert proposal.verification.violations_before > proposal.verification.violations_after
    assert proposal.verification.improved is True


def test_low_confidence_repair_proposal_requires_human_review() -> None:
    out = synthesize_and_repair("industrial board, 12V input, 3.3V rail at 1A")
    report = build_repair_proposal_report(out["repair"])

    assert report.human_review_required is True
    assert any(proposal.confidence < 1.0 for proposal in report.proposals)
    assert report.remaining


def test_silent_repair_without_iteration_evidence_blocks() -> None:
    patch = Patch(
        rule_id="ERC999",
        component_ref="U1",
        field="footprint",
        old_value="",
        new_value="QFN-32",
        rationale="untracked mutation",
    )
    repair = RepairResult(patches=[patch], converged=True)

    report = build_repair_proposal_report(repair)

    assert report.proposal_count == 0
    assert report.silent_repair_count == 1
    assert report.blocked is True


def test_write_repair_proposal_report(tmp_path: Path) -> None:
    design = _design_with(Component(id="C1", ref="C1", type="capacitor", value="100nF"))
    repair = repair_design(design)
    report = build_repair_proposal_report(repair)

    out = write_repair_proposal_report(report, tmp_path / "repair-proposals.json")
    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["schema_version"] == "1.0"
    assert data["proposal_count"] == 1
    assert data["proposals"][0]["alternatives"][1]["selected"] is True
