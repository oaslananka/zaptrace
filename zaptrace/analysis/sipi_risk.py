"""Aggregate SI/PI risk report for proof-pack evidence."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.analysis.signal_integrity import build_impedance_return_path_report
from zaptrace.core.models import Design, Net, NetType


class SipiRiskStatus(StrEnum):
    PASS = "pass"
    HUMAN_REVIEW_REQUIRED = "human-review-required"
    FAIL = "fail"


class SipiRiskFinding(BaseModel):
    model_config = ConfigDict(strict=False)

    category: str
    subject: str
    status: SipiRiskStatus
    message: str
    metrics: dict[str, object] = Field(default_factory=dict)


class SipiRiskReport(BaseModel):
    schema_version: str = "1.0"
    high_speed_net_count: int
    impedance_assumption_count: int
    return_path_diagnostic_count: int
    decoupling_issue_count: int
    unsupported_high_speed_count: int
    blocked: bool
    human_review_required: bool
    findings: list[SipiRiskFinding]
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "heuristic SI/PI risk evidence, not solver-grade signoff",
            "external SI/PI/PDN tools are required for production validation",
        ]
    )


def _is_high_speed(net: Net) -> bool:
    name = net.name.upper()
    if net.constraints and (net.constraints.impedance_target is not None or net.constraints.length_match_group):
        return True
    if net.type == NetType.DIFFERENTIAL:
        return True
    return name.startswith(("USB", "HDMI", "MIPI", "CLK", "RF", "ANT")) or name.endswith(("_P", "_N"))


def _power_nets(design: Design) -> list[Net]:
    return [
        net
        for net in design.nets.values()
        if net.type == NetType.POWER or net.name.upper().startswith(("VDD", "VCC", "VBUS", "VIN"))
    ]


def _component_on_net(design: Design, net: Net, predicate: str) -> bool:
    refs = {node.component_ref for node in net.nodes}
    for component in design.components.values():
        if (component.ref in refs or component.id in refs) and (
            predicate in component.type.lower() or predicate in (component.value or "").lower()
        ):
            return True
    return False


def _decoupling_findings(design: Design) -> list[SipiRiskFinding]:
    findings: list[SipiRiskFinding] = []
    for net in _power_nets(design):
        has_cap = _component_on_net(design, net, "capacitor") or _component_on_net(design, net, "cap")
        if not has_cap:
            findings.append(
                SipiRiskFinding(
                    category="decoupling",
                    subject=net.name,
                    status=SipiRiskStatus.HUMAN_REVIEW_REQUIRED,
                    message="power rail has no capacitor/decoupling evidence on the same net",
                )
            )
    return findings


def build_sipi_risk_report(design: Design) -> SipiRiskReport:
    """Build aggregate SI/PI risk evidence for proof packs."""
    findings: list[SipiRiskFinding] = []
    high_speed = [net for net in design.nets.values() if _is_high_speed(net)]
    unsupported = []
    for net in high_speed:
        if net.constraints is None or net.constraints.impedance_target is None:
            unsupported.append(net)
            findings.append(
                SipiRiskFinding(
                    category="high_speed_support",
                    subject=net.name,
                    status=SipiRiskStatus.HUMAN_REVIEW_REQUIRED,
                    message="high-speed/RF net lacks explicit impedance target evidence",
                )
            )
    return_path = build_impedance_return_path_report(design)
    for diagnostic in return_path.diagnostics:
        findings.append(
            SipiRiskFinding(
                category="return_path",
                subject=diagnostic.net_name,
                status=SipiRiskStatus.HUMAN_REVIEW_REQUIRED
                if diagnostic.status.value != "pass"
                else SipiRiskStatus.PASS,
                message=diagnostic.message,
                metrics={"risk": diagnostic.risk, "return_path_net": diagnostic.return_path_net or ""},
            )
        )
    findings.extend(_decoupling_findings(design))
    decoupling_issues = sum(1 for item in findings if item.category == "decoupling")
    review = (
        any(item.status == SipiRiskStatus.HUMAN_REVIEW_REQUIRED for item in findings)
        or return_path.human_review_required
    )
    blocked = any(item.status == SipiRiskStatus.FAIL for item in findings) or return_path.blocked
    return SipiRiskReport(
        high_speed_net_count=len(high_speed),
        impedance_assumption_count=return_path.assumption_count,
        return_path_diagnostic_count=return_path.diagnostic_count,
        decoupling_issue_count=decoupling_issues,
        unsupported_high_speed_count=len(unsupported),
        blocked=blocked,
        human_review_required=review,
        findings=findings,
    )
