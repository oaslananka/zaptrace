#!/usr/bin/env python3
"""Capture and enforce the committed historical Sonar debt budget."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover - direct script bootstrap
    sys.path.insert(0, str(ROOT))

from zaptrace.evidence.identity import EvidenceMode, capture_evidence_identity  # noqa: E402
from zaptrace.evidence.sonar_debt import (  # noqa: E402
    SonarWebApiClient,
    build_sonar_debt_report,
    compare_report_to_budget,
    load_sonar_debt_policy,
    load_sonar_debt_report,
    validate_policy_baseline,
)

DEFAULT_POLICY = ROOT / ".github" / "sonar-debt-policy.json"
DEFAULT_BASELINE = ROOT / "docs" / "reports" / "sonar-historical-debt-baseline.json"
SOURCE_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    ".github/sonar-debt-policy.json",
    ".github/workflows/sonar-debt.yml",
    "docs/reports/sonar-historical-debt-baseline.json",
    "schemas/sonar-debt-report-v1.schema.json",
    "scripts/ci_sonar_debt.py",
    "zaptrace/evidence/identity.py",
    "zaptrace/evidence/sonar_debt.py",
)
METRICS = [
    "bugs",
    "code_smells",
    "duplicated_lines_density",
    "maintainability_rating",
    "ncloc",
    "reliability_rating",
    "security_rating",
    "vulnerabilities",
]


def _resolve_output(path: Path, *, trusted_root: Path, suffix: str) -> Path:
    candidate = path if path.is_absolute() else trusted_root / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(trusted_root)
    except ValueError as exc:
        raise ValueError(f"output escapes trusted root: {path}") from exc
    if resolved.suffix.lower() != suffix:
        raise ValueError(f"output must use {suffix}: {path}")
    return resolved


def render_markdown(report: dict[str, Any], failures: list[str]) -> str:
    lines = ["# Sonar Historical Debt", ""]
    lines.extend(
        [
            f"- Quality gate: `{report['quality_gate']}`",
            f"- Analysis revision: `{report['analysis_revision']}`",
            f"- Total unresolved findings: `{report['total']}`",
            f"- BLOCKER findings: `{report['blocker_count']}`",
            f"- Critical security/reliability findings: `{report['critical_security_reliability_count']}`",
            f"- Report SHA-256: `{report['report_sha256']}`",
            "",
        ]
    )
    for title, key in (
        ("Severity", "counts_by_severity"),
        ("Type", "counts_by_type"),
        ("Owner", "counts_by_owner"),
        ("Age", "counts_by_age"),
        ("Remediation", "counts_by_remediation"),
    ):
        lines.extend([f"## {title}", "", "| Group | Count |", "|---|---:|"])
        lines.extend(f"| `{name}` | {count} |" for name, count in report[key].items())
        lines.append("")
    if report.get("api_warnings"):
        lines.extend(["## API warnings", ""])
        lines.extend(f"- {item}" for item in report["api_warnings"])
        lines.append("")
    if failures:
        lines.extend(["## Ratchet failures", ""])
        lines.extend(f"- {item}" for item in failures)
        lines.append("")
    lines.extend(["## Non-claims", ""])
    lines.extend(f"- {item}" for item in report.get("non_claims", []))
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "check"))
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--trusted-output-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("sonar-debt-report.json"))
    parser.add_argument("--markdown", type=Path, default=Path("sonar-debt-report.md"))
    parser.add_argument("--expected-analysis-revision", default="")
    parser.add_argument("--analysis-attempts", type=int, default=30)
    parser.add_argument("--analysis-poll-seconds", type=float, default=10.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        token = os.environ.get("SONAR_TOKEN", "").strip()
        if not token:
            raise ValueError("SONAR_TOKEN is required")
        trusted_root = args.trusted_output_root.resolve(strict=True)
        output = _resolve_output(args.output, trusted_root=trusted_root, suffix=".json")
        markdown = _resolve_output(args.markdown, trusted_root=trusted_root, suffix=".md")
        policy = load_sonar_debt_policy(args.policy, trusted_root=ROOT)
        baseline = load_sonar_debt_report(args.baseline, trusted_root=ROOT)
        baseline_errors = validate_policy_baseline(policy, baseline)
        if baseline_errors:
            raise ValueError("committed Sonar baseline binding failed: " + "; ".join(baseline_errors))
        identity = capture_evidence_identity(root=ROOT, mode=EvidenceMode.SNAPSHOT, source_inputs=SOURCE_INPUTS)
        client = SonarWebApiClient(token=token)
        expected = args.expected_analysis_revision.strip().lower()
        if expected:
            revision, analysis_date = client.wait_for_analysis(
                project_key=policy.project_key,
                branch=policy.branch,
                expected_revision=expected,
                max_attempts=args.analysis_attempts,
                poll_seconds=args.analysis_poll_seconds,
                sleep=time.sleep,
            )
        else:
            revision, analysis_date = client.fetch_latest_analysis(
                project_key=policy.project_key,
                branch=policy.branch,
            )
        issues = client.fetch_issues(project_key=policy.project_key, branch=policy.branch)
        quality_gate = client.fetch_quality_gate(project_key=policy.project_key, branch=policy.branch)
        measures = client.fetch_measures(project_key=policy.project_key, branch=policy.branch, metrics=METRICS)
        report = build_sonar_debt_report(
            issues=issues,
            policy=policy,
            captured_at=datetime.now(UTC),
            analysis_revision=revision,
            analysis_date=analysis_date,
            quality_gate=quality_gate,
            measures=measures,
            evidence_identity=identity.model_dump(mode="json"),
            api_identity="sonarcloud-v1",
            token_expiration=client.token_expiration,
            api_warnings=client.api_warnings,
        )
        failures = compare_report_to_budget(report, policy) if args.mode == "check" else []
        payload = report.model_dump(mode="json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(render_markdown(payload, failures), encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"Sonar debt evidence error: {exc}", file=sys.stderr)
        return 2
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
