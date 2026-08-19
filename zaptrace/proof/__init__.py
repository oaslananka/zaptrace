"""Proof Pack — self-verifying design validation packages.

A Proof Pack is a portable, self-contained validation bundle that proves a PCB design
is manufacturable. It includes: design constraints, expected outputs, pass/fail criteria,
and optionally reference files (golden outputs).

Usage:
    from zaptrace.proof import ProofPack, run_proof

    pack = ProofPack.load("path/to/proof.yaml")
    results = pack.run()
    results.summary()  # "PASS: 12/12 checks"
"""

from __future__ import annotations

from .checker import CheckResult, CheckStatus, ProofRunner
from .claims import (
    FORBIDDEN_FABRICATION_CLAIMS,
    FabricationClaimViolation,
    assert_no_unapproved_fabrication_claims,
    find_unapproved_fabrication_claims,
)
from .manifest import (
    ArchitectureProofEvidence,
    ArtifactRecord,
    AssumptionsEvidence,
    CheckDefinition,
    CheckRecord,
    CheckSource,
    ComponentMetadataEvidence,
    ComponentSelectionProofEvidence,
    ComponentSelectionRecord,
    CurrentDensityEvidence,
    DatasheetProvenanceEvidence,
    DeratingEvidence,
    DiffPairLengthEvidence,
    EngineeringReviewEvidence,
    EnvironmentRecord,
    FootprintProofEvidence,
    ImpedanceReturnPathEvidence,
    InputRecord,
    LayoutQualityEvidence,
    ManifestModel,
    ManufacturingProofEvidence,
    NetlistParityEvidence,
    PlacementScorecardEvidence,
    ProofManifest,
    RailCurrentBudgetEvidence,
    RegulatorMarginEvidence,
    ReleaseGateProofEvidence,
    RepairProposalEvidence,
    RequirementsCoverageEvidence,
    SimulationSignoffProofEvidence,
    SipiRiskEvidence,
    VerifyRepairProofEvidence,
)
from .manifest import (
    CheckStatus as ManifestCheckStatus,
)
from .pack import ProofPack, capture_environment, hash_file, run_proof, validate_proof_pack
from .signoff import (
    AutonomousSignoffDecision,
    AutonomousSignoffPolicy,
    AutonomousSignoffStatus,
    SignoffCheckStatus,
    SignoffEvidence,
)
from .simulation_signoff import attach_simulation_signoff_evidence
from .verify_repair import attach_verify_repair_evidence

__all__ = [
    "ProofManifest",
    "ArchitectureProofEvidence",
    "ManifestModel",
    "ManufacturingProofEvidence",
    "ManufacturingProofEvidence",
    "ManufacturingProofEvidence",
    "AssumptionsEvidence",
    "ComponentMetadataEvidence",
    "ComponentSelectionProofEvidence",
    "ComponentSelectionRecord",
    "CurrentDensityEvidence",
    "DatasheetProvenanceEvidence",
    "DiffPairLengthEvidence",
    "EngineeringReviewEvidence",
    "FootprintProofEvidence",
    "ImpedanceReturnPathEvidence",
    "LayoutQualityEvidence",
    "PlacementScorecardEvidence",
    "RailCurrentBudgetEvidence",
    "RegulatorMarginEvidence",
    "ReleaseGateProofEvidence",
    "RepairProposalEvidence",
    "VerifyRepairProofEvidence",
    "DeratingEvidence",
    "NetlistParityEvidence",
    "RequirementsCoverageEvidence",
    "SipiRiskEvidence",
    "SimulationSignoffProofEvidence",
    "CheckDefinition",
    "CheckRecord",
    "CheckSource",
    "ArtifactRecord",
    "EnvironmentRecord",
    "InputRecord",
    "ProofRunner",
    "CheckResult",
    "CheckStatus",
    "ManifestCheckStatus",
    "ProofPack",
    "run_proof",
    "validate_proof_pack",
    "capture_environment",
    "hash_file",
    "AutonomousSignoffStatus",
    "SignoffCheckStatus",
    "SignoffEvidence",
    "AutonomousSignoffDecision",
    "AutonomousSignoffPolicy",
    "FORBIDDEN_FABRICATION_CLAIMS",
    "FabricationClaimViolation",
    "find_unapproved_fabrication_claims",
    "assert_no_unapproved_fabrication_claims",
    "attach_simulation_signoff_evidence",
    "attach_verify_repair_evidence",
]
