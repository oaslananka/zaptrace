"""Digest-bound captures for mutable authoritative web evidence.

A source capture records bounded claims observed on a mutable manufacturer or
authorized-distributor page. It is not a hash of the remote HTTP response and
does not replace human review. The committed JSON file itself is SHA-bound by
``FieldProvenance.source_capture_sha256``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from zaptrace.library.schema import ComponentField, ProvenanceSourceType, StrictSchemaModel

_MUTABLE_SOURCE_TYPES = {
    ProvenanceSourceType.MANUFACTURER_WEB,
    ProvenanceSourceType.AUTHORIZED_DISTRIBUTOR,
}


class MutableWebClaim(StrictSchemaModel):
    """One bounded claim extracted from a mutable authoritative web source."""

    claim: str = Field(min_length=1)
    value: str = Field(min_length=1)


class MutableWebEvidenceCapture(StrictSchemaModel):
    """Canonical repository snapshot of claims observed on one mutable page."""

    schema_version: Literal["1.0"] = "1.0"
    component_id: str = Field(min_length=1)
    source_type: ProvenanceSourceType
    source_locator: str = Field(min_length=1)
    source_identity: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    captured_at: date
    claims: dict[ComponentField, MutableWebClaim] = Field(min_length=1)
    non_claims: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mutable_source(self) -> MutableWebEvidenceCapture:
        if self.source_type not in _MUTABLE_SOURCE_TYPES:
            raise ValueError("web evidence capture requires manufacturer_web or authorized_distributor source")
        return self


def _capture_path(path: str, *, repository_root: Path) -> Path:
    root = repository_root.resolve(strict=True)
    candidate = repository_root / path
    if candidate.is_symlink():
        raise ValueError(f"source capture must not be a symbolic link: {path}")
    resolved = candidate.resolve(strict=True)
    if resolved.suffix.lower() != ".json":
        raise ValueError(f"source capture must be JSON: {path}")
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError(f"source capture is outside repository root or not a regular file: {path}")
    return resolved


def load_mutable_web_evidence_capture(
    path: str,
    *,
    repository_root: Path,
) -> tuple[MutableWebEvidenceCapture, str]:
    """Load one safe repository-local capture and return it with its file digest."""

    resolved = _capture_path(path, repository_root=repository_root)
    payload = resolved.read_bytes()
    capture = MutableWebEvidenceCapture.model_validate(json.loads(payload))
    return capture, hashlib.sha256(payload).hexdigest()


def mutable_web_claim_value(spec: Any, field_name: ComponentField) -> str:
    """Return the canonical component value a mutable-web capture must support."""

    if field_name is ComponentField.LIFECYCLE:
        return str(getattr(spec, "lifecycle", ""))
    if field_name is ComponentField.SOURCING:
        sourcing = getattr(spec, "sourcing", {})
        if isinstance(sourcing, dict):
            return str(sourcing.get("status", ""))
        return str(getattr(sourcing, "status", ""))
    raise ValueError(f"mutable web capture is not supported for {field_name.value}")


def validate_mutable_web_capture_binding(
    *,
    component_id: str,
    field_name: ComponentField,
    evidence_source_type: ProvenanceSourceType,
    source_locator: str,
    source_identity: str,
    source_version: str,
    extracted_at: date | None,
    capture_path: str,
    capture_sha256: str,
    repository_root: Path,
    expected_claim_value: str,
) -> list[tuple[str, str]]:
    """Return deterministic ``(code, message)`` violations for one capture binding."""

    if evidence_source_type not in _MUTABLE_SOURCE_TYPES:
        return [
            ("field-source-capture-not-allowed", "source capture is only valid for mutable authoritative web sources")
        ]
    if field_name not in {ComponentField.LIFECYCLE, ComponentField.SOURCING}:
        return [
            (
                "field-source-capture-field-not-supported",
                "mutable web capture is only supported for lifecycle or sourcing evidence",
            )
        ]
    if not capture_path or not capture_sha256:
        return [("field-source-hash-missing", "authoritative source has neither a raw SHA-256 nor a capture binding")]
    try:
        capture, observed_digest = load_mutable_web_evidence_capture(capture_path, repository_root=repository_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [("field-source-capture-invalid", str(exc))]
    if observed_digest != capture_sha256:
        return [
            ("field-source-capture-hash-mismatch", "source capture digest does not match the committed capture file")
        ]
    comparisons = (
        (capture.component_id == component_id, "component id"),
        (capture.source_type is evidence_source_type, "source type"),
        (capture.source_locator == source_locator, "source locator"),
        (capture.source_identity == source_identity, "source identity"),
        (capture.source_version == source_version, "source version"),
        (capture.captured_at == extracted_at, "capture date"),
    )
    mismatches = [label for matches, label in comparisons if not matches]
    if mismatches:
        return [
            (
                "field-source-capture-metadata-mismatch",
                "source capture does not match field provenance: " + ", ".join(mismatches),
            )
        ]
    if field_name not in capture.claims:
        return [("field-source-capture-claim-missing", "source capture has no claim for this critical field")]
    if capture.claims[field_name].value != expected_claim_value:
        return [
            (
                "field-source-capture-claim-mismatch",
                "source capture claim does not match the committed component field value",
            )
        ]
    return []
