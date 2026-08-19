"""Proof-manifest integration for release verify/repair evidence."""

from __future__ import annotations

from pathlib import Path

from zaptrace.pipeline.verify_repair_models import VerifyRepairReport
from zaptrace.proof.manifest import ProofManifest, VerifyRepairProofEvidence


def attach_verify_repair_evidence(
    manifest: ProofManifest,
    report: VerifyRepairReport,
    *,
    report_path: str | Path,
) -> VerifyRepairProofEvidence:
    """Bind a finalized verify/repair report to a proof manifest and bundle reference."""
    if not report.report_sha256 or report.report_sha256 != report.compute_sha256():
        raise ValueError("verify/repair report must be finalized and hash-valid before proof attachment")
    source = Path(report_path)
    reference_name = source.name or "verify-repair.json"
    evidence = VerifyRepairProofEvidence.from_report(report, report_path=reference_name)
    manifest.verify_repair = evidence
    manifest.references[reference_name] = str(report_path)
    return evidence


__all__ = ["attach_verify_repair_evidence"]
