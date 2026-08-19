"""Proof agent tool implementations."""

from __future__ import annotations

from .deps import Any
from .runtime import _get_session, _validate_path


def tool_proof_run(path: str) -> dict[str, Any]:
    """Run a Proof Pack from a file or directory path."""
    from zaptrace.proof import run_proof

    p = _validate_path(path, must_exist=True)
    pack = run_proof(str(p))
    return {
        "name": pack.manifest.name,
        "passed": pack.passed,
        "total": len(pack.results),
        "passed_count": sum(1 for r in pack.results if r.passed),
        "failed_count": sum(1 for r in pack.results if not r.passed and r.status != "skip"),
        "skipped_count": sum(1 for r in pack.results if r.status == "skip"),
        "results": [r.to_dict() for r in pack.results],
        "autonomous_signoff": pack.autonomous_signoff.to_evidence_record(),
        "summary": pack.summary,
    }


def tool_proof_run_design(
    design_name: str,
    checks: list[dict] | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Run proof checks directly against a design in the current session.

    If checks is None, only validates that the design loads (structural check).
    """
    from zaptrace.proof import CheckDefinition, ProofRunner

    session = _get_session(session_id)
    design = session.get("designs", {}).get(design_name)
    if design is None:
        raise ValueError(f"Design '{design_name}' not found")

    runner = ProofRunner(design)
    check_defs = []
    if checks:
        for c in checks:
            check_defs.append(CheckDefinition(**c))
    else:
        # Default: structural validation
        check_defs = [
            CheckDefinition(name="design_exists", type="footprint_exists", description="Verify design loads"),
            CheckDefinition(name="all_routed", type="routed", description="All nets routed"),
            CheckDefinition(
                name="footprints_present",
                type="footprint_exists",
                description="All components have footprints",
            ),
        ]

    results = runner.run_checks(check_defs)
    passed = all(r.passed for r in results)
    return {
        "design": design_name,
        "passed": passed,
        "total": len(results),
        "passed_count": sum(1 for r in results if r.passed),
        "failed_count": sum(1 for r in results if not r.passed and r.status != "skip"),
        "results": [r.to_dict() for r in results],
    }


def tool_proof_list_checks(path: str) -> dict[str, Any]:
    """List all checks defined in a Proof Pack without running them."""

    from zaptrace.proof import ProofPack

    path_obj = _validate_path(path, must_exist=True)
    if path_obj.is_dir():
        path_obj = _validate_path(path_obj / "proof.yaml", must_exist=True)
    pack = ProofPack.load(path_obj)
    return {
        "name": pack.manifest.name,
        "description": pack.manifest.description,
        "version": pack.manifest.version,
        "design_path": pack.manifest.design_path,
        "checks": [
            {
                "name": c.name,
                "type": c.type,
                "severity": c.severity.value,
                "description": c.description,
                "category": c.category.value,
            }
            for c in pack.manifest.checks
        ],
        "constraints": pack.manifest.model.model_dump(),
    }


__all__ = ["tool_proof_run", "tool_proof_run_design", "tool_proof_list_checks"]
