"""Strict human-engineered reference corpus and attempt contracts.

This module validates immutable upstream source identity and attempt evidence. It
never fetches upstream content and does not convert source provenance into a
qualified engineering approval.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_RFC3339_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SPDX_RE = re.compile(r"^[A-Za-z0-9.+() -]+$")
_PROHIBITED_REVIEWERS = {
    "zaptrace",
    "zaptrace core team",
    "ci",
    "github actions",
    "example-only",
    "chatgpt",
    "openai",
    "ai agent",
}
_EXPECTED_DIMENSIONS = {
    "requirements-coverage",
    "erc-drc-oracle",
    "schematic-parity",
    "component-evidence",
    "layout-quality",
    "dfm-readiness",
    "simulation-analysis",
    "human-review",
}
_KIND_SUFFIXES: dict[str, set[str]] = {
    "project": {".pro", ".kicad_pro"},
    "schematic": {".sch", ".kicad_sch"},
    "pcb": {".kicad_pcb"},
}

EngineeringOrigin = Literal["human-engineered-upstream"]
SourceVerification = Literal["vendored-byte-exact", "reference-only-hash-pinned"]
ReviewStatus = Literal["pending-human-review", "reviewed", "rejected"]
EvidenceAuthority = Literal["verified", "reviewed", "reported", "missing"]
AttemptStatus = Literal["template", "submitted"]


class HumanReferenceError(ValueError):
    """Raised when a human-reference JSON contract cannot be loaded."""


class HumanReferenceArtifact(BaseModel):
    """One selected upstream project artifact in a normalized reference."""

    model_config = ConfigDict(extra="forbid", strict=True)

    path: str
    kind: Literal["project", "schematic", "pcb"]
    format: str
    size_bytes: int = Field(ge=1)
    sha256: str

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        stripped = value.strip()
        path = Path(stripped)
        if not stripped or path.is_absolute() or ".." in path.parts:
            raise ValueError("artifact path must be relative and must not contain '..'")
        return path.as_posix()

    @field_validator("format")
    @classmethod
    def _validate_format(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("artifact format must not be empty")
        return value.strip()

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def _validate_kind_suffix(self) -> HumanReferenceArtifact:
        if Path(self.path).suffix.lower() not in _KIND_SUFFIXES[self.kind]:
            raise ValueError(f"{self.kind} artifact path uses an incompatible file extension")
        return self


class HumanReviewRecord(BaseModel):
    """Identity-bound qualified human review metadata."""

    model_config = ConfigDict(extra="forbid", strict=True)

    reviewer_name: str
    reviewer_organization: str
    reviewer_role: str
    reviewed_at: str
    review_decision: Literal["approved", "rejected"]
    evidence_url: str
    notes: str

    @field_validator("reviewer_name")
    @classmethod
    def _validate_reviewer_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reviewer_name must not be empty")
        if stripped.casefold() in _PROHIBITED_REVIEWERS:
            raise ValueError("reviewer identity is not independent human evidence")
        return stripped

    @field_validator("reviewer_organization", "reviewer_role", "notes")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("review metadata values must not be empty")
        return value.strip()

    @field_validator("reviewed_at")
    @classmethod
    def _validate_reviewed_at(cls, value: str) -> str:
        if not _RFC3339_UTC_RE.fullmatch(value):
            raise ValueError("reviewed_at must be an RFC 3339 UTC timestamp")
        return value

    @field_validator("evidence_url")
    @classmethod
    def _validate_evidence_url(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("review evidence_url must use https")
        return value


class HumanReferenceDesign(BaseModel):
    """Pinned identity and normalized artifact summary for one upstream design."""

    model_config = ConfigDict(extra="forbid", strict=True)

    reference_id: str
    title: str
    domain: str
    upstream_repository: str
    upstream_commit: str
    upstream_source_root: str
    license_expression: str
    license_source_path: str
    engineering_origin: EngineeringOrigin
    source_verification: SourceVerification
    zaptrace_review_status: ReviewStatus
    review_record: HumanReviewRecord | None
    artifacts: list[HumanReferenceArtifact]
    artifact_count: int = Field(ge=0)
    total_bytes: int = Field(ge=1)
    artifact_set_sha256: str
    expected_dimensions: list[str] = Field(min_length=8, max_length=8)
    limitations: list[str] = Field(min_length=1)

    @field_validator("reference_id", "title", "domain", "upstream_source_root", "license_source_path")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reference identity values must not be empty")
        return value.strip()

    @field_validator("upstream_repository")
    @classmethod
    def _validate_repository(cls, value: str) -> str:
        if not value.startswith("https://github.com/"):
            raise ValueError("upstream_repository must be an HTTPS GitHub URL")
        return value.rstrip("/")

    @field_validator("upstream_commit")
    @classmethod
    def _validate_commit(cls, value: str) -> str:
        if not _COMMIT_RE.fullmatch(value):
            raise ValueError("upstream_commit must be 40 lowercase hexadecimal characters")
        return value

    @field_validator("license_expression")
    @classmethod
    def _validate_license(cls, value: str) -> str:
        if not value.strip() or not _SPDX_RE.fullmatch(value):
            raise ValueError("license_expression must be a non-empty SPDX expression")
        return value.strip()

    @field_validator("artifact_set_sha256")
    @classmethod
    def _validate_artifact_set_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("artifact_set_sha256 must be 64 lowercase hexadecimal characters")
        return value

    @field_validator("expected_dimensions")
    @classmethod
    def _validate_dimensions(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("expected_dimensions must be unique")
        if set(values) != _EXPECTED_DIMENSIONS:
            raise ValueError("expected_dimensions must contain the eight canonical dimensions")
        return values

    @field_validator("limitations")
    @classmethod
    def _validate_limitations(cls, values: list[str]) -> list[str]:
        if any(not item.strip() for item in values):
            raise ValueError("limitations entries must not be empty")
        return values

    @model_validator(mode="after")
    def _validate_artifact_inventory(self) -> HumanReferenceDesign:
        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate artifact path")
        kinds = [artifact.kind for artifact in self.artifacts]
        if len(self.artifacts) != 3 or sorted(kinds) != ["pcb", "project", "schematic"]:
            raise ValueError("reference artifacts must include exactly project, schematic, and pcb kinds")
        if self.artifact_count != len(self.artifacts):
            raise ValueError("artifact_count mismatch")
        if self.total_bytes != sum(artifact.size_bytes for artifact in self.artifacts):
            raise ValueError("total_bytes mismatch")
        observed = compute_reference_artifact_set_sha256(self.artifacts)
        if self.artifact_set_sha256 != observed:
            raise ValueError(f"artifact_set_sha256 mismatch: expected {self.artifact_set_sha256}, observed {observed}")
        return self

    @model_validator(mode="after")
    def _validate_review_state(self) -> HumanReferenceDesign:
        if self.zaptrace_review_status == "pending-human-review" and self.review_record is not None:
            raise ValueError("pending-human-review requires review_record=null")
        if self.zaptrace_review_status == "reviewed" and (
            self.review_record is None or self.review_record.review_decision != "approved"
        ):
            raise ValueError("reviewed status requires an approved review_record")
        if self.zaptrace_review_status == "rejected" and (
            self.review_record is None or self.review_record.review_decision != "rejected"
        ):
            raise ValueError("rejected status requires a rejected review_record")
        return self


class HumanReferenceCorpusManifest(BaseModel):
    """Strict six-or-more-reference corpus contract."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"]
    corpus_id: str
    corpus_version: str
    rubric_path: str
    references: list[HumanReferenceDesign] = Field(min_length=6)
    non_claims: list[str] = Field(min_length=1)

    @field_validator("corpus_id", "corpus_version")
    @classmethod
    def _validate_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("corpus identity values must not be empty")
        return value.strip()

    @field_validator("rubric_path")
    @classmethod
    def _validate_rubric_path(cls, value: str) -> str:
        path = Path(value.strip())
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("rubric_path must be repository-relative")
        if path.suffix.lower() != ".json":
            raise ValueError("rubric_path must use .json")
        return path.as_posix()

    @field_validator("non_claims")
    @classmethod
    def _validate_non_claims(cls, values: list[str]) -> list[str]:
        if any(not item.strip() for item in values):
            raise ValueError("non_claims entries must not be empty")
        return values

    @model_validator(mode="after")
    def _validate_reference_ids(self) -> HumanReferenceCorpusManifest:
        ids = [reference.reference_id for reference in self.references]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate reference_id")
        return self


class HumanReferenceRubricDimension(BaseModel):
    """One weighted dimension in the canonical scoring rubric."""

    model_config = ConfigDict(extra="forbid", strict=True)

    dimension_id: str
    title: str
    weight: int = Field(ge=1, le=100)
    minimum_score: int = Field(ge=0, le=100)
    required: bool
    release_blocking: bool
    accepted_authorities: list[Literal["verified", "reviewed"]] = Field(min_length=1)
    reviewer_required: bool

    @field_validator("dimension_id", "title")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rubric dimension identity must not be empty")
        return value.strip()

    @field_validator("accepted_authorities")
    @classmethod
    def _validate_authorities(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("accepted_authorities must be unique")
        return values

    @model_validator(mode="after")
    def _validate_human_review_policy(self) -> HumanReferenceRubricDimension:
        if self.dimension_id == "human-review":
            if self.accepted_authorities != ["reviewed"]:
                raise ValueError("human-review must accept reviewed authority only")
            if not self.reviewer_required:
                raise ValueError("human-review must require a reviewer")
        return self


class HumanReferenceRubric(BaseModel):
    """Versioned eight-dimension weighted scoring policy."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"]
    rubric_id: str
    rubric_version: str
    overall_pass_score: int = Field(ge=0, le=100)
    dimensions: list[HumanReferenceRubricDimension] = Field(min_length=8)
    non_claims: list[str] = Field(min_length=1)

    @field_validator("rubric_id", "rubric_version")
    @classmethod
    def _validate_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rubric identity values must not be empty")
        return value.strip()

    @field_validator("non_claims")
    @classmethod
    def _validate_non_claims(cls, values: list[str]) -> list[str]:
        if any(not item.strip() for item in values):
            raise ValueError("rubric non_claims entries must not be empty")
        return values

    @model_validator(mode="after")
    def _validate_dimensions(self) -> HumanReferenceRubric:
        ids = [dimension.dimension_id for dimension in self.dimensions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate dimension_id")
        if set(ids) != _EXPECTED_DIMENSIONS:
            raise ValueError("rubric must contain the eight canonical dimensions")
        if sum(dimension.weight for dimension in self.dimensions) != 100:
            raise ValueError("rubric weights must total 100")
        if not all(dimension.required and dimension.release_blocking for dimension in self.dimensions):
            raise ValueError("all canonical rubric dimensions must be required and release_blocking")
        return self


class HumanReferenceEvidence(BaseModel):
    """Attempt evidence and score for one rubric dimension."""

    model_config = ConfigDict(extra="forbid", strict=True)

    dimension_id: str
    score: int = Field(ge=0, le=100)
    evidence_authority: EvidenceAuthority
    evidence_references: list[str]
    reviewer: HumanReviewRecord | None
    notes: str

    @field_validator("dimension_id", "notes")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("attempt evidence identity values must not be empty")
        return value.strip()

    @field_validator("evidence_references")
    @classmethod
    def _validate_evidence_references(cls, values: list[str]) -> list[str]:
        if any(not item.strip() for item in values):
            raise ValueError("evidence_references entries must not be empty")
        if len(values) != len(set(values)):
            raise ValueError("evidence_references must be unique")
        for item in values:
            path = Path(item)
            if not item.startswith("https://") and (path.is_absolute() or ".." in path.parts):
                raise ValueError("evidence reference must be HTTPS or repository-relative")
        return values

    @model_validator(mode="after")
    def _validate_claim(self) -> HumanReferenceEvidence:
        if self.evidence_authority == "missing" and self.score != 0:
            raise ValueError("missing evidence requires score zero")
        if self.score > 0 and not self.evidence_references:
            raise ValueError("positive score requires evidence_references")
        if self.evidence_authority == "reviewed":
            if self.reviewer is None or self.reviewer.review_decision != "approved":
                raise ValueError("reviewed evidence requires reviewer")
        elif self.reviewer is not None:
            raise ValueError("reviewer is allowed only for reviewed evidence")
        return self


class HumanReferenceAttempt(BaseModel):
    """Non-authoritative template or identity-bound submitted attempt."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"]
    attempt_status: AttemptStatus
    evidence_status: Literal["non-authoritative-example", "submitted-evidence"]
    attempt_id: str
    reference_id: str
    reference_artifact_set_sha256: str
    tool_name: str
    tool_version: str
    source_commit: str
    dimensions: list[HumanReferenceEvidence] = Field(min_length=8)
    limitations: list[str] = Field(min_length=1)
    non_claims: list[str] = Field(min_length=1)

    @field_validator("attempt_id", "reference_id", "tool_name", "tool_version")
    @classmethod
    def _validate_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("attempt identity values must not be empty")
        return value.strip()

    @field_validator("reference_artifact_set_sha256")
    @classmethod
    def _validate_reference_hash(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("reference_artifact_set_sha256 must be 64 lowercase hexadecimal characters")
        return value

    @field_validator("source_commit")
    @classmethod
    def _validate_source_commit(cls, value: str) -> str:
        if not _COMMIT_RE.fullmatch(value):
            raise ValueError("source_commit must be 40 lowercase hexadecimal characters")
        return value

    @field_validator("limitations", "non_claims")
    @classmethod
    def _validate_string_lists(cls, values: list[str]) -> list[str]:
        if any(not item.strip() for item in values):
            raise ValueError("attempt list entries must not be empty")
        return values

    @model_validator(mode="after")
    def _validate_dimension_inventory(self) -> HumanReferenceAttempt:
        ids = [dimension.dimension_id for dimension in self.dimensions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate dimension_id")
        if set(ids) != _EXPECTED_DIMENSIONS:
            raise ValueError("attempt must contain the eight canonical dimensions")
        return self

    @model_validator(mode="after")
    def _validate_status(self) -> HumanReferenceAttempt:
        if self.attempt_status == "template":
            if self.evidence_status != "non-authoritative-example":
                raise ValueError("template attempt requires non-authoritative-example evidence_status")
            if self.tool_name != "example-only" or self.tool_version != "not-run" or self.source_commit != "0" * 40:
                raise ValueError("template attempt requires placeholder tool and source identity")
            if any(item.score or item.evidence_authority != "missing" for item in self.dimensions):
                raise ValueError("template attempt must contain missing zero-score evidence only")
        else:
            if self.evidence_status != "submitted-evidence":
                raise ValueError("submitted attempt requires submitted-evidence status")
            if self.tool_name == "example-only" or self.tool_version == "not-run" or self.source_commit == "0" * 40:
                raise ValueError("submitted attempt requires real tool and source identity")
        return self


def compute_reference_artifact_set_sha256(artifacts: list[HumanReferenceArtifact]) -> str:
    """Return a deterministic identity for selected upstream artifacts."""
    rows = [
        {
            "path": artifact.path,
            "kind": artifact.kind,
            "format": artifact.format,
            "size_bytes": artifact.size_bytes,
            "sha256": artifact.sha256,
        }
        for artifact in artifacts
    ]
    payload = json.dumps(sorted(rows, key=lambda row: row["path"]), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _load_json(path: str | Path, *, kind: str) -> object:
    contract_path = Path(path)
    try:
        return json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        message = str(exc).replace(str(contract_path.resolve(strict=False)), contract_path.name)
        raise HumanReferenceError(f"cannot load human reference {kind} {contract_path}: {message[:500]}") from exc


def load_human_reference_corpus(path: str | Path) -> HumanReferenceCorpusManifest:
    """Load a strict human-reference corpus manifest."""
    return HumanReferenceCorpusManifest.model_validate(_load_json(path, kind="corpus"))


def load_human_reference_rubric(path: str | Path) -> HumanReferenceRubric:
    """Load a strict human-reference scoring rubric."""
    return HumanReferenceRubric.model_validate(_load_json(path, kind="rubric"))


def load_human_reference_attempt(path: str | Path) -> HumanReferenceAttempt:
    """Load a strict human-reference attempt contract."""
    return HumanReferenceAttempt.model_validate(_load_json(path, kind="attempt"))


ScoreStatus = Literal["pass", "fail", "blocked"]


class HumanReferenceDimensionScore(BaseModel):
    """Scored result for one required rubric dimension."""

    model_config = ConfigDict(extra="forbid", strict=True)

    dimension_id: str
    title: str
    weight: int = Field(ge=1, le=100)
    minimum_score: int = Field(ge=0, le=100)
    score: int = Field(ge=0, le=100)
    evidence_authority: EvidenceAuthority
    evidence_references: list[str]
    reviewer: HumanReviewRecord | None
    weighted_points: float = Field(ge=0, le=100)
    authority_accepted: bool
    threshold_met: bool
    reviewer_present: bool
    status: ScoreStatus
    detail: str


class HumanReferenceScorecard(BaseModel):
    """Deterministic weighted scorecard bound to corpus, rubric, and attempt identity."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    corpus_id: str
    corpus_version: str
    rubric_id: str
    rubric_version: str
    reference_id: str
    reference_artifact_set_sha256: str
    attempt_id: str
    attempt_source_commit: str
    tool_name: str
    tool_version: str
    dimensions: list[HumanReferenceDimensionScore]
    total_score: float = Field(ge=0, le=100)
    passed_dimension_count: int = Field(ge=0)
    failed_dimension_count: int = Field(ge=0)
    blocked_dimension_count: int = Field(ge=0)
    overall_status: ScoreStatus
    generated_at: str = ""
    canonical_hash: str = ""
    limitations: list[str]
    non_claims: list[str]

    @field_validator("reference_artifact_set_sha256", "canonical_hash")
    @classmethod
    def _validate_optional_hash(cls, value: str) -> str:
        if value and not _SHA256_RE.fullmatch(value):
            raise ValueError("scorecard hashes must be 64 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def _validate_counts(self) -> HumanReferenceScorecard:
        total = self.passed_dimension_count + self.failed_dimension_count + self.blocked_dimension_count
        if total != len(self.dimensions):
            raise ValueError("scorecard dimension counts do not match dimensions")
        return self


def _unique_strings(*groups: list[str]) -> list[str]:
    result: list[str] = []
    for group in groups:
        for item in group:
            if item not in result:
                result.append(item)
    return result


def canonical_scorecard_hash(scorecard: HumanReferenceScorecard) -> str:
    """Hash all scoring inputs while excluding generation time and the hash itself."""
    payload = scorecard.model_dump(mode="json", exclude={"generated_at", "canonical_hash"})
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _dimension_status(
    dimension: HumanReferenceRubricDimension,
    evidence: HumanReferenceEvidence,
) -> tuple[ScoreStatus, bool, bool, bool, str]:
    authority_accepted = evidence.evidence_authority in dimension.accepted_authorities
    threshold_met = evidence.score >= dimension.minimum_score
    reviewer_present = evidence.reviewer is not None
    if evidence.evidence_authority in {"missing", "reported"}:
        return (
            "blocked",
            authority_accepted,
            threshold_met,
            reviewer_present,
            "required evidence is missing or reported only",
        )
    if dimension.reviewer_required and not reviewer_present:
        return "blocked", authority_accepted, threshold_met, reviewer_present, "required reviewer identity is missing"
    if not authority_accepted:
        return "blocked", authority_accepted, threshold_met, reviewer_present, "evidence authority is not accepted"
    if not threshold_met:
        return "fail", authority_accepted, threshold_met, reviewer_present, "score is below the dimension threshold"
    return (
        "pass",
        authority_accepted,
        threshold_met,
        reviewer_present,
        "accepted evidence meets the dimension threshold",
    )


def score_human_reference_attempt(
    corpus: HumanReferenceCorpusManifest,
    rubric: HumanReferenceRubric,
    attempt: HumanReferenceAttempt,
    *,
    generated_at: str = "",
) -> HumanReferenceScorecard:
    """Score one validated attempt without converting missing review into a pass."""
    reference = next((row for row in corpus.references if row.reference_id == attempt.reference_id), None)
    if reference is None:
        raise HumanReferenceError(f"unknown human reference: {attempt.reference_id}")
    if attempt.reference_artifact_set_sha256 != reference.artifact_set_sha256:
        raise HumanReferenceError(
            "reference_artifact_set_sha256 mismatch: "
            f"expected {reference.artifact_set_sha256}, observed {attempt.reference_artifact_set_sha256}"
        )
    rubric_ids = {row.dimension_id for row in rubric.dimensions}
    if rubric_ids != set(reference.expected_dimensions):
        raise HumanReferenceError("reference expected_dimensions do not match rubric dimensions")

    evidence_by_id = {row.dimension_id: row for row in attempt.dimensions}
    results: list[HumanReferenceDimensionScore] = []
    for dimension in rubric.dimensions:
        evidence = evidence_by_id[dimension.dimension_id]
        status, authority_accepted, threshold_met, reviewer_present, detail = _dimension_status(dimension, evidence)
        results.append(
            HumanReferenceDimensionScore(
                dimension_id=dimension.dimension_id,
                title=dimension.title,
                weight=dimension.weight,
                minimum_score=dimension.minimum_score,
                score=evidence.score,
                evidence_authority=evidence.evidence_authority,
                evidence_references=evidence.evidence_references,
                reviewer=evidence.reviewer,
                weighted_points=round(evidence.score * dimension.weight / 100, 6),
                authority_accepted=authority_accepted,
                threshold_met=threshold_met,
                reviewer_present=reviewer_present,
                status=status,
                detail=detail,
            )
        )

    total_score = round(sum(row.weighted_points for row in results), 6)
    passed_count = sum(row.status == "pass" for row in results)
    failed_count = sum(row.status == "fail" for row in results)
    blocked_count = sum(row.status == "blocked" for row in results)
    if blocked_count:
        overall_status: ScoreStatus = "blocked"
    elif failed_count or total_score < rubric.overall_pass_score:
        overall_status = "fail"
    else:
        overall_status = "pass"

    scorecard = HumanReferenceScorecard(
        corpus_id=corpus.corpus_id,
        corpus_version=corpus.corpus_version,
        rubric_id=rubric.rubric_id,
        rubric_version=rubric.rubric_version,
        reference_id=reference.reference_id,
        reference_artifact_set_sha256=reference.artifact_set_sha256,
        attempt_id=attempt.attempt_id,
        attempt_source_commit=attempt.source_commit,
        tool_name=attempt.tool_name,
        tool_version=attempt.tool_version,
        dimensions=results,
        total_score=total_score,
        passed_dimension_count=passed_count,
        failed_dimension_count=failed_count,
        blocked_dimension_count=blocked_count,
        overall_status=overall_status,
        generated_at=generated_at,
        limitations=_unique_strings(reference.limitations, attempt.limitations),
        non_claims=_unique_strings(corpus.non_claims, rubric.non_claims, attempt.non_claims),
    )
    return scorecard.model_copy(update={"canonical_hash": canonical_scorecard_hash(scorecard)})


__all__ = [
    "score_human_reference_attempt",
    "canonical_scorecard_hash",
    "ScoreStatus",
    "HumanReferenceScorecard",
    "HumanReferenceDimensionScore",
    "AttemptStatus",
    "EngineeringOrigin",
    "EvidenceAuthority",
    "HumanReferenceArtifact",
    "HumanReferenceAttempt",
    "HumanReferenceCorpusManifest",
    "HumanReferenceDesign",
    "HumanReferenceError",
    "HumanReferenceEvidence",
    "HumanReferenceRubric",
    "HumanReferenceRubricDimension",
    "HumanReviewRecord",
    "ReviewStatus",
    "SourceVerification",
    "compute_reference_artifact_set_sha256",
    "load_human_reference_attempt",
    "load_human_reference_corpus",
    "load_human_reference_rubric",
]
