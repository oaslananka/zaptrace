"""Fail-closed release evidence and approval identity helpers.

This module contains deterministic, surface-independent policy primitives used
by CLI, MCP, REST, CI, and direct release-export paths.  It does not emit
artifacts; it only describes whether the exact current design state has complete
release evidence and binds human approval to that evidence identity.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from zaptrace.core.models import Design
from zaptrace.ee.footprint_proof import (
    FootprintSourceProvenance,
    FootprintSourceType,
    build_footprint_proof,
    file_sha256,
    validate_footprint_proof,
    validate_risky_package_policy,
)
from zaptrace.ee.footprint_vendor import resolve_vendored_footprint, vendored_footprint_path
from zaptrace.ee.footprints import generate_footprint_for_component

RELEASE_GATE_VERSION = "2.1"


class ReleaseEvidenceStatus(StrEnum):
    """Canonical status vocabulary for release-critical evidence."""

    PASS = "pass"
    FAIL = "fail"
    MISSING_EVIDENCE = "missing-evidence"
    SKIP_APPROVED = "skip-approved"
    SKIP_UNAPPROVED = "skip-unapproved"
    HUMAN_REVIEW_REQUIRED = "human-review-required"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def release_design_state_hash(design: Design) -> str:
    """Hash release-relevant design state while excluding computed DRC output."""
    structural = design.model_dump(mode="json", exclude={"drc_result"})
    if structural.get("net_classes") is None:
        structural["net_classes"] = {}
    return _sha256_json(structural)


def _vendored_source(name: str) -> FootprintSourceProvenance | None:
    path = vendored_footprint_path(name)
    if path is None:
        return None
    return FootprintSourceProvenance(
        source_type=FootprintSourceType.VENDORED,
        source_name=name,
        source_path=path.relative_to(path.parents[3]).as_posix(),
        source_sha256=file_sha256(path),
        attribution="Vendored upstream land pattern; see data/footprints/vendor/ATTRIBUTION.md",
    )


def _component_geometry(component: Any) -> tuple[Any, FootprintSourceProvenance | None]:
    vendored_source = _vendored_source(component.footprint) if component.footprint else None
    if component.footprint_def is not None:
        return component.footprint_def, vendored_source
    if not component.footprint:
        return None, None
    if vendored_source is not None:
        return resolve_vendored_footprint(component.footprint), vendored_source
    generated = generate_footprint_for_component(component.footprint, component.type)
    return generated, None


def _placement_gap(component: Any) -> dict[str, Any]:
    return {
        "component_id": component.id,
        "component_ref": component.ref,
        "footprint": component.footprint,
        "reason": "pick-and-place position is unresolved",
    }


def _geometry_gap(component: Any) -> dict[str, Any]:
    return {
        "component_id": component.id,
        "component_ref": component.ref,
        "footprint": component.footprint,
        "reason": "footprint geometry is unresolved",
    }


def _component_proof_row(
    component: Any,
    footprint: Any,
    source: FootprintSourceProvenance | None,
    *,
    risky_package_reviewed: bool,
    risky_package_approval_id: str,
) -> dict[str, Any]:
    package_id = component.footprint or component.type or component.ref
    proof = build_footprint_proof(
        package_id,
        footprint,
        footprint_name=component.footprint or package_id,
        source=source,
    )
    proof_payload = proof.model_dump(mode="json")
    proof_validation = validate_footprint_proof(proof)
    review_authorized = risky_package_reviewed and bool(risky_package_approval_id.strip())
    risky_policy = validate_risky_package_policy(
        proof,
        reviewed=review_authorized,
        approval_id=risky_package_approval_id if review_authorized else "",
    )
    return {
        "component_id": component.id,
        "component_ref": component.ref,
        "footprint": component.footprint,
        "pad_count": proof.pad_count,
        "pin_count": proof.pin_count,
        "footprint_proof_sha256": _sha256_json(proof_payload),
        "footprint_source": proof_payload["source"],
        "proof_blocked": proof_validation.blocked,
        "proof_diagnostic_codes": [item.code for item in proof_validation.diagnostics],
        "risky": risky_policy.risky,
        "risky_family": risky_policy.family,
        "risky_policy_blocked": risky_policy.blocked,
        "risky_diagnostic_codes": [item.code for item in risky_policy.diagnostics],
    }


def _component_coverage_status(
    *,
    unresolved_components: list[dict[str, Any]],
    placement_missing_components: list[dict[str, Any]],
    blocked_components: list[dict[str, Any]],
) -> ReleaseEvidenceStatus:
    if unresolved_components or placement_missing_components:
        return ReleaseEvidenceStatus.MISSING_EVIDENCE
    if blocked_components:
        return ReleaseEvidenceStatus.HUMAN_REVIEW_REQUIRED
    return ReleaseEvidenceStatus.PASS


def build_component_coverage(
    design: Design,
    *,
    risky_package_reviewed: bool = False,
    risky_package_approval_id: str = "",
) -> dict[str, Any]:
    """Reconcile populated components with footprint and risky-package evidence."""
    checked_components: list[dict[str, Any]] = []
    unresolved_components: list[dict[str, Any]] = []
    placement_missing_components: list[dict[str, Any]] = []
    blocked_components: list[dict[str, Any]] = []
    risky_components: list[dict[str, Any]] = []
    populated = [component for component in design.components.values() if not component.dnp]
    placement = design.placement or {}

    for component in sorted(populated, key=lambda item: item.ref):
        if placement.get(component.id) is None and component.position is None:
            placement_missing_components.append(_placement_gap(component))
        footprint, source = _component_geometry(component)
        if footprint is None or not footprint.pads:
            unresolved_components.append(_geometry_gap(component))
            continue
        row = _component_proof_row(
            component,
            footprint,
            source,
            risky_package_reviewed=risky_package_reviewed,
            risky_package_approval_id=risky_package_approval_id,
        )
        checked_components.append(row)
        if row["proof_blocked"] or row["risky_policy_blocked"]:
            blocked_components.append(row)
        if row["risky"]:
            risky_components.append(row)

    status = _component_coverage_status(
        unresolved_components=unresolved_components,
        placement_missing_components=placement_missing_components,
        blocked_components=blocked_components,
    )
    return {
        "schema_version": "1.0",
        "status": status,
        "component_count": len(design.components),
        "populated_component_count": len(populated),
        "dnp_component_count": len(design.components) - len(populated),
        "bom_accounted_component_count": len(populated),
        "pick_and_place_accounted_component_count": len(populated) - len(placement_missing_components),
        "checked_component_count": len(checked_components),
        "unresolved_component_count": len(unresolved_components),
        "placement_missing_component_count": len(placement_missing_components),
        "risky_component_count": len(risky_components),
        "blocked_component_count": len(blocked_components),
        "risky_package_reviewed": risky_package_reviewed,
        "risky_package_approval_id": risky_package_approval_id.strip(),
        "checked_components": checked_components,
        "unresolved_components": unresolved_components,
        "placement_missing_components": placement_missing_components,
        "risky_components": risky_components,
        "blocked_components": blocked_components,
    }


def build_fab_profile_policy(
    *,
    fab_profile: str,
    skip_reason: str,
    skip_approval_id: str,
) -> dict[str, Any]:
    """Classify manufacturer-profile evidence without conflating it with release approval."""
    profile = fab_profile.strip()
    reason = skip_reason.strip()
    approval = skip_approval_id.strip()
    if profile:
        status = ReleaseEvidenceStatus.PASS
    elif reason and approval:
        status = ReleaseEvidenceStatus.SKIP_APPROVED
    elif reason:
        status = ReleaseEvidenceStatus.SKIP_UNAPPROVED
    else:
        status = ReleaseEvidenceStatus.MISSING_EVIDENCE
    return {
        "status": status,
        "fab_profile": profile,
        "skip_reason": reason,
        "skip_approval_id": approval,
    }


def require_current_validation(
    *,
    design_name: str,
    current_hash: str,
    validation: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Require fresh passing ERC and DRC bound to one release identity."""
    if validation is None:
        raise ValueError(
            f"Release export for '{design_name}' requires fresh ERC and DRC validation for the current design state"
        )
    erc = validation.get("erc")
    if not erc:
        raise ValueError(f"Release export for '{design_name}' requires fresh passing ERC evidence")
    if erc.get("design_state_hash") != current_hash:
        raise ValueError(f"Release export for '{design_name}' requires fresh ERC for the current design state")
    if not erc.get("passed"):
        raise ValueError(f"Release export for '{design_name}' requires passing ERC validation")
    drc = validation.get("drc")
    if not drc:
        raise ValueError(f"Release export for '{design_name}' requires fresh passing DRC evidence")
    if drc.get("design_state_hash") != current_hash:
        raise ValueError(f"Release export for '{design_name}' requires fresh DRC for the current design state")
    if not drc.get("passed"):
        raise ValueError(f"Release export for '{design_name}' requires passing DRC validation")
    return erc, drc


def require_complete_component_coverage(*, design_name: str, coverage: dict[str, Any]) -> None:
    """Reject missing or review-blocked component and assembly evidence."""
    if coverage["status"] != ReleaseEvidenceStatus.PASS:
        raise ValueError(
            f"Release export for '{design_name}' requires complete footprint and risky-package evidence "
            f"(status={coverage['status']})"
        )


def require_approved_fab_profile_policy(*, design_name: str, policy: dict[str, Any]) -> None:
    """Reject absent or unapproved fabrication-profile evidence."""
    if policy["status"] == ReleaseEvidenceStatus.SKIP_UNAPPROVED:
        raise ValueError(
            f"Release export for '{design_name}' has an unapproved fabrication-profile skip; "
            "provide fab_profile_skip_approval_id"
        )
    if policy["status"] == ReleaseEvidenceStatus.MISSING_EVIDENCE:
        raise ValueError(
            f"Release export for '{design_name}' requires a fabrication profile or an explicit approved skip reason"
        )


def build_release_evidence_identity(
    *,
    design_state_hash: str,
    erc: dict[str, Any],
    drc: dict[str, Any],
    component_coverage: dict[str, Any],
    fab_profile_status: str,
    fab_profile: str,
    fab_profile_skip_reason: str,
    fab_profile_skip_approval_id: str = "",
    engineering_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the deterministic identity to which release approval is bound."""

    identity = {
        "gate_version": RELEASE_GATE_VERSION,
        "design_state_hash": design_state_hash,
        "erc": erc,
        "drc": drc,
        "component_coverage": component_coverage,
        "fab_profile_policy": {
            "status": fab_profile_status,
            "fab_profile": fab_profile,
            "skip_reason": fab_profile_skip_reason,
            "skip_approval_id": fab_profile_skip_approval_id,
        },
    }
    if engineering_review is not None:
        identity["engineering_review"] = engineering_review
    return {**identity, "evidence_identity_hash": _sha256_json(identity)}


def bind_release_approval(
    approval_store: dict[str, dict[str, Any]],
    *,
    approval_id: str,
    evidence_identity: dict[str, Any],
) -> dict[str, Any]:
    """Bind one approval identifier to exactly one immutable evidence identity."""

    normalized = approval_id.strip()
    if not normalized:
        raise ValueError("approval_id is required for release-export operations")
    evidence_hash = str(evidence_identity.get("evidence_identity_hash") or "")
    if not evidence_hash:
        raise ValueError("release evidence identity hash is required before approval")

    existing = approval_store.get(normalized)
    if existing is not None:
        if existing.get("evidence_identity_hash") != evidence_hash:
            raise ValueError(f"approval_id '{normalized}' is already bound to different release evidence")
        return existing

    binding_material = {
        "approval_id": normalized,
        "gate_version": str(evidence_identity.get("gate_version") or RELEASE_GATE_VERSION),
        "evidence_identity_hash": evidence_hash,
    }
    record = {**binding_material, "approval_binding_hash": _sha256_json(binding_material)}
    approval_store[normalized] = record
    return record
