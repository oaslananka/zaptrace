"""Evidence Producer Protocol (v1) schema and models."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceProducerStatus(StrEnum):
    __test__ = False
    PASS = "pass"
    FAIL = "fail"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"
    WARNING = "warning"


class EvidenceAuthority(StrEnum):
    AUTOMATED_ORACLE = "automated_oracle"
    HEURISTIC_CHECK = "heuristic_check"
    EXTERNAL_SOLVER = "external_solver"
    HUMAN_REVIEW = "human_review"


class ArtifactDigest(BaseModel):
    """Digest metadata for a retained execution artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str = Field(..., description="Workspace relative path of artifact")
    sha256: str = Field(..., description="SHA-256 hash digest of artifact content")
    size_bytes: int = Field(..., description="Artifact size in bytes")


class EvidenceProducerRecord(BaseModel):
    """Standardized record produced by any evidence engine/oracle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    producer_id: str = Field(..., description="Unique engine/tool identifier (e.g. kicad-drc-oracle)")
    producer_version: str = Field(..., description="Version of the producer software/script")
    producer_class: str = Field(..., description="Class of producer (oracle, analyzer, simulator)")
    execution_environment: dict[str, str] = Field(default_factory=dict, description="OS and runtime metadata")
    input_design_sha256: str = Field(..., description="SHA-256 hash of the input design state")
    config_sha256: str = Field(..., description="SHA-256 hash of producer configuration/rules")
    status: EvidenceProducerStatus = Field(..., description="Execution/verification result status")
    evidence_authority: EvidenceAuthority = Field(..., description="Authority level of the producer")
    retained_artifacts: list[ArtifactDigest] = Field(default_factory=list, description="Retained output artifacts")
    warnings: list[str] = Field(default_factory=list, description="Warning messages produced")
    errors: list[str] = Field(default_factory=list, description="Error messages produced")
    human_review_required: bool = Field(default=True, description="Enforces human review gate")
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(), description="ISO-8601 execution time")
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "Execution success does not constitute release or fabrication approval.",
            "A passing result indicates only that checked rule constraints were satisfied.",
        ]
    )

    def calculate_record_hash(self) -> str:
        """Compute canonical SHA-256 digest of the producer record."""
        raw = self.model_dump_json(by_alias=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
