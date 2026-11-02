"""Strict state-bound checks on untrusted, self-declared local review records.

Neither a reviewer identity, a signature, a qualified decision nor a
time-to-trustworthy-decision measurement is authenticated here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from review_studio_change_diff import canonical_decision_hash, evidence_catalog
from review_studio_local_file_guard import read_regular_bytes

FIELDS = {
    "schema_version",
    "kind",
    "review_state_hash",
    "source_sha256",
    "proposed_sha256",
    "evidence_sha256",
    "reviewer",
    "outcome",
    "note",
    "evidence_ids",
    "timing",
    "fabrication_approved",
    "electrically_approved",
    "source_modified",
}
OUTCOMES = {"investigate", "repair_required", "reject_proposal"}


def validate_audit(state: dict, audit: dict) -> dict:
    if (
        state.get("schema_version") != 1
        or state.get("kind") != "unsigned_local_design_change_decision_not_approval"
        or state.get("decision_hash_contract") != "native_source_and_semantic_evidence_v2"
        or state.get("state_hash") != canonical_decision_hash(state)
        or state.get("audit_evidence_catalog") != evidence_catalog(state)
        or any(
            state.get(k) is not False for k in ("approval_supported", "fabrication_approved", "electrically_approved")
        )
    ):
        raise ValueError("Unsupported or altered native review state")
    if (
        not isinstance(audit, dict)
        or set(audit) != FIELDS
        or audit["schema_version"] != 2
        or audit["kind"] != "local_self_declared_evidence_review_not_identity_verified"
    ):
        raise ValueError("Unsupported local audit schema or authority claims")
    for key, counterpart in (
        ("review_state_hash", "state_hash"),
        ("source_sha256", "source_sha256"),
        ("proposed_sha256", "proposed_sha256"),
        ("evidence_sha256", "evidence_sha256"),
    ):
        if audit[key] != state[counterpart]:
            raise ValueError("Stale state or source/evidence hash")
    if any(audit[k] is not False for k in ("fabrication_approved", "electrically_approved", "source_modified")):
        raise ValueError("Unsigned audit cannot approve production or modify the source")
    reviewer = audit["reviewer"]
    if (
        not isinstance(reviewer, dict)
        or set(reviewer) != {"label", "identity_verified", "declaration"}
        or reviewer["identity_verified"] is not False
        or reviewer["declaration"] != "self_declared_unverified"
        or not isinstance(reviewer["label"], str)
        or not 2 <= len(reviewer["label"]) <= 80
        or reviewer["label"] != reviewer["label"].strip()
        or not all(ch.isprintable() for ch in reviewer["label"])
    ):
        raise ValueError("Only an unverified self-declared reviewer label is supported")
    if audit["outcome"] not in OUTCOMES:
        raise ValueError("Invalid local review outcome")
    note = audit["note"]
    if (
        not isinstance(note, str)
        or not 12 <= len(note.strip()) <= 600
        or any(ord(ch) < 32 and ch != "\\n" for ch in note)
    ):
        raise ValueError("A bounded engineering rationale is required")
    refs = audit["evidence_ids"]
    known = {x["id"] for x in state["audit_evidence_catalog"]}
    if (
        not isinstance(refs, list)
        or not 1 <= len(refs) <= 8
        or any(not isinstance(x, str) or x not in known for x in refs)
        or len(set(refs)) != len(refs)
    ):
        raise ValueError("Inspected evidence must be traceable to this native state")
    timer = audit["timing"]
    if (
        not isinstance(timer, dict)
        or set(timer) != {"source", "first_evidence_ms", "elapsed_ms", "time_to_trustworthy_decision_ms"}
        or timer["source"] != "local_browser_monotonic_unattested"
        or timer["time_to_trustworthy_decision_ms"] is not None
    ):
        raise ValueError("Browser timing does not establish trustworthy decision speed")
    first, elapsed = timer["first_evidence_ms"], timer["elapsed_ms"]
    if type(first) is not int or type(elapsed) is not int or not 0 <= first <= elapsed <= 3_600_000:
        raise ValueError("Unattested local timing is inconsistent")
    return {
        "kind": "unsigned_state_reference_validation_only",
        "validation_passed": True,
        "review_state_hash": state["state_hash"],
        "evidence_refs_checked": len(refs),
        "self_declared_identity_only": True,
        "cryptographic_signature_verified": False,
        "independent_engineering_review_verified": False,
        "time_to_trustworthy_decision_ms": None,
        "browser_reported_local_elapsed_ms": elapsed,
        "audit_content_sha256": hashlib.sha256(
            json.dumps(audit, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def _read(path: Path, max_size: int) -> dict:
    if path.suffix != ".json":
        raise ValueError("Review audit inputs must be JSON files")
    value = json.loads(read_regular_bytes(path, max_size=max_size).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    a = parser.parse_args()
    print(json.dumps(validate_audit(_read(a.state, 10_000_000), _read(a.audit, 1_048_576)), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
