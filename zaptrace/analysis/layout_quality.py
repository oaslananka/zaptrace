"""Constraint-driven PCB layout quality aggregation and bounded repair evidence.

This module unifies existing placement, routing, SI/PI, thermal, mechanical,
and design-for-test evidence into one deterministic report. It is an adapter,
not a second DRC engine, and does not claim fabrication or solver-grade signoff.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from copy import deepcopy
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.analysis.current_density import CurrentDensityStatus, build_current_density_report
from zaptrace.analysis.dft import analyze_testability
from zaptrace.analysis.diffpair import DiffPairCheckStatus, build_diffpair_length_report
from zaptrace.analysis.mechanical import mechanical_review
from zaptrace.analysis.reports import AnalysisSeverity, generate_electrical_analysis_report
from zaptrace.analysis.sipi_risk import SipiRiskStatus, build_sipi_risk_report
from zaptrace.core.models import Design
from zaptrace.core.state import design_state_hash
from zaptrace.synthesis.placement import PlacementObservation, analyze_placement


class LayoutQualityEvidenceStatus(StrEnum):
    """Normalized layout-quality outcome."""

    PASS = "pass"
    WARNING = "warning"
    HUMAN_REVIEW_REQUIRED = "human-review-required"
    BLOCKING = "blocking"


class LayoutRuleFamily(StrEnum):
    """Required rule families from the layout-quality contract."""

    DECOUPLING_LOOP = "decoupling-loop-area"
    POWER_PATH = "power-path-current-density"
    RETURN_PATH = "ground-return-split-plane"
    HIGH_SPEED = "high-speed-differential"
    ANALOG_DIGITAL = "analog-digital-separation"
    THERMAL = "thermal-placement-copper"
    MECHANICAL = "connector-mechanical"
    TESTABILITY = "test-debug-access"


class LayoutRuleConstraint(BaseModel):
    """One machine-readable layout-quality policy rule."""

    model_config = ConfigDict(strict=False, frozen=True)

    rule_id: str
    family: LayoutRuleFamily
    description: str
    evidence_sources: list[str]
    unavailable_status: LayoutQualityEvidenceStatus = LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED
    release_blocking: bool = True


class LayoutQualityPolicy(BaseModel):
    """Versioned policy that identifies the unified layout gate."""

    model_config = ConfigDict(strict=False, frozen=True)

    schema_version: str = "1.0"
    policy_version: str = "2026.07"
    rules: list[LayoutRuleConstraint]
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "layout-quality evidence is deterministic heuristic evidence, not fabrication approval",
            "SI/PI, EMC, thermal, and mechanical production signoff require "
            "qualified engineering review and external tools",
            "bounded repairs operate on a copy and do not silently mutate the approved design",
        ]
    )

    def identity_sha256(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LayoutQualityFinding(BaseModel):
    """One normalized finding from an existing analysis source."""

    model_config = ConfigDict(strict=False)

    rule_id: str
    family: LayoutRuleFamily
    status: LayoutQualityEvidenceStatus
    subject: str
    message: str
    source: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    repairable: bool = False


class LayoutQualitySection(BaseModel):
    """Aggregate score and status for one rule family."""

    model_config = ConfigDict(strict=False)

    family: LayoutRuleFamily
    score: float = Field(ge=0, le=1)
    status: LayoutQualityEvidenceStatus
    finding_count: int = Field(default=0, ge=0)
    blocking_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    human_review_count: int = Field(default=0, ge=0)


class LayoutRepairEvidence(BaseModel):
    """Before/after evidence for one bounded layout repair."""

    model_config = ConfigDict(strict=False)

    action: str
    family: LayoutRuleFamily
    subject: str
    before_score: float = Field(ge=0, le=1)
    after_score: float = Field(ge=0, le=1)
    delta: float
    rationale: str
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)


class LayoutQualityReport(BaseModel):
    """Unified machine-readable layout-quality report."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    design_name: str
    design_state_hash: str
    policy_version: str
    policy_sha256: str
    overall_score: float = Field(ge=0, le=1)
    status: LayoutQualityEvidenceStatus
    blocked: bool
    human_review_required: bool
    sections: list[LayoutQualitySection]
    findings: list[LayoutQualityFinding]
    constraints: list[LayoutRuleConstraint]
    repairs: list[LayoutRepairEvidence] = Field(default_factory=list)
    non_claims: list[str]


class LayoutRepairResult(BaseModel):
    """A repaired copy plus deterministic before/after evidence."""

    model_config = ConfigDict(strict=False)

    repaired_design: Design
    before: LayoutQualityReport
    after: LayoutQualityReport
    repairs: list[LayoutRepairEvidence]

    @property
    def repair_count(self) -> int:
        return len(self.repairs)

    @property
    def improved_metric_count(self) -> int:
        return sum(1 for repair in self.repairs if repair.delta > 0)


def builtin_layout_quality_policy() -> LayoutQualityPolicy:
    """Return the built-in versioned layout-quality policy."""

    specs = [
        (
            "layout.decoupling-loop",
            LayoutRuleFamily.DECOUPLING_LOOP,
            "Decoupling proximity and switching-loop area",
            ["placement-scorecard", "electrical-analysis"],
        ),
        (
            "layout.power-path",
            LayoutRuleFamily.POWER_PATH,
            "Power trace width and current-density margin",
            ["current-density", "electrical-analysis"],
        ),
        (
            "layout.return-path",
            LayoutRuleFamily.RETURN_PATH,
            "Ground-return continuity and split-plane risk",
            ["sipi-risk", "electrical-analysis"],
        ),
        (
            "layout.high-speed",
            LayoutRuleFamily.HIGH_SPEED,
            "High-speed impedance and differential-pair length constraints",
            ["sipi-risk", "diffpair-length", "electrical-analysis"],
        ),
        (
            "layout.analog-digital",
            LayoutRuleFamily.ANALOG_DIGITAL,
            "Analog/digital placement separation",
            ["placement-scorecard"],
        ),
        (
            "layout.thermal",
            LayoutRuleFamily.THERMAL,
            "Thermal component spacing and copper-risk evidence",
            ["placement-scorecard", "electrical-analysis"],
        ),
        (
            "layout.mechanical",
            LayoutRuleFamily.MECHANICAL,
            "Connector edge intent, keepouts, mounting, and board-edge risk",
            ["placement-scorecard", "mechanical-review"],
        ),
        (
            "layout.testability",
            LayoutRuleFamily.TESTABILITY,
            "Power test points and debug/reset accessibility",
            ["testability-report"],
        ),
    ]
    return LayoutQualityPolicy(
        rules=[
            LayoutRuleConstraint(rule_id=rule_id, family=family, description=description, evidence_sources=sources)
            for rule_id, family, description, sources in specs
        ]
    )


_STATUS_RANK = {
    LayoutQualityEvidenceStatus.PASS: 0,
    LayoutQualityEvidenceStatus.WARNING: 1,
    LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED: 2,
    LayoutQualityEvidenceStatus.BLOCKING: 3,
}
_STATUS_PENALTY = {
    LayoutQualityEvidenceStatus.PASS: 0.0,
    LayoutQualityEvidenceStatus.WARNING: 0.12,
    LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED: 0.25,
    LayoutQualityEvidenceStatus.BLOCKING: 0.5,
}


def _status_for_findings(findings: list[LayoutQualityFinding]) -> LayoutQualityEvidenceStatus:
    return max(
        (finding.status for finding in findings),
        key=lambda item: _STATUS_RANK[item],
        default=LayoutQualityEvidenceStatus.PASS,
    )


def _add_finding(
    findings: list[LayoutQualityFinding],
    *,
    rule_id: str,
    family: LayoutRuleFamily,
    status: LayoutQualityEvidenceStatus,
    subject: str,
    message: str,
    source: str,
    metrics: dict[str, Any] | None = None,
    repairable: bool = False,
) -> None:
    findings.append(
        LayoutQualityFinding(
            rule_id=rule_id,
            family=family,
            status=status,
            subject=subject,
            message=message,
            source=source,
            metrics=metrics or {},
            repairable=repairable,
        )
    )


def _layout_family_for_placement(observation: PlacementObservation) -> LayoutRuleFamily:
    if observation.category == "proximity":
        return LayoutRuleFamily.DECOUPLING_LOOP
    if observation.category == "separation":
        return LayoutRuleFamily.ANALOG_DIGITAL
    if observation.category == "thermal_spacing":
        return LayoutRuleFamily.THERMAL
    if observation.category == "keepout" and observation.constraint is not None and observation.constraint.near:
        return LayoutRuleFamily.DECOUPLING_LOOP
    return LayoutRuleFamily.MECHANICAL


def _placement_findings(design: Design, findings: list[LayoutQualityFinding]) -> None:
    if not design.placement:
        _add_finding(
            findings,
            rule_id="layout.placement-evidence",
            family=LayoutRuleFamily.MECHANICAL,
            status=LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED,
            subject=design.meta.name,
            message="component placement evidence is missing",
            source="placement-scorecard",
        )
        return
    analysis = analyze_placement(design)
    placed_count = len(design.placement)
    if placed_count < len(design.components):
        _add_finding(
            findings,
            rule_id="layout.placement-coverage",
            family=LayoutRuleFamily.MECHANICAL,
            status=LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED,
            subject=design.meta.name,
            message=f"{placed_count}/{len(design.components)} components have placement evidence",
            source="placement-scorecard",
            metrics={"placed": placed_count, "components": len(design.components)},
        )
    for observation in analysis.observations:
        if observation.severity == "info":
            continue
        family = _layout_family_for_placement(observation)
        status = (
            LayoutQualityEvidenceStatus.BLOCKING
            if observation.severity == "error"
            else LayoutQualityEvidenceStatus.WARNING
        )
        _add_finding(
            findings,
            rule_id=f"layout.placement.{observation.category}",
            family=family,
            status=status,
            subject=",".join(observation.component_ids) or design.meta.name,
            message=observation.message,
            source="placement-scorecard",
            metrics={"component_ids": observation.component_ids},
            repairable=observation.category in {"proximity", "keepout", "edge"},
        )


def _routing_findings(design: Design, findings: list[LayoutQualityFinding]) -> None:
    if design.routing is None or not design.routing.traces:
        _add_finding(
            findings,
            rule_id="layout.routing-evidence",
            family=LayoutRuleFamily.POWER_PATH,
            status=LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED,
            subject=design.meta.name,
            message="routed trace evidence is missing",
            source="routing",
        )

    density = build_current_density_report(design)
    for entry in density.traces:
        if entry.status != CurrentDensityStatus.FAIL:
            continue
        _add_finding(
            findings,
            rule_id="layout.current-density",
            family=LayoutRuleFamily.POWER_PATH,
            status=LayoutQualityEvidenceStatus.BLOCKING,
            subject=entry.net_name,
            message=entry.message,
            source="current-density",
            metrics=entry.model_dump(mode="json"),
            repairable=True,
        )
    for net_id in density.missing_route_nets:
        net = design.nets.get(net_id)
        _add_finding(
            findings,
            rule_id="layout.current-density-route",
            family=LayoutRuleFamily.POWER_PATH,
            status=LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED,
            subject=net.name if net else net_id,
            message="high-current net lacks routed trace evidence",
            source="current-density",
            metrics={"net_id": net_id},
        )

    diffpair = build_diffpair_length_report(design)
    for entry in diffpair.entries:
        if entry.status == DiffPairCheckStatus.PASS:
            continue
        status = (
            LayoutQualityEvidenceStatus.BLOCKING
            if entry.blocking and entry.status == DiffPairCheckStatus.FAIL
            else LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED
        )
        _add_finding(
            findings,
            rule_id="layout.diffpair-length",
            family=LayoutRuleFamily.HIGH_SPEED,
            status=status,
            subject=entry.group_name,
            message=entry.message,
            source="diffpair-length",
            metrics=entry.model_dump(mode="json"),
        )


def _sipi_family(category: str) -> LayoutRuleFamily:
    if category == "decoupling":
        return LayoutRuleFamily.DECOUPLING_LOOP
    if category == "return_path":
        return LayoutRuleFamily.RETURN_PATH
    return LayoutRuleFamily.HIGH_SPEED


def _report_status(
    *,
    blocked: bool,
    human_review_required: bool,
    has_warning: bool,
) -> LayoutQualityEvidenceStatus:
    if blocked:
        return LayoutQualityEvidenceStatus.BLOCKING
    if human_review_required:
        return LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED
    if has_warning:
        return LayoutQualityEvidenceStatus.WARNING
    return LayoutQualityEvidenceStatus.PASS


def _sipi_findings(design: Design, findings: list[LayoutQualityFinding]) -> None:
    report = build_sipi_risk_report(design)
    for item in report.findings:
        if item.status == SipiRiskStatus.PASS:
            continue
        family = _sipi_family(item.category)
        status = (
            LayoutQualityEvidenceStatus.BLOCKING
            if item.status == SipiRiskStatus.FAIL
            else LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED
        )
        _add_finding(
            findings,
            rule_id=f"layout.sipi.{item.category}",
            family=family,
            status=status,
            subject=item.subject,
            message=item.message,
            source="sipi-risk",
            metrics=item.metrics,
        )


def _electrical_findings(design: Design, findings: list[LayoutQualityFinding]) -> None:
    category_map = {
        "pdn_ir_drop_current_density": LayoutRuleFamily.POWER_PATH,
        "thermal_hotspot": LayoutRuleFamily.THERMAL,
        "emc_switcher_loop_area": LayoutRuleFamily.DECOUPLING_LOOP,
        "emc_split_plane_crossing": LayoutRuleFamily.RETURN_PATH,
        "emc_fast_edge_rate": LayoutRuleFamily.HIGH_SPEED,
        "controlled_impedance": LayoutRuleFamily.HIGH_SPEED,
        "differential_pair_length_match": LayoutRuleFamily.HIGH_SPEED,
        "length_constraints": LayoutRuleFamily.HIGH_SPEED,
    }
    for item in generate_electrical_analysis_report(design).findings:
        family = category_map.get(item.category)
        if family is None or item.severity == AnalysisSeverity.INFO:
            continue
        status = (
            LayoutQualityEvidenceStatus.WARNING
            if item.severity in {AnalysisSeverity.WARNING, AnalysisSeverity.NONBLOCKING}
            else LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED
        )
        _add_finding(
            findings,
            rule_id=f"layout.analysis.{item.category}",
            family=family,
            status=status,
            subject=item.subject,
            message=item.message,
            source="electrical-analysis",
            metrics=item.metrics,
        )


def _mechanical_findings(design: Design, findings: list[LayoutQualityFinding]) -> None:
    for item in mechanical_review(design):
        status = (
            LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED
            if item.topic == "mounting-holes" and item.severity == "warning"
            else LayoutQualityEvidenceStatus.WARNING
        )
        _add_finding(
            findings,
            rule_id=f"layout.mechanical.{item.topic}",
            family=LayoutRuleFamily.MECHANICAL,
            status=status,
            subject=design.meta.name,
            message=item.detail,
            source="mechanical-review",
        )


def _testability_findings(design: Design, findings: list[LayoutQualityFinding]) -> None:
    report = analyze_testability(design)
    for recommendation in report.recommendations:
        _add_finding(
            findings,
            rule_id="layout.testability-access",
            family=LayoutRuleFamily.TESTABILITY,
            status=LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED,
            subject=design.meta.name,
            message=recommendation,
            source="testability-report",
            metrics={
                "testpoint_count": report.testpoint_count,
                "power_rails_uncovered": report.power_rails_uncovered,
                "has_debug_access": report.has_debug_access,
                "has_reset_access": report.has_reset_access,
            },
        )


def _sections(findings: list[LayoutQualityFinding]) -> list[LayoutQualitySection]:
    sections: list[LayoutQualitySection] = []
    for family in LayoutRuleFamily:
        family_findings = [finding for finding in findings if finding.family == family]
        penalty = sum(_STATUS_PENALTY[finding.status] for finding in family_findings)
        score = round(max(0.0, 1.0 - penalty), 3)
        sections.append(
            LayoutQualitySection(
                family=family,
                score=score,
                status=_status_for_findings(family_findings),
                finding_count=len(family_findings),
                blocking_count=sum(
                    1 for finding in family_findings if finding.status == LayoutQualityEvidenceStatus.BLOCKING
                ),
                warning_count=sum(
                    1 for finding in family_findings if finding.status == LayoutQualityEvidenceStatus.WARNING
                ),
                human_review_count=sum(
                    1
                    for finding in family_findings
                    if finding.status == LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED
                ),
            )
        )
    return sections


def build_layout_quality_report(
    design: Design,
    *,
    policy: LayoutQualityPolicy | None = None,
    repairs: list[LayoutRepairEvidence] | None = None,
) -> LayoutQualityReport:
    """Aggregate all current layout evidence under one versioned policy."""

    selected_policy = policy or builtin_layout_quality_policy()
    findings: list[LayoutQualityFinding] = []
    _placement_findings(design, findings)
    _routing_findings(design, findings)
    _sipi_findings(design, findings)
    _electrical_findings(design, findings)
    _mechanical_findings(design, findings)
    _testability_findings(design, findings)
    sections = _sections(findings)
    overall = round(sum(section.score for section in sections) / len(sections), 3) if sections else 1.0
    blocked = any(finding.status == LayoutQualityEvidenceStatus.BLOCKING for finding in findings)
    human_review = not blocked and any(
        finding.status == LayoutQualityEvidenceStatus.HUMAN_REVIEW_REQUIRED for finding in findings
    )
    has_warning = any(finding.status == LayoutQualityEvidenceStatus.WARNING for finding in findings)
    status = _report_status(blocked=blocked, human_review_required=human_review, has_warning=has_warning)
    return LayoutQualityReport(
        design_name=design.meta.name,
        design_state_hash=design_state_hash(design),
        policy_version=selected_policy.policy_version,
        policy_sha256=selected_policy.identity_sha256(),
        overall_score=overall,
        status=status,
        blocked=blocked,
        human_review_required=human_review,
        sections=sections,
        findings=findings,
        constraints=selected_policy.rules,
        repairs=repairs or [],
        non_claims=selected_policy.non_claims,
    )


def _score(report: LayoutQualityReport, family: LayoutRuleFamily) -> float:
    return next(section.score for section in report.sections if section.family == family)


def _is_decoupling_component(component: Any) -> bool:
    value = str(getattr(component, "value", "") or "").lower()
    return component.ref.upper().startswith("C") and any(token in value for token in ("nf", "pf", "100n", "0.1u"))


def _match_component(design: Design, pattern: str) -> list[str]:
    return [
        cid
        for cid, component in design.components.items()
        if fnmatch.fnmatchcase(cid, pattern) or fnmatch.fnmatchcase(component.ref, pattern)
    ]


def _move_one_decoupling_cap(design: Design) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    placement = design.placement
    if not placement:
        return None
    ic_ids = [
        cid
        for cid, component in design.components.items()
        if component.type.lower() in {"ic", "mcu", "microcontroller", "regulator", "sensor", "op-amp", "amplifier"}
        and cid in placement
    ]
    for cid, component in design.components.items():
        if not _is_decoupling_component(component) or cid not in placement or not ic_ids:
            continue
        old = placement[cid]
        nearest = min(
            ic_ids,
            key=lambda target: (old[0] - placement[target][0]) ** 2 + (old[1] - placement[target][1]) ** 2,
        )
        target = placement[nearest]
        distance_sq = (old[0] - target[0]) ** 2 + (old[1] - target[1]) ** 2
        if distance_sq <= 25.0:
            continue
        new = (target[0] + 1.0, target[1])
        placement[cid] = new
        return component.ref, {"position": list(old), "target": design.components[nearest].ref}, {"position": list(new)}
    return None


def _board_dimensions(design: Design) -> tuple[float, float]:
    if design.board_def is not None:
        return design.board_def.width, design.board_def.height
    return design.board.width_mm, design.board.height_mm


def _edge_aligned_position(
    edge: str,
    position: tuple[float, float],
    width: float,
    height: float,
) -> tuple[float, float]:
    x, y = position
    positions = {
        "left": (1.0, y),
        "right": (width - 1.0, y),
        "top": (x, height - 1.0),
        "bottom": (x, 1.0),
    }
    return positions.get(edge, position)


def _align_one_connector(design: Design) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    placement = design.placement
    if not placement:
        return None
    width, height = _board_dimensions(design)
    for intent in design.constraints.placement:
        if not intent.edge:
            continue
        for cid in _match_component(design, intent.component):
            old = placement.get(cid)
            if old is None:
                continue
            new = _edge_aligned_position(intent.edge, old, width, height)
            if new == old:
                continue
            placement[cid] = new
            component = design.components[cid]
            return component.ref, {"position": list(old), "edge": intent.edge}, {"position": list(new)}
    return None


def _widen_one_high_current_trace(design: Design) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    density = build_current_density_report(design)
    if design.routing is None:
        return None
    failure = next((entry for entry in density.traces if entry.status == CurrentDensityStatus.FAIL), None)
    if failure is None:
        return None
    changed = False
    old_widths: list[float] = []
    new_widths: list[float] = []
    for segment in design.routing.traces:
        if segment.net_id != failure.net_id or segment.width >= failure.required_width_mm:
            continue
        old_widths.append(segment.width)
        segment.width = failure.required_width_mm
        new_widths.append(segment.width)
        changed = True
    if not changed:
        return None
    return (
        failure.net_name,
        {"widths_mm": old_widths},
        {"widths_mm": new_widths, "required_width_mm": failure.required_width_mm},
    )


def apply_bounded_layout_repairs(
    design: Design,
    *,
    policy: LayoutQualityPolicy | None = None,
) -> LayoutRepairResult:
    """Apply three bounded, deterministic repairs to a deep copy of *design*."""

    selected_policy = policy or builtin_layout_quality_policy()
    repaired = deepcopy(design)
    before = build_layout_quality_report(repaired, policy=selected_policy)
    repairs: list[LayoutRepairEvidence] = []
    operations = [
        (
            "move-decoupling-capacitor",
            LayoutRuleFamily.DECOUPLING_LOOP,
            _move_one_decoupling_cap,
            "Move one distant decoupling capacitor within 5 mm of its nearest active IC.",
        ),
        (
            "align-connector-to-edge",
            LayoutRuleFamily.MECHANICAL,
            _align_one_connector,
            "Align one explicitly constrained connector with its required board edge.",
        ),
        (
            "widen-high-current-trace",
            LayoutRuleFamily.POWER_PATH,
            _widen_one_high_current_trace,
            "Widen one failing high-current route to its computed minimum width.",
        ),
    ]
    current = before
    for action, family, operation, rationale in operations:
        change = operation(repaired)
        if change is None:
            continue
        subject, before_value, after_value = change
        next_report = build_layout_quality_report(repaired, policy=selected_policy)
        before_score = _score(current, family)
        after_score = _score(next_report, family)
        repairs.append(
            LayoutRepairEvidence(
                action=action,
                family=family,
                subject=subject,
                before_score=before_score,
                after_score=after_score,
                delta=round(after_score - before_score, 3),
                rationale=rationale,
                before=before_value,
                after=after_value,
            )
        )
        current = next_report
    after = build_layout_quality_report(repaired, policy=selected_policy, repairs=repairs)
    return LayoutRepairResult(repaired_design=repaired, before=before, after=after, repairs=repairs)


def layout_quality_report_schema_json() -> str:
    """Serialize the canonical layout-quality report JSON Schema."""

    return json.dumps(LayoutQualityReport.model_json_schema(), indent=2, sort_keys=True) + "\n"


def write_layout_quality_report(report: LayoutQualityReport, output_path: str | Path) -> Path:
    """Write a layout-quality JSON report using the repository's report convention."""

    out = Path(output_path)
    if out.suffix.lower() != ".json":
        raise ValueError(f"unexpected layout-quality report suffix: {out.suffix}")
    resolved = out.resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return resolved
