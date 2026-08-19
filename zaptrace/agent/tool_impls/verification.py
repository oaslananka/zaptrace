"""Verification agent tool implementations."""

from __future__ import annotations

from .deps import Any, ERCResult, _erc_rules, copy
from .runtime import (
    _get_erc_runner_type,
    _get_session,
    _record_drc_evidence,
    _record_erc_evidence,
    _record_validation_status,
)


def tool_erc_validate(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Run all ERC rules on a design."""
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    runner = _get_erc_runner_type()()
    result = runner.run(design)
    session["erc_results"] = {**session.get("erc_results", {}), design_name: result}
    _record_erc_evidence(session, design_name, result)
    validation = _record_validation_status(session, design_name)
    return {
        "design": design_name,
        "passed": result.passed,
        "validation_status": validation,
        "total_errors": result.total_errors,
        "total_warnings": result.total_warnings,
        "total_info": result.total_info,
        "coverage_summary": result.coverage_summary(),
        "categories_covered": result.categories_covered,
        "checks_run": [
            {
                "rule_id": c.rule_id,
                "title": c.title,
                "category": c.category,
                "violation_count": c.violation_count,
            }
            for c in result.checks_run
        ],
        "coverage_gaps": result.coverage_gaps,
        "violations": [
            {
                "rule_id": v.rule_id,
                "severity": v.severity.value,
                "message": v.message,
                "components": v.component_refs,
                "nets": v.net_refs,
            }
            for v in result.violations
        ],
    }


def tool_erc_get_result(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Get the latest ERC result for a design."""
    session = _get_session(session_id)
    result: ERCResult | None = session.get("erc_results", {}).get(design_name)
    if result is None:
        raise ValueError(f"No ERC result for '{design_name}'. Run erc_validate first.")
    return {
        "design": design_name,
        "passed": result.passed,
        "total_errors": result.total_errors,
        "total_warnings": result.total_warnings,
        "total_info": result.total_info,
        "violation_count": len(result.violations),
        "coverage_summary": result.coverage_summary(),
        "categories_covered": result.categories_covered,
        "coverage_gaps": result.coverage_gaps,
    }


def tool_erc_list_rules() -> dict[str, Any]:
    """List all registered ERC rules with descriptions."""
    import inspect

    rules_info: list[dict[str, str]] = []
    for name, obj in inspect.getmembers(_erc_rules, inspect.isfunction):
        if name.startswith("rule_erc"):
            doc = (obj.__doc__ or "No description").strip()
            rules_info.append(
                {
                    "id": name.removeprefix("rule_").upper(),
                    "description": doc.split("\n")[0],
                }
            )
    rules_info.sort(key=lambda x: x["id"])
    return {"rules": rules_info}


def _get_drc_engine(fab_profile: str | None = None) -> Any:
    from zaptrace.ee.drc.engine import DRCEngine

    if fab_profile:
        from zaptrace.fab.profile import load_builtin_profile

        return DRCEngine(fab_profile=load_builtin_profile(fab_profile))
    return DRCEngine()


def tool_drc_run(design_name: str, fab_profile: str | None = None, session_id: str = "default") -> dict[str, Any]:
    """Run DRC on a design, optionally against a manufacturer fab profile.

    When ``fab_profile`` is a built-in profile name (e.g. ``"jlcpcb-2layer"``),
    DRC also reports that fab's profile-specific violations (min trace/space/
    drill/annular ring, via and board limits).
    """
    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    engine = _get_drc_engine(fab_profile)
    result = engine.run(copy.deepcopy(design))
    session.setdefault("drc_results", {})[design_name] = result
    _record_drc_evidence(session, design_name, result, fab_profile=fab_profile)
    validation = _record_validation_status(session, design_name)
    return {
        "design": design_name,
        "fab_profile": fab_profile,
        "passed": result.passed,
        "validation_status": validation,
        "total_violations": result.total_violations,
        "violations": [
            {"rule_id": v.rule_id, "severity": v.severity.value, "message": v.message} for v in result.violations
        ],
    }


def tool_drc_get_result(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Get the latest DRC result for a design."""
    session = _get_session(session_id)
    result = session.get("drc_results", {}).get(design_name)
    if result is None:
        return {"design": design_name, "result": None, "message": "No DRC result found. Run drc_run first."}
    return {
        "design": design_name,
        "passed": result.passed,
        "total_violations": result.total_violations,
        "violations": [
            {"rule_id": v.rule_id, "severity": v.severity.value, "message": v.message} for v in result.violations
        ],
        "evidence": copy.deepcopy(session.get("drc_evidence", {}).get(design_name)),
        "validation_status": copy.deepcopy(session.get("validation_status", {}).get(design_name)),
    }


def tool_drc_list_rules() -> dict[str, Any]:
    """List all DRC rules with descriptions."""
    from zaptrace.ee.drc import list_drc_rules

    rules = list_drc_rules()
    return {"rules": rules, "count": len(rules)}


def _require_design(design_name: str, session_id: str) -> Any:
    design = _get_session(session_id).get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")
    return design


def tool_mechanical_review(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Review mounting holes vs board size and edges (mechanical / enclosure)."""
    from zaptrace.analysis.mechanical import mechanical_review

    design = _require_design(design_name, session_id)
    findings = mechanical_review(design)
    return {"design": design_name, "finding_count": len(findings), "findings": [f.to_dict() for f in findings]}


def tool_security_review(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Review hardware-security exposure (debug access, secure element, etc.)."""
    from zaptrace.analysis.security_review import security_review

    design = _require_design(design_name, session_id)
    findings = security_review(design)
    return {"design": design_name, "finding_count": len(findings), "findings": [f.to_dict() for f in findings]}


def tool_testability_report(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Assess test-point coverage, debug/reset access, and a bring-up checklist."""
    from zaptrace.analysis.dft import analyze_testability, bringup_checklist

    design = _require_design(design_name, session_id)
    report = analyze_testability(design)
    return {"design": design_name, "report": report.to_dict(), "bringup_checklist": bringup_checklist(design)}


def tool_electrical_analysis(design_name: str, session_id: str = "default") -> dict[str, Any]:
    """Heuristic SI/PI/thermal pre-check (impedance, length-match, PDN, thermal).

    A pre-check, not signoff — the report carries its own assumptions and
    limitations.
    """
    from zaptrace.analysis.reports import generate_electrical_analysis_report

    design = _require_design(design_name, session_id)
    report = generate_electrical_analysis_report(design)
    return {"design": design_name, "report": report.model_dump()}


__all__ = [
    "tool_erc_validate",
    "tool_erc_get_result",
    "tool_erc_list_rules",
    "_get_drc_engine",
    "tool_drc_run",
    "tool_drc_get_result",
    "tool_drc_list_rules",
    "_require_design",
    "tool_mechanical_review",
    "tool_security_review",
    "tool_testability_report",
    "tool_electrical_analysis",
]
