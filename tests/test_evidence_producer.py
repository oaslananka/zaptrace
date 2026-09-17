from __future__ import annotations

from zaptrace.evidence.producer import (
    ArtifactDigest,
    EvidenceAuthority,
    EvidenceProducerRecord,
    EvidenceProducerStatus,
)


def test_evidence_producer_record_hash_computation() -> None:
    artifact = ArtifactDigest(
        relative_path="artifacts/drc_report.json",
        sha256="a" * 64,
        size_bytes=1024,
    )
    record = EvidenceProducerRecord(
        producer_id="kicad-drc-oracle",
        producer_version="8.0.2",
        producer_class="oracle",
        execution_environment={"os": "linux", "python": "3.12"},
        input_design_sha256="b" * 64,
        config_sha256="c" * 64,
        status=EvidenceProducerStatus.PASS,
        evidence_authority=EvidenceAuthority.AUTOMATED_ORACLE,
        retained_artifacts=[artifact],
        warnings=["Non-critical silkscreen overlap warning"],
        human_review_required=True,
    )

    digest = record.calculate_record_hash()
    assert isinstance(digest, str)
    assert len(digest) == 64
    assert record.status == EvidenceProducerStatus.PASS
    assert record.evidence_authority == EvidenceAuthority.AUTOMATED_ORACLE
    assert record.human_review_required is True
    assert record.retained_artifacts[0].relative_path == "artifacts/drc_report.json"
