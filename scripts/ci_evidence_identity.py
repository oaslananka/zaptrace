"""Audit release-critical evidence identity and committed report classification."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.evidence.identity import EvidenceIdentity, EvidenceMode, capture_evidence_identity  # noqa: E402

RELEASE_GATE_SCRIPT = "scripts/ci_release_gate.py"
QUALITY_WORKFLOW_PATH = ".github/workflows/quality.yml"
REPORTS_DIRECTORY = "docs/reports"

FORBIDDEN_CURRENT_REPORTS = (
    "docs/reports/generated-board-release-gate.json",
    "docs/reports/benchmark-fixture-coverage.json",
    "docs/reports/benchmark-fixture-integrity.json",
    "docs/reports/v0.3.0-release-gate.json",
)

IDENTITY_PRODUCERS = (
    RELEASE_GATE_SCRIPT,
    "scripts/ci_generated_board_release_gate.py",
    "scripts/ci_benchmark_001.py",
    "scripts/ci_benchmark_fixture_coverage.py",
    "scripts/ci_benchmark_fixture_integrity.py",
    "scripts/ci_validation_environment.py",
    "scripts/ci_critical_runtime_coverage.py",
    "scripts/ci_version_consistency.py",
)

_CLASSIFICATIONS = {
    "sample": "non-authoritative-example",
    "reference": "deterministic-reference-not-current-evidence",
    "historical_snapshot": "historical-governance-snapshot",
    "policy_artifact": "generated-policy-not-runtime-evidence",
}

_HISTORICAL_RELEASE_RE = re.compile(r"\bv0\.3\.0\b")


class AuditViolation(BaseModel):
    """One repository evidence-policy violation."""

    model_config = ConfigDict(frozen=True)

    code: str
    path: str
    message: str


class EvidenceAuditResult(BaseModel):
    """Repository-level evidence inventory result."""

    model_config = ConfigDict(frozen=True)

    passed: bool
    checked_report_count: int = Field(ge=0)
    classified_report_count: int = Field(ge=0)
    identity_report_count: int = Field(ge=0)
    identity_producer_count: int = Field(ge=0)
    violations: list[AuditViolation]


def _violation(code: str, path: str, message: str) -> AuditViolation:
    return AuditViolation(code=code, path=path, message=message)


def _classification_status(payload: dict[str, Any]) -> str | None:
    matches = [expected for marker, expected in _CLASSIFICATIONS.items() if payload.get(marker) is True]
    if len(matches) != 1:
        return None
    expected = matches[0]
    return expected if payload.get("evidence_status") == expected else None


def _audit_forbidden_current_reports(root_path: Path) -> list[AuditViolation]:
    violations: list[AuditViolation] = []
    for relative in FORBIDDEN_CURRENT_REPORTS:
        if (root_path / relative).exists():
            violations.append(
                _violation(
                    "committed-current-evidence",
                    relative,
                    "current release/benchmark evidence must be a revision-bound CI artifact, not a committed report",
                )
            )
    return violations


def _audit_identity_producers(root_path: Path) -> tuple[int, list[AuditViolation]]:
    identity_producer_count = 0
    violations: list[AuditViolation] = []
    for relative in IDENTITY_PRODUCERS:
        path = root_path / relative
        if not path.is_file():
            violations.append(
                _violation("missing-identity-producer", relative, "required evidence producer is missing")
            )
        elif "evidence_identity" not in path.read_text(encoding="utf-8"):
            violations.append(
                _violation(
                    "identity-not-embedded",
                    relative,
                    "release-critical producer does not embed the shared evidence identity",
                )
            )
        else:
            identity_producer_count += 1
    return identity_producer_count, violations


def _audit_hardcoded_release_identity(root_path: Path) -> list[AuditViolation]:
    violations: list[AuditViolation] = []
    generic_gate = root_path / RELEASE_GATE_SCRIPT
    if generic_gate.is_file() and _HISTORICAL_RELEASE_RE.search(generic_gate.read_text(encoding="utf-8")):
        violations.append(
            _violation(
                "hardcoded-release-identity",
                RELEASE_GATE_SCRIPT,
                "generic release gate hard-codes historical v0.3.0 identity",
            )
        )

    quality_workflow = root_path / QUALITY_WORKFLOW_PATH
    if quality_workflow.is_file() and "Generate v0.3.0 gate summary" in quality_workflow.read_text(encoding="utf-8"):
        violations.append(
            _violation(
                "hardcoded-release-identity",
                QUALITY_WORKFLOW_PATH,
                "branch/PR workflow labels snapshot evidence as historical release evidence",
            )
        )
    return violations


def _load_report_payload(path: Path, relative: str) -> tuple[dict[str, Any] | None, AuditViolation | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, _violation("invalid-report-json", relative, str(exc))
    if not isinstance(payload, dict):
        return None, _violation("invalid-report-shape", relative, "report must be a JSON object")
    return payload, None


def _classify_report_payload(relative: str, payload: dict[str, Any]) -> tuple[int, int, AuditViolation | None]:
    if "evidence_identity" in payload:
        try:
            EvidenceIdentity.model_validate(payload["evidence_identity"])
        except (TypeError, ValueError) as exc:
            return 0, 0, _violation("invalid-evidence-identity", relative, str(exc))
        return 1, 0, None
    if _classification_status(payload) is not None:
        return 0, 1, None
    return (
        0,
        0,
        _violation(
            "unclassified-report",
            relative,
            (
                "committed JSON without evidence_identity must be explicitly classified as sample, reference, "
                "historical snapshot, or policy artifact"
            ),
        ),
    )


def _audit_committed_reports(root_path: Path) -> tuple[int, int, int, list[AuditViolation]]:
    checked_report_count = 0
    classified_report_count = 0
    identity_report_count = 0
    violations: list[AuditViolation] = []
    reports_dir = root_path / REPORTS_DIRECTORY
    paths = sorted(reports_dir.glob("*.json")) if reports_dir.is_dir() else []
    forbidden = set(FORBIDDEN_CURRENT_REPORTS)

    for path in paths:
        relative = path.relative_to(root_path).as_posix()
        checked_report_count += 1
        payload, load_violation = _load_report_payload(path, relative)
        if load_violation is not None:
            violations.append(load_violation)
            continue
        if relative in forbidden or payload is None:
            continue
        identity_increment, classified_increment, classification_violation = _classify_report_payload(relative, payload)
        identity_report_count += identity_increment
        classified_report_count += classified_increment
        if classification_violation is not None:
            violations.append(classification_violation)

    return checked_report_count, classified_report_count, identity_report_count, violations


def audit_repository(root: str | Path = ROOT) -> EvidenceAuditResult:
    """Audit committed reports and identity-producing scripts without mutating files."""
    root_path = Path(root).resolve()
    violations = _audit_forbidden_current_reports(root_path)
    identity_producer_count, producer_violations = _audit_identity_producers(root_path)
    violations.extend(producer_violations)
    violations.extend(_audit_hardcoded_release_identity(root_path))
    checked_report_count, classified_report_count, identity_report_count, report_violations = _audit_committed_reports(
        root_path
    )
    violations.extend(report_violations)

    return EvidenceAuditResult(
        passed=not violations,
        checked_report_count=checked_report_count,
        classified_report_count=classified_report_count,
        identity_report_count=identity_report_count,
        identity_producer_count=identity_producer_count,
        violations=violations,
    )


def build_report(root: str | Path = ROOT) -> dict[str, Any]:
    """Build an identity-bound CI report for the repository evidence audit."""
    root_path = Path(root).resolve()
    result = audit_repository(root_path)
    report_paths = sorted(
        path.relative_to(root_path).as_posix() for path in (root_path / "docs/reports").glob("*.json")
    )
    source_inputs = [
        "pyproject.toml",
        "uv.lock",
        "scripts/ci_evidence_identity.py",
        QUALITY_WORKFLOW_PATH,
        *IDENTITY_PRODUCERS,
        *report_paths,
    ]
    identity = capture_evidence_identity(
        root=root_path,
        mode=EvidenceMode.SNAPSHOT,
        source_inputs=source_inputs,
    )
    return {
        "schema_version": "1.0",
        "generated_at": identity.generated_at,
        "evidence_identity": identity.model_dump(mode="json"),
        **result.model_dump(mode="json"),
        "non_claims": [
            "identity completeness does not prove circuit correctness",
            "identity verification does not imply fabrication readiness or manufacturer approval",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit evidence identity and committed report classification")
    parser.add_argument("--output", type=Path, help="Write JSON audit evidence to this path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when evidence policy violations exist")
    args = parser.parse_args(argv)

    report = build_report(ROOT)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if report["violations"]:
        for item in report["violations"]:
            print(f"{item['code']}: {item['path']}: {item['message']}", file=sys.stderr)
    if args.strict and not report["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
