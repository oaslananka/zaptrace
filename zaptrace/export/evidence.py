"""Manufacturing evidence adapters for generated fabrication artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.evidence.identity import EvidenceIdentity, EvidenceMode, capture_evidence_identity
from zaptrace.export.gerber import validate_gerber_x2_attributes
from zaptrace.fab.dfm import DFMCheckResult


class ManufacturingArtifactKind(StrEnum):
    GERBER = "gerber"
    EXCELLON = "excellon"
    ODBPP = "odbpp"
    IPC2581 = "ipc2581"
    MECHANICAL_REVIEW = "mechanical_review"
    BOM = "bom"
    PICK_AND_PLACE = "pick_and_place"
    STACKUP = "stackup"
    MANIFEST = "manifest"
    GERBER_JOB = "gerber_job"
    BUNDLE = "bundle"
    DFM_REPORT = "dfm_report"
    OTHER = "other"


class ManufacturingValidationStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    SKIPPED = "skipped"
    APPROVED_SKIP = "approved-skip"
    HUMAN_REVIEW_REQUIRED = "human-review-required"


class ManufacturingArtifactEvidence(BaseModel):
    """Hashed manufacturing artifact record."""

    model_config = ConfigDict(strict=False)

    path: str
    kind: ManufacturingArtifactKind
    size_bytes: int = Field(ge=0)
    sha256: str
    role: str = ""
    required: bool = True


class ManufacturingValidationEvidence(BaseModel):
    """Smoke/parser/profile validation result for manufacturing evidence."""

    model_config = ConfigDict(strict=False)

    name: str
    status: ManufacturingValidationStatus
    severity: str = "error"
    release_blocking: bool = True
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def blocks_release(self) -> bool:
        return self.release_blocking and self.status in {
            ManufacturingValidationStatus.FAIL,
            ManufacturingValidationStatus.HUMAN_REVIEW_REQUIRED,
        }


class ManufacturingEvidenceBundle(BaseModel):
    """Machine-readable manufacturing evidence bundle."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "2.1"
    generated_at: str
    evidence_identity: EvidenceIdentity
    fab_profile: str
    fab_profile_version: str = ""
    fab_profile_sha256: str = ""
    readiness_status: str = "human-review-required"
    readiness_report_sha256: str = ""
    blocked: bool
    artifacts: list[ManufacturingArtifactEvidence]
    validations: list[ManufacturingValidationEvidence]
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "Manufacturing evidence is not manufacturer approval.",
            "External fabrication review is required before ordering boards.",
            "Smoke validation checks file shape, not full DFM correctness.",
        ]
    )


class ManufacturingEvidenceAdapter(Protocol):
    """Adapter interface for manufacturing evidence collection."""

    name: str

    def collect(
        self,
        root: Path,
        *,
        fab_profile: str = "",
        dfm_result: DFMCheckResult | None = None,
        evidence_identity: EvidenceIdentity | None = None,
    ) -> ManufacturingEvidenceBundle:
        """Collect evidence for artifacts under *root*."""
        ...


_GERBER_SUFFIXES = {".GTL", ".GBL", ".GTO", ".GTS", ".GBS", ".GKO", ".GPT", ".GTP", ".GBP"}
_EXCELLON_SUFFIXES = {".DRL", ".TXT", ".XLN"}
_SUFFIX_ARTIFACT_KINDS = {
    ".GBRJOB": ManufacturingArtifactKind.GERBER_JOB,
    ".ZIP": ManufacturingArtifactKind.BUNDLE,
}
_ODBPP_SUFFIXES = {".ODB", ".ODBPP", ".TGZ"}
_IPC2581_SUFFIXES = {".IPC2581", ".XML"}
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_MANUFACTURING_IDENTITY_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "zaptrace/export/evidence.py",
    "zaptrace/export/manufacturing.py",
    "zaptrace/export/gerber.py",
    "zaptrace/export/excellon.py",
)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_artifact_kind(lower_name: str) -> ManufacturingArtifactKind | None:
    if "pick" in lower_name:
        return ManufacturingArtifactKind.PICK_AND_PLACE
    if "bom" in lower_name:
        return ManufacturingArtifactKind.BOM
    return None


def _json_artifact_kind(lower_name: str) -> ManufacturingArtifactKind | None:
    if "dfm-readiness" in lower_name:
        return ManufacturingArtifactKind.DFM_REPORT
    if "manifest" in lower_name:
        return ManufacturingArtifactKind.MANIFEST
    return None


def _named_artifact_kind(suffix: str, lower_name: str) -> ManufacturingArtifactKind | None:
    if suffix == ".CSV":
        return _csv_artifact_kind(lower_name)
    if suffix == ".JSON":
        return _json_artifact_kind(lower_name)
    if suffix in _ODBPP_SUFFIXES or "odb" in lower_name:
        return ManufacturingArtifactKind.ODBPP
    if suffix == ".GLB":
        return ManufacturingArtifactKind.MECHANICAL_REVIEW
    if suffix in _IPC2581_SUFFIXES and ("ipc" in lower_name or "2581" in lower_name):
        return ManufacturingArtifactKind.IPC2581
    if "stackup" in lower_name:
        return ManufacturingArtifactKind.STACKUP
    return None


def classify_manufacturing_artifact(path: Path) -> ManufacturingArtifactKind:
    suffix = path.suffix.upper()
    if suffix in _GERBER_SUFFIXES:
        return ManufacturingArtifactKind.GERBER
    if suffix in _EXCELLON_SUFFIXES:
        return ManufacturingArtifactKind.EXCELLON
    named = _named_artifact_kind(suffix, path.name.lower())
    if named is not None:
        return named
    if suffix in _SUFFIX_ARTIFACT_KINDS:
        return _SUFFIX_ARTIFACT_KINDS[suffix]
    return ManufacturingArtifactKind.OTHER


def build_artifact_evidence(path: Path, *, root: Path) -> ManufacturingArtifactEvidence:
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        relative = resolved.relative_to(root_resolved)
    except ValueError:
        relative = resolved
    return ManufacturingArtifactEvidence(
        path=relative.as_posix(),
        kind=classify_manufacturing_artifact(path),
        size_bytes=path.stat().st_size,
        sha256=hash_file(path),
        role=path.suffix.lstrip(".").lower(),
    )


def smoke_validate_gerber(path: Path) -> ManufacturingValidationEvidence:
    text = path.read_text(encoding="utf-8", errors="replace")
    required_tokens = ["MOMM", "FSLAX", "M02*"]
    missing = [token for token in required_tokens if token not in text]
    status = ManufacturingValidationStatus.FAIL if missing else ManufacturingValidationStatus.PASS
    return ManufacturingValidationEvidence(
        name=f"gerber-smoke:{path.name}",
        status=status,
        summary="Gerber smoke validation passed" if not missing else "Gerber file is missing required tokens",
        details={"missing_tokens": missing, "size_bytes": path.stat().st_size},
    )


def smoke_validate_excellon(path: Path) -> ManufacturingValidationEvidence:
    text = path.read_text(encoding="utf-8", errors="replace")
    required_tokens = ["M48", "M30"]
    missing = [token for token in required_tokens if token not in text]
    status = ManufacturingValidationStatus.FAIL if missing else ManufacturingValidationStatus.PASS
    return ManufacturingValidationEvidence(
        name=f"excellon-smoke:{path.name}",
        status=status,
        summary="Excellon smoke validation passed" if not missing else "Excellon file is missing required tokens",
        details={"missing_tokens": missing, "size_bytes": path.stat().st_size},
    )


def validate_gerber_x2_file(path: Path) -> ManufacturingValidationEvidence:
    """Validate required Gerber X2 attributes for one Gerber artifact."""
    result = validate_gerber_x2_attributes(path.read_text(encoding="utf-8", errors="replace"))
    raw_missing = result.get("missing_attributes", [])
    missing = [str(item) for item in raw_missing] if isinstance(raw_missing, list) else []
    status = ManufacturingValidationStatus.FAIL if missing else ManufacturingValidationStatus.PASS
    return ManufacturingValidationEvidence(
        name=f"gerber-x2:{path.name}",
        status=status,
        summary=(
            "Gerber X2 attributes present" if not missing else "Gerber file is missing required X2 fabrication metadata"
        ),
        details={"missing_attributes": missing, "size_bytes": path.stat().st_size},
    )


def validate_gerber_job_file(path: Path) -> ManufacturingValidationEvidence:
    """Validate the Gerber Job File shape."""
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return ManufacturingValidationEvidence(
            name=f"gerber-job:{path.name}",
            status=ManufacturingValidationStatus.FAIL,
            summary="Gerber Job File is not valid JSON",
            details={"error": str(exc)},
        )
    missing = [field for field in ("format", "files", "board") if field not in data]
    if not data.get("files"):
        missing.append("files[]")
    status = ManufacturingValidationStatus.FAIL if missing else ManufacturingValidationStatus.PASS
    return ManufacturingValidationEvidence(
        name=f"gerber-job:{path.name}",
        status=status,
        summary="Gerber Job File validation passed" if not missing else "Gerber Job File is missing required metadata",
        details={
            "missing_fields": missing,
            "file_count": len(data.get("files", [])) if isinstance(data.get("files"), list) else 0,
        },
    )


def validation_from_dfm_result(result: DFMCheckResult) -> ManufacturingValidationEvidence:
    if result.errors:
        status = ManufacturingValidationStatus.FAIL
        summary = f"Fab profile {result.profile_name} has {result.errors} blocking error(s)"
    elif result.human_reviews:
        status = ManufacturingValidationStatus.HUMAN_REVIEW_REQUIRED
        summary = f"Fab profile {result.profile_name} requires {result.human_reviews} human review item(s)"
    elif result.approved_skips:
        status = ManufacturingValidationStatus.APPROVED_SKIP
        summary = f"Fab profile {result.profile_name} has {result.approved_skips} approved skip(s)"
    elif result.warnings:
        status = ManufacturingValidationStatus.WARNING
        summary = f"Fab profile {result.profile_name} has {result.warnings} warning(s)"
    else:
        status = ManufacturingValidationStatus.PASS
        summary = f"Fab profile {result.profile_name} passed"
    return ManufacturingValidationEvidence(
        name="fab-profile-dfm",
        status=status,
        severity="error" if result.errors else "warning",
        release_blocking=True,
        summary=summary,
        details=result.to_dict(),
    )


def _read_dfm_readiness_report(path: Path) -> dict[str, Any]:
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _readiness_validation(report: dict[str, Any]) -> ManufacturingValidationEvidence:
    status_value = str(report.get("status") or "human-review-required")
    status = {
        "pass": ManufacturingValidationStatus.PASS,
        "warning": ManufacturingValidationStatus.WARNING,
        "hard-fail": ManufacturingValidationStatus.FAIL,
        "approved-skip": ManufacturingValidationStatus.APPROVED_SKIP,
        "human-review-required": ManufacturingValidationStatus.HUMAN_REVIEW_REQUIRED,
    }.get(status_value, ManufacturingValidationStatus.HUMAN_REVIEW_REQUIRED)
    return ManufacturingValidationEvidence(
        name="dfm-readiness-report",
        status=status,
        severity="error" if status == ManufacturingValidationStatus.FAIL else "warning",
        release_blocking=True,
        summary=f"Manufacturer-aware DFM readiness status: {status_value}",
        details=report,
    )


@dataclass
class _ReadinessMetadata:
    profile_name: str = ""
    profile_version: str = ""
    profile_sha256: str = ""
    status: str = "human-review-required"
    report_sha256: str = ""


def _artifact_validations(
    path: Path,
    artifact: ManufacturingArtifactEvidence,
) -> list[ManufacturingValidationEvidence]:
    if artifact.kind == ManufacturingArtifactKind.GERBER:
        return [smoke_validate_gerber(path), validate_gerber_x2_file(path)]
    if artifact.kind == ManufacturingArtifactKind.GERBER_JOB:
        return [validate_gerber_job_file(path)]
    if artifact.kind == ManufacturingArtifactKind.EXCELLON:
        return [smoke_validate_excellon(path)]
    if artifact.kind == ManufacturingArtifactKind.DFM_REPORT:
        return [_readiness_validation(_read_dfm_readiness_report(path))]
    return []


def _metadata_from_report(
    path: Path,
    artifact: ManufacturingArtifactEvidence,
    current: _ReadinessMetadata,
) -> _ReadinessMetadata:
    report = _read_dfm_readiness_report(path)
    raw_profile = report.get("profile")
    profile: dict[str, Any] = raw_profile if isinstance(raw_profile, dict) else {}
    return _ReadinessMetadata(
        profile_name=str(profile.get("name") or current.profile_name),
        profile_version=str(profile.get("version") or ""),
        profile_sha256=str(profile.get("sha256") or ""),
        status=str(report.get("status") or current.status),
        report_sha256=artifact.sha256,
    )


def _metadata_with_dfm_fallback(
    metadata: _ReadinessMetadata,
    result: DFMCheckResult | None,
) -> _ReadinessMetadata:
    if result is None or metadata.profile_name:
        return metadata
    return _ReadinessMetadata(
        profile_name=result.profile_name,
        profile_version=result.profile_version,
        profile_sha256=result.profile_sha256,
        status=result.readiness_status.value,
        report_sha256=metadata.report_sha256,
    )


class DirectoryManufacturingEvidenceAdapter:
    """Collect evidence by scanning a manufacturing output directory."""

    name = "directory-manufacturing-evidence"

    def collect(
        self,
        root: Path,
        *,
        fab_profile: str = "",
        dfm_result: DFMCheckResult | None = None,
        evidence_identity: EvidenceIdentity | None = None,
    ) -> ManufacturingEvidenceBundle:
        identity = evidence_identity or capture_evidence_identity(
            root=_REPOSITORY_ROOT,
            mode=EvidenceMode.SNAPSHOT,
            source_inputs=_MANUFACTURING_IDENTITY_INPUTS,
        )
        artifacts: list[ManufacturingArtifactEvidence] = []
        validations: list[ManufacturingValidationEvidence] = []
        metadata = _ReadinessMetadata(profile_name=fab_profile)
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            artifact = build_artifact_evidence(path, root=root)
            artifacts.append(artifact)
            validations.extend(_artifact_validations(path, artifact))
            if artifact.kind == ManufacturingArtifactKind.DFM_REPORT:
                metadata = _metadata_from_report(path, artifact, metadata)
        if dfm_result is not None:
            validations.append(validation_from_dfm_result(dfm_result))
        metadata = _metadata_with_dfm_fallback(metadata, dfm_result)
        return ManufacturingEvidenceBundle(
            generated_at=identity.generated_at,
            evidence_identity=identity,
            fab_profile=metadata.profile_name,
            fab_profile_version=metadata.profile_version,
            fab_profile_sha256=metadata.profile_sha256,
            readiness_status=metadata.status,
            readiness_report_sha256=metadata.report_sha256,
            blocked=any(validation.blocks_release for validation in validations),
            artifacts=artifacts,
            validations=validations,
        )


def collect_manufacturing_evidence(
    root: str | Path,
    *,
    fab_profile: str = "",
    dfm_result: DFMCheckResult | None = None,
    evidence_identity: EvidenceIdentity | None = None,
) -> ManufacturingEvidenceBundle:
    adapter = DirectoryManufacturingEvidenceAdapter()
    return adapter.collect(
        Path(root),
        fab_profile=fab_profile,
        dfm_result=dfm_result,
        evidence_identity=evidence_identity,
    )
