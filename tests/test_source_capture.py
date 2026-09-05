from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from zaptrace.library.schema import ComponentField, ProvenanceSourceType
from zaptrace.library.source_capture import validate_mutable_web_capture_binding


def _capture(tmp_path: Path, **overrides: object) -> tuple[str, str]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "component_id": "part-1",
        "source_type": "manufacturer_web",
        "source_locator": "https://manufacturer.example/part-1",
        "source_identity": "manufacturer:part-1",
        "source_version": "captured-2026-09-05",
        "captured_at": "2026-09-05",
        "claims": {"lifecycle": {"claim": "product_status", "value": "active"}},
        "non_claims": ["human review required"],
    }
    payload.update(overrides)
    relative_path = "evidence/web/part-1.json"
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return relative_path, hashlib.sha256(path.read_bytes()).hexdigest()


def _validate(tmp_path: Path, path: str, digest: str, **overrides: object) -> list[tuple[str, str]]:
    arguments: dict[str, object] = {
        "component_id": "part-1",
        "field_name": ComponentField.LIFECYCLE,
        "evidence_source_type": ProvenanceSourceType.MANUFACTURER_WEB,
        "source_locator": "https://manufacturer.example/part-1",
        "source_identity": "manufacturer:part-1",
        "source_version": "captured-2026-09-05",
        "extracted_at": date(2026, 9, 5),
        "capture_path": path,
        "capture_sha256": digest,
        "repository_root": tmp_path,
        "expected_claim_value": "active",
    }
    arguments.update(overrides)
    return validate_mutable_web_capture_binding(**arguments)  # type: ignore[arg-type]


def test_mutable_web_capture_binding_accepts_exact_digest_metadata_and_claim(tmp_path: Path) -> None:
    path, digest = _capture(tmp_path)

    assert _validate(tmp_path, path, digest) == []


def test_mutable_web_capture_binding_rejects_digest_mismatch(tmp_path: Path) -> None:
    path, _ = _capture(tmp_path)

    violations = _validate(tmp_path, path, "0" * 64)

    assert [code for code, _ in violations] == ["field-source-capture-hash-mismatch"]


def test_mutable_web_capture_binding_rejects_metadata_mismatch(tmp_path: Path) -> None:
    path, digest = _capture(tmp_path, source_identity="manufacturer:other-part")

    violations = _validate(tmp_path, path, digest)

    assert [code for code, _ in violations] == ["field-source-capture-metadata-mismatch"]


def test_mutable_web_capture_binding_rejects_claim_mismatch(tmp_path: Path) -> None:
    path, digest = _capture(
        tmp_path,
        claims={"lifecycle": {"claim": "product_status", "value": "obsolete"}},
    )

    violations = _validate(tmp_path, path, digest)

    assert [code for code, _ in violations] == ["field-source-capture-claim-mismatch"]


def test_mutable_web_capture_binding_is_limited_to_lifecycle_and_sourcing(tmp_path: Path) -> None:
    path, digest = _capture(tmp_path)

    violations = _validate(tmp_path, path, digest, field_name=ComponentField.MPN)

    assert [code for code, _ in violations] == ["field-source-capture-field-not-supported"]
