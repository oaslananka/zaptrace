"""Generate strict generated-board release-gate evidence."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.algo.placer import place_components  # noqa: E402
from zaptrace.evidence.identity import EvidenceIdentity, EvidenceMode, capture_evidence_identity  # noqa: E402
from zaptrace.generation import (  # noqa: E402
    compile_intent_to_design_ir,
    generate_project_evidence_bundle,
    minimal_board_generation_intent_example,
    validate_board_generation_intent,
)
from zaptrace.generation.compiler import CompiledDesignIR  # noqa: E402
from zaptrace.generation.evidence import GeneratedProjectEvidenceBundle  # noqa: E402
from zaptrace.security.paths import resolve_trusted_path  # noqa: E402
from zaptrace.security.release import ReleaseEvidenceStatus, build_component_coverage  # noqa: E402

EVIDENCE_SOURCE_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "scripts/ci_generated_board_release_gate.py",
    "zaptrace/generation/compiler.py",
    "zaptrace/generation/evidence.py",
    "zaptrace/algo/placer.py",
    "zaptrace/security/release.py",
    "data/footprints/vendor/ATTRIBUTION.md",
    "data/footprints/vendor/ESP32-WROOM-32.kicad_mod",
    "data/footprints/vendor/USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.kicad_mod",
)

EXPECTED_ARTIFACT_KINDS = [
    "intent",
    "design-ir-compile-report",
    "kicad-project",
    "kicad-schematic",
    "schematic-generation-report",
    "kicad-pcb",
    "pcb-generation-report",
    "manufacturing-export-manifest",
    "review-handoff",
]


def _artifact_hashes(bundle: GeneratedProjectEvidenceBundle) -> dict[str, str]:
    return {artifact.kind: artifact.sha256 for artifact in bundle.artifacts}


def _artifact_paths(bundle: GeneratedProjectEvidenceBundle) -> dict[str, str]:
    return {artifact.kind: artifact.path for artifact in bundle.artifacts}


def _evaluate_risky_package_policy(
    compiled: CompiledDesignIR,
    *,
    reviewed: bool,
    approval_id: str,
) -> dict[str, Any]:
    """Return compatibility risky-package fields from full component coverage."""
    coverage = build_component_coverage(
        compiled.design,
        risky_package_reviewed=reviewed,
        risky_package_approval_id=approval_id,
    )
    return {
        "status": coverage["status"],
        "reviewed": reviewed,
        "approval_id": approval_id,
        "component_count": coverage["component_count"],
        "populated_component_count": coverage["populated_component_count"],
        "bom_accounted_component_count": coverage["bom_accounted_component_count"],
        "pick_and_place_accounted_component_count": coverage["pick_and_place_accounted_component_count"],
        "checked_component_count": coverage["checked_component_count"],
        "unresolved_component_count": coverage["unresolved_component_count"],
        "placement_missing_component_count": coverage["placement_missing_component_count"],
        "risky_component_count": coverage["risky_component_count"],
        "blocked_component_count": coverage["blocked_component_count"],
        "checked_components": coverage["checked_components"],
        "unresolved_components": coverage["unresolved_components"],
        "placement_missing_components": coverage["placement_missing_components"],
        "risky_components": coverage["risky_components"],
        "blocked_components": coverage["blocked_components"],
    }


def _prepare_compiled_board() -> tuple[Any, CompiledDesignIR]:
    intent = validate_board_generation_intent(minimal_board_generation_intent_example())
    compiled = compile_intent_to_design_ir(intent)
    positions = place_components(compiled.design)
    compiled.design.placement = dict(positions)
    for component_id, position in positions.items():
        compiled.design.components[component_id].position = position
    return intent, compiled


def _artifact_blocking_reasons(
    bundle: GeneratedProjectEvidenceBundle,
    artifact_hashes: dict[str, str],
) -> list[str]:
    reasons: list[str] = []
    missing_kinds = sorted(set(EXPECTED_ARTIFACT_KINDS) - set(artifact_hashes))
    malformed_hash_kinds = sorted(kind for kind, value in artifact_hashes.items() if len(value) != 64)
    if missing_kinds:
        reasons.append(f"missing artifact kind(s): {', '.join(missing_kinds)}")
    if malformed_hash_kinds:
        reasons.append(f"malformed SHA-256 hash for kind(s): {', '.join(malformed_hash_kinds)}")
    if "not fabrication-ready" not in " ".join(bundle.non_claims).lower():
        reasons.append("missing non-claim(s): not fabrication-ready")
    return reasons


def _component_coverage_blocking_reasons(coverage: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if coverage["unresolved_component_count"]:
        refs = ", ".join(row["component_ref"] for row in coverage["unresolved_components"])
        reasons.append(f"component footprint evidence unresolved for: {refs}")
    if coverage["placement_missing_component_count"]:
        refs = ", ".join(row["component_ref"] for row in coverage["placement_missing_components"])
        reasons.append(f"pick-and-place evidence unresolved for: {refs}")
    if coverage["blocked_component_count"]:
        refs = ", ".join(row["component_ref"] for row in coverage["blocked_components"])
        reasons.append(f"risky-package policy blocked component(s): {refs}")
    explained = (
        coverage["unresolved_component_count"]
        or coverage["placement_missing_component_count"]
        or coverage["blocked_component_count"]
    )
    if coverage["status"] != ReleaseEvidenceStatus.PASS and not explained:
        reasons.append(f"component coverage status is {coverage['status']}")
    return reasons


def build_report(
    artifact_dir: Path,
    *,
    trusted_root: Path,
    risky_package_reviewed: bool = False,
    risky_package_approval_id: str = "",
    evidence_identity: EvidenceIdentity | None = None,
) -> dict[str, Any]:
    """Run the generated-board pipeline and return release-gate evidence."""
    artifact_dir = resolve_trusted_path(
        artifact_dir,
        trusted_root=trusted_root,
        label="artifact directory",
        require_child=True,
    )
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    identity = evidence_identity or capture_evidence_identity(
        root=ROOT,
        mode=EvidenceMode.SNAPSHOT,
        source_inputs=EVIDENCE_SOURCE_INPUTS,
    )
    intent, compiled = _prepare_compiled_board()
    bundle = generate_project_evidence_bundle(intent, compiled, artifact_dir).bundle
    component_coverage = _evaluate_risky_package_policy(
        compiled,
        reviewed=risky_package_reviewed,
        approval_id=risky_package_approval_id,
    )
    artifact_hashes = _artifact_hashes(bundle)
    blocking_reasons = [
        *bundle.blocking_reasons,
        *_artifact_blocking_reasons(bundle, artifact_hashes),
        *_component_coverage_blocking_reasons(component_coverage),
    ]
    return {
        "schema_version": "3.0",
        "gate_id": "generated-board-release-gate-v3",
        "evidence_identity": identity.model_dump(mode="json"),
        "family_id": bundle.family_id,
        "design_name": bundle.design_name,
        "passed": bundle.passed and not blocking_reasons,
        "generated_project_evidence_passed": bundle.passed,
        "artifact_count": bundle.artifact_count,
        "required_artifact_count": bundle.required_artifact_count,
        "missing_required_artifact_count": bundle.missing_required_artifact_count,
        "expected_artifact_kinds": EXPECTED_ARTIFACT_KINDS,
        "artifact_paths": _artifact_paths(bundle),
        "artifact_hashes": artifact_hashes,
        "requirement_trace_count": bundle.requirement_trace_count,
        "provenance_record_count": bundle.provenance_record_count,
        "schematic_passed": bundle.schematic_passed,
        "pcb_passed": bundle.pcb_passed,
        "manufacturing_manifest_present": bundle.manufacturing_manifest_present,
        "review_handoff_present": bundle.review_handoff_present,
        "non_claims": bundle.non_claims,
        "blocking_reasons": blocking_reasons,
        "component_coverage": component_coverage,
        "risky_package_policy": component_coverage,
        "non_claims_enforced": True,
        "path_policy": (
            "generated artifacts are written to a working directory; "
            "this report stores relative paths and stable content hashes"
        ),
    }


def report_json(report: dict[str, Any]) -> str:
    """Serialize a release-gate report as stable JSON."""
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def render_markdown(report: dict[str, Any]) -> str:
    """Render generated-board release-gate evidence as Markdown."""
    lines = ["# Generated Board Release Gate", ""]
    lines.append(f"Gate: `{report['gate_id']}`")
    lines.append(f"Family: `{report['family_id']}`")
    lines.append(f"Design: `{report['design_name']}`")
    lines.append(f"Passed: `{str(report['passed']).lower()}`")
    lines.append("")
    lines.append("## Evidence identity")
    lines.append("")
    identity = report["evidence_identity"]
    lines.append(f"- Mode: `{identity['mode']}`")
    lines.append(f"- Package version: `{identity['package_version']}`")
    lines.append(f"- Source commit: `{identity['source_commit']}`")
    lines.append(f"- Source ref: `{identity['source_ref']}`")
    lines.append(f"- Dirty working tree: `{str(identity['dirty']).lower()}`")
    lines.append(f"- Lock SHA-256: `{identity['lock_sha256']}`")
    lines.append(f"- Source-input SHA-256: `{identity['source_inputs_sha256']}`")
    lines.append(f"- Identity SHA-256: `{identity['identity_sha256']}`")
    lines.append("")
    lines.append("## Counts")
    lines.append("")
    lines.append(f"- Artifacts: {report['artifact_count']}")
    lines.append(f"- Required artifacts: {report['required_artifact_count']}")
    lines.append(f"- Missing required artifacts: {report['missing_required_artifact_count']}")
    lines.append(f"- Requirement traces: {report['requirement_trace_count']}")
    lines.append(f"- Provenance records: {report['provenance_record_count']}")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    lines.append(f"- Schematic generation passed: `{str(report['schematic_passed']).lower()}`")
    lines.append(f"- PCB generation passed: `{str(report['pcb_passed']).lower()}`")
    lines.append(f"- Manufacturing manifest present: `{str(report['manufacturing_manifest_present']).lower()}`")
    lines.append(f"- Review handoff present: `{str(report['review_handoff_present']).lower()}`")
    lines.append("")
    lines.append("## Artifact hashes")
    lines.append("")
    lines.append("| Kind | SHA-256 |")
    lines.append("|------|---------|")
    for kind in report["expected_artifact_kinds"]:
        lines.append(f"| `{kind}` | `{report['artifact_hashes'].get(kind, '')}` |")
    lines.append("")
    lines.append("## Non-claims")
    lines.append("")
    for claim in report["non_claims"]:
        lines.append(f"- {claim}")
    lines.append("")
    lines.append("## Blocking reasons")
    lines.append("")
    if report["blocking_reasons"]:
        for reason in report["blocking_reasons"]:
            lines.append(f"- {reason}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Risky package policy")
    lines.append("")
    policy = report.get("risky_package_policy", {})
    lines.append(f"- Status: `{policy.get('status', 'missing-evidence')}`")
    lines.append(f"- Populated components: {policy.get('populated_component_count', 0)}")
    lines.append(f"- BOM-accounted components: {policy.get('bom_accounted_component_count', 0)}")
    lines.append(f"- Pick-and-place-accounted components: {policy.get('pick_and_place_accounted_component_count', 0)}")
    lines.append(f"- Checked components: {policy.get('checked_component_count', 0)}")
    lines.append(f"- Unresolved components: {policy.get('unresolved_component_count', 0)}")
    lines.append(f"- Placement-missing components: {policy.get('placement_missing_component_count', 0)}")
    lines.append(f"- Risky components: {policy.get('risky_component_count', 0)}")
    lines.append(f"- Blocked components: {policy.get('blocked_component_count', 0)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, *, trusted_root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Generate strict generated-board release-gate evidence")
    parser.add_argument("--artifact-dir", type=Path, default=Path(".generated/generated-board-release-gate"))
    parser.add_argument("--output", type=Path, help="Write JSON release-gate evidence to this path")
    parser.add_argument("--markdown", type=Path, help="Write Markdown release-gate summary to this path")
    parser.add_argument(
        "--risky-package-reviewed",
        action="store_true",
        help="Treat risky packages as human-reviewed for policy evaluation",
    )
    parser.add_argument(
        "--risky-package-approval-id",
        default="",
        help="Approval identifier for risky-package policy exceptions",
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero if the release gate does not pass")
    args = parser.parse_args(argv)

    try:
        report = build_report(
            args.artifact_dir,
            trusted_root=trusted_root,
            risky_package_reviewed=args.risky_package_reviewed,
            risky_package_approval_id=args.risky_package_approval_id,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report_json(report), encoding="utf-8")
    else:
        print(report_json(report), end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    if args.strict and not report["passed"]:
        print("generated-board release gate failed")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
