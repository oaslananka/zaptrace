from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from scripts import ci_container_scan_policy


def _scan(*vulnerabilities: dict[str, object]) -> dict[str, object]:
    return {
        "SchemaVersion": 2,
        "ArtifactName": "zaptrace:scan",
        "Results": [
            {
                "Target": "zaptrace:scan (debian 13)",
                "Class": "os-pkgs",
                "Type": "debian",
                "Vulnerabilities": list(vulnerabilities),
            }
        ],
    }


def _vulnerability(
    advisory: str,
    *,
    package: str = "openssl",
    severity: str = "HIGH",
    installed: str = "1.0",
    fixed: str = "1.1",
) -> dict[str, object]:
    return {
        "VulnerabilityID": advisory,
        "PkgName": package,
        "InstalledVersion": installed,
        "FixedVersion": fixed,
        "Severity": severity,
        "Title": "controlled fixture",
        "PrimaryURL": f"https://example.invalid/{advisory}",
    }


def _write_inputs(
    tmp_path: Path,
    scan: dict[str, object],
    *,
    exceptions: list[dict[str, str]] | None = None,
    enforcement_on: str = "2026-08-14",
) -> tuple[Path, Path, Path, Path]:
    scan_path = tmp_path / "trivy.json"
    scan_path.write_text(json.dumps(scan), encoding="utf-8")
    exception_path = tmp_path / "exceptions.json"
    exception_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "high_enforcement_on": enforcement_on,
                "exceptions": exceptions or [],
            }
        ),
        encoding="utf-8",
    )
    digest_path = tmp_path / "image-digest.txt"
    digest_path.write_text("sha256:" + "a" * 64 + "\n", encoding="utf-8")
    sbom_path = tmp_path / "sbom.json"
    sbom_path.write_bytes(b'{"bomFormat":"CycloneDX"}\n')
    return scan_path, exception_path, digest_path, sbom_path


def test_critical_finding_blocks_every_mode_and_cannot_be_waived(tmp_path: Path) -> None:
    exception = {
        "advisory": "CVE-CRITICAL",
        "package": "openssl",
        "rationale": "controlled exception",
        "owner": "security@example.invalid",
        "expires_on": "2026-12-31",
    }
    paths = _write_inputs(
        tmp_path,
        _scan(_vulnerability("CVE-CRITICAL", severity="CRITICAL")),
        exceptions=[exception],
    )

    for mode in ("advisory", "release"):
        report = ci_container_scan_policy.evaluate(*paths, mode=mode, today=date(2026, 7, 21))
        assert report["passed"] is False
        assert report["blocking_count"] == 1
        assert report["findings"][0]["policy_reason"] == "critical-unwaivable"


def test_high_is_advisory_before_baseline_and_enforced_after_date(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, _scan(_vulnerability("CVE-HIGH")))

    pull_request = ci_container_scan_policy.evaluate(*paths, mode="advisory", today=date(2027, 1, 1))
    baseline = ci_container_scan_policy.evaluate(*paths, mode="release", today=date(2026, 7, 21))
    enforced = ci_container_scan_policy.evaluate(*paths, mode="release", today=date(2026, 8, 14))

    assert pull_request["passed"] is True
    assert pull_request["findings"][0]["policy_reason"] == "pull-request-advisory"
    assert baseline["passed"] is True
    assert baseline["findings"][0]["policy_reason"] == "high-baseline-period"
    assert enforced["passed"] is False
    assert enforced["findings"][0]["policy_reason"] == "high-enforced"


def test_valid_high_exception_requires_exact_match_and_unexpired_metadata(tmp_path: Path) -> None:
    exception = {
        "advisory": "CVE-HIGH",
        "package": "openssl",
        "rationale": "not reachable in the supported entrypoint",
        "owner": "security@example.invalid",
        "expires_on": "2026-09-01",
    }
    paths = _write_inputs(tmp_path, _scan(_vulnerability("CVE-HIGH")), exceptions=[exception])

    accepted = ci_container_scan_policy.evaluate(*paths, mode="release", today=date(2026, 8, 20))
    expired = ci_container_scan_policy.evaluate(*paths, mode="release", today=date(2026, 9, 2))

    assert accepted["passed"] is True
    assert accepted["findings"][0]["exception_status"] == "accepted"
    assert expired["passed"] is False
    assert expired["findings"][0]["exception_status"] == "expired"


def test_invalid_exception_metadata_is_a_policy_error(tmp_path: Path) -> None:
    paths = _write_inputs(
        tmp_path,
        _scan(),
        exceptions=[{"advisory": "CVE-X", "package": "openssl"}],
    )

    report = ci_container_scan_policy.evaluate(*paths, mode="release", today=date(2026, 7, 21))

    assert report["passed"] is False
    assert report["policy_errors"]
    assert "rationale" in report["policy_errors"][0]


def test_report_binds_image_digest_sbom_hash_and_finding_identity(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, _scan(_vulnerability("CVE-HIGH", package="libssl3")))

    report = ci_container_scan_policy.evaluate(*paths, mode="advisory", today=date(2026, 7, 21))

    assert report["image_digest"] == "sha256:" + "a" * 64
    assert report["sbom_sha256"] == hashlib.sha256(paths[3].read_bytes()).hexdigest()
    finding = report["findings"][0]
    assert finding["advisory"] == "CVE-HIGH"
    assert finding["package"] == "libssl3"
    assert finding["installed_version"] == "1.0"
    assert finding["fixed_version"] == "1.1"
    assert finding["severity"] == "HIGH"
    assert finding["package_type"] == "debian"


def test_invalid_image_digest_is_rejected(tmp_path: Path) -> None:
    paths = list(_write_inputs(tmp_path, _scan()))
    paths[2].write_text("latest\n", encoding="utf-8")

    evaluation_date = date(2026, 7, 21)
    with pytest.raises(ValueError, match="image digest"):
        ci_container_scan_policy.evaluate(*paths, mode="advisory", today=evaluation_date)


def test_main_writes_only_fixed_repository_evidence_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _write_inputs(tmp_path, _scan())
    output = tmp_path / "container-scan-policy.json"
    markdown = tmp_path / "container-scan-summary.md"
    monkeypatch.setattr(ci_container_scan_policy, "ROOT", tmp_path)
    monkeypatch.setattr(ci_container_scan_policy, "OUTPUT_PATH", output)
    monkeypatch.setattr(ci_container_scan_policy, "MARKDOWN_PATH", markdown)

    result = ci_container_scan_policy.main(
        [
            "--scan",
            paths[0].name,
            "--exceptions",
            paths[1].name,
            "--image-digest",
            paths[2].name,
            "--sbom",
            paths[3].name,
            "--mode",
            "advisory",
            "--strict",
        ]
    )

    assert result == 0
    assert output.is_file()
    assert markdown.is_file()
    parser = ci_container_scan_policy.build_parser()
    option_strings = {item for action in parser._actions for item in action.option_strings}
    assert "--output" not in option_strings
    assert "--markdown" not in option_strings
    assert "--root" not in option_strings


def test_result_findings_emits_each_vulnerability_once() -> None:
    result = {
        "Target": "image",
        "Class": "os-pkgs",
        "Type": "alpine",
        "Vulnerabilities": [_vulnerability("CVE-ONE"), _vulnerability("CVE-TWO")],
    }
    findings = ci_container_scan_policy._result_findings(result)
    assert [finding["advisory"] for finding in findings] == ["CVE-ONE", "CVE-TWO"]
