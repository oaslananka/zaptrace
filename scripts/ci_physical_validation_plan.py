"""Validate the bounded pre-fabrication physical reference-board plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.evidence.identity import EvidenceMode, capture_evidence_identity  # noqa: E402

DEFAULT_PLAN = Path("benchmarks/esp32_usb_sensor/physical-validation-plan.json")
EVIDENCE_SOURCE_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "scripts/ci_physical_validation_plan.py",
    "benchmarks/esp32_usb_sensor/physical-validation-plan.json",
    "benchmarks/esp32_usb_sensor/requirements.json",
    "benchmarks/esp32_usb_sensor/exports/manifest.json",
)
REQUIRED_MEASUREMENTS = {
    "vbus_voltage",
    "rail_3v3_voltage",
    "i2c_functional",
    "idle_current",
    "active_current",
    "component_temperature",
}
REQUIRED_INSTRUMENT_FIELDS = {
    "manufacturer",
    "model",
    "serial_or_asset_id",
    "calibration_status",
    "range",
    "resolution",
    "uncertainty",
}
REQUIRED_DESIGN_CHECKS = {
    "exact_component_identity",
    "usb_c_sink_cc_termination",
    "footprint_resolution_complete",
    "placement_complete",
    "internal_erc_clean",
    "internal_drc_clean",
    "kicad_erc_clean",
    "kicad_drc_clean",
    "profile_bound_dfm_non_hard_fail",
}
REQUIRED_CORRELATION_FIELDS = {
    "measurement_id",
    "predicted_source",
    "predicted_value_or_range",
    "measured_value",
    "units",
    "uncertainty",
    "result",
    "discrepancy_id",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _mapping(value: Any, field: str, violations: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        violations.append(f"{field} must be an object")
        return {}
    return value


def _required(section: dict[str, Any], field: str, prefix: str, violations: list[str]) -> Any:
    if field not in section:
        violations.append(f"missing required field: {prefix}.{field}")
        return None
    return section[field]


def _list(value: Any, field: str, violations: list[str]) -> list[Any]:
    if not isinstance(value, list) or not value:
        violations.append(f"{field} must be a non-empty list")
        return []
    return value


def _resolve_plan(path: Path, trusted_root: Path) -> Path:
    root = trusted_root.resolve(strict=True)
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"plan path escapes trusted root: {path}") from exc
    return resolved


def _load_plan_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("physical validation plan must be a JSON object")
    return payload


def _validate_metadata(payload: dict[str, Any], violations: list[str]) -> None:
    expected = {
        "schema_version": "1.0",
        "family_id": "esp32_usb_sensor",
        "status": "pre-fabrication-candidate",
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            violations.append(f"{field} must be {value}")


def _validate_power_scope(power_scope: dict[str, Any], violations: list[str]) -> None:
    current_limit = _required(power_scope, "supply_current_limit_a", "power_scope", violations)
    if current_limit is not None and (not isinstance(current_limit, (int, float)) or not 0 < current_limit <= 1.0):
        violations.append("power_scope.supply_current_limit_a must be > 0 and <= 1.0 A")

    stop_conditions = _required(power_scope, "stop_conditions", "power_scope", violations)
    if stop_conditions is None:
        return
    stops = _list(stop_conditions, "power_scope.stop_conditions", violations)
    if len(stops) < 4:
        violations.append("power_scope.stop_conditions must define at least four bounded stop conditions")


def _validate_required_values(
    section: dict[str, Any],
    *,
    field: str,
    prefix: str,
    required_values: set[str],
    missing_label: str,
    violations: list[str],
) -> None:
    values = _required(section, field, prefix, violations)
    if values is None:
        return
    found = {str(value) for value in _list(values, f"{prefix}.{field}", violations)}
    missing = sorted(required_values - found)
    if missing:
        violations.append(f"missing {missing_label}(s): {', '.join(missing)}")


def _validate_measurement_program(measurements: dict[str, Any], violations: list[str]) -> None:
    _validate_required_values(
        measurements,
        field="required_measurements",
        prefix="measurement_program",
        required_values=REQUIRED_MEASUREMENTS,
        missing_label="required measurement kind",
        violations=violations,
    )
    _validate_required_values(
        measurements,
        field="instrument_metadata_required",
        prefix="measurement_program",
        required_values=REQUIRED_INSTRUMENT_FIELDS,
        missing_label="instrument metadata field",
        violations=violations,
    )


def _validate_correlation_report(correlation: dict[str, Any], violations: list[str]) -> None:
    _validate_required_values(
        correlation,
        field="required_fields",
        prefix="correlation_report",
        required_values=REQUIRED_CORRELATION_FIELDS,
        missing_label="correlation report field",
        violations=violations,
    )
    if correlation.get("preserve_original_prediction") is not True:
        violations.append("correlation_report.preserve_original_prediction must be true")


def _validate_selection_decision(selection: dict[str, Any], violations: list[str]) -> None:
    if selection.get("status") != "approved":
        violations.append("selection_decision.status must be approved")
    if selection.get("scope") != "board-selection-only":
        violations.append("selection_decision.scope must be board-selection-only")
    if not selection.get("decided_by"):
        violations.append("selection_decision.decided_by is required")
    if not selection.get("decided_at"):
        violations.append("selection_decision.decided_at is required")
    if selection.get("selected_family") != "esp32_usb_sensor":
        violations.append("selection_decision.selected_family must be esp32_usb_sensor")
    non_claim = str(selection.get("non_claim", "")).lower()
    if "not" not in non_claim or "fabrication approval" not in non_claim:
        violations.append("selection_decision.non_claim must disclaim fabrication approval")


def _validate_design_readiness(readiness: dict[str, Any], violations: list[str]) -> str:
    status = str(readiness.get("status", ""))
    if status not in {"blocked", "ready"}:
        violations.append("design_readiness.status must be blocked or ready")
    checks = _list(readiness.get("required_checks"), "design_readiness.required_checks", violations)
    missing = sorted(REQUIRED_DESIGN_CHECKS - {str(value) for value in checks})
    if missing:
        violations.append(f"missing design readiness check(s): {', '.join(missing)}")
    blockers = readiness.get("blocking_reasons")
    if status == "blocked":
        _list(blockers, "design_readiness.blocking_reasons", violations)
    elif blockers not in (None, []):
        violations.append("design_readiness.blocking_reasons must be empty when status is ready")
    return status


def _validate_human_review(human_review: dict[str, Any], violations: list[str]) -> Any:
    review_status = human_review.get("status")
    if review_status not in {"pending", "approved"}:
        violations.append("human_review.status must be pending or approved")
    if review_status == "approved" and (not human_review.get("reviewer") or not human_review.get("reviewed_at")):
        violations.append("approved human_review requires reviewer and reviewed_at")
    return review_status


def _is_forbidden_fabrication_source(source_path: Any) -> bool:
    if not isinstance(source_path, str):
        return False
    lowered = source_path.lower()
    return any(
        token in lowered
        for token in (
            "/golden/",
            "starter-fixture",
            "benchmarks/esp32_usb_sensor/golden/",
        )
    )


def _validate_eligible_fabrication(fabrication: dict[str, Any], source_path: Any, violations: list[str]) -> None:
    bundle_hash = fabrication.get("ordered_bundle_sha256")
    if not isinstance(bundle_hash, str) or SHA256_RE.fullmatch(bundle_hash) is None:
        violations.append("fabrication.ordered_bundle_sha256 must be a SHA-256 when eligible")
    if not isinstance(source_path, str) or not source_path.strip():
        violations.append("fabrication.source_path is required when eligible")


def _validate_fabrication(fabrication: dict[str, Any], review_status: Any, violations: list[str]) -> tuple[bool, Any]:
    eligible = fabrication.get("eligible")
    if not isinstance(eligible, bool):
        violations.append("fabrication.eligible must be boolean")
        eligible = False

    source_path = fabrication.get("source_path")
    if _is_forbidden_fabrication_source(source_path):
        violations.append("starter fixture paths are forbidden as fabrication sources")
    if review_status == "pending" and eligible:
        violations.append("fabrication cannot be eligible while human review is pending")
    if eligible:
        _validate_eligible_fabrication(fabrication, source_path, violations)

    blocking_reasons = fabrication.get("blocking_reasons")
    if not eligible:
        _list(blocking_reasons, "fabrication.blocking_reasons", violations)
    return eligible, blocking_reasons


def _validate_non_claims(payload: dict[str, Any], violations: list[str]) -> list[Any]:
    non_claims = _list(payload.get("non_claims"), "non_claims", violations)
    non_claim_text = " ".join(str(value).lower() for value in non_claims)
    if "starter fixture" not in non_claim_text:
        violations.append("non_claims must state that the starter fixture is not a fabrication source")
    if "fabrication approval" not in non_claim_text:
        violations.append("non_claims must disclaim fabrication approval")
    return non_claims


def _report_blocking_reasons(blocking_reasons: Any) -> list[Any]:
    return list(blocking_reasons) if isinstance(blocking_reasons, list) else []


def evaluate_plan(plan_path: Path, *, trusted_root: Path) -> dict[str, Any]:
    """Validate a physical-validation plan without granting fabrication approval."""
    path = _resolve_plan(plan_path, trusted_root)
    payload = _load_plan_payload(path)
    violations: list[str] = []

    _validate_metadata(payload, violations)
    selection_decision = _mapping(payload.get("selection_decision"), "selection_decision", violations)
    design_readiness = _mapping(payload.get("design_readiness"), "design_readiness", violations)
    human_review = _mapping(payload.get("human_review"), "human_review", violations)
    fabrication = _mapping(payload.get("fabrication"), "fabrication", violations)
    power_scope = _mapping(payload.get("power_scope"), "power_scope", violations)
    measurements = _mapping(payload.get("measurement_program"), "measurement_program", violations)
    correlation = _mapping(payload.get("correlation_report"), "correlation_report", violations)

    _validate_selection_decision(selection_decision, violations)
    readiness_status = _validate_design_readiness(design_readiness, violations)
    _validate_power_scope(power_scope, violations)
    _validate_measurement_program(measurements, violations)
    _validate_correlation_report(correlation, violations)
    review_status = _validate_human_review(human_review, violations)
    eligible, blocking_reasons = _validate_fabrication(fabrication, review_status, violations)
    if eligible and readiness_status != "ready":
        violations.append("fabrication cannot be eligible while design readiness is blocked")
    non_claims = _validate_non_claims(payload, violations)

    return {
        "schema_version": "1.0",
        "gate_id": "physical-validation-plan-gate-v1",
        "plan_id": payload.get("plan_id", ""),
        "family_id": payload.get("family_id", ""),
        "status": payload.get("status", ""),
        "selection_decision": selection_decision,
        "design_readiness": design_readiness,
        "passed": not violations,
        "plan_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "human_review": human_review,
        "fabrication": fabrication,
        "power_scope": power_scope,
        "measurement_program": measurements,
        "correlation_report": correlation,
        "non_claims": non_claims,
        "blocking_reasons": _report_blocking_reasons(blocking_reasons),
        "violations": violations,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Physical Validation Plan Gate", ""]
    lines.append(f"Plan: `{report['plan_id']}`")
    lines.append(f"Family: `{report['family_id']}`")
    lines.append(f"Passed: `{str(report['passed']).lower()}`")
    lines.append(f"Board selection: `{report['selection_decision'].get('status', '')}`")
    lines.append(f"Design readiness: `{report['design_readiness'].get('status', '')}`")
    lines.append(f"Human review: `{report['human_review'].get('status', '')}`")
    lines.append(f"Fabrication eligible: `{str(report['fabrication'].get('eligible', False)).lower()}`")
    lines.append(f"Plan SHA-256: `{report['plan_sha256']}`")
    identity = report.get("evidence_identity")
    if isinstance(identity, dict):
        lines.extend(
            [
                "",
                "## Evidence identity",
                "",
                f"- Source commit: `{identity['source_commit']}`",
                f"- Source ref: `{identity['source_ref']}`",
                f"- Identity SHA-256: `{identity['identity_sha256']}`",
            ]
        )
    lines.extend(["", "## Design-readiness blockers", ""])
    for reason in report["design_readiness"].get("blocking_reasons", []):
        lines.append(f"- {reason}")
    lines.extend(["", "## Fabrication blockers", ""])
    for reason in report["blocking_reasons"]:
        lines.append(f"- {reason}")
    lines.extend(["", "## Violations", ""])
    if report["violations"]:
        for violation in report["violations"]:
            lines.append(f"- {violation}")
    else:
        lines.append("- None")
    lines.extend(["", "## Non-claims", ""])
    for claim in report["non_claims"]:
        lines.append(f"- {claim}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = evaluate_plan(args.plan, trusted_root=ROOT)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    identity = capture_evidence_identity(
        root=ROOT,
        mode=EvidenceMode.SNAPSHOT,
        source_inputs=EVIDENCE_SOURCE_INPUTS,
    )
    report["schema_version"] = "2.0"
    report["evidence_identity"] = identity.model_dump(mode="json")
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = render_markdown(report)
    if args.markdown:
        args.markdown.write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
