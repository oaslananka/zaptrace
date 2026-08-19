"""Proof-manifest integration for simulation sign-off evidence."""

from __future__ import annotations

from pathlib import Path

from zaptrace.analysis.simulation_signoff import SimulationFamilyReport
from zaptrace.proof.manifest import ProofManifest, SimulationSignoffProofEvidence


def _existing_model_artifact(model_path: str, root: Path) -> Path | None:
    if not model_path:
        return None
    candidate = Path(model_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate if candidate.is_file() else None


def attach_simulation_signoff_evidence(
    manifest: ProofManifest,
    report: SimulationFamilyReport,
    *,
    report_path: str | Path,
    artifact_root: str | Path | None = None,
) -> SimulationSignoffProofEvidence:
    """Attach only finalized, hash-valid simulation evidence to a proof manifest."""
    if not report.report_sha256 or report.report_sha256 != report.compute_sha256():
        raise ValueError("simulation sign-off report must be finalized and hash-valid before proof attachment")
    source = Path(report_path)
    reference_name = source.name or "simulation-signoff.json"
    evidence = SimulationSignoffProofEvidence.from_report(report, report_path=reference_name)
    manifest.simulation_signoff = evidence
    manifest.references[reference_name] = str(report_path)
    root = Path(artifact_root) if artifact_root is not None else source.parent
    for model in report.models:
        for model_path in (model.artifact_path, model.netlist_path):
            candidate = _existing_model_artifact(model_path, root)
            if candidate is None:
                continue
            bundle_name = f"simulation-models/{report.family_id}/{candidate.name}"
            manifest.references[bundle_name] = str(candidate)
    return evidence


__all__ = ["attach_simulation_signoff_evidence"]
