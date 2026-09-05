"""Deterministic review-readiness evidence for bounded component qualification cohorts.

Qualification readiness is deliberately weaker than verification or release
eligibility.  Machine-readable evidence can be review-ready while a human
review is still required.  This module never promotes component trust tiers and
never synthesizes reviewer identity or fabrication/release approval.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from zaptrace.ee.footprint_proof import (
    FootprintProof,
    FootprintSourceType,
    classify_risky_package,
    validate_footprint_proof,
)
from zaptrace.library.governance import validate_governed_component
from zaptrace.library.schema import (
    ComponentField,
    ProvenanceConfidence,
    ProvenanceSourceType,
    ReviewScope,
)

COHORT_A_COMPONENT_IDS: tuple[str, ...] = (
    "esp32-c3-mini-1",
    "usb-c-16p",
    "ap2112k-3.3",
    "bme280",
    "atecc608b",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMPONENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_AUTHORITATIVE_SOURCES = {
    ProvenanceSourceType.MANUFACTURER_DOCUMENT,
    ProvenanceSourceType.MANUFACTURER_WEB,
    ProvenanceSourceType.AUTHORIZED_DISTRIBUTOR,
}
_TIME_BOUND_FIELDS = {ComponentField.LIFECYCLE, ComponentField.SOURCING}
_REQUIRED_REVIEW_SCOPES = {ReviewScope.RELEASE, ReviewScope.FABRICATION}


class QualificationBlockerClass(StrEnum):
    """Whether a readiness blocker requires machine evidence or human review."""

    MACHINE = "machine"
    HUMAN = "human"


class QualificationBlocker(BaseModel):
    """One exact blocker preventing review readiness or human completion."""

    blocker_class: QualificationBlockerClass
    code: str
    field: str = ""
    message: str


class ComponentQualificationReadiness(BaseModel):
    """Review-readiness result for one component without trust promotion."""

    component_id: str
    trust_tier: str
    release_eligible: bool
    review_ready: bool
    human_review_required: bool
    footprint_proof_path: str = ""
    footprint_proof_sha256: str = ""
    evidence_sha256: str
    blockers: list[QualificationBlocker] = Field(default_factory=list)


class ComponentQualificationReport(BaseModel):
    """Deterministic historical cohort qualification-readiness report."""

    schema_version: str = "1.0"
    historical_snapshot: bool = True
    evidence_status: str = "historical-governance-snapshot"
    as_of: date
    freshness_days: int = Field(ge=1)
    component_count: int = Field(ge=0)
    review_ready_count: int = Field(ge=0)
    machine_blocked_count: int = Field(ge=0)
    human_review_required_count: int = Field(ge=0)
    release_eligible_count: int = Field(ge=0)
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    components: list[ComponentQualificationReadiness]
    non_claims: list[str] = Field(default_factory=list)


def _blocker(
    blocker_class: QualificationBlockerClass,
    code: str,
    message: str,
    *,
    field: str = "",
) -> QualificationBlocker:
    return QualificationBlocker(
        blocker_class=blocker_class,
        code=code,
        field=field,
        message=message,
    )


def _freshness_blocker(
    field_name: ComponentField, evidence: Any, *, as_of: date, freshness_days: int
) -> QualificationBlocker | None:
    if field_name not in _TIME_BOUND_FIELDS or evidence.extracted_at is None:
        return None
    age_days = (as_of - evidence.extracted_at).days
    if age_days < 0:
        return _blocker(
            QualificationBlockerClass.MACHINE,
            "time-bound-source-captured-in-future",
            "time-bound evidence capture date is after the qualification as-of date",
            field=field_name.value,
        )
    if age_days > freshness_days:
        return _blocker(
            QualificationBlockerClass.MACHINE,
            "time-bound-source-stale",
            f"time-bound evidence is {age_days} days old; policy limit is {freshness_days}",
            field=field_name.value,
        )
    return None


def _field_evidence_machine_blockers(
    field_name: ComponentField, evidence: Any, *, as_of: date, freshness_days: int
) -> list[QualificationBlocker]:
    field = field_name.value
    checks = (
        (
            evidence.source_type in _AUTHORITATIVE_SOURCES,
            "field-source-not-authoritative",
            "verified qualification requires manufacturer or authorized-distributor evidence",
        ),
        (bool(evidence.source_locator), "field-source-locator-missing", "authoritative source locator is missing"),
        (bool(evidence.source_identity), "field-source-identity-missing", "authoritative source identity is missing"),
        (
            bool(_SHA256_RE.fullmatch(evidence.source_sha256)),
            "field-source-hash-missing",
            "authoritative source is not bound to a SHA-256 digest",
        ),
        (
            bool(evidence.source_version),
            "field-source-version-missing",
            "authoritative source version/capture identity is missing",
        ),
        (
            bool(evidence.extraction_method and evidence.extracted_at is not None),
            "field-extraction-metadata-missing",
            "evidence extraction method/date is incomplete",
        ),
    )
    blockers = [
        _blocker(QualificationBlockerClass.MACHINE, code, message, field=field)
        for passed, code, message in checks
        if not passed
    ]
    freshness = _freshness_blocker(field_name, evidence, as_of=as_of, freshness_days=freshness_days)
    if freshness is not None:
        blockers.append(freshness)
    return blockers


def _field_machine_blockers(spec: Any, *, as_of: date, freshness_days: int) -> list[QualificationBlocker]:
    blockers: list[QualificationBlocker] = []
    provenance = getattr(spec, "field_provenance", {})
    for field_name in ComponentField:
        evidence = provenance.get(field_name)
        if evidence is None:
            blockers.append(
                _blocker(
                    QualificationBlockerClass.MACHINE,
                    "field-provenance-missing",
                    "critical component field has no provenance",
                    field=field_name.value,
                )
            )
            continue
        blockers.extend(
            _field_evidence_machine_blockers(field_name, evidence, as_of=as_of, freshness_days=freshness_days)
        )
    return blockers


def _field_human_blockers(spec: Any) -> list[QualificationBlocker]:
    blockers: list[QualificationBlocker] = []
    provenance = getattr(spec, "field_provenance", {})
    for field_name in ComponentField:
        evidence = provenance.get(field_name)
        if evidence is None:
            continue
        field = field_name.value
        if not evidence.reviewed_by or evidence.reviewed_at is None:
            blockers.append(
                _blocker(
                    QualificationBlockerClass.HUMAN,
                    "field-review-metadata-missing",
                    "field evidence has not been explicitly reviewed by a named reviewer",
                    field=field,
                )
            )
        if evidence.confidence is not ProvenanceConfidence.HIGH:
            blockers.append(
                _blocker(
                    QualificationBlockerClass.HUMAN,
                    "field-confidence-not-high",
                    "verified promotion requires explicit high-confidence review",
                    field=field,
                )
            )
    return blockers


def _safe_repository_file(repository_root: Path, relative_path: str) -> Path:
    root = repository_root.resolve(strict=True)
    candidate = repository_root / relative_path
    if candidate.is_symlink():
        raise ValueError(f"evidence path must not be a symbolic link: {relative_path}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError(f"evidence path is outside repository root or not a regular file: {relative_path}")
    return resolved


def _proof_identity_blockers(spec: Any, proof: FootprintProof) -> list[QualificationBlocker]:
    if proof.package_id == getattr(spec, "package", "") and proof.footprint_name == getattr(spec, "footprint", ""):
        return []
    return [
        _blocker(
            QualificationBlockerClass.MACHINE,
            "footprint-proof-identity-mismatch",
            "footprint proof package/name does not match the component record",
            field="footprint",
        )
    ]


def _proof_source_blockers(proof: FootprintProof, *, repository_root: Path) -> list[QualificationBlocker]:
    if proof.source.source_type not in {FootprintSourceType.VENDORED, FootprintSourceType.IMPORTED}:
        return [
            _blocker(
                QualificationBlockerClass.MACHINE,
                "footprint-proof-source-not-reviewable",
                "qualification cohort requires a committed vendored/imported footprint source",
                field="footprint",
            )
        ]
    if not proof.source.source_path or not _SHA256_RE.fullmatch(proof.source.source_sha256):
        return [
            _blocker(
                QualificationBlockerClass.MACHINE,
                "footprint-proof-source-identity-missing",
                "footprint proof source path/hash is incomplete",
                field="footprint",
            )
        ]
    try:
        source_path = _safe_repository_file(repository_root, proof.source.source_path)
    except (OSError, ValueError) as exc:
        return [
            _blocker(
                QualificationBlockerClass.MACHINE,
                "footprint-proof-source-unavailable",
                str(exc),
                field="footprint",
            )
        ]
    observed = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if observed == proof.source.source_sha256:
        return []
    return [
        _blocker(
            QualificationBlockerClass.MACHINE,
            "footprint-proof-source-hash-mismatch",
            "footprint source digest does not match the committed source file",
            field="footprint",
        )
    ]


def _proof_pin_contract_blockers(spec: Any, proof: FootprintProof) -> list[QualificationBlocker]:
    physical_pins = set(getattr(spec, "package_pin_map", {}))
    if not physical_pins:
        return [
            _blocker(
                QualificationBlockerClass.MACHINE,
                "package-pin-map-missing",
                "qualification requires an exact physical package pin map",
                field="package_pin_map",
            )
        ]
    validation = validate_footprint_proof(proof, expected_physical_pins=physical_pins)
    if not validation.blocked:
        return []
    codes = ", ".join(sorted({item.code for item in validation.diagnostics if item.severity.value == "error"}))
    return [
        _blocker(
            QualificationBlockerClass.MACHINE,
            "footprint-proof-blocked",
            f"footprint proof validation failed: {codes}",
            field="footprint",
        )
    ]


def _proof_machine_blockers(
    spec: Any,
    *,
    component_id: str,
    repository_root: Path,
) -> tuple[list[QualificationBlocker], str, str]:
    relative_path = f"data/library/evidence/footprints/{component_id}.json"
    proof_path = repository_root / relative_path
    if not proof_path.is_file() or proof_path.is_symlink():
        return (
            [
                _blocker(
                    QualificationBlockerClass.MACHINE,
                    "footprint-proof-missing",
                    "committed SHA-bound footprint proof is missing",
                    field="footprint",
                )
            ],
            relative_path,
            "",
        )

    proof_bytes = proof_path.read_bytes()
    proof_digest = hashlib.sha256(proof_bytes).hexdigest()
    try:
        proof = FootprintProof.model_validate_json(proof_bytes)
    except ValueError as exc:
        return (
            [
                _blocker(
                    QualificationBlockerClass.MACHINE,
                    "footprint-proof-invalid",
                    f"footprint proof does not satisfy schema: {exc}",
                    field="footprint",
                )
            ],
            relative_path,
            proof_digest,
        )

    blockers = _proof_identity_blockers(spec, proof)
    blockers.extend(_proof_source_blockers(proof, repository_root=repository_root))
    blockers.extend(_proof_pin_contract_blockers(spec, proof))
    return blockers, relative_path, proof_digest


def _component_human_review_blockers(spec: Any) -> list[QualificationBlocker]:
    blockers = _field_human_blockers(spec)
    approval = getattr(spec, "human_review", None)
    if approval is None or not _REQUIRED_REVIEW_SCOPES.issubset(approval.scopes):
        blockers.append(
            _blocker(
                QualificationBlockerClass.HUMAN,
                "component-review-approval-missing",
                "verified promotion requires explicit release and fabrication review scopes",
                field="human_review",
            )
        )
    if classify_risky_package(getattr(spec, "package", ""), getattr(spec, "footprint", "")):
        blockers.append(
            _blocker(
                QualificationBlockerClass.HUMAN,
                "risky-package-review-required",
                "risky package family requires explicit reviewed footprint approval",
                field="footprint",
            )
        )
    return blockers


def _evidence_digest(
    spec: Any,
    *,
    component_id: str,
    proof_sha256: str,
    as_of: date,
    freshness_days: int,
) -> str:
    provenance = {
        field.value: evidence.model_dump(mode="json")
        for field, evidence in sorted(getattr(spec, "field_provenance", {}).items(), key=lambda item: item[0].value)
    }
    review = getattr(spec, "human_review", None)
    payload = {
        "component_id": component_id,
        "manufacturer": getattr(spec, "manufacturer", ""),
        "mpn": getattr(spec, "mpn", ""),
        "package": getattr(spec, "package", ""),
        "footprint": getattr(spec, "footprint", ""),
        "package_pin_map": dict(sorted(getattr(spec, "package_pin_map", {}).items())),
        "trust_tier": getattr(getattr(spec, "trust_tier", ""), "value", str(getattr(spec, "trust_tier", ""))),
        "field_provenance": provenance,
        "human_review": review.model_dump(mode="json") if review is not None else None,
        "footprint_proof_sha256": proof_sha256,
        "as_of": as_of.isoformat(),
        "freshness_days": freshness_days,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _missing_component_row(component_id: str, *, as_of: date, freshness_days: int) -> ComponentQualificationReadiness:
    blocker = _blocker(
        QualificationBlockerClass.MACHINE,
        "component-not-found",
        "cohort component id is not present in the committed library",
    )
    encoded = json.dumps(
        {"component_id": component_id, "as_of": as_of.isoformat(), "freshness_days": freshness_days},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return ComponentQualificationReadiness(
        component_id=component_id,
        trust_tier="missing",
        release_eligible=False,
        review_ready=False,
        human_review_required=True,
        evidence_sha256=hashlib.sha256(encoded).hexdigest(),
        blockers=[blocker],
    )


def _component_row(
    spec: Any,
    *,
    component_id: str,
    repository_root: Path,
    as_of: date,
    freshness_days: int,
) -> ComponentQualificationReadiness:
    machine = _field_machine_blockers(spec, as_of=as_of, freshness_days=freshness_days)
    proof_blockers, proof_path, proof_sha256 = _proof_machine_blockers(
        spec,
        component_id=component_id,
        repository_root=repository_root,
    )
    machine.extend(proof_blockers)
    human = _component_human_review_blockers(spec)
    governance = validate_governed_component(spec)
    trust_tier = getattr(getattr(spec, "trust_tier", ""), "value", str(getattr(spec, "trust_tier", "")))
    return ComponentQualificationReadiness(
        component_id=component_id,
        trust_tier=trust_tier,
        release_eligible=governance.release_eligible,
        review_ready=not machine,
        human_review_required=bool(human),
        footprint_proof_path=proof_path,
        footprint_proof_sha256=proof_sha256,
        evidence_sha256=_evidence_digest(
            spec,
            component_id=component_id,
            proof_sha256=proof_sha256,
            as_of=as_of,
            freshness_days=freshness_days,
        ),
        blockers=machine + human,
    )


def write_component_qualification_report(report: ComponentQualificationReport, output_path: str | Path) -> Path:
    """Write one deterministic qualification report to JSON."""

    out = Path(output_path)
    if out.suffix.lower() != ".json":
        raise ValueError(f"unexpected qualification report suffix: {out.suffix}")
    resolved = out.resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return resolved


def evaluate_component_qualification_readiness(
    specs: dict[str, Any],
    component_ids: tuple[str, ...] | list[str],
    *,
    repository_root: str | Path,
    as_of: date,
    freshness_days: int = 90,
) -> ComponentQualificationReport:
    """Evaluate one bounded cohort without changing trust or approval state."""

    ids = list(component_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate component id in qualification cohort")
    if any(not _COMPONENT_ID_RE.fullmatch(component_id) for component_id in ids):
        raise ValueError("unsafe component id in qualification cohort")
    if freshness_days < 1:
        raise ValueError("freshness_days must be positive")

    root = Path(repository_root)
    rows = [
        _component_row(
            specs[component_id],
            component_id=component_id,
            repository_root=root,
            as_of=as_of,
            freshness_days=freshness_days,
        )
        if component_id in specs
        else _missing_component_row(component_id, as_of=as_of, freshness_days=freshness_days)
        for component_id in ids
    ]
    payload = {
        "schema_version": "1.0",
        "as_of": as_of.isoformat(),
        "freshness_days": freshness_days,
        "components": [row.model_dump(mode="json") for row in rows],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ComponentQualificationReport(
        as_of=as_of,
        freshness_days=freshness_days,
        component_count=len(rows),
        review_ready_count=sum(row.review_ready for row in rows),
        machine_blocked_count=sum(not row.review_ready for row in rows),
        human_review_required_count=sum(row.human_review_required for row in rows),
        release_eligible_count=sum(row.release_eligible for row in rows),
        report_sha256=digest,
        components=rows,
        non_claims=[
            (
                "Review readiness is not verified trust, release eligibility, fabrication approval, "
                "or physical hardware validation."
            ),
            "No reviewer identity or approval scope is synthesized by this report.",
        ],
    )
