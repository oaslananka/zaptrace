"""Tests for normalized Cargo advisory evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import ci_cargo_audit


def _write_lock(path: Path) -> None:
    path.write_text('version = 4\n\n[[package]]\nname = "demo"\nversion = "1.0.0"\n', encoding="utf-8")


def test_clean_report_passes_and_records_identity(tmp_path: Path) -> None:
    lockfile = tmp_path / "Cargo.lock"
    _write_lock(lockfile)
    raw = {
        "vulnerabilities": {"found": False, "count": 0, "list": []},
        "warnings": {},
    }

    report = ci_cargo_audit.normalize_report(raw, lockfile, "cargo-audit 0.22.2", tmp_path)

    assert report["schema_version"] == 1
    assert report["status"] == "pass"
    assert report["vulnerability_count"] == 0
    assert report["warning_count"] == 0
    assert report["cargo_audit_version"] == "cargo-audit 0.22.2"
    assert report["cargo_lock_sha256"] == hashlib.sha256(lockfile.read_bytes()).hexdigest()
    assert report["advisory_ids"] == []
    assert len(report["evidence_digest"]) == 64


def test_vulnerability_report_fails_and_lists_advisories(tmp_path: Path) -> None:
    lockfile = tmp_path / "Cargo.lock"
    _write_lock(lockfile)
    raw = {
        "vulnerabilities": {
            "found": True,
            "count": 2,
            "list": [
                {"advisory": {"id": "RUSTSEC-2026-0001"}},
                {"advisory": {"id": "RUSTSEC-2026-0002"}},
            ],
        },
        "warnings": {},
    }

    report = ci_cargo_audit.normalize_report(raw, lockfile, "cargo-audit 0.22.2", tmp_path)

    assert report["status"] == "fail"
    assert report["vulnerability_count"] == 2
    assert report["advisory_ids"] == ["RUSTSEC-2026-0001", "RUSTSEC-2026-0002"]


def test_warnings_are_counted_without_failing_clean_audit(tmp_path: Path) -> None:
    lockfile = tmp_path / "Cargo.lock"
    _write_lock(lockfile)
    raw = {
        "vulnerabilities": {"found": False, "count": 0, "list": []},
        "warnings": {
            "unmaintained": [{"package": {"name": "legacy"}}],
            "yanked": [{"package": {"name": "old"}}, {"package": {"name": "older"}}],
        },
    }

    report = ci_cargo_audit.normalize_report(raw, lockfile, "cargo-audit 0.22.2", tmp_path)

    assert report["status"] == "pass"
    assert report["warning_count"] == 3
    assert report["warning_categories"] == {"unmaintained": 1, "yanked": 2}


def test_invalid_json_fails_closed(tmp_path: Path) -> None:
    raw_path = tmp_path / "cargo-audit.json"
    raw_path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ci_cargo_audit.CargoAuditEvidenceError, match="valid JSON"):
        ci_cargo_audit.load_raw_report(raw_path, tmp_path)


def test_strict_exit_behavior() -> None:
    assert ci_cargo_audit.exit_code({"status": "pass"}, strict=True) == 0
    assert ci_cargo_audit.exit_code({"status": "fail"}, strict=True) == 1
    assert ci_cargo_audit.exit_code({"status": "fail"}, strict=False) == 0


def test_cli_writes_normalized_evidence(tmp_path: Path) -> None:
    lockfile = tmp_path / "Cargo.lock"
    _write_lock(lockfile)
    raw_path = tmp_path / "cargo-audit.json"
    raw_path.write_text(
        json.dumps({"vulnerabilities": {"found": False, "count": 0, "list": []}, "warnings": {}}),
        encoding="utf-8",
    )
    output = tmp_path / "cargo-audit-evidence.json"

    result = ci_cargo_audit.main(
        [
            "--workspace-root",
            str(tmp_path),
            "--input",
            str(raw_path),
            "--lockfile",
            str(lockfile),
            "--tool-version",
            "cargo-audit 0.22.2",
            "--output",
            str(output),
            "--strict",
        ]
    )

    assert result == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "pass"


def test_inconsistent_found_flag_fails_closed(tmp_path: Path) -> None:
    lockfile = tmp_path / "Cargo.lock"
    _write_lock(lockfile)
    raw = {
        "vulnerabilities": {"found": True, "count": 0, "list": []},
        "warnings": {},
    }

    report = ci_cargo_audit.normalize_report(raw, lockfile, "cargo-audit 0.22.2", tmp_path)

    assert report["status"] == "fail"


def test_input_outside_workspace_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(ci_cargo_audit.CargoAuditEvidenceError, match="outside workspace"):
        ci_cargo_audit.load_raw_report(outside, workspace)


def test_symlink_input_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = workspace / "cargo-audit.json"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    with pytest.raises(ci_cargo_audit.CargoAuditEvidenceError, match="symbolic link"):
        ci_cargo_audit.load_raw_report(link, workspace)


def test_output_outside_workspace_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    raw_path = workspace / "cargo-audit.json"
    raw_path.write_text(
        json.dumps({"vulnerabilities": {"found": False, "count": 0, "list": []}, "warnings": {}}),
        encoding="utf-8",
    )
    lockfile = workspace / "Cargo.lock"
    _write_lock(lockfile)

    result = ci_cargo_audit.main(
        [
            "--workspace-root",
            str(workspace),
            "--input",
            str(raw_path),
            "--lockfile",
            str(lockfile),
            "--tool-version",
            "cargo-audit 0.22.2",
            "--output",
            str(tmp_path / "outside.json"),
            "--strict",
        ]
    )

    assert result == 1
