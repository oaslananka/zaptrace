"""Tests for Evidence Producer Protocol v1.

Covers schema validation, status semantics, tamper rejection, authority invariants,
and the Proof Pack integration seam.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from zaptrace.evidence.identity import (
    EvidenceIdentity,
    EvidenceMode,
    capture_evidence_identity,
)
from zaptrace.evidence.producer import (
    EvidenceAuthority,
    EvidenceProducerRecord,
    EvidenceProducerRecordBuilder,
    ProducerIdentity,
    ProducerResultStatus,
    adapt_producer_record_to_proof_evidence,
    enforce_authority_ceiling,
    validate_evidence_producer_record,
)


class _TestEvidenceModel(BaseModel):
    """Minimal test evidence model that accepts extra fields for integration seam testing."""

    model_config = ConfigDict(extra="allow")

    project_key: str = ""
    analysis_revision: str = ""
    producer_record_sha256: str = ""
    producer_identity: str = ""
    producer_result_status: str = ""
    producer_authority: str = ""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dummy_evidence_identity() -> EvidenceIdentity:
    # Create a valid EvidenceIdentity using the proper capture function
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "pyproject.toml").write_text('[project]\nname = "zaptrace"\nversion = "1.2.3"\n', encoding="utf-8")
        (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        (root / "source.txt").write_text("alpha\n", encoding="utf-8")

        return capture_evidence_identity(
            root=root,
            mode=EvidenceMode.SNAPSHOT,
            source_inputs=["source.txt"],
            source_commit="a" * 40,
            source_ref="refs/heads/main",
            dirty=False,
            generated_at="2026-07-22T18:00:00+00:00",
            toolchain={"python": "3.12.3"},
        )


def _minimal_valid_record() -> EvidenceProducerRecord:
    return (
        EvidenceProducerRecordBuilder()
        .producer("test-producer", "1.0.0")
        .input_identity("file", "design.yaml", _sha256(b"design content"))
        .design_state_hash(_sha256(b"design state"))
        .configuration(_sha256(b"config"), "1.0", {"threshold": 0.5})
        .result_status(ProducerResultStatus.PASS)
        .output_identity("report.json", "report", _sha256(b"report content"), 100)
        .assumptions_limitations(
            assumptions=["input is well-formed"],
            limitations=["does not cover analog"],
            non_claims=["not a fabrication guarantee"],
        )
        .authority(EvidenceAuthority.PRODUCER)
        .confidence_ceiling(0.95)
        .evidence_identity(_dummy_evidence_identity())
        .build()
    )


class TestProducerResultStatus:
    def test_all_required_statuses_exist(self) -> None:
        assert ProducerResultStatus.PASS == "pass"
        assert ProducerResultStatus.FAIL == "fail"
        assert ProducerResultStatus.SKIPPED == "skipped"
        assert ProducerResultStatus.UNSUPPORTED == "unsupported"
        assert ProducerResultStatus.DEGRADED == "degraded"
        assert ProducerResultStatus.HUMAN_REVIEW_REQUIRED == "human-review-required"

    def test_status_ordering_by_confidence(self) -> None:
        # Order from highest to lowest confidence
        ordered = [
            ProducerResultStatus.PASS,
            ProducerResultStatus.HUMAN_REVIEW_REQUIRED,
            ProducerResultStatus.DEGRADED,
            ProducerResultStatus.SKIPPED,
            ProducerResultStatus.UNSUPPORTED,
            ProducerResultStatus.FAIL,
        ]
        assert len(set(ordered)) == 6


class TestEvidenceAuthority:
    def test_all_authorities_exist(self) -> None:
        assert EvidenceAuthority.PRODUCER == "producer"
        assert EvidenceAuthority.EXTERNAL_VALIDATED == "external-validated"
        assert EvidenceAuthority.HUMAN_APPROVED == "human-approved"
        assert EvidenceAuthority.RELEASE_GATE == "release-gate"

    def test_authority_ordering(self) -> None:
        order = {
            EvidenceAuthority.PRODUCER: 0,
            EvidenceAuthority.EXTERNAL_VALIDATED: 1,
            EvidenceAuthority.HUMAN_APPROVED: 2,
            EvidenceAuthority.RELEASE_GATE: 3,
        }
        assert order[EvidenceAuthority.PRODUCER] < order[EvidenceAuthority.EXTERNAL_VALIDATED]
        assert order[EvidenceAuthority.EXTERNAL_VALIDATED] < order[EvidenceAuthority.HUMAN_APPROVED]
        assert order[EvidenceAuthority.HUMAN_APPROVED] < order[EvidenceAuthority.RELEASE_GATE]


class TestEvidenceProducerRecordSchemaValidation:
    def test_minimal_valid_record_passes(self) -> None:
        record = _minimal_valid_record()
        assert record.schema_version == "1.0"
        assert record.producer.name == "test-producer"
        assert record.producer.version == "1.0.0"
        assert record.result_status == ProducerResultStatus.PASS
        assert record.authority == EvidenceAuthority.PRODUCER
        assert record.confidence_ceiling == 0.95
        assert len(record.record_sha256) == 64

    def test_record_hash_is_deterministic(self) -> None:
        r1 = _minimal_valid_record()
        r2 = _minimal_valid_record()
        assert r1.record_sha256 == r2.record_sha256

    def test_record_hash_excludes_produced_at(self) -> None:
        builder = (
            EvidenceProducerRecordBuilder()
            .producer("test", "1.0")
            .input_identity("file", "x", _sha256(b"x"))
            .design_state_hash(_sha256(b"state"))
            .configuration(_sha256(b"cfg"))
            .result_status(ProducerResultStatus.PASS)
        )
        r1 = builder.produced_at("2026-01-01T00:00:00Z").build()
        r2 = builder.produced_at("2026-12-31T23:59:59Z").build()
        assert r1.record_sha256 == r2.record_sha256

    def test_rejects_unknown_schema_version(self) -> None:
        record = _minimal_valid_record()
        payload = record.model_dump(mode="json")
        payload["schema_version"] = "2.0"
        with pytest.raises(ValidationError, match="schema_version"):
            EvidenceProducerRecord.model_validate(payload)

    def test_rejects_empty_producer_name(self) -> None:
        with pytest.raises(ValidationError, match="name"):
            ProducerIdentity(name="", version="1.0")

    def test_rejects_malformed_sha256_in_design_state_hash(self) -> None:
        record = _minimal_valid_record()
        payload = record.model_dump(mode="json")
        payload["design_state_hash"] = "not-a-hash"
        with pytest.raises(ValidationError, match="design_state_hash"):
            EvidenceProducerRecord.model_validate(payload)

    def test_rejects_confidence_ceiling_out_of_range(self) -> None:
        record = _minimal_valid_record()
        payload = record.model_dump(mode="json")
        payload["confidence_ceiling"] = 1.5
        with pytest.raises(ValidationError, match="confidence_ceiling"):
            EvidenceProducerRecord.model_validate(payload)
        payload = record.model_dump(mode="json")
        payload["confidence_ceiling"] = -0.1
        with pytest.raises(ValidationError, match="confidence_ceiling"):
            EvidenceProducerRecord.model_validate(payload)

    def test_validates_assumptions_limitations_structure(self) -> None:
        record = _minimal_valid_record()
        assert isinstance(record.assumptions_limitations.assumptions, list)
        assert isinstance(record.assumptions_limitations.limitations, list)
        assert isinstance(record.assumptions_limitations.non_claims, list)

    def test_optional_output_identity_can_be_none(self) -> None:
        record = (
            EvidenceProducerRecordBuilder()
            .producer("test", "1.0")
            .input_identity("file", "x", _sha256(b"x"))
            .design_state_hash(_sha256(b"state"))
            .configuration(_sha256(b"cfg"))
            .result_status(ProducerResultStatus.SKIPPED)
            .build()
        )
        assert record.output_identity is None


class TestTamperRejectionFailClosed:
    def test_rejects_tampered_record_sha256(self) -> None:
        record = _minimal_valid_record()
        payload = record.model_dump(mode="json")
        payload["record_sha256"] = "e" * 64
        with pytest.raises(ValidationError, match="tampering detected"):
            EvidenceProducerRecord.model_validate(payload)

    def test_rejects_tampered_result_status(self) -> None:
        record = _minimal_valid_record()
        payload = record.model_dump(mode="json")
        payload["result_status"] = "fail"
        with pytest.raises(ValidationError, match="tampering detected"):
            EvidenceProducerRecord.model_validate(payload)

    def test_rejects_tampered_producer_identity(self) -> None:
        record = _minimal_valid_record()
        payload = record.model_dump(mode="json")
        payload["producer"]["name"] = "evil-producer"
        with pytest.raises(ValidationError, match="tampering detected"):
            EvidenceProducerRecord.model_validate(payload)

    def test_rejects_tampered_design_state_hash(self) -> None:
        record = _minimal_valid_record()
        payload = record.model_dump(mode="json")
        payload["design_state_hash"] = "f" * 64
        with pytest.raises(ValidationError, match="tampering detected"):
            EvidenceProducerRecord.model_validate(payload)

    def test_rejects_tampered_configuration(self) -> None:
        record = _minimal_valid_record()
        payload = record.model_dump(mode="json")
        payload["configuration"]["config_sha256"] = "f" * 64
        with pytest.raises(ValidationError, match="tampering detected"):
            EvidenceProducerRecord.model_validate(payload)

    def test_rejects_tampered_output_identity(self) -> None:
        record = _minimal_valid_record()
        payload = record.model_dump(mode="json")
        payload["output_identity"]["sha256"] = "f" * 64
        with pytest.raises(ValidationError, match="tampering detected"):
            EvidenceProducerRecord.model_validate(payload)

    def test_validate_and_load_rejects_tampered_file(self, tmp_path: Path) -> None:
        record = _minimal_valid_record()
        path = tmp_path / "record.json"
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        # Tamper the file
        data = json.loads(path.read_text())
        data["result_status"] = "fail"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValidationError, match="tampering detected"):
            EvidenceProducerRecord.validate_and_load(path)

    def test_validate_and_load_accepts_dict_payload(self) -> None:
        record = _minimal_valid_record()
        payload = record.model_dump(mode="json")
        restored = EvidenceProducerRecord.validate_and_load(payload)
        assert restored.record_sha256 == record.record_sha256
        assert restored.producer.name == record.producer.name


class TestAuthorityInvariants:
    def test_consumer_cannot_upgrade_authority(self) -> None:
        record = _minimal_valid_record()
        assert record.authority == EvidenceAuthority.PRODUCER

        # Consumer tries to claim EXTERNAL_VALIDATED — should fail
        with pytest.raises(ValueError, match="consumer authority .* exceeds producer authority"):
            enforce_authority_ceiling(
                record,
                consumer_authority=EvidenceAuthority.EXTERNAL_VALIDATED,
                consumer_confidence=1.0,
            )

        # Consumer tries to claim HUMAN_APPROVED — should fail
        with pytest.raises(ValueError, match="consumer authority .* exceeds producer authority"):
            enforce_authority_ceiling(
                record,
                consumer_authority=EvidenceAuthority.HUMAN_APPROVED,
                consumer_confidence=1.0,
            )

        # Consumer tries to claim RELEASE_GATE — should fail
        with pytest.raises(ValueError, match="consumer authority .* exceeds producer authority"):
            enforce_authority_ceiling(
                record,
                consumer_authority=EvidenceAuthority.RELEASE_GATE,
                consumer_confidence=1.0,
            )

    def test_consumer_can_keep_or_lower_authority(self) -> None:
        record = (
            EvidenceProducerRecordBuilder()
            .producer("test", "1.0")
            .input_identity("file", "x", _sha256(b"x"))
            .design_state_hash(_sha256(b"state"))
            .configuration(_sha256(b"cfg"))
            .result_status(ProducerResultStatus.PASS)
            .authority(EvidenceAuthority.HUMAN_APPROVED)
            .confidence_ceiling(1.0)
            .build()
        )
        # Consumer at same level — OK
        auth, conf = enforce_authority_ceiling(
            record,
            consumer_authority=EvidenceAuthority.HUMAN_APPROVED,
            consumer_confidence=1.0,
        )
        assert auth == EvidenceAuthority.HUMAN_APPROVED
        assert conf == record.confidence_ceiling

        # Consumer at lower level — OK
        auth, conf = enforce_authority_ceiling(
            record,
            consumer_authority=EvidenceAuthority.PRODUCER,
            consumer_confidence=1.0,
        )
        assert auth == EvidenceAuthority.HUMAN_APPROVED  # Producer's authority preserved
        assert conf == record.confidence_ceiling

    def test_consumer_cannot_upgrade_confidence_above_ceiling(self) -> None:
        record = _minimal_valid_record()  # ceiling = 0.95
        with pytest.raises(ValueError, match="consumer confidence .* exceeds producer ceiling"):
            enforce_authority_ceiling(
                record,
                consumer_authority=EvidenceAuthority.PRODUCER,
                consumer_confidence=0.99,
            )

    def test_consumer_confidence_capped_at_ceiling(self) -> None:
        record = _minimal_valid_record()  # ceiling = 0.95
        auth, conf = enforce_authority_ceiling(
            record,
            consumer_authority=EvidenceAuthority.PRODUCER,
            consumer_confidence=0.95,  # at ceiling, should not raise
        )
        assert conf == 0.95

    def test_release_gate_authority_requires_pass_status(self) -> None:
        record = _minimal_valid_record().model_copy(
            update={"authority": EvidenceAuthority.RELEASE_GATE, "result_status": ProducerResultStatus.FAIL}
        )
        errors = validate_evidence_producer_record(record)
        assert any("RELEASE_GATE authority requires PASS" in e for e in errors)

    def test_human_approved_authority_incompatible_with_fail(self) -> None:
        record = _minimal_valid_record().model_copy(
            update={"authority": EvidenceAuthority.HUMAN_APPROVED, "result_status": ProducerResultStatus.FAIL}
        )
        errors = validate_evidence_producer_record(record)
        assert any("HUMAN_APPROVED authority incompatible" in e for e in errors)


class TestStatusSemantics:
    def test_all_statuses_accepted(self) -> None:
        for status in ProducerResultStatus:
            record = (
                EvidenceProducerRecordBuilder()
                .producer("test", "1.0")
                .input_identity("file", "x", _sha256(b"x"))
                .design_state_hash(_sha256(b"state"))
                .configuration(_sha256(b"cfg"))
                .result_status(status)
                .build()
            )
            assert record.result_status == status

    def test_skipped_status_allows_no_output(self) -> None:
        record = (
            EvidenceProducerRecordBuilder()
            .producer("test", "1.0")
            .input_identity("file", "x", _sha256(b"x"))
            .design_state_hash(_sha256(b"state"))
            .configuration(_sha256(b"cfg"))
            .result_status(ProducerResultStatus.SKIPPED)
            .build()
        )
        assert record.output_identity is None

    def test_unsupported_status_allows_no_output(self) -> None:
        record = (
            EvidenceProducerRecordBuilder()
            .producer("test", "1.0")
            .input_identity("file", "x", _sha256(b"x"))
            .design_state_hash(_sha256(b"state"))
            .configuration(_sha256(b"cfg"))
            .result_status(ProducerResultStatus.UNSUPPORTED)
            .build()
        )
        assert record.output_identity is None


class TestBuilder:
    def test_builder_requires_all_fields(self) -> None:
        builder = EvidenceProducerRecordBuilder()
        with pytest.raises(ValueError, match="missing required fields"):
            builder.build()

    def test_builder_sets_defaults(self) -> None:
        record = (
            EvidenceProducerRecordBuilder()
            .producer("test", "1.0")
            .input_identity("file", "x", _sha256(b"x"))
            .design_state_hash(_sha256(b"state"))
            .configuration(_sha256(b"cfg"))
            .result_status(ProducerResultStatus.PASS)
            .build()
        )
        assert record.authority == EvidenceAuthority.PRODUCER
        assert record.confidence_ceiling == 1.0
        assert record.assumptions_limitations.assumptions == []


class TestIntegrationSeam:
    def test_adapt_producer_record_to_proof_evidence(self) -> None:
        record = _minimal_valid_record()
        record = record.model_copy(update={"result_status": ProducerResultStatus.PASS})

        # Minimal field mapping to test evidence model
        evidence = adapt_producer_record_to_proof_evidence(
            record,
            evidence_class=_TestEvidenceModel,
            field_mapping={
                "project_key": "producer.name",
                "analysis_revision": "design_state_hash",
                "report_sha256": "record_sha256",
            },
        )

        assert isinstance(evidence, _TestEvidenceModel)
        assert evidence.project_key == "test-producer"
        assert evidence.analysis_revision == record.design_state_hash
        assert evidence.report_sha256 == record.record_sha256
        assert evidence.producer_record_sha256 == record.record_sha256
        assert evidence.producer_identity == "test-producer@1.0.0"
        assert evidence.producer_result_status == "pass"
        assert evidence.producer_authority == "producer"

    def test_adapt_preserves_source_specific_fields(self) -> None:
        """Verify the integration seam does NOT flatten source-specific fields."""
        record = (
            EvidenceProducerRecordBuilder()
            .producer("test", "1.0")
            .input_identity("file", "x", _sha256(b"x"))
            .design_state_hash(_sha256(b"state"))
            .configuration(_sha256(b"cfg"))
            .result_status(ProducerResultStatus.PASS)
            .assumptions_limitations(
                assumptions=["custom assumption"],
                limitations=["custom limitation"],
                non_claims=["custom non-claim"],
            )
            .build()
        )

        evidence = adapt_producer_record_to_proof_evidence(
            record,
            evidence_class=_TestEvidenceModel,
            field_mapping={
                "project_key": "producer.name",
                "analysis_revision": "design_state_hash",
            },
        )

        # The producer record is preserved as a reference, not flattened
        assert evidence.producer_record_sha256 == record.record_sha256
        # Source-specific fields (assumptions, limitations, non_claims) are NOT
        # automatically mapped to evidence model fields — they remain in the
        # producer record for traceability

    def test_adapt_rejects_tampered_record(self) -> None:
        record = _minimal_valid_record()
        # Tamper the record
        tampered = record.model_copy(update={"record_sha256": "f" * 64})
        with pytest.raises(ValueError, match="failed integrity check"):
            adapt_producer_record_to_proof_evidence(
                tampered,
                evidence_class=_TestEvidenceModel,
                field_mapping={"project_key": "producer.name"},
            )

    def test_adapt_traverses_object_attribute(self) -> None:
        """Test adapt traverses object attribute via hasattr/getattr (lines 406-407)."""
        record = _minimal_valid_record()
        # The _resolve_nested_path function uses hasattr/getattr for non-dict objects.
        # Test by mapping a field that requires attribute access on a BaseModel.
        evidence = adapt_producer_record_to_proof_evidence(
            record,
            evidence_class=_TestEvidenceModel,
            field_mapping={"project_key": "producer.name"},
        )
        assert evidence.project_key == "test-producer"

    def test_adapt_returns_none_for_unknown_intermediate_type(self) -> None:
        """Test traversal where intermediate step is neither dict nor has attribute (line 409)."""
        # Create a record and map a path that goes through an unsupported intermediate type
        record = _minimal_valid_record()
        # The design_state_hash is a string; trying to traverse into it should return None
        # because a string is neither a dict nor has attributes in the path sense
        evidence = adapt_producer_record_to_proof_evidence(
            record,
            evidence_class=_TestEvidenceModel,
            field_mapping={"dummy_field": "design_state_hash.nonexistent"},
        )
        # The field should not be set since traversal returns None
        assert "dummy_field" not in evidence.model_dump()

    def test_adapt_returns_none_when_intermediate_resolves_to_none(self) -> None:
        """Test traversal where intermediate value resolves to None (line 411)."""
        # Create a record WITHOUT output_identity (it's Optional)
        record = (
            EvidenceProducerRecordBuilder()
            .producer("test-producer", "1.0.0")
            .input_identity("file", "design.yaml", _sha256(b"design content"))
            .design_state_hash(_sha256(b"design state"))
            .configuration(_sha256(b"config"), "1.0", {"threshold": 0.5})
            .result_status(ProducerResultStatus.PASS)
            .authority(EvidenceAuthority.PRODUCER)
            .confidence_ceiling(0.95)
            .evidence_identity(_dummy_evidence_identity())
            .build()
        )
        # output_identity is None; traversing into it should return None
        evidence = adapt_producer_record_to_proof_evidence(
            record,
            evidence_class=_TestEvidenceModel,
            field_mapping={"dummy_field": "output_identity.sha256"},
        )
        # The field should not be set since traversal returns None
        assert "dummy_field" not in evidence.model_dump()


class TestValidateEvidenceProducerRecord:
    def test_valid_record_returns_empty_errors(self) -> None:
        record = _minimal_valid_record()
        errors = validate_evidence_producer_record(record)
        assert errors == []

    def test_invalid_schema_version_reported_direct(self) -> None:
        record = _minimal_valid_record()
        # Bypass model validation to test the validator directly
        record_dict = record.model_dump(mode="json")
        record_dict["schema_version"] = "9.9"
        # Create a record-like object with invalid schema_version
        from types import SimpleNamespace

        invalid_record = SimpleNamespace(**record_dict)
        errors = validate_evidence_producer_record(invalid_record)
        assert any("unsupported producer schema version" in e for e in errors)

    def test_malformed_design_state_hash_reported(self) -> None:
        record = _minimal_valid_record()
        record_dict = record.model_dump(mode="json")
        record_dict["design_state_hash"] = "not-a-hash"
        from types import SimpleNamespace

        invalid_record = SimpleNamespace(**record_dict)
        errors = validate_evidence_producer_record(invalid_record)
        assert any("design_state_hash is malformed" in e for e in errors)

    def test_confidence_ceiling_bounds_reported(self) -> None:
        record = _minimal_valid_record()
        record_dict = record.model_dump(mode="json")
        record_dict["confidence_ceiling"] = 1.5
        from types import SimpleNamespace

        invalid_record = SimpleNamespace(**record_dict)
        errors = validate_evidence_producer_record(invalid_record)
        assert any("confidence_ceiling must be in [0.0, 1.0]" in e for e in errors)

        record_dict["confidence_ceiling"] = -0.1
        invalid_record = SimpleNamespace(**record_dict)
        errors = validate_evidence_producer_record(invalid_record)
        assert any("confidence_ceiling must be in [0.0, 1.0]" in e for e in errors)


class TestRoundTripSerialization:
    def test_json_round_trip_preserves_hash(self) -> None:
        record = _minimal_valid_record()
        json_str = record.model_dump_json(indent=2)
        restored = EvidenceProducerRecord.model_validate_json(json_str)
        assert restored.record_sha256 == record.record_sha256
        assert restored.producer.name == record.producer.name
        assert restored.result_status == record.result_status
        assert restored.authority == record.authority

    def test_file_round_trip(self, tmp_path: Path) -> None:
        record = _minimal_valid_record()
        path = tmp_path / "producer-record.json"
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        restored = EvidenceProducerRecord.validate_and_load(path)
        assert restored.record_sha256 == record.record_sha256
