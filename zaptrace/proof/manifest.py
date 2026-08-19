"""Proof Pack manifest — defines what a proof pack validates.

Schema v1.0 includes:
  - Input record (source type, checksums)
  - Environment metadata (Python, OS, tool versions)
  - Artifact records (path, kind, SHA-256 hash)
  - Check records (source, status, severity, summary)
  - Limitations list

See docs/strategy/proof-pack-spec.md for the full specification.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.evidence.identity import EvidenceIdentity
from zaptrace.security.release import ReleaseEvidenceStatus

from .signoff import AutonomousSignoffDecision, AutonomousSignoffPolicy

if TYPE_CHECKING:
    from zaptrace.analysis.simulation_signoff import SimulationFamilyReport
    from zaptrace.pipeline.verify_repair_models import VerifyRepairReport

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class CheckCategory(StrEnum):
    """Categories of proof checks."""

    DRC = "drc"
    ERC = "erc"
    ROUTING = "routing"
    FOOTPRINT = "footprint"
    SIGNAL_INTEGRITY = "signal_integrity"
    THERMAL = "thermal"
    MANUFACTURING = "manufacturing"
    SPICE = "spice"
    CUSTOM = "custom"


class CheckSeverity(StrEnum):
    """Severity of a check."""

    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class CheckSource(StrEnum):
    """Source of a validation check."""

    ZAPTRACE = "zaptrace"
    KICAD = "kicad"
    FAB_PROFILE = "fab_profile"
    EXTERNAL = "external"


class CheckStatus(StrEnum):
    """Result status of a single check."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    SKIPPED = "skipped"


class CheckDefinition(BaseModel):
    """Definition of a single proof check."""

    name: str = Field(description="Unique check name")
    description: str = Field(default="", description="Human-readable description")
    category: CheckCategory = Field(default=CheckCategory.CUSTOM)
    severity: CheckSeverity = Field(default=CheckSeverity.ERROR)

    # Check type and parameters
    type: str = Field(description="Check type: drc, erc, routed, footprint_exists, net_connected, clearance, custom")
    params: dict[str, Any] = Field(default_factory=dict)

    # Expected outcome
    expected: str = Field(
        default="pass",
        description="Expected result: 'pass', 'fail', or count threshold",
    )
    expected_count: int | None = Field(
        default=None,
        description="Expected number of violations (0 for clean)",
    )

    # Tagging for filtered runs
    tags: list[str] = Field(default_factory=list)


class ManifestModel(BaseModel):
    """Model-level constraints for the design."""

    min_clearance_mm: float = Field(default=0.15, ge=0)
    min_trace_width_mm: float = Field(default=0.15, ge=0)
    min_annular_ring_mm: float = Field(default=0.05, ge=0)
    max_board_size_mm: tuple[float, float] | None = Field(default=None)
    min_board_size_mm: tuple[float, float] | None = Field(default=None)
    max_layer_count: int = Field(default=2, ge=1)
    allowed_layer_counts: list[int] = Field(default_factory=lambda: [1, 2, 4])


# ---------------------------------------------------------------------------
# v1 evidence records
# ---------------------------------------------------------------------------


class InputRecord(BaseModel):
    """Record of the design input that produced this proof pack."""

    source_type: str = Field(default="file", description="Type of input source: file, intent, api")
    filename: str = Field(default="", description="Original input filename if applicable")
    checksum_sha256: str | None = Field(default=None, description="SHA-256 hex digest of the input file")
    normalized_intent_checksum_sha256: str | None = Field(
        default=None, description="SHA-256 of normalized intent if synthesis was used"
    )


class EnvironmentRecord(BaseModel):
    """Runtime environment snapshot for reproducibility."""

    zaptrace_version: str = Field(default="", description="ZapTrace version")
    python_version: str = Field(default="", description="Python version string")
    platform: str = Field(default="", description="Platform identifier (e.g. 'Linux-6.2-x86_64')")
    os: str = Field(default="", description="OS name (e.g. 'Linux', 'Windows', 'Darwin')")
    lock_sha256: str = Field(default="", description="SHA-256 of the committed uv.lock when available")
    dependency_versions: dict[str, str] = Field(
        default_factory=dict,
        description="Resolved release-relevant Python dependency versions",
    )
    tool_versions: dict[str, str] = Field(
        default_factory=dict,
        description="External tool versions captured at runtime (e.g. {'kicad-cli': '8.0.0'})",
    )
    evidence_identity: EvidenceIdentity | None = Field(
        default=None,
        description="Shared source, lock, dirty-state, and toolchain identity for this proof environment",
    )


class ArtifactRecord(BaseModel):
    """Record of a generated artifact in the proof pack."""

    path: str = Field(description="Relative path of the artifact within the proof pack")
    kind: str = Field(description="Artifact kind: gerber, excellon, bom, kicad, netlist, report, other")
    sha256: str | None = Field(default=None, description="SHA-256 hex digest of the artifact contents")
    size_bytes: int = Field(default=0, description="File size in bytes")


class KiCadOracleEvidence(BaseModel):
    """Structured KiCad oracle evidence stored in a proof-pack manifest."""

    check: str = Field(description="Oracle check name, such as erc, drc, or export_smoke")
    status: str = Field(description="Oracle result: passed, failed, or skipped")
    version: str = Field(default="", description="Detected kicad-cli version")
    cli_path: str = Field(default="", description="Detected kicad-cli executable path")
    command: list[str] = Field(default_factory=list, description="Executed command, if any")
    exit_code: int | None = Field(default=None, description="Process exit code, if a command ran")
    report_path: str | None = Field(default=None, description="Path to detailed oracle report artifact, if any")
    report_sha256: str = Field(default="", description="SHA-256 of the oracle report artifact, if available")
    errors: int = Field(default=0, ge=0, description="Parsed error count")
    warnings: int = Field(default=0, ge=0, description="Parsed warning count")
    message: str = Field(default="", description="Human-readable outcome summary")
    skip_reason: str = Field(default="", description="Explicit reason when status is skipped")
    approval_id: str = Field(default="", description="Human approval/waiver identifier, if waived")
    waiver_reason: str = Field(default="", description="Human-readable waiver rationale, if waived")


class BomProvenanceEvidence(BaseModel):
    """Structured BOM intelligence provenance stored in a proof-pack manifest."""

    provider: str = Field(description="BOM intelligence provider name")
    cache_policy: str = Field(
        default="",
        description="Provider cache/offline policy used for this run",
    )
    generated_at: str = Field(default="", description="Timestamp for the BOM risk report")
    report_path: str | None = Field(
        default=None,
        description="Path to detailed BOM risk report artifact",
    )
    highest_risk: str = Field(default="unknown", description="Highest observed BOM risk level")
    blocked: bool = Field(default=False, description="Whether BOM risk blocks release acceptance")
    cache_age_hours: float | None = Field(
        default=None,
        ge=0,
        description="Oldest cache age in the report",
    )
    unresolved_required_parts: int = Field(
        default=0,
        ge=0,
        description="Required parts not resolved by provider",
    )
    obsolete_required_parts: int = Field(
        default=0,
        ge=0,
        description="Required parts marked obsolete",
    )
    message: str = Field(default="", description="Human-readable BOM provenance summary")


class ManufacturingProofEvidence(BaseModel):
    """Structured manufacturing evidence stored in a proof-pack manifest."""

    fab_profile: str = Field(default="", description="Selected fabrication profile")
    fab_profile_version: str = Field(default="", description="Version of the fabrication capability profile")
    fab_profile_sha256: str = Field(default="", description="Digest of the complete fabrication profile")
    readiness_status: str = Field(default="human-review-required", description="Manufacturer-aware DFM readiness state")
    readiness_report_sha256: str = Field(default="", description="Digest of the DFM readiness report artifact")
    artifact_sha256: dict[str, str] = Field(default_factory=dict, description="Manufacturing artifact path to SHA-256")
    report_path: str | None = Field(default=None, description="Path to detailed manufacturing evidence report")
    blocked: bool = Field(default=False, description="Whether manufacturing evidence blocks release acceptance")
    artifact_count: int = Field(default=0, ge=0, description="Number of manufacturing artifacts recorded")
    validation_count: int = Field(default=0, ge=0, description="Number of validations recorded")
    gerber_smoke_status: str = Field(default="unknown", description="Aggregate Gerber smoke validation status")
    excellon_smoke_status: str = Field(default="unknown", description="Aggregate Excellon smoke validation status")
    odbpp_status: str = Field(default="not-attached", description="ODB++ evidence status")
    ipc2581_status: str = Field(default="not-attached", description="IPC-2581 evidence status")
    mechanical_review_status: str = Field(
        default="not-attached",
        description="3D mechanical-review evidence status; attachment alone is not fit validation",
    )
    message: str = Field(default="", description="Human-readable manufacturing evidence summary")

    @classmethod
    def from_evidence_bundle(
        cls,
        bundle: Any,
        *,
        report_path: str | None = None,
    ) -> ManufacturingProofEvidence:
        """Build proof metadata from a manufacturing evidence bundle."""
        artifacts = list(getattr(bundle, "artifacts", []))
        validations = list(getattr(bundle, "validations", []))
        artifact_sha256 = {str(item.path): str(item.sha256) for item in artifacts}

        def aggregate(prefix: str) -> str:
            statuses = [str(item.status.value) for item in validations if str(item.name).startswith(prefix)]
            if "fail" in statuses:
                return "fail"
            if "human-review-required" in statuses:
                return "human-review-required"
            if "warning" in statuses:
                return "warning"
            return "pass" if statuses else "unknown"

        readiness_hash = str(getattr(bundle, "readiness_report_sha256", ""))
        if not readiness_hash and report_path:
            readiness_hash = artifact_sha256.get(report_path, "")
        artifact_kinds = {
            str(getattr(getattr(item, "kind", ""), "value", getattr(item, "kind", ""))) for item in artifacts
        }
        return cls(
            fab_profile=str(getattr(bundle, "fab_profile", "")),
            fab_profile_version=str(getattr(bundle, "fab_profile_version", "")),
            fab_profile_sha256=str(getattr(bundle, "fab_profile_sha256", "")),
            readiness_status=str(getattr(bundle, "readiness_status", "human-review-required")),
            readiness_report_sha256=readiness_hash,
            artifact_sha256=artifact_sha256,
            report_path=report_path,
            blocked=bool(getattr(bundle, "blocked", False)),
            artifact_count=len(artifacts),
            validation_count=len(validations),
            gerber_smoke_status=aggregate("gerber-smoke:"),
            excellon_smoke_status=aggregate("excellon-smoke:"),
            odbpp_status="attached" if "odbpp" in artifact_kinds else "not-attached",
            ipc2581_status="attached" if "ipc2581" in artifact_kinds else "not-attached",
            mechanical_review_status=("attached-degraded" if "mechanical_review" in artifact_kinds else "not-attached"),
            message="Manufacturer-aware DFM readiness and artifact hashes attached.",
        )


class EngineeringReviewEvidence(BaseModel):
    """Authenticated, state-bound human engineering review evidence."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    status: str = Field(description="Human review state, separate from autonomous sign-off")
    review_session_id: str = ""
    decision_id: str = ""
    decision: str = ""
    reviewer_id: str = ""
    decided_at: str = ""
    reason: str = ""
    waiver_notes: str = ""
    design_state_hash: str = ""
    approval_id: str = ""
    current: bool = False
    approval_id_matched: bool = False
    checklist_results: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_release_gate(cls, gate: dict[str, Any]) -> EngineeringReviewEvidence:
        """Extract normalized review evidence from a release gate response."""
        review = gate.get("engineering_review")
        if not isinstance(review, dict):
            raise ValueError("release gate does not include engineering_review evidence")
        return cls.model_validate(review)


class ReleaseGateProofEvidence(BaseModel):
    """Complete release decision identity attached to a proof-pack manifest."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    status: ReleaseEvidenceStatus
    automated_gate_status: ReleaseEvidenceStatus = ReleaseEvidenceStatus.MISSING_EVIDENCE
    fabrication_status: str = "human-review-required"
    engineering_review: EngineeringReviewEvidence | None = None
    gate_version: str = Field(min_length=1)
    design_state_hash: str = Field(min_length=1)
    evidence_identity_hash: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    approval_binding_hash: str = Field(min_length=1)
    evidence_identity: dict[str, Any]
    approval_binding: dict[str, Any]

    @classmethod
    def from_release_gate(cls, gate: dict[str, Any]) -> ReleaseGateProofEvidence:
        """Build proof evidence from the exact gate returned by a release export."""
        identity = gate.get("evidence_identity")
        binding = gate.get("approval_binding")
        if not isinstance(identity, dict) or not isinstance(binding, dict):
            raise ValueError("release gate must include evidence_identity and approval_binding")
        approval_id = str(gate.get("approval_id") or "")
        identity_hash = str(identity.get("evidence_identity_hash") or "")
        if binding.get("approval_id") != approval_id or binding.get("evidence_identity_hash") != identity_hash:
            raise ValueError("release gate approval binding does not match the evidence identity")
        review_payload = gate.get("engineering_review")
        engineering_review = (
            EngineeringReviewEvidence.model_validate(review_payload) if isinstance(review_payload, dict) else None
        )
        return cls(
            status=gate.get("status", ReleaseEvidenceStatus.MISSING_EVIDENCE),
            automated_gate_status=gate.get(
                "automated_gate_status",
                gate.get("status", ReleaseEvidenceStatus.MISSING_EVIDENCE),
            ),
            fabrication_status=str(gate.get("fabrication_status") or "human-review-required"),
            engineering_review=engineering_review,
            gate_version=str(identity.get("gate_version") or ""),
            design_state_hash=str(identity.get("design_state_hash") or ""),
            evidence_identity_hash=identity_hash,
            approval_id=approval_id,
            approval_binding_hash=str(binding.get("approval_binding_hash") or ""),
            evidence_identity=identity,
            approval_binding=binding,
        )


class AssumptionsEvidence(BaseModel):
    """Structured assumptions evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to assumptions.json")
    requirements_hash: str = Field(description="Hash of the frozen requirements contract")
    approved: bool = Field(description="Whether all required assumptions are confirmed")
    assumption_count: int = Field(default=0, ge=0, description="Number of assumptions in the artifact")
    unconfirmed_high_risk_count: int = Field(
        default=0,
        ge=0,
        description="Number of high-risk assumptions that still lack confirmation",
    )
    message: str = Field(default="", description="Human-readable assumptions summary")


class SipiRiskEvidence(BaseModel):
    """Structured SI/PI risk evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to SI/PI risk JSON report")
    passed: bool = Field(description="Whether SI/PI risk evidence passed")
    high_speed_net_count: int = Field(default=0, ge=0, description="High-speed/RF net count")
    impedance_assumption_count: int = Field(default=0, ge=0, description="Impedance assumption count")
    return_path_diagnostic_count: int = Field(default=0, ge=0, description="Return-path diagnostic count")
    decoupling_issue_count: int = Field(default=0, ge=0, description="Decoupling issue count")
    unsupported_high_speed_count: int = Field(default=0, ge=0, description="Unsupported high-speed/RF net count")
    human_review_required: bool = Field(default=False, description="Whether SI/PI evidence needs review")
    blocked: bool = Field(default=False, description="Whether SI/PI evidence blocks autonomous sign-off")
    message: str = Field(default="", description="Human-readable SI/PI risk summary")


class CurrentDensityEvidence(BaseModel):
    """Structured current-density/copper-width evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to current density JSON report")
    passed: bool = Field(description="Whether current density checks passed")
    high_current_net_count: int = Field(default=0, ge=0, description="Number of high-current nets checked")
    trace_count: int = Field(default=0, ge=0, description="Number of trace segments checked")
    violation_count: int = Field(default=0, ge=0, description="Trace width/current violation count")
    missing_route_count: int = Field(default=0, ge=0, description="High-current nets without routed trace evidence")
    human_review_required: bool = Field(default=False, description="Whether current-density evidence needs review")
    blocked: bool = Field(default=False, description="Whether current-density evidence blocks autonomous sign-off")
    message: str = Field(default="", description="Human-readable current-density summary")


class RegulatorMarginEvidence(BaseModel):
    """Structured regulator dropout/thermal margin evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to regulator margin JSON report")
    passed: bool = Field(description="Whether regulator dropout/thermal margin checks passed")
    regulator_count: int = Field(default=0, ge=0, description="Number of regulators checked")
    failure_count: int = Field(default=0, ge=0, description="Dropout/thermal failure count")
    missing_metadata_count: int = Field(default=0, ge=0, description="Missing regulator margin metadata count")
    human_review_required: bool = Field(default=False, description="Whether regulator margin evidence needs review")
    blocked: bool = Field(default=False, description="Whether regulator margin evidence blocks autonomous sign-off")
    message: str = Field(default="", description="Human-readable regulator margin summary")


class RailCurrentBudgetEvidence(BaseModel):
    """Structured rail current budget evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to rail current budget JSON report")
    passed: bool = Field(description="Whether rail current budget passed")
    rail_count: int = Field(default=0, ge=0, description="Number of rails checked")
    failure_count: int = Field(default=0, ge=0, description="Rail current budget failure count")
    missing_metadata_count: int = Field(default=0, ge=0, description="Missing source/load current metadata count")
    human_review_required: bool = Field(default=False, description="Whether budget evidence needs human review")
    blocked: bool = Field(default=False, description="Whether budget evidence blocks autonomous sign-off")
    message: str = Field(default="", description="Human-readable rail current budget summary")


class RepairProposalEvidence(BaseModel):
    """Structured auto-repair proposal evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to repair proposal JSON report")
    passed: bool = Field(description="Whether repair proposals passed evidence policy")
    proposal_count: int = Field(default=0, ge=0, description="Number of repair proposals recorded")
    verified_count: int = Field(default=0, ge=0, description="Number of proposals with improving verification")
    silent_repair_count: int = Field(default=0, ge=0, description="Repairs without proposal evidence")
    human_review_required: bool = Field(default=False, description="Whether repair evidence requires human review")
    blocked: bool = Field(default=False, description="Whether repair evidence blocks autonomous sign-off")
    message: str = Field(default="", description="Human-readable repair proposal evidence summary")


class VerifyRepairProofEvidence(BaseModel):
    """Release verify/repair gate history bound to one proof-pack manifest."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    report_path: str = Field(min_length=1)
    report_sha256: str = Field(pattern=_SHA256_PATTERN)
    policy_version: str = Field(min_length=1)
    policy_sha256: str = Field(pattern=_SHA256_PATTERN)
    initial_design_state_hash: str = Field(pattern=_SHA256_PATTERN)
    final_design_state_hash: str = Field(pattern=_SHA256_PATTERN)
    converged: bool
    stop_reason: str = Field(min_length=1)
    enabled_domains: list[str] = Field(default_factory=list)
    gate_history_count: int = Field(default=0, ge=0)
    repair_count: int = Field(default=0, ge=0)
    blocking_gate_count: int = Field(default=0, ge=0)
    human_review_required: bool = False
    blocks_autonomous_release: bool = True
    message: str = ""

    @classmethod
    def from_report(cls, report: VerifyRepairReport, *, report_path: str) -> VerifyRepairProofEvidence:
        stop_reason = report.stop_reason.value
        return cls(
            report_path=report_path,
            report_sha256=report.report_sha256,
            policy_version=report.policy_version,
            policy_sha256=report.policy_sha256,
            initial_design_state_hash=report.initial_design_state_hash,
            final_design_state_hash=report.final_design_state_hash,
            converged=report.converged,
            stop_reason=stop_reason,
            enabled_domains=[domain.value for domain in report.enabled_domains],
            gate_history_count=len(report.gate_history),
            repair_count=len(report.repairs),
            blocking_gate_count=sum(gate.blocks_autonomous_release for gate in report.final_gates),
            human_review_required=report.human_review_required,
            blocks_autonomous_release=report.blocks_autonomous_release,
            message=f"verify/repair {stop_reason}; converged={str(report.converged).lower()}",
        )


class SimulationSignoffProofEvidence(BaseModel):
    """Unified simulation/analytical sign-off evidence bound to one design state."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    report_path: str = Field(min_length=1)
    report_sha256: str = Field(pattern=_SHA256_PATTERN)
    family_id: str = Field(min_length=1)
    design_state_hash: str = Field(pattern=_SHA256_PATTERN)
    model_count: int = Field(default=0, ge=0)
    check_count: int = Field(default=0, ge=0)
    live_simulation_pass_count: int = Field(default=0, ge=0)
    fail_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    human_review_count: int = Field(default=0, ge=0)
    blocked: bool
    human_review_required: bool
    message: str = ""

    @classmethod
    def from_report(
        cls,
        report: SimulationFamilyReport,
        *,
        report_path: str,
    ) -> SimulationSignoffProofEvidence:
        return cls(
            report_path=report_path,
            report_sha256=report.report_sha256,
            family_id=report.family_id,
            design_state_hash=report.design_state_hash,
            model_count=len(report.models),
            check_count=report.check_count,
            live_simulation_pass_count=report.live_simulation_pass_count,
            fail_count=report.fail_count,
            skipped_count=report.skipped_count,
            human_review_count=report.human_review_count,
            blocked=report.blocked,
            human_review_required=report.human_review_required,
            message=(
                f"simulation sign-off: {report.check_count} check(s), "
                f"{report.live_simulation_pass_count} live simulation pass(es)"
            ),
        )


class ImpedanceReturnPathEvidence(BaseModel):
    """Structured impedance/return-path risk evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to impedance/return-path JSON report")
    passed: bool = Field(description="Whether impedance/return-path risk checks passed")
    assumption_count: int = Field(default=0, ge=0, description="Number of explicit impedance assumptions")
    diagnostic_count: int = Field(default=0, ge=0, description="Return-path diagnostic count")
    human_review_required: bool = Field(default=False, description="Whether unsupported/high-risk cases need review")
    blocked: bool = Field(default=False, description="Whether risk evidence blocks autonomous sign-off")
    message: str = Field(default="", description="Human-readable impedance/return-path summary")


class DiffPairLengthEvidence(BaseModel):
    """Structured differential-pair length/skew evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to differential-pair length/skew JSON report")
    passed: bool = Field(description="Whether differential-pair length/skew checks passed")
    pair_count: int = Field(default=0, ge=0, description="Number of length/differential groups checked")
    violation_count: int = Field(default=0, ge=0, description="Length/skew violation count")
    missing_route_count: int = Field(default=0, ge=0, description="Missing routed-length evidence count")
    message: str = Field(default="", description="Human-readable differential-pair length/skew summary")


class PlacementScorecardEvidence(BaseModel):
    """Structured placement scorecard evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to placement scorecard JSON")
    passed: bool = Field(description="Whether placement scorecard passed autonomous threshold")
    overall_score: float = Field(default=0.0, ge=0, le=1, description="Overall placement score")
    min_autonomous_score: float = Field(default=0.75, ge=0, le=1, description="Minimum score for autonomous-pass")
    warning_count: int = Field(default=0, ge=0, description="Placement warning count")
    blocking_observation_count: int = Field(default=0, ge=0, description="Blocking placement observation count")
    human_review_required: bool = Field(default=False, description="Whether placement scorecard needs human review")
    message: str = Field(default="", description="Human-readable placement scorecard summary")


class LayoutQualityEvidence(BaseModel):
    """Unified constraint-driven layout-quality evidence."""

    report_path: str = Field(description="Path to layout-quality JSON report")
    passed: bool = Field(description="Whether no release-blocking layout finding exists")
    overall_score: float = Field(default=0.0, ge=0, le=1, description="Aggregate layout-quality score")
    policy_version: str = Field(default="", description="Layout-quality policy version")
    policy_sha256: str = Field(default="", description="Canonical layout-quality policy digest")
    design_state_hash: str = Field(default="", description="Design state bound to the layout report")
    finding_count: int = Field(default=0, ge=0, description="Normalized layout finding count")
    repair_count: int = Field(default=0, ge=0, description="Bounded layout repair evidence count")
    blocking_count: int = Field(default=0, ge=0, description="Release-blocking layout finding count")
    warning_count: int = Field(default=0, ge=0, description="Layout warning count")
    human_review_count: int = Field(default=0, ge=0, description="Human-review-required finding count")
    human_review_required: bool = Field(default=False, description="Whether layout evidence needs human review")
    blocked: bool = Field(default=False, description="Whether layout evidence blocks autonomous sign-off")
    message: str = Field(default="", description="Human-readable layout-quality summary")

    @classmethod
    def from_report(cls, report: Any, *, report_path: str) -> LayoutQualityEvidence:
        findings = list(getattr(report, "findings", []))
        status_values = [
            str(getattr(getattr(item, "status", ""), "value", getattr(item, "status", ""))) for item in findings
        ]
        blocked = bool(getattr(report, "blocked", False))
        review = bool(getattr(report, "human_review_required", False))
        report_status = getattr(report, "status", "")
        status_value = str(getattr(report_status, "value", report_status))
        overall_score = float(getattr(report, "overall_score", 0.0))
        return cls(
            report_path=report_path,
            passed=not blocked,
            overall_score=overall_score,
            policy_version=str(getattr(report, "policy_version", "")),
            policy_sha256=str(getattr(report, "policy_sha256", "")),
            design_state_hash=str(getattr(report, "design_state_hash", "")),
            finding_count=len(findings),
            repair_count=len(getattr(report, "repairs", [])),
            blocking_count=status_values.count("blocking"),
            warning_count=status_values.count("warning"),
            human_review_count=status_values.count("human-review-required"),
            human_review_required=review,
            blocked=blocked,
            message=f"layout quality {status_value}; score={overall_score:.3f}",
        )


class FootprintProofEvidence(BaseModel):
    """Structured footprint proof validation evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to footprint proof validation report JSON")
    passed: bool = Field(description="Whether footprint proof validation passed")
    proof_count: int = Field(default=0, ge=0, description="Number of footprint proofs validated")
    error_count: int = Field(default=0, ge=0, description="Blocking footprint proof error count")
    warning_count: int = Field(default=0, ge=0, description="Non-blocking footprint proof warning count")
    message: str = Field(default="", description="Human-readable footprint proof summary")


class DatasheetProvenanceEvidence(BaseModel):
    """Structured datasheet fact/provenance evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to datasheet fact provenance report JSON")
    component_count: int = Field(default=0, ge=0, description="Number of components with datasheet evidence")
    fact_count: int = Field(default=0, ge=0, description="Number of datasheet facts recorded")
    absolute_maximum_count: int = Field(default=0, ge=0, description="Number of absolute maximum facts")
    recommended_operating_count: int = Field(
        default=0, ge=0, description="Number of recommended operating condition facts"
    )
    missing_hash_count: int = Field(default=0, ge=0, description="Facts without datasheet SHA-256 provenance")
    low_confidence_count: int = Field(default=0, ge=0, description="Facts below confidence policy threshold")
    conflict_count: int = Field(default=0, ge=0, description="Conflicting datasheet fact groups")
    stale_fact_count: int = Field(default=0, ge=0, description="Facts stale because source hash changed")
    hash_mismatch_count: int = Field(default=0, ge=0, description="Datasheet source hash mismatch count")
    human_review_required: bool = Field(default=False, description="Whether low-confidence facts require human review")
    blocked: bool = Field(default=False, description="Whether datasheet provenance blocks autonomous sign-off")
    message: str = Field(default="", description="Human-readable datasheet provenance summary")


class DeratingEvidence(BaseModel):
    """Structured component derating policy evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to derating report JSON")
    passed: bool = Field(description="Whether derating policy passed")
    component_count: int = Field(default=0, ge=0, description="Number of components inspected")
    finding_count: int = Field(default=0, ge=0, description="Number of derating findings")
    blocking_finding_count: int = Field(default=0, ge=0, description="Number of failed derating findings")
    message: str = Field(default="", description="Human-readable derating summary")


class ComponentMetadataEvidence(BaseModel):
    """Structured component metadata gate evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to component metadata gate JSON report")
    valid: bool = Field(description="Whether critical component metadata passed the gate")
    component_count: int = Field(default=0, ge=0, description="Number of components inspected")
    critical_issue_count: int = Field(default=0, ge=0, description="Blocking schema/metadata issue count")
    warning_count: int = Field(default=0, ge=0, description="Non-blocking metadata warning count")
    release_eligible_count: int = Field(
        default=0, ge=0, description="Components eligible for release/fabrication under trust policy"
    )
    blocked_component_count: int = Field(
        default=0, ge=0, description="Schema-valid components blocked by trust/review policy"
    )
    human_review_required_count: int = Field(
        default=0, ge=0, description="Components requiring policy-scoped human review"
    )
    trust_tier_counts: dict[str, int] = Field(
        default_factory=dict, description="Component counts by verified/curated/heuristic/placeholder tier"
    )
    message: str = Field(default="", description="Human-readable component metadata summary")


class ArchitectureProofEvidence(BaseModel):
    """Canonical requirements-to-architecture traceability evidence."""

    model_config = ConfigDict(strict=False)

    report_path: str = Field(min_length=1)
    artifact_path: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: str = Field(min_length=1)
    requirement_count: int = Field(default=0, ge=0)
    assumption_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    untraced_element_count: int = Field(default=0, ge=0)
    uncovered_requirement_count: int = Field(default=0, ge=0)
    fully_traced: bool
    blocked: bool
    human_review_required: bool
    message: str = ""


class ComponentSelectionRecord(BaseModel):
    """One selected-part decision with rationale and extracted constraints."""

    model_config = ConfigDict(strict=False)

    requirement_id: str = Field(min_length=1)
    position: str = Field(min_length=1)
    selected_component_id: str = ""
    decision_hash: str = Field(min_length=64, max_length=64)
    rationale: str = Field(min_length=1)
    extracted_constraints: dict[str, Any] = Field(default_factory=dict)
    blocked: bool = False
    human_review_required: bool = False


class ComponentSelectionProofEvidence(BaseModel):
    """Aggregate component-selection evidence stored in a proof-pack manifest."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    report_path: str = Field(min_length=1)
    report_sha256: str = Field(min_length=64, max_length=64)
    requirement_count: int = Field(default=0, ge=0)
    selected_count: int = Field(default=0, ge=0)
    blocked_count: int = Field(default=0, ge=0)
    human_review_required_count: int = Field(default=0, ge=0)
    selections: list[ComponentSelectionRecord] = Field(default_factory=list)
    message: str = ""


class NetlistParityEvidence(BaseModel):
    """Structured netlist parity evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to netlist parity JSON report")
    check: str = Field(default="ir_to_kicad_schematic_netlist", description="Parity check name")
    passed: bool = Field(description="Whether the compared netlists match")
    missing_net_count: int = Field(default=0, ge=0, description="Nets missing from KiCad evidence")
    extra_net_count: int = Field(default=0, ge=0, description="Nets unexpectedly present in KiCad evidence")
    pin_mismatch_count: int = Field(default=0, ge=0, description="Nets with pin-level connectivity mismatch")
    message: str = Field(default="", description="Human-readable parity summary")


class RequirementsCoverageEvidence(BaseModel):
    """Structured requirements coverage evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to requirements_coverage.json")
    requirements_hash: str = Field(description="Hash of the frozen requirements contract")
    fully_covered: bool = Field(description="Whether stated requirements are covered and artifacts are traced")
    fully_traced: bool = Field(description="Whether generated artifacts have requirement IDs")
    requirement_count: int = Field(default=0, ge=0, description="Number of requirement IDs in the report")
    untraced_artifact_count: int = Field(default=0, ge=0, description="Artifact rows without requirement trace IDs")
    message: str = Field(default="", description="Human-readable coverage summary")


class ManufacturingExportEvidence(BaseModel):
    """Structured manufacturing export log stored in a proof-pack manifest."""

    backend: str = Field(description="Export backend, such as zaptrace, kicad-cli, or external")
    tool_version: str = Field(default="", description="Exporter or external tool version")
    command: list[str] = Field(default_factory=list, description="Command/config entry point used for export")
    artifact_kinds: list[str] = Field(
        default_factory=list,
        description=(
            "Generated or attached artifact kinds: gerber, drill, bom, pick_and_place, "
            "odbpp, ipc2581, mechanical_review"
        ),
    )
    report_path: str | None = Field(default=None, description="Path to detailed manufacturing export log JSON")
    blocked: bool = Field(default=False, description="Whether unsupported export paths block release")
    warnings: list[str] = Field(default_factory=list, description="Warnings emitted during export")
    unsupported: list[str] = Field(
        default_factory=list,
        description="Unsupported paths or variants that were not hidden",
    )


class CheckRecord(BaseModel):
    """Record of a validation check result in the proof pack."""

    name: str = Field(description="Check name")
    source: str = Field(default="zaptrace", description="Check source: zaptrace, kicad, fab_profile, external")
    status: str = Field(description="Result status: pass, warning, fail, skipped")
    severity: str = Field(default="error", description="Check severity: info, warning, error, critical")
    summary: str = Field(default="", description="Human-readable summary of the check outcome")
    details_path: str | None = Field(default=None, description="Path to detailed JSON report, if any")


# ---------------------------------------------------------------------------
# Main manifest
# ---------------------------------------------------------------------------


class AgentDecisionRecord(BaseModel):
    """A single agent or human decision captured in the Proof Pack.

    Enables post-hoc review of *why* a component was chosen, a topology was
    selected, or a trade-off was made — not just *what* was generated.
    """

    model_config = ConfigDict(strict=False)

    decision_id: str = Field(description="Unique decision identifier")
    actor: str = Field(description="Agent name or human identifier that made the decision")
    decision_type: str = Field(
        description="Category: 'component_selection', 'topology', 'constraint', 'waiver', 'human_approval'"
    )
    summary: str = Field(description="One-line summary of what was decided")
    rationale: str = Field(default="", description="Detailed explanation of why this decision was made")
    alternatives_considered: list[str] = Field(
        default_factory=list, description="Other options that were evaluated and rejected"
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="Artifact IDs, datasheet URLs, or requirement IDs that support this decision",
    )
    timestamp: str | None = Field(default=None, description="ISO-8601 timestamp")


class ProofManifest(BaseModel):
    """Complete proof pack manifest (proof.yaml content)."""

    version: str = Field(default="1.0", description="Proof pack format version")
    name: str = Field(description="Proof pack name")
    description: str = Field(default="")

    # Design to validate
    design_path: str = Field(description="Path to the design YAML file")

    # Constraints
    model: ManifestModel = Field(default_factory=ManifestModel)

    # Checks
    checks: list[CheckDefinition] = Field(
        default_factory=list,
        description="List of checks to run",
    )

    # Reference files (golden outputs)
    references: dict[str, str] = Field(
        default_factory=dict,
        description="Map of output file -> reference file path",
    )

    # Metadata
    author: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    requires: list[str] = Field(
        default_factory=list,
        description="Required ZapTrace version or features",
    )

    # --- v1 evidence fields ---
    input_record: InputRecord = Field(default_factory=InputRecord, description="Input source evidence")
    environment: EnvironmentRecord = Field(
        default_factory=EnvironmentRecord, description="Runtime environment snapshot"
    )
    artifacts: list[ArtifactRecord] = Field(default_factory=list, description="Generated artifact records")
    check_records: list[CheckRecord] = Field(default_factory=list, description="Validation check result records")
    kicad_oracle: list[KiCadOracleEvidence] = Field(
        default_factory=list,
        description="KiCad oracle pass/fail/skip evidence metadata",
    )
    requires_kicad_oracle: bool = Field(
        default=False,
        description="Whether missing/skipped KiCad oracle evidence blocks autonomous sign-off",
    )
    bom_provenance: list[BomProvenanceEvidence] = Field(
        default_factory=list,
        description="BOM provider provenance, cache age, and risk summary evidence",
    )
    manufacturing_evidence: list[ManufacturingProofEvidence] = Field(
        default_factory=list,
        description="Manufacturing artifact, smoke-validation, and fab-profile evidence metadata",
    )
    release_evidence: ReleaseGateProofEvidence | None = Field(
        default=None,
        description="Complete release evidence identity and approval binding used for a release decision",
    )
    engineering_review: EngineeringReviewEvidence | None = Field(
        default=None,
        description="Authenticated human review evidence, explicitly separate from autonomous sign-off",
    )
    manufacturing_exports: list[ManufacturingExportEvidence] = Field(
        default_factory=list,
        description="Manufacturing export logs with artifact kinds, tool versions, warnings, and unsupported paths",
    )
    kicad_schematic_parity: NetlistParityEvidence | None = Field(
        default=None,
        description="IR-to-KiCad schematic netlist parity evidence metadata",
    )
    kicad_pcb_parity: NetlistParityEvidence | None = Field(
        default=None,
        description="KiCad schematic-to-PCB netlist parity evidence metadata",
    )
    ipc_d356_parity: NetlistParityEvidence | None = Field(
        default=None,
        description="IPC-D-356 manufacturing netlist parity evidence metadata",
    )
    component_metadata: ComponentMetadataEvidence | None = Field(
        default=None,
        description="Component metadata validator/gate evidence metadata",
    )
    architecture_evidence: ArchitectureProofEvidence | None = Field(
        default=None,
        description="Canonical requirements-to-architecture artifact and traceability evidence",
    )
    component_selection: ComponentSelectionProofEvidence | None = Field(
        default=None,
        description="Selected-part rationale, constraints, and pre-layout gate evidence",
    )
    derating_evidence: DeratingEvidence | None = Field(
        default=None,
        description="Component derating policy evidence metadata",
    )
    datasheet_provenance: DatasheetProvenanceEvidence | None = Field(
        default=None,
        description="Datasheet-derived fact/provenance evidence metadata",
    )
    footprint_proof: FootprintProofEvidence | None = Field(
        default=None,
        description="Footprint proof validation evidence metadata",
    )
    placement_scorecard: PlacementScorecardEvidence | None = Field(
        default=None,
        description="Constraint-aware placement scorecard evidence metadata",
    )
    layout_quality: LayoutQualityEvidence | None = Field(
        default=None,
        description="Unified constraint-driven layout-quality evidence metadata",
    )
    diffpair_length: DiffPairLengthEvidence | None = Field(
        default=None,
        description="Differential-pair length/skew evidence metadata",
    )
    impedance_return_path: ImpedanceReturnPathEvidence | None = Field(
        default=None,
        description="Impedance assumption and return-path risk evidence metadata",
    )
    repair_proposals: RepairProposalEvidence | None = Field(
        default=None,
        description="Auto-repair proposal and verification evidence metadata",
    )
    verify_repair: VerifyRepairProofEvidence | None = Field(
        default=None,
        description="Release verify/repair policy, gate history, repair, and stop-reason evidence",
    )
    simulation_signoff: SimulationSignoffProofEvidence | None = Field(
        default=None,
        description="State-bound simulation and analytical sign-off evidence metadata",
    )
    rail_current_budget: RailCurrentBudgetEvidence | None = Field(
        default=None,
        description="Rail current budget evidence metadata",
    )
    regulator_margin: RegulatorMarginEvidence | None = Field(
        default=None,
        description="Regulator dropout and thermal margin evidence metadata",
    )
    current_density: CurrentDensityEvidence | None = Field(
        default=None,
        description="Current density and copper width evidence metadata",
    )
    sipi_risk: SipiRiskEvidence | None = Field(
        default=None,
        description="SI/PI aggregate risk evidence metadata",
    )

    requirements_coverage: RequirementsCoverageEvidence | None = Field(
        default=None,
        description="Requirements coverage and traceability evidence metadata",
    )
    assumptions_evidence: AssumptionsEvidence | None = Field(
        default=None,
        description="Assumptions artifact metadata and approval state",
    )

    autonomous_signoff: AutonomousSignoffDecision = Field(
        default_factory=lambda: AutonomousSignoffPolicy().evaluate([]),
        description="Conservative autonomous sign-off decision derived from proof evidence",
    )
    final_state_hash: str = Field(default="", description="Final approved design state hash")
    transaction_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Transaction history evidence for the final state",
    )

    # --- v2 evidence fields: decision & evidence graph ---
    captured_intent: str = Field(
        default="",
        description="Original natural-language design intent verbatim, before normalization",
    )
    agent_decisions: list[AgentDecisionRecord] = Field(
        default_factory=list,
        description="Agent and human decisions captured during the design process",
    )

    limitations: list[str] = Field(
        default_factory=lambda: [
            "Human engineer review is required before fabrication.",
            "ZapTrace is pre-1.0 software — outputs are experimental.",
            "Proof Pack is evidence, not a fabrication guarantee.",
            "KiCad oracle results are external validation, not absolute correctness.",
            "Fab profiles are constraints, not manufacturer approval.",
        ],
        description="List of limitations and warnings accompanying this proof pack",
    )
