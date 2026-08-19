"""Machine-readable manufacturer-aware DFM readiness reports."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.fab.dfm import DFMCheckResult, DFMReadinessStatus
from zaptrace.fab.profile import FabProfile


class DFMApprovedSkip(BaseModel):
    """One explicitly approved DFM skip."""

    model_config = ConfigDict(strict=False)

    rule_id: str
    reason: str
    approval_id: str


class DFMReadinessReport(BaseModel):
    """Profile-bound readiness evidence for one manufacturing bundle."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    design_name: str
    generated_at: str
    status: DFMReadinessStatus
    blocks_autonomous_release: bool
    profile: dict[str, str] = Field(default_factory=dict)
    violations: list[dict[str, str]] = Field(default_factory=list)
    approved_skips: list[DFMApprovedSkip] = Field(default_factory=list)
    human_review_reasons: list[str] = Field(default_factory=list)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "This DFM report is evidence, not manufacturer approval.",
            "Assembly capability data must be independently verified before ordering.",
            "Human engineering review remains required for unsupported or unmodeled constraints.",
        ]
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_dfm_readiness_report(
    design_name: str,
    artifact_paths: list[Path],
    *,
    profile: FabProfile | None = None,
    result: DFMCheckResult | None = None,
    approved_skip_reason: str = "",
    approved_skip_id: str = "",
) -> DFMReadinessReport:
    """Build a deterministic readiness report from profile checks and artifacts."""
    approved_skips: list[DFMApprovedSkip] = []
    human_review_reasons: list[str] = []
    violations: list[dict[str, str]] = []
    profile_identity: dict[str, str] = {}

    if profile is not None:
        profile_identity = profile.identity()
    if result is not None:
        status = result.readiness_status
        violations = result.to_dict()["violations"]
        human_review_reasons = [
            violation.message for violation in result.violations if violation.severity == "human-review-required"
        ]
    elif approved_skip_reason.strip() and approved_skip_id.strip():
        status = DFMReadinessStatus.APPROVED_SKIP
        approved_skips.append(
            DFMApprovedSkip(
                rule_id="manufacturer-profile",
                reason=approved_skip_reason.strip(),
                approval_id=approved_skip_id.strip(),
            )
        )
    else:
        status = DFMReadinessStatus.HUMAN_REVIEW_REQUIRED
        human_review_reasons.append("No manufacturer fabrication profile was selected.")

    artifact_hashes = {
        path.name: _hash_file(path) for path in sorted(artifact_paths, key=lambda item: item.name) if path.is_file()
    }
    return DFMReadinessReport(
        design_name=design_name,
        generated_at=datetime.now(UTC).isoformat(),
        status=status,
        blocks_autonomous_release=status in {DFMReadinessStatus.HARD_FAIL, DFMReadinessStatus.HUMAN_REVIEW_REQUIRED},
        profile=profile_identity,
        violations=violations,
        approved_skips=approved_skips,
        human_review_reasons=human_review_reasons,
        artifact_hashes=artifact_hashes,
    )


def require_dfm_release_ready(status: str, *, report_path: str = "") -> None:
    """Fail closed when a manufacturing readiness result blocks release."""
    normalized = status.strip().lower()
    if normalized in {
        DFMReadinessStatus.PASS.value,
        DFMReadinessStatus.WARNING.value,
        DFMReadinessStatus.APPROVED_SKIP.value,
    }:
        return
    location = f"; report={report_path}" if report_path else ""
    raise ValueError(f"manufacturing release blocked by DFM readiness status={normalized or 'missing'}{location}")


__all__ = [
    "DFMApprovedSkip",
    "DFMReadinessReport",
    "DFMReadinessStatus",
    "build_dfm_readiness_report",
    "require_dfm_release_ready",
]
