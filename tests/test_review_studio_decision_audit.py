"""Local review schema must not be elevated to engineering authorization."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from review_studio_change_diff import canonical_decision_hash, evidence_catalog  # noqa: E402
from review_studio_decision_audit import validate_audit  # noqa: E402


def data():
    state = {
        "schema_version": 1,
        "kind": "unsigned_local_design_change_decision_not_approval",
        "decision_hash_contract": "native_source_and_semantic_evidence_v2",
        "source_sha256": "a" * 64,
        "proposed_sha256": "b" * 64,
        "evidence_sha256": "c" * 64,
        "approval_supported": False,
        "fabrication_approved": False,
        "electrically_approved": False,
        "changed": [{"ref": "R1"}],
        "drc": {"before_rules": 2, "after_rules": 2},
        "schematic": None,
    }
    state["audit_evidence_catalog"] = evidence_catalog(state)
    state["state_hash"] = canonical_decision_hash(state)
    audit = {
        "schema_version": 2,
        "kind": "local_self_declared_evidence_review_not_identity_verified",
        "review_state_hash": state["state_hash"],
        "source_sha256": state["source_sha256"],
        "proposed_sha256": state["proposed_sha256"],
        "evidence_sha256": state["evidence_sha256"],
        "reviewer": {"label": "Reviewer A", "identity_verified": False, "declaration": "self_declared_unverified"},
        "outcome": "repair_required",
        "note": "Recheck the native engineering evidence.",
        "evidence_ids": ["pcb-change:0"],
        "timing": {
            "source": "local_browser_monotonic_unattested",
            "first_evidence_ms": 1000,
            "elapsed_ms": 2300,
            "time_to_trustworthy_decision_ms": None,
        },
        "fabrication_approved": False,
        "electrically_approved": False,
        "source_modified": False,
    }
    return state, audit


def test_unverified_audit_remains_not_approval():
    state, audit = data()
    report = validate_audit(state, audit)
    assert report["validation_passed"] is True
    assert report["cryptographic_signature_verified"] is False
    assert report["self_declared_identity_only"] is True
    assert report["independent_engineering_review_verified"] is False
    assert report["time_to_trustworthy_decision_ms"] is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("review_state_hash", "0" * 64),
        ("evidence_sha256", "0" * 64),
        ("outcome", "approve"),
        ("evidence_ids", ["fake:1"]),
        ("evidence_ids", ["pcb-change:0", "pcb-change:0"]),
        ("fabrication_approved", True),
        ("note", "short"),
    ],
)
def test_rejects_stale_unrelated_and_forged_claims(key, value):
    state, audit = data()
    audit[key] = value
    with pytest.raises(ValueError):
        validate_audit(state, audit)


@pytest.mark.parametrize(
    "field,value", [("identity_verified", True), ("label", " "), ("declaration", "identity_verified")]
)
def test_review_identity_is_only_self_declared(field, value):
    state, audit = data()
    audit["reviewer"][field] = value
    with pytest.raises(ValueError):
        validate_audit(state, audit)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "verified_by_human"),
        ("first_evidence_ms", True),
        ("elapsed_ms", 500),
        ("time_to_trustworthy_decision_ms", 2000),
    ],
)
def test_browser_local_time_cannot_claim_trustworthy_decision(field, value):
    state, audit = data()
    audit["timing"][field] = value
    with pytest.raises(ValueError):
        validate_audit(state, audit)


def test_tampered_catalog_and_fake_crypto_proof_are_rejected():
    state, audit = data()
    forged = copy.deepcopy(state)
    forged["audit_evidence_catalog"][0]["rule"] = "passed_all_rules"
    with pytest.raises(ValueError):
        validate_audit(forged, audit)
    audit["signature_verified"] = True
    with pytest.raises(ValueError):
        validate_audit(state, audit)
