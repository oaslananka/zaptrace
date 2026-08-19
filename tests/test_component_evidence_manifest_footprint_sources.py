from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from tests.test_component_evidence_manifest import _entry, _verified_spec, _write_proof
from zaptrace.library.evidence_manifest import (
    ComponentEvidenceManifest,
    validate_component_evidence_manifest,
)


def _manifest_for_proof(proof: Path) -> ComponentEvidenceManifest:
    entry = _entry(
        footprint_proof={
            "proof_path": "evidence/footprints/acme-ldo.json",
            "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "artifact_id": "datasheet-rev4",
        }
    )
    return ComponentEvidenceManifest.model_validate({"schema_version": "1.0", "components": {"acme-ldo": entry}})


def _bind_vendored_source(proof: Path, source: Path) -> None:
    payload = json.loads(proof.read_text(encoding="utf-8"))
    payload["source"]["source_type"] = "vendored"
    payload["source"]["source_name"] = "acme-land-pattern"
    payload["source"]["source_path"] = "data/footprints/vendor/acme.kicad_mod"
    payload["source"]["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    payload["source"]["attribution"] = "data/footprints/vendor/ATTRIBUTION.md"
    proof.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_verified_footprint_field_and_vendored_proof_use_distinct_hashes(tmp_path: Path) -> None:
    source = tmp_path / "data" / "footprints" / "vendor" / "acme.kicad_mod"
    source.parent.mkdir(parents=True)
    source.write_text("(footprint acme)\n", encoding="utf-8")
    proof = _write_proof(tmp_path, source_sha256="0" * 64)
    _bind_vendored_source(proof, source)
    manifest = _manifest_for_proof(proof)

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is True
    assert report.violations == []


def test_vendored_footprint_source_hash_mismatch_is_blocked(tmp_path: Path) -> None:
    source = tmp_path / "data" / "footprints" / "vendor" / "acme.kicad_mod"
    source.parent.mkdir(parents=True)
    source.write_text("(footprint acme)\n", encoding="utf-8")
    proof = _write_proof(tmp_path, source_sha256="0" * 64)
    _bind_vendored_source(proof, source)
    source.write_text("(footprint changed)\n", encoding="utf-8")
    manifest = _manifest_for_proof(proof)

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert report.passed is False
    assert [violation.code for violation in report.violations] == ["footprint-proof-source-hash-mismatch"]


def test_vendored_footprint_without_source_path_is_blocked(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path)
    payload = json.loads(proof.read_text(encoding="utf-8"))
    payload["source"]["source_type"] = "vendored"
    payload["source"]["source_path"] = ""
    proof.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = _manifest_for_proof(proof)

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert [violation.code for violation in report.violations] == ["footprint-proof-source-unavailable"]
    assert "requires a repository source path" in report.violations[0].message


def test_missing_vendored_footprint_source_is_blocked(tmp_path: Path) -> None:
    proof = _write_proof(tmp_path)
    payload = json.loads(proof.read_text(encoding="utf-8"))
    payload["source"]["source_type"] = "vendored"
    payload["source"]["source_path"] = "data/footprints/vendor/missing.kicad_mod"
    payload["source"]["source_sha256"] = "a" * 64
    proof.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = _manifest_for_proof(proof)

    report = validate_component_evidence_manifest(
        {"acme-ldo": _verified_spec()},
        manifest,
        repository_root=tmp_path,
        as_of=date(2026, 8, 9),
    )

    assert [violation.code for violation in report.violations] == ["footprint-proof-source-unavailable"]
    assert "missing.kicad_mod" in report.violations[0].message
