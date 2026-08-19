from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.test_component_evidence_manifest import (
    _artifact,
    _entry,
    _verified_spec,
    _write_proof,
)
from zaptrace.library.evidence_manifest import (
    ComponentEvidenceManifest,
    load_component_evidence_manifest,
    validate_component_evidence_manifest,
)
from zaptrace.library.schema import ComponentField


def test_artifact_rejects_invalid_validity_window() -> None:
    payload = _artifact("datasheet-rev4", valid_until="2026-07-31")

    with pytest.raises(ValidationError, match="valid_until"):
        ComponentEvidenceManifest.model_validate(
            {
                "schema_version": "1.0",
                "components": {"acme-ldo": _entry(artifacts={"datasheet-rev4": payload})},
            }
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("trust-tier", "verified trust tier"),
        ("artifact-key", "does not match artifact_id"),
        ("unknown-field-artifact", "unknown artifacts"),
        ("unknown-footprint-artifact", "footprint proof references unknown artifact"),
        ("missing-review-scope", "release and fabrication scopes"),
    ],
)
def test_entry_rejects_inconsistent_contract(mutation: str, message: str) -> None:
    entry = _entry()
    if mutation == "trust-tier":
        entry["trust_tier"] = "curated"
    elif mutation == "artifact-key":
        entry["artifacts"]["datasheet-rev4"]["artifact_id"] = "other"
    elif mutation == "unknown-field-artifact":
        entry["field_artifacts"][ComponentField.PIN_MAP.value] = "missing"
    elif mutation == "unknown-footprint-artifact":
        entry["footprint_proof"]["artifact_id"] = "missing"
    else:
        entry["review"]["scopes"] = ["release"]

    with pytest.raises(ValidationError, match=message):
        ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})


def test_manifest_rejects_component_key_mismatch() -> None:
    with pytest.raises(ValidationError, match="component key"):
        ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"other": _entry()}})


def test_manifest_loader_rejects_symlink_non_json_directory_and_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "manifest.json"
    target.write_text('{"schema_version":"1.0","components":{}}\n', encoding="utf-8")
    symlink = root / "link.json"
    symlink.symlink_to(target)
    with pytest.raises(ValueError, match="symbolic link"):
        load_component_evidence_manifest(symlink, allowed_root=root)

    text = root / "manifest.txt"
    text.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be JSON"):
        load_component_evidence_manifest(text, allowed_root=root)

    directory = root / "directory.json"
    directory.mkdir()
    with pytest.raises(ValueError, match="not a regular file"):
        load_component_evidence_manifest(directory, allowed_root=root)

    outside = tmp_path / "outside.json"
    outside.write_text('{"schema_version":"1.0","components":{}}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="outside allowed root"):
        load_component_evidence_manifest(outside, allowed_root=root)


def test_manifest_reports_missing_field_provenance(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path)
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    spec = _verified_spec()
    del spec.field_provenance[ComponentField.PIN_MAP]
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": spec}, manifest, repository_root=tmp_path, as_of=date(2026, 8, 9)
    )

    assert [(item.code, item.field) for item in report.violations] == [("field-provenance-missing", "pin_map")]


def test_manifest_reports_unavailable_and_invalid_footprint_proof(tmp_path: Path) -> None:
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/missing.json",
            "proof_sha256": "c" * 64,
            "artifact_id": "datasheet-rev4",
        }
    )
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})
    unavailable = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )
    assert [item.code for item in unavailable.violations] == ["footprint-proof-unavailable"]

    proof = tmp_path / "evidence" / "footprints" / "invalid.json"
    proof.parent.mkdir(parents=True, exist_ok=True)
    proof.write_text('{"not":"a-footprint-proof"}\n', encoding="utf-8")
    entry["footprint_proof"]["proof_path"] = "evidence/footprints/invalid.json"
    entry["footprint_proof"]["proof_sha256"] = hashlib.sha256(proof.read_bytes()).hexdigest()
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})
    invalid = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )
    assert [item.code for item in invalid.violations] == ["footprint-proof-invalid"]


def test_manifest_rejects_symlinked_footprint_proof(tmp_path: Path) -> None:
    target = _write_proof(tmp_path)
    symlink = target.with_name("proof-link.json")
    symlink.symlink_to(target)
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/proof-link.json",
            "proof_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert [item.code for item in report.violations] == ["footprint-proof-unavailable"]
    assert "symbolic link" in report.violations[0].message


def test_manifest_reports_entry_for_missing_component(tmp_path: Path) -> None:
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": _entry()}})

    report = validate_component_evidence_manifest({}, manifest, repository_root=tmp_path, as_of=date(2026, 8, 9))

    assert [item.code for item in report.violations] == ["component-not-found"]


def test_manifest_rejects_footprint_proof_outside_repository(tmp_path: Path) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    outside = tmp_path / "outside-proof.json"
    outside.write_text('{"schema_version":"1.0"}\n', encoding="utf-8")
    entry = _entry(
        footprint_proof={
            "proof_path": str(outside),
            "proof_sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    manifest = ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=repository_root,
        as_of=date(2026, 8, 9),
    )

    assert [item.code for item in report.violations] == ["footprint-proof-unavailable"]
    assert "outside repository root" in report.violations[0].message
