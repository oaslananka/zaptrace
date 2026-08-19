"""Release-evidence identity, approval binding, and component coverage tests."""

from __future__ import annotations

import pytest

import zaptrace.security.release as release_policy
from zaptrace.core.models import Component, Design, DesignMeta, FootprintDef, Pad, RouteResult, TraceSegment
from zaptrace.ee.footprint_vendor import vendored_footprint_path
from zaptrace.security.release import (
    RELEASE_GATE_VERSION,
    ReleaseEvidenceStatus,
    bind_release_approval,
    build_component_coverage,
    build_fab_profile_policy,
    build_release_evidence_identity,
)


def _design(*components: Component) -> Design:
    return Design(meta=DesignMeta(name="ReleaseEvidenceBoard"), components={item.id: item for item in components})


def _component(
    component_id: str,
    ref: str,
    *,
    footprint: str = "0603",
    footprint_def: FootprintDef | None = None,
    dnp: bool = False,
    position: tuple[float, float] | None = (10.0, 10.0),
) -> Component:
    return Component(
        id=component_id,
        ref=ref,
        type="resistor",
        value="10k",
        footprint=footprint,
        footprint_def=footprint_def,
        position=position,
        dnp=dnp,
    )


def test_component_coverage_passes_when_every_populated_component_has_geometry() -> None:
    coverage = build_component_coverage(_design(_component("r1", "R1")))

    assert coverage["status"] == ReleaseEvidenceStatus.PASS
    assert coverage["populated_component_count"] == 1
    assert coverage["checked_component_count"] == 1
    assert coverage["unresolved_component_count"] == 0
    assert coverage["blocked_component_count"] == 0


def test_component_coverage_treats_missing_footprint_name_as_missing_evidence() -> None:
    coverage = build_component_coverage(_design(_component("u1", "U1", footprint="")))

    assert coverage["status"] == ReleaseEvidenceStatus.MISSING_EVIDENCE
    assert coverage["unresolved_components"][0]["reason"] == "footprint geometry is unresolved"


def test_component_coverage_treats_zero_checked_components_as_missing_evidence() -> None:
    coverage = build_component_coverage(_design(_component("u1", "U1", footprint="UNKNOWN-PACKAGE")))

    assert coverage["status"] == ReleaseEvidenceStatus.MISSING_EVIDENCE
    assert coverage["populated_component_count"] == 1
    assert coverage["checked_component_count"] == 0
    assert coverage["unresolved_component_count"] == 1
    assert coverage["unresolved_components"][0]["component_ref"] == "U1"


def test_component_coverage_excludes_dnp_components_from_release_denominator() -> None:
    coverage = build_component_coverage(_design(_component("r1", "R1", footprint="", dnp=True)))

    assert coverage["status"] == ReleaseEvidenceStatus.PASS
    assert coverage["component_count"] == 1
    assert coverage["populated_component_count"] == 0
    assert coverage["checked_component_count"] == 0


def test_component_coverage_rejects_missing_pick_and_place_position() -> None:
    coverage = build_component_coverage(_design(_component("r1", "R1", position=None)))

    assert coverage["status"] == ReleaseEvidenceStatus.MISSING_EVIDENCE
    assert coverage["bom_accounted_component_count"] == 1
    assert coverage["pick_and_place_accounted_component_count"] == 0
    assert coverage["placement_missing_component_count"] == 1
    assert coverage["placement_missing_components"][0]["component_ref"] == "R1"


def test_component_coverage_records_full_footprint_proof_and_upstream_source_hash() -> None:
    coverage = build_component_coverage(_design(_component("u1", "U1", footprint="ESP32-WROOM-32")))

    row = coverage["checked_components"][0]
    source_path = vendored_footprint_path("ESP32-WROOM-32")

    assert source_path is not None
    assert len(row["footprint_proof_sha256"]) == 64
    assert row["footprint_source"]["source_type"] == "vendored"
    assert row["footprint_source"]["source_sha256"] == release_policy.file_sha256(source_path)


def test_footprint_proof_identity_changes_when_geometry_changes_without_count_change() -> None:
    first = _component(
        "u1",
        "U1",
        footprint="QFN-2",
        footprint_def=FootprintDef(
            courtyard=(2.0, 2.0),
            pads=[Pad(id="1", position=(0.0, 0.0)), Pad(id="2", position=(1.0, 0.0))],
        ),
    )
    changed = first.model_copy(deep=True)
    assert changed.footprint_def is not None
    changed.footprint_def.pads[1].position = (1.5, 0.0)

    first_coverage = build_component_coverage(
        _design(first), risky_package_reviewed=True, risky_package_approval_id="FP-REVIEW-1"
    )
    changed_coverage = build_component_coverage(
        _design(changed), risky_package_reviewed=True, risky_package_approval_id="FP-REVIEW-1"
    )

    assert first_coverage["checked_components"][0]["pad_count"] == 2
    assert changed_coverage["checked_components"][0]["pad_count"] == 2
    assert (
        first_coverage["checked_components"][0]["footprint_proof_sha256"]
        != changed_coverage["checked_components"][0]["footprint_proof_sha256"]
    )


def test_component_coverage_requires_explicit_review_for_risky_package() -> None:
    risky = _component(
        "u1",
        "U1",
        footprint="QFN-16",
        footprint_def=FootprintDef(
            courtyard=(4.0, 4.0),
            pads=[Pad(id=str(index), position=(float(index), 0.0)) for index in range(1, 17)],
        ),
    )

    blocked = build_component_coverage(_design(risky))
    approved = build_component_coverage(
        _design(risky),
        risky_package_reviewed=True,
        risky_package_approval_id="FP-REVIEW-1",
    )

    assert blocked["status"] == ReleaseEvidenceStatus.HUMAN_REVIEW_REQUIRED
    assert blocked["blocked_component_count"] == 1
    assert approved["status"] == ReleaseEvidenceStatus.PASS
    assert approved["blocked_component_count"] == 0
    assert approved["risky_package_approval_id"] == "FP-REVIEW-1"


def test_risky_package_review_requires_both_review_flag_and_approval_id() -> None:
    risky = _component(
        "u1",
        "U1",
        footprint="QFN-16",
        footprint_def=FootprintDef(
            courtyard=(4.0, 4.0),
            pads=[Pad(id=str(index), position=(float(index), 0.0)) for index in range(1, 17)],
        ),
    )

    missing_id = build_component_coverage(_design(risky), risky_package_reviewed=True)
    missing_review = build_component_coverage(
        _design(risky),
        risky_package_reviewed=False,
        risky_package_approval_id="FP-REVIEW-1",
    )

    assert missing_id["status"] == ReleaseEvidenceStatus.HUMAN_REVIEW_REQUIRED
    assert missing_review["status"] == ReleaseEvidenceStatus.HUMAN_REVIEW_REQUIRED
    assert missing_id["blocked_component_count"] == 1
    assert missing_review["blocked_component_count"] == 1


def test_fab_profile_policy_distinguishes_approved_and_unapproved_skips() -> None:
    unapproved = build_fab_profile_policy(
        fab_profile="",
        skip_reason="Manufacturer profile is not applicable",
        skip_approval_id="",
    )
    approved = build_fab_profile_policy(
        fab_profile="",
        skip_reason="Manufacturer profile is not applicable",
        skip_approval_id="FAB-SKIP-1",
    )

    assert unapproved["status"] == ReleaseEvidenceStatus.SKIP_UNAPPROVED
    assert approved["status"] == ReleaseEvidenceStatus.SKIP_APPROVED
    assert approved["skip_approval_id"] == "FAB-SKIP-1"


def test_release_design_hash_changes_with_footprint_and_routing() -> None:
    base = _design(_component("r1", "R1"))
    footprint_changed = base.model_copy(deep=True)
    footprint_changed.components["r1"].footprint = "0805"
    routed = base.model_copy(deep=True)
    routed.routing = RouteResult(
        traces=[TraceSegment(layer="F.Cu", start=(0.0, 0.0), end=(5.0, 0.0), net_id="n1")],
        layers_used=["F.Cu"],
        total_trace_length_mm=5.0,
        net_count=1,
        routed_net_count=1,
    )

    base_hash = release_policy.release_design_state_hash(base)

    assert release_policy.release_design_state_hash(footprint_changed) != base_hash
    assert release_policy.release_design_state_hash(routed) != base_hash


def test_release_identity_hash_changes_with_gate_version(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = {
        "design_state_hash": "design-hash",
        "erc": {"status": "pass", "total_errors": 0},
        "drc": {"status": "pass", "total_violations": 0, "fab_profile": "jlcpcb-2layer"},
        "component_coverage": {"status": "pass", "checked_component_count": 1},
        "fab_profile_status": "pass",
        "fab_profile": "jlcpcb-2layer",
        "fab_profile_skip_reason": "",
    }
    base = build_release_evidence_identity(**kwargs)
    monkeypatch.setattr(release_policy, "RELEASE_GATE_VERSION", "3.0")
    changed = build_release_evidence_identity(**kwargs)

    assert base["evidence_identity_hash"] != changed["evidence_identity_hash"]
    assert changed["gate_version"] == "3.0"


def test_release_identity_hash_changes_with_profile_and_gate_version() -> None:
    base = build_release_evidence_identity(
        design_state_hash="design-hash",
        erc={"status": "pass", "total_errors": 0},
        drc={"status": "pass", "total_violations": 0, "fab_profile": "jlcpcb-2layer"},
        component_coverage={"status": "pass", "checked_component_count": 1},
        fab_profile_status="pass",
        fab_profile="jlcpcb-2layer",
        fab_profile_skip_reason="",
    )
    changed_profile = build_release_evidence_identity(
        design_state_hash="design-hash",
        erc={"status": "pass", "total_errors": 0},
        drc={"status": "pass", "total_violations": 0, "fab_profile": "pcbway-standard"},
        component_coverage={"status": "pass", "checked_component_count": 1},
        fab_profile_status="pass",
        fab_profile="pcbway-standard",
        fab_profile_skip_reason="",
    )

    assert base["gate_version"] == RELEASE_GATE_VERSION
    assert base["evidence_identity_hash"] != changed_profile["evidence_identity_hash"]


def test_approval_binding_rejects_missing_identifier_or_identity_hash() -> None:
    with pytest.raises(ValueError, match="approval_id is required"):
        bind_release_approval({}, approval_id=" ", evidence_identity={"evidence_identity_hash": "hash"})
    with pytest.raises(ValueError, match="evidence identity hash is required"):
        bind_release_approval({}, approval_id="APPROVAL-1", evidence_identity={})


def test_approval_id_cannot_be_reused_for_different_evidence_identity() -> None:
    approvals: dict[str, dict[str, object]] = {}
    first_identity = {"gate_version": RELEASE_GATE_VERSION, "evidence_identity_hash": "identity-a"}
    second_identity = {"gate_version": RELEASE_GATE_VERSION, "evidence_identity_hash": "identity-b"}

    first = bind_release_approval(approvals, approval_id="APPROVAL-1", evidence_identity=first_identity)
    repeated = bind_release_approval(approvals, approval_id="APPROVAL-1", evidence_identity=first_identity)

    assert repeated == first
    assert first["approval_binding_hash"]
    with pytest.raises(ValueError, match="bound to different release evidence"):
        bind_release_approval(approvals, approval_id="APPROVAL-1", evidence_identity=second_identity)
