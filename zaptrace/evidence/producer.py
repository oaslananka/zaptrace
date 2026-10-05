"""Evidence Producer Protocol v1 — machine-readable producer records and validation.

This module defines a versioned, public schema for evidence producers to emit
self-describing, tamper-evident records that can be consumed by the Proof Pack
and release-evidence plumbing without flattening source-specific fields.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from zaptrace.evidence.identity import EvidenceIdentity

_PRODUCER_SCHEMA_VERSION = "1.0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProducerResultStatus(StrEnum):
    """Canonical result-status vocabulary for evidence producers.

    Values are fixed and ordered by confidence. Consumers MUST NOT upgrade
    a producer's declared status to a higher-confidence value.
    """

    PASS = "pass"  # nosec B105 # noqa: S105
    FAIL = "fail"
    SKIPPED = "skipped"
    UNSUPPORTED = "unsupported"
    DEGRADED = "degraded"
    HUMAN_REVIEW_REQUIRED = "human-review-required"


class EvidenceAuthority(StrEnum):
    """Authority level of the evidence producer.

    PRODUCER: The producer's own assessment (default).
    EXTERNAL_VALIDATED: Producer output validated by an independent external checker.
    HUMAN_APPROVED: Human reviewer has explicitly approved this evidence.
    RELEASE_GATE: Evidence has passed the project's release gate policy.
    """

    PRODUCER = "producer"
    EXTERNAL_VALIDATED = "external-validated"
    HUMAN_APPROVED = "human-approved"
    RELEASE_GATE = "release-gate"


class ProducerIdentity(BaseModel):
    """Identity and version of the evidence producer itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, description="Producer name, e.g. 'zaptrace-sonar-debt'")
    version: str = Field(min_length=1, description="Producer version, e.g. '1.2.3'")
    schema_version: Literal["1.0"] = _PRODUCER_SCHEMA_VERSION


class InputIdentity(BaseModel):
    """Exact identity of the inputs consumed by the producer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_type: str = Field(min_length=1, description="Type of input: file, intent, api, design-state")
    identifier: str = Field(min_length=1, description="Stable identifier for the input (path, hash, ref)")
    sha256: str = Field(pattern=_SHA256_RE.pattern, description="SHA-256 of the exact input bytes")


class ConfigurationIdentity(BaseModel):
    """Identity of the configuration that parameterized the producer run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    config_sha256: str = Field(pattern=_SHA256_RE.pattern, description="SHA-256 of the configuration blob")
    config_version: str = Field(default="", description="Optional semantic version of the config schema")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Resolved parameter values")


class OutputIdentity(BaseModel):
    """Identity of the primary retained output artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1, description="Relative path of the output artifact")
    kind: str = Field(min_length=1, description="Artifact kind: report, bundle, log, manifest")
    sha256: str = Field(pattern=_SHA256_RE.pattern, description="SHA-256 of the output artifact")
    size_bytes: int = Field(ge=0, description="Size of the output artifact in bytes")


class AssumptionsLimitations(BaseModel):
    """Assumptions and limitations declared by the producer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assumptions: list[str] = Field(default_factory=list, description="Explicit assumptions made during production")
    limitations: list[str] = Field(default_factory=list, description="Known limitations of this evidence")
    non_claims: list[str] = Field(default_factory=list, description="Explicit non-claims to prevent misinterpretation")


class EvidenceProducerRecord(BaseModel):
    """Versioned, self-verifying evidence producer record.

    This is the canonical v1 record that producers emit. It includes all fields
    required for consumers to verify provenance, detect tampering, and assess
    authority without upgrading the producer's declared confidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Protocol versioning
    schema_version: Literal["1.0"] = _PRODUCER_SCHEMA_VERSION

    # Producer identity
    producer: ProducerIdentity

    # Exact input identity
    input_identity: InputIdentity

    # Design state hash (for design-bound evidence)
    design_state_hash: str = Field(
        pattern=_SHA256_RE.pattern,
        description="SHA-256 of the design state bound to this evidence",
    )

    # Configuration identity
    configuration: ConfigurationIdentity

    # Result status — fixed vocabulary, consumers MUST NOT upgrade
    result_status: ProducerResultStatus

    # Retained output identity
    output_identity: OutputIdentity | None = Field(default=None, description="Primary output artifact, if any")

    # Assumptions and limitations
    assumptions_limitations: AssumptionsLimitations = Field(default_factory=AssumptionsLimitations)

    # Evidence authority — set by producer, consumers MUST NOT upgrade
    authority: EvidenceAuthority = Field(default=EvidenceAuthority.PRODUCER)

    # Producer-declared confidence ceiling (0.0 to 1.0)
    confidence_ceiling: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Maximum confidence a consumer may assign"
    )

    # Timestamps
    produced_at: str = Field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    # Optional: link to the shared EvidenceIdentity for the environment
    evidence_identity: EvidenceIdentity | None = Field(
        default=None, description="Shared environment/toolchain identity"
    )

    # Tamper-evident hash over all fields except record_sha256
    record_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_record_hash(self) -> Self:
        """Reject tampered or mismatched records fail-closed."""
        if self.record_sha256:
            expected = self.compute_sha256()
            if self.record_sha256 != expected:
                raise ValueError("record_sha256 does not match record fields — tampering detected")
        return self

    def compute_sha256(self) -> str:
        """Compute deterministic SHA-256 over all fields except record_sha256 and produced_at."""
        payload = self.model_dump(mode="json", exclude={"record_sha256", "produced_at"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    def finalize(self) -> EvidenceProducerRecord:
        """Set record_sha256 and return a new finalized record."""
        return self.model_copy(update={"record_sha256": self.compute_sha256()})

    @classmethod
    def validate_and_load(cls, data: dict[str, Any] | str | Path) -> EvidenceProducerRecord:
        """Load and validate a record, rejecting tampered records fail-closed."""
        if isinstance(data, (str, Path)):
            path = Path(data)
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        else:
            payload = data
        return cls.model_validate(payload)


def validate_evidence_producer_record(record: EvidenceProducerRecord) -> list[str]:
    """Validate an evidence producer record for internal consistency.

    Returns a list of error messages (empty = valid). This is a soft validation
    that does not raise; the model_validator on the record enforces hard fail-closed.
    """
    errors: list[str] = []

    if record.schema_version != _PRODUCER_SCHEMA_VERSION:
        errors.append(f"unsupported producer schema version: {record.schema_version}")

    if record.authority == EvidenceAuthority.RELEASE_GATE and record.result_status != ProducerResultStatus.PASS:
        errors.append("RELEASE_GATE authority requires PASS result status")

    if record.authority == EvidenceAuthority.HUMAN_APPROVED and record.result_status in {
        ProducerResultStatus.FAIL,
        ProducerResultStatus.UNSUPPORTED,
    }:
        errors.append("HUMAN_APPROVED authority incompatible with FAIL/UNSUPPORTED result")

    return errors


def enforce_authority_ceiling(
    record: EvidenceProducerRecord,
    *,
    consumer_authority: EvidenceAuthority,
    consumer_confidence: float,
) -> tuple[EvidenceAuthority, float]:
    """Enforce that consumers cannot upgrade producer authority or confidence.

    Returns the effective (authority, confidence) after applying the producer's
    declared ceiling. Raises ValueError if the consumer attempts to upgrade.
    """
    # Authority ordering: PRODUCER < EXTERNAL_VALIDATED < HUMAN_APPROVED < RELEASE_GATE
    authority_order = {
        EvidenceAuthority.PRODUCER: 0,
        EvidenceAuthority.EXTERNAL_VALIDATED: 1,
        EvidenceAuthority.HUMAN_APPROVED: 2,
        EvidenceAuthority.RELEASE_GATE: 3,
    }

    producer_level = authority_order[record.authority]
    consumer_level = authority_order[consumer_authority]

    if consumer_level > producer_level:
        raise ValueError(
            f"consumer authority {consumer_authority.value} exceeds producer authority {record.authority.value} — "
            "consumers cannot upgrade producer authority"
        )

    if consumer_confidence > record.confidence_ceiling + 1e-9:
        raise ValueError(
            f"consumer confidence {consumer_confidence:.3f} exceeds producer ceiling {record.confidence_ceiling:.3f} — "
            "consumers cannot upgrade producer confidence"
        )

    effective_confidence = min(consumer_confidence, record.confidence_ceiling)

    effective_authority_level = min(consumer_level, producer_level)
    authority_by_level = {v: k for k, v in authority_order.items()}
    effective_authority = authority_by_level[effective_authority_level]

    return effective_authority, effective_confidence


class EvidenceProducerRecordBuilder:
    """Fluent builder for constructing valid EvidenceProducerRecord instances."""

    def __init__(self) -> None:
        self._producer: ProducerIdentity | None = None
        self._input_identity: InputIdentity | None = None
        self._design_state_hash: str | None = None
        self._configuration: ConfigurationIdentity | None = None
        self._result_status: ProducerResultStatus | None = None
        self._output_identity: OutputIdentity | None = None
        self._assumptions_limitations: AssumptionsLimitations | None = None
        self._authority: EvidenceAuthority = EvidenceAuthority.PRODUCER
        self._confidence_ceiling: float = 1.0
        self._evidence_identity: EvidenceIdentity | None = None
        self._produced_at: str | None = None

    def producer(self, name: str, version: str) -> Self:
        self._producer = ProducerIdentity(name=name, version=version)
        return self

    def input_identity(self, source_type: str, identifier: str, sha256: str) -> Self:
        self._input_identity = InputIdentity(source_type=source_type, identifier=identifier, sha256=sha256)
        return self

    def design_state_hash(self, hash_value: str) -> Self:
        self._design_state_hash = hash_value
        return self

    def configuration(
        self, config_sha256: str, config_version: str = "", parameters: dict[str, Any] | None = None
    ) -> Self:
        self._configuration = ConfigurationIdentity(
            config_sha256=config_sha256,
            config_version=config_version,
            parameters=parameters or {},
        )
        return self

    def result_status(self, status: ProducerResultStatus) -> Self:
        self._result_status = status
        return self

    def output_identity(self, path: str, kind: str, sha256: str, size_bytes: int) -> Self:
        self._output_identity = OutputIdentity(path=path, kind=kind, sha256=sha256, size_bytes=size_bytes)
        return self

    def assumptions_limitations(
        self,
        assumptions: list[str] | None = None,
        limitations: list[str] | None = None,
        non_claims: list[str] | None = None,
    ) -> Self:
        self._assumptions_limitations = AssumptionsLimitations(
            assumptions=assumptions or [],
            limitations=limitations or [],
            non_claims=non_claims or [],
        )
        return self

    def authority(self, authority: EvidenceAuthority) -> Self:
        self._authority = authority
        return self

    def confidence_ceiling(self, ceiling: float) -> Self:
        self._confidence_ceiling = ceiling
        return self

    def evidence_identity(self, identity: EvidenceIdentity) -> Self:
        self._evidence_identity = identity
        return self

    def produced_at(self, timestamp: str) -> Self:
        self._produced_at = timestamp
        return self

    def build(self) -> EvidenceProducerRecord:
        missing = []
        if self._producer is None:
            missing.append("producer")
        if self._input_identity is None:
            missing.append("input_identity")
        if self._design_state_hash is None:
            missing.append("design_state_hash")
        if self._configuration is None:
            missing.append("configuration")
        if self._result_status is None:
            missing.append("result_status")
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")

        record_data = {
            "producer": self._producer,
            "input_identity": self._input_identity,
            "design_state_hash": self._design_state_hash,
            "configuration": self._configuration,
            "result_status": self._result_status,
            "output_identity": self._output_identity,
            "assumptions_limitations": self._assumptions_limitations or AssumptionsLimitations(),
            "authority": self._authority,
            "confidence_ceiling": self._confidence_ceiling,
            "evidence_identity": self._evidence_identity,
        }
        if self._produced_at is not None:
            record_data["produced_at"] = self._produced_at

        record = EvidenceProducerRecord(**record_data)
        return record.finalize()


def _resolve_nested_path(data: dict[str, Any], path: str) -> Any:
    """Resolve a dot-notation path through a nested dictionary.

    Supports traversal through dict keys only (input is a pre-dumped dict).

    Returns None if any intermediate step is missing or resolves to None.

    Args:
        data: The root dictionary to traverse (pre-dumped from model_dump).
        path: Dot-separated path string (e.g., "producer.name" or "output_identity.sha256").

    Returns:
        The resolved value, or None if the path cannot be fully resolved.
    """
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


# Integration seam: adapt a producer record into Proof Pack evidence metadata
# without flattening source-specific fields.
def adapt_producer_record_to_proof_evidence(
    record: EvidenceProducerRecord,
    *,
    evidence_class: type[BaseModel],
    field_mapping: dict[str, str],
) -> BaseModel:
    """Adapt an EvidenceProducerRecord into a Proof Pack evidence model.

    This is the minimal integration seam proving the contract can enter existing
    Proof Pack/evidence plumbing without flattening source-specific fields.

    Args:
        record: The validated producer record.
        evidence_class: Target Proof Pack evidence model class (e.g., SonarDebtReport).
        field_mapping: Mapping from producer record field paths to evidence model fields.
                       Supports nested paths using dot notation.

    Returns:
        An instance of the evidence_class populated from the producer record.

    Raises:
        ValueError: If required fields are missing or mapping fails.
    """
    record_dict = record.model_dump(mode="json")

    payload_for_hash = {
        k: v for k, v in record_dict.items() if k not in ("record_sha256", "produced_at")
    }
    import hashlib as _hashlib
    import json as _json

    encoded = _json.dumps(
        payload_for_hash,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode()
    computed_hash = _hashlib.sha256(encoded).hexdigest()
    if record.record_sha256 != computed_hash:
        raise ValueError("producer record failed integrity check — cannot adapt tampered evidence")

    evidence_data: dict[str, Any] = {}
    for target_field, source_path in field_mapping.items():
        value = _resolve_nested_path(record_dict, source_path)
        if value is not None:
            evidence_data[target_field] = value

    # Ensure the producer record itself is preserved for traceability
    evidence_data.setdefault("producer_record_sha256", record.record_sha256)
    evidence_data.setdefault("producer_identity", f"{record.producer.name}@{record.producer.version}")
    evidence_data.setdefault("producer_result_status", record.result_status.value)
    evidence_data.setdefault("producer_authority", record.authority.value)

    return evidence_class.model_validate(evidence_data)
