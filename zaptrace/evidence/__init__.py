"""Reusable evidence identity, verification primitives, and producer protocol."""

from zaptrace.evidence.identity import (
    EvidenceIdentity,
    EvidenceMode,
    capture_evidence_identity,
    hash_source_inputs,
    parse_name_value_pairs,
    verify_evidence_identity,
)
from zaptrace.evidence.producer import (
    AssumptionsLimitations,
    ConfigurationIdentity,
    EvidenceAuthority,
    EvidenceProducerRecord,
    EvidenceProducerRecordBuilder,
    InputIdentity,
    OutputIdentity,
    ProducerIdentity,
    ProducerResultStatus,
    adapt_producer_record_to_proof_evidence,
    enforce_authority_ceiling,
    validate_evidence_producer_record,
)

__all__ = [
    "EvidenceIdentity",
    "EvidenceMode",
    "capture_evidence_identity",
    "hash_source_inputs",
    "parse_name_value_pairs",
    "verify_evidence_identity",
    "EvidenceProducerRecord",
    "EvidenceProducerRecordBuilder",
    "EvidenceAuthority",
    "ProducerResultStatus",
    "ProducerIdentity",
    "InputIdentity",
    "ConfigurationIdentity",
    "OutputIdentity",
    "AssumptionsLimitations",
    "validate_evidence_producer_record",
    "enforce_authority_ceiling",
    "adapt_producer_record_to_proof_evidence",
]
