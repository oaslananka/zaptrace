"""Unified constraint-driven layout quality evidence."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from zaptrace.analysis.layout_quality import (
    LayoutQualityEvidenceStatus,
    LayoutRuleFamily,
    apply_bounded_layout_repairs,
    build_layout_quality_report,
    builtin_layout_quality_policy,
    layout_quality_report_schema_json,
    write_layout_quality_report,
)
from zaptrace.core.parser import parse_file
from zaptrace.proof import CheckDefinition, CheckResult, CheckStatus, ProofManifest, ProofPack
from zaptrace.proof.manifest import LayoutQualityEvidence
from zaptrace.proof.signoff import AutonomousSignoffStatus
from zaptrace.review.panels import collect_review_bundle
from zaptrace.synthesis.engine import synthesize

FIXTURE_ROOT = Path("tests/fixtures/layout-quality")
GOOD = FIXTURE_ROOT / "known-good.yaml"
BAD = FIXTURE_ROOT / "known-bad.yaml"


def _section_scores(report) -> dict[str, float]:
    return {section.family.value: section.score for section in report.sections}


def test_policy_is_versioned_deterministic_and_covers_required_rule_families() -> None:
    policy = builtin_layout_quality_policy()

    assert policy.schema_version == "1.0"
    assert policy.policy_version
    assert len(policy.identity_sha256()) == 64
    assert policy.identity_sha256() == builtin_layout_quality_policy().identity_sha256()
    assert {rule.family for rule in policy.rules} == set(LayoutRuleFamily)


def test_committed_layout_quality_schema_matches_pydantic_contract() -> None:
    committed = Path("schemas/layout-quality-report-v1.schema.json").read_text(encoding="utf-8")

    assert committed == layout_quality_report_schema_json()


def test_report_schema_exposes_four_outcome_contract() -> None:
    schema = build_layout_quality_report(parse_file(GOOD)).model_json_schema()
    status_ref = schema["properties"]["status"]["$ref"].rsplit("/", 1)[-1]

    assert set(schema["$defs"][status_ref]["enum"]) == {
        "pass",
        "warning",
        "human-review-required",
        "blocking",
    }


def test_known_good_and_bad_fixture_boards_have_expected_gate_outcomes() -> None:
    good = build_layout_quality_report(parse_file(GOOD))
    bad = build_layout_quality_report(parse_file(BAD))

    assert good.blocked is False
    assert good.status in {LayoutQualityEvidenceStatus.PASS, LayoutQualityEvidenceStatus.WARNING}
    assert bad.blocked is True
    assert bad.status == LayoutQualityEvidenceStatus.BLOCKING
    assert {section.family for section in good.sections} == set(LayoutRuleFamily)
    assert {finding.family for finding in bad.findings} == set(LayoutRuleFamily)


def test_switching_regulator_family_surfaces_loop_area_risk() -> None:
    report = build_layout_quality_report(synthesize("switching regulator module"))

    assert any(
        finding.family == LayoutRuleFamily.DECOUPLING_LOOP
        and finding.rule_id == "layout.analysis.emc_switcher_loop_area"
        for finding in report.findings
    )


def test_missing_physical_layout_evidence_fails_closed_to_human_review() -> None:
    design = synthesize("ESP32 I2C sensor")

    report = build_layout_quality_report(design)

    assert report.blocked is False
    assert report.human_review_required is True
    assert report.status == LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED
    assert any(finding.rule_id == "layout.placement-evidence" for finding in report.findings)
    assert any(finding.rule_id == "layout.routing-evidence" for finding in report.findings)


@pytest.mark.parametrize(
    "intent",
    [
        "ESP32 I2C sensor",
        "RP2040 USB HID",
        "STM32 RS485 node",
        "switching regulator module",
        "ESP32 LoRa gateway",
    ],
)
def test_five_representative_board_families_produce_layout_reports(intent: str) -> None:
    report = build_layout_quality_report(synthesize(intent))

    assert report.design_name
    assert len(report.policy_sha256) == 64
    assert len(report.design_state_hash) == 64
    assert len(report.sections) == len(LayoutRuleFamily)
    assert report.status in set(LayoutQualityEvidenceStatus)


def test_bounded_repairs_improve_three_measured_scores_without_mutating_input() -> None:
    design = parse_file(BAD)
    original = copy.deepcopy(design)

    result = apply_bounded_layout_repairs(design)
    before = _section_scores(result.before)
    after = _section_scores(result.after)

    assert design == original
    assert result.repair_count == 3
    assert result.improved_metric_count >= 3
    assert after[LayoutRuleFamily.DECOUPLING_LOOP.value] > before[LayoutRuleFamily.DECOUPLING_LOOP.value]
    assert after[LayoutRuleFamily.POWER_PATH.value] > before[LayoutRuleFamily.POWER_PATH.value]
    assert after[LayoutRuleFamily.MECHANICAL.value] > before[LayoutRuleFamily.MECHANICAL.value]
    assert {repair.action for repair in result.repairs} == {
        "move-decoupling-capacitor",
        "align-connector-to-edge",
        "widen-high-current-trace",
    }
    assert all(repair.after_score > repair.before_score for repair in result.repairs)


def test_report_writer_round_trips_machine_readable_json(tmp_path: Path) -> None:
    report = build_layout_quality_report(parse_file(BAD))

    out = write_layout_quality_report(report, tmp_path / "layout-quality.json")
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "1.0"
    assert payload["policy_sha256"] == report.policy_sha256
    assert payload["design_state_hash"] == report.design_state_hash
    assert payload["status"] == "blocking"
    with pytest.raises(ValueError, match="unexpected layout-quality report suffix"):
        write_layout_quality_report(report, tmp_path / "layout-quality.txt")


def test_proof_pack_layout_quality_evidence_blocks_autonomous_pass() -> None:
    report = build_layout_quality_report(parse_file(BAD))
    manifest = ProofManifest(
        name="LayoutQualityBlocked",
        design_path="design.yaml",
        layout_quality=LayoutQualityEvidence.from_report(report, report_path="layout-quality.json"),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    payload = json.loads(pack.report_json())

    assert payload["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert payload["autonomous_signoff"]["blocking_checks"] == ["layout-quality"]


def test_proof_pack_missing_layout_evidence_requires_human_review() -> None:
    report = build_layout_quality_report(synthesize("ESP32 I2C sensor"))
    manifest = ProofManifest(
        name="LayoutQualityReview",
        design_path="design.yaml",
        layout_quality=LayoutQualityEvidence.from_report(report, report_path="layout-quality.json"),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    payload = json.loads(pack.report_json())

    assert payload["autonomous_signoff"]["status"] == AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED
    assert payload["autonomous_signoff"]["human_review_checks"] == ["layout-quality"]


def test_review_studio_layout_panel_surfaces_policy_findings_and_repairs() -> None:
    repair = apply_bounded_layout_repairs(parse_file(BAD))
    design = repair.repaired_design
    object.__setattr__(design, "layout_quality_report", repair.after)
    object.__setattr__(design, "layout_repair_evidence", repair)

    bundle = collect_review_bundle(design, panel_ids=["layout_quality"])
    panel = bundle.panels["layout_quality"]

    assert panel.panel_id == "layout_quality"
    assert panel.status in {"pass", "warning", "fail"}
    assert "policy_sha256" in panel.items[0]
    assert any(item.get("kind") == "repair" for item in panel.items)
    assert panel.actions == ["open_layout_quality_report", "open_layout_repair_evidence"]
