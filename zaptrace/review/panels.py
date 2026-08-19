"""Review panel aggregation — collect evidence from all sources into unified panels.

Each panel corresponds to a review screen defined in the Review Studio spec:
requirements, assumptions, constraints, schematic, PCB, ERC, DRC, DFM, BOM,
supply, manufacturing, simulation, proof pack, decision log.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.core.diff import diff_designs
from zaptrace.core.models import Design
from zaptrace.export.bom import generate_bom_json

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_dict(obj: Any) -> dict[str, Any]:
    """Convert an object to a dict, handling BaseModel and dataclasses."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    from dataclasses import asdict

    try:
        result = asdict(obj)
        # Convert enum values to strings
        return {k: v.value if hasattr(v, "value") else v for k, v in result.items()}
    except (TypeError, ValueError):
        pass
    return {"message": str(obj)}


# ---------------------------------------------------------------------------
# Panel model
# ---------------------------------------------------------------------------


class ReviewPanel(BaseModel):
    """One review panel — corresponds to a Review Studio screen or widget."""

    model_config = ConfigDict(strict=False)

    panel_id: str
    title: str
    status: str = "info"  # info / warning / blocking / pass / fail
    summary: str = ""
    items: list[dict[str, Any]] = Field(default_factory=list)
    details_url: str = ""
    actions: list[str] = Field(default_factory=list)


class ReviewPanelBundle(BaseModel):
    """Aggregated review panels for one design at one point in time."""

    model_config = ConfigDict(strict=False)

    design_name: str
    design_state_hash: str = ""
    panels: dict[str, ReviewPanel] = Field(default_factory=dict)
    non_claims: list[str] = Field(default_factory=list)
    overall_status: str = "pending"  # pending / ready / blocked


# ---------------------------------------------------------------------------
# Panel aggregation helpers
# ---------------------------------------------------------------------------


def _erc_panel(design: Design) -> ReviewPanel:
    """Aggregate ERC violations into a review panel."""
    raw = getattr(design, "erc_result", None)
    items: list[dict[str, Any]] = []
    status = "pass"
    if raw is not None:
        violations: list[Any] = []
        if hasattr(raw, "violations"):
            violations = raw.violations if raw.violations else []
        elif isinstance(raw, list):
            violations = raw
        for v in violations:
            d = _to_dict(v)
            items.append(d)
            sev = d.get("severity", d.get("level", "info"))
            if sev in ("error", "fail"):
                status = "fail"
            elif sev == "warning" and status != "fail":
                status = "warning"
    return ReviewPanel(
        panel_id="erc",
        title="ERC — Electrical Rules Check",
        status=status,
        summary=f"{len(items)} violation(s)" if items else "No ERC violations",
        items=items,
    )


def _drc_panel(design: Design) -> ReviewPanel:
    """Aggregate DRC violations into a review panel."""
    drc = getattr(design, "drc_result", None)
    items: list[dict[str, Any]] = []
    status = "pass"
    if drc is not None:
        for v in getattr(drc, "violations", []):
            d = v.model_dump(mode="json") if hasattr(v, "model_dump") else {"message": str(v)}
            items.append(d)
            if d.get("severity") in ("error", "fail"):
                status = "fail"
            elif d.get("severity") == "warning" and status != "fail":
                status = "warning"
    return ReviewPanel(
        panel_id="drc",
        title="DRC — Design Rules Check",
        status=status,
        summary=f"{len(items)} violation(s)" if items else "No DRC violations",
        items=items,
    )


def _review_status_for_severity(status: str, severity: object) -> str:
    normalized = str(severity or "").lower()
    if normalized in {"error", "fail"}:
        return "fail"
    if normalized == "warning" and status != "fail":
        return "warning"
    return status


def _dfm_panel_items(design: Design) -> tuple[list[dict[str, Any]], str]:
    items: list[dict[str, Any]] = []
    status = "pass"
    results: list[Any] | None = getattr(design, "dfm_result", None)
    for result in results or []:
        for finding in getattr(result, "findings", []):
            payload: dict[str, Any] = (
                finding.model_dump(mode="json") if hasattr(finding, "model_dump") else {"message": str(finding)}
            )
            items.append({**payload, "profile": result.profile_name})
            status = _review_status_for_severity(status, payload.get("severity"))
    return items, status


def _dfm_panel(design: Design) -> ReviewPanel:
    """Aggregate DFM findings into a review panel."""
    findings, status = _dfm_panel_items(design)
    return ReviewPanel(
        panel_id="dfm",
        title="DFM — Design for Manufacturing",
        status=status,
        summary=f"{len(findings)} finding(s)" if findings else "No DFM findings",
        items=findings,
    )


def _bom_panel(design: Design) -> ReviewPanel:
    """Aggregate BOM data into a review panel."""
    bom_json_str = generate_bom_json(design)
    import json

    bom_data = json.loads(bom_json_str) if isinstance(bom_json_str, str) else bom_json_str
    items = bom_data.get("items", []) if isinstance(bom_data, dict) else []
    return ReviewPanel(
        panel_id="bom",
        title="BOM — Bill of Materials",
        status="info",
        summary=f"{len(items)} line items" if items else "Empty BOM",
        items=items,
        actions=["export_csv", "export_json", "enrich_supply"],
    )


def _supply_panel(design: Design) -> ReviewPanel:
    """Aggregate supply-chain risk data into a review panel."""
    supply = getattr(design, "supply_result", None)
    items: list[dict[str, Any]] = []
    status = "info"
    if supply is not None:
        if hasattr(supply, "model_dump"):
            items = supply.model_dump(mode="json").get("items", [])
        elif isinstance(supply, list):
            items = [s.model_dump(mode="json") if hasattr(s, "model_dump") else {"part": str(s)} for s in supply]
        for item in items:
            risk = item.get("risk", item.get("risk_level", "low"))
            if risk in ("high", "critical"):
                status = "warning"
    return ReviewPanel(
        panel_id="supply",
        title="Supply-Chain Risk",
        status=status,
        summary=f"{len(items)} part(s) checked" if items else "No supply data",
        items=items,
    )


def _manufacturing_panel(design: Design) -> ReviewPanel:
    """Aggregate manufacturing evidence into a review panel."""
    manif = getattr(design, "manufacturing_evidence", None)
    items: list[dict[str, Any]] = []
    if manif is not None:
        if hasattr(manif, "model_dump"):
            items = manif.model_dump(mode="json").get("artifacts", [])
        elif isinstance(manif, list):
            items = manif
    return ReviewPanel(
        panel_id="manufacturing",
        title="Manufacturing Evidence",
        status="info",
        summary=f"{len(items)} artifact(s)" if items else "No manufacturing evidence",
        items=items,
        actions=["export_gerber", "export_excellon", "export_ipc2581"],
    )


def _simulation_panel(design: Design) -> ReviewPanel:
    """Aggregate simulation/analysis findings into a review panel."""
    findings: list[dict[str, Any]] = []
    status = "pass"
    analysis = getattr(design, "analysis_result", None)
    if analysis is not None:
        raw = analysis.model_dump(mode="json") if hasattr(analysis, "model_dump") else {"findings": []}
        for f in raw.get("findings", []):
            findings.append(f)
            sev = f.get("severity", "info")
            if sev in ("error", "fail"):
                status = "fail"
            elif sev == "warning" and status != "fail":
                status = "warning"
    return ReviewPanel(
        panel_id="simulation",
        title="Simulation & Analysis",
        status=status,
        summary=f"{len(findings)} finding(s)" if findings else "No analysis findings",
        items=findings,
    )


def _proof_pack_panel(design: Design) -> ReviewPanel:
    """Aggregate proof checks and artifact hashes into a review panel."""
    proof = getattr(design, "proof_manifest", None)
    raw: dict[str, Any] = {}
    if proof is not None and hasattr(proof, "model_dump"):
        raw = proof.model_dump(mode="json")
    elif isinstance(proof, dict):
        raw = proof

    checks = list(raw.get("check_records", []))
    artifacts = [
        {"kind": "artifact", **artifact} for artifact in raw.get("artifacts", []) if isinstance(artifact, dict)
    ]
    status = "info"
    for item in checks:
        item_status = item.get("status", "")
        if item_status in ("fail", "error"):
            status = "fail"
        elif item_status == "warning" and status != "fail":
            status = "warning"
    if checks and status == "info":
        status = "pass"
    summary = f"{len(checks)} check(s), {len(artifacts)} artifact(s)" if checks or artifacts else "No proof pack data"
    return ReviewPanel(
        panel_id="proof_pack",
        title="Proof Pack",
        status=status,
        summary=summary,
        items=[*checks, *artifacts],
    )


_LAYOUT_QUALITY_TITLE = "Layout Quality"
_BENCHMARK_READINESS_TITLE = "Benchmark Readiness"
_SEMANTIC_DIFF_TITLE = "Semantic Diff"


def _layout_quality_panel(design: Design) -> ReviewPanel:
    """Surface unified layout-quality policy, findings, and repair deltas."""
    report = getattr(design, "layout_quality_report", None)
    if report is None:
        try:
            from zaptrace.analysis.layout_quality import build_layout_quality_report

            report = build_layout_quality_report(design)
        except (TypeError, ValueError):
            report = None
    if report is None:
        return ReviewPanel(
            panel_id="layout_quality",
            title=_LAYOUT_QUALITY_TITLE,
            status="warning",
            summary="Layout-quality evidence unavailable",
            items=[],
            actions=["open_layout_quality_report", "open_layout_repair_evidence"],
        )
    raw = _to_dict(report)
    status_value = str(raw.get("status", "human-review-required"))
    if status_value == "blocking":
        status = "fail"
    elif status_value == "pass":
        status = "pass"
    else:
        status = "warning"
    items: list[dict[str, Any]] = [
        {
            "kind": "policy",
            "policy_version": raw.get("policy_version", ""),
            "policy_sha256": raw.get("policy_sha256", ""),
            "design_state_hash": raw.get("design_state_hash", ""),
            "overall_score": raw.get("overall_score", 0.0),
            "status": status_value,
        }
    ]
    items.extend({"kind": "finding", **item} for item in raw.get("findings", []) if isinstance(item, dict))
    repair_source = getattr(design, "layout_repair_evidence", None)
    if repair_source is not None:
        repair_raw = _to_dict(repair_source)
        items.extend({"kind": "repair", **item} for item in repair_raw.get("repairs", []) if isinstance(item, dict))
    else:
        items.extend({"kind": "repair", **item} for item in raw.get("repairs", []) if isinstance(item, dict))
    return ReviewPanel(
        panel_id="layout_quality",
        title=_LAYOUT_QUALITY_TITLE,
        status=status,
        summary=f"score {float(raw.get('overall_score', 0.0)):.3f}; {len(raw.get('findings', []))} finding(s)",
        items=items,
        actions=["open_layout_quality_report", "open_layout_repair_evidence"],
    )


def _benchmark_source(design: Design) -> Any | None:
    for attr in ("benchmark_report", "benchmark_result", "benchmark_summary"):
        raw = getattr(design, attr, None)
        if raw is not None:
            return raw
    return None


def _benchmark_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_results = data.get("results") or data.get("cases") or data.get("families") or []
    items = (
        [item if isinstance(item, dict) else {"message": str(item)} for item in raw_results]
        if isinstance(raw_results, list)
        else []
    )
    items.extend({"kind": "non_claim", "message": claim} for claim in data.get("non_claims", []) or [])
    if not any(item.get("kind") == "non_claim" for item in items):
        items.append({"kind": "non_claim", "message": "Benchmark evidence does not imply fabrication approval."})
    return items


def _blocking_benchmark_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if item.get("caught") is False
        or item.get("passed") is False
        or item.get("status") in {"fail", "blocking"}
        or item.get("blocking") is True
    ]


def _benchmark_summary(data: dict[str, Any], missed: int, blocking_count: int) -> str:
    if "caught_count" in data or "missed_count" in data:
        return f"{data.get('caught_count', 0)} caught / {missed} missed known failure(s)"
    return f"{blocking_count} blocking benchmark item(s)"


def _benchmark_panel(design: Design) -> ReviewPanel:
    """Aggregate benchmark/release-readiness evidence into a review panel."""
    raw = _benchmark_source(design)
    if raw is None:
        return ReviewPanel(
            panel_id="benchmark",
            title=_BENCHMARK_READINESS_TITLE,
            status="info",
            summary="No benchmark evidence",
            items=[
                {
                    "kind": "non_claim",
                    "message": "Benchmark pass is regression evidence, not fabrication approval.",
                }
            ],
        )

    data = _to_dict(raw)
    items = _benchmark_items(data)
    blocking_items = _blocking_benchmark_items(items)
    missed = int(data.get("missed_count", 0) or 0)
    passed = bool(data.get("passed", missed == 0 and not blocking_items))
    status = "fail" if not passed or missed or blocking_items else "pass"
    return ReviewPanel(
        panel_id="benchmark",
        title=_BENCHMARK_READINESS_TITLE,
        status=status,
        summary=_benchmark_summary(data, missed, len(blocking_items)),
        items=items,
        actions=["open_benchmark_report", "open_release_gate_summary"],
    )


def _decision_log_panel(design: Design) -> ReviewPanel:
    """Aggregate decision log entries into a review panel."""
    decisions = getattr(design, "decision_log", None)
    items: list[dict[str, Any]] = []
    if decisions is not None:
        if hasattr(decisions, "model_dump"):
            items = decisions.model_dump(mode="json").get("entries", [])
        elif isinstance(decisions, list):
            items = decisions
    return ReviewPanel(
        panel_id="decision_log",
        title="Decision Log",
        status="info",
        summary=f"{len(items)} decision(s)" if items else "No decisions recorded",
        items=items,
    )


def _diff_panel(design: Design, baseline: Design | None = None) -> ReviewPanel:
    """Compute semantic diff against a baseline design if available."""
    if baseline is None:
        return ReviewPanel(
            panel_id="semantic_diff",
            title=_SEMANTIC_DIFF_TITLE,
            status="info",
            summary="No baseline design — diff not available",
            items=[],
        )
    try:
        changes = diff_designs(baseline, design)
        items = [getattr(c, "model_dump", lambda mode="json", _c=c: {"message": str(_c)})() for c in changes]
        return ReviewPanel(
            panel_id="semantic_diff",
            title=_SEMANTIC_DIFF_TITLE,
            status="info",
            summary=f"{len(changes)} change(s)",
            items=items,
        )
    except (ValueError, TypeError):
        return ReviewPanel(
            panel_id="semantic_diff",
            title=_SEMANTIC_DIFF_TITLE,
            status="warning",
            summary="Diff computation failed",
            items=[],
        )


def _requirements_panel(design: Design) -> ReviewPanel:
    """Aggregate requirements traceability into a review panel."""
    reqs = getattr(design, "requirements", None)
    items: list[dict[str, Any]] = []
    if reqs is not None:
        if hasattr(reqs, "model_dump"):
            items = reqs.model_dump(mode="json").get("requirements", [])
        elif isinstance(reqs, list):
            items = reqs
    return ReviewPanel(
        panel_id="requirements",
        title="Requirements",
        status="info",
        summary=f"{len(items)} requirement(s)" if items else "No requirements",
        items=items,
    )


def _assumptions_panel(design: Design) -> ReviewPanel:
    """Surface architecture assumptions that require explicit confirmation."""
    source = getattr(design, "architecture_artifact", None)
    if source is not None and hasattr(source, "model_dump"):
        raw = source.model_dump(mode="json")
    elif isinstance(source, dict):
        raw = source
    else:
        raw = {}
    items = [item for item in raw.get("assumptions", []) if isinstance(item, dict)]
    requires_confirmation = [
        item
        for item in items
        if item.get("requires_confirmation") is True
        or item.get("confirmed") is False
        or item.get("risk_level") in {"high", "critical"}
    ]
    if requires_confirmation:
        summary = f"{len(requires_confirmation)} assumption(s) require confirmation"
    elif items:
        summary = f"{len(items)} assumption(s)"
    else:
        summary = "No assumption evidence"
    return ReviewPanel(
        panel_id="assumptions",
        title="Assumptions & Confirmations",
        status="warning" if requires_confirmation else "info",
        summary=summary,
        items=items,
        actions=["confirm_assumption", "request_evidence"] if requires_confirmation else [],
    )


# ---------------------------------------------------------------------------
# Factory registries
# ---------------------------------------------------------------------------

_PANEL_BUILDERS: dict[str, tuple[str, Any]] = {
    "requirements": ("Requirements", _requirements_panel),
    "assumptions": ("Assumptions & Confirmations", _assumptions_panel),
    "erc": ("ERC — Electrical Rules Check", _erc_panel),
    "drc": ("DRC — Design Rules Check", _drc_panel),
    "dfm": ("DFM — Design for Manufacturing", _dfm_panel),
    "bom": ("BOM — Bill of Materials", _bom_panel),
    "supply": ("Supply-Chain Risk", _supply_panel),
    "manufacturing": ("Manufacturing Evidence", _manufacturing_panel),
    "simulation": ("Simulation & Analysis", _simulation_panel),
    "layout_quality": (_LAYOUT_QUALITY_TITLE, _layout_quality_panel),
    "proof_pack": ("Proof Pack", _proof_pack_panel),
    "benchmark": ("Benchmark Readiness", _benchmark_panel),
    "decision_log": ("Decision Log", _decision_log_panel),
}


# ---------------------------------------------------------------------------
# Public aggregation API
# ---------------------------------------------------------------------------


def collect_panels(
    design: Design,
    *,
    baseline: Design | None = None,
    panel_ids: list[str] | None = None,
) -> dict[str, ReviewPanel]:
    """Build all requested review panels for *design*.

    Args:
        design: The design to inspect.
        baseline: Optional baseline design for semantic diff.
        panel_ids: Subset of panel IDs to build; ``None`` builds all.

    Returns:
        Ordered dict of ``{panel_id: ReviewPanel}``.
    """
    ids = panel_ids or list(_PANEL_BUILDERS.keys())
    panels: dict[str, ReviewPanel] = {}
    for pid in ids:
        if pid == "semantic_diff":
            panels[pid] = _diff_panel(design, baseline)
        elif pid in _PANEL_BUILDERS:
            _title, builder = _PANEL_BUILDERS[pid]
            panels[pid] = builder(design)
    return panels


def collect_review_bundle(
    design: Design,
    *,
    baseline: Design | None = None,
    panel_ids: list[str] | None = None,
) -> ReviewPanelBundle:
    """Build a full review bundle — panels, non-claims, overall status.

    Args:
        design: The design under review.
        baseline: Optional baseline design for semantic diff.
        panel_ids: Subset of panel IDs; ``None`` builds all.

    Returns:
        A :class:`ReviewPanelBundle` ready for API or static bundle output.
    """
    panels = collect_panels(design, baseline=baseline, panel_ids=panel_ids)
    overall = "pass"
    for p in panels.values():
        if p.status == "fail":
            overall = "fail"
            break
        if p.status == "warning" and overall != "fail":
            overall = "warning"
        if p.status == "blocking" and overall != "fail":
            overall = "blocking"
    non_claims = [
        "Review Studio is a review and approval workbench, not a full EDA editor",
        "Static mode shows approve/reject controls as disabled — interactive approval requires hosted mode",
        "Human review remains required before fabrication",
    ]
    state_hash = ""
    try:
        from zaptrace.core.state import design_state_hash

        state_hash = design_state_hash(design)
    except Exception:
        pass
    return ReviewPanelBundle(
        design_name=design.meta.name,
        design_state_hash=state_hash,
        panels=panels,
        overall_status=overall,
        non_claims=non_claims,
    )
