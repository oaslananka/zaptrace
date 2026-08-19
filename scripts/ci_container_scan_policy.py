#!/usr/bin/env python3
"""Evaluate Trivy image findings against ZapTrace container policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "container-scan-policy.json"
MARKDOWN_PATH = ROOT / "container-scan-summary.md"
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_REQUIRED_EXCEPTION_FIELDS = ("advisory", "package", "rationale", "owner", "expires_on")


def _common_root(paths: tuple[Path, ...]) -> Path:
    parents = [str(path.resolve().parent) for path in paths]
    return Path(os.path.commonpath(parents)).resolve()


def _resolve_within(root: Path, candidate: Path, *, require_file: bool = False) -> Path:
    canonical_root = root.resolve()
    resolved = candidate.resolve() if candidate.is_absolute() else (canonical_root / candidate).resolve()
    try:
        resolved.relative_to(canonical_root)
    except ValueError as exc:
        raise ValueError(f"path escapes container scan workspace: {candidate}") from exc
    if require_file and not resolved.is_file():
        raise ValueError(f"required container scan input is missing: {candidate}")
    return resolved


def _read_json(root: Path, path: Path) -> Any:
    resolved = _resolve_within(root, path, require_file=True)
    return json.loads(resolved.read_text(encoding="utf-8"))


def _parse_enforcement_date(raw: dict[str, Any]) -> date:
    try:
        return date.fromisoformat(str(raw["high_enforcement_on"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("high_enforcement_on must be an ISO date") from exc


def _normalize_exception(item: Any, position: int) -> tuple[dict[str, str] | None, str | None]:
    if not isinstance(item, dict):
        return None, f"exception[{position}] must be an object"
    normalized = {
        field: value.strip()
        for field in _REQUIRED_EXCEPTION_FIELDS
        if isinstance((value := item.get(field)), str) and value.strip()
    }
    missing = [field for field in _REQUIRED_EXCEPTION_FIELDS if field not in normalized]
    if missing:
        return None, f"exception[{position}] missing required fields: {', '.join(missing)}"
    try:
        date.fromisoformat(normalized["expires_on"])
    except ValueError:
        return None, f"exception[{position}] expires_on must be an ISO date"
    return normalized, None


def _index_exceptions(items: list[Any]) -> tuple[dict[tuple[str, str], dict[str, str]], list[str]]:
    index: dict[tuple[str, str], dict[str, str]] = {}
    errors: list[str] = []
    for position, item in enumerate(items):
        normalized, error = _normalize_exception(item, position)
        if error is not None:
            errors.append(error)
            continue
        assert normalized is not None
        key = (normalized["advisory"], normalized["package"])
        if key in index:
            errors.append(f"duplicate exception for advisory/package: {key[0]} / {key[1]}")
            continue
        index[key] = normalized
    return index, errors


def _load_policy(
    root: Path,
    path: Path,
) -> tuple[date, dict[tuple[str, str], dict[str, str]], list[str]]:
    raw = _read_json(root, path)
    if not isinstance(raw, dict):
        raise ValueError("container exception policy must be an object")
    exceptions = raw.get("exceptions")
    if not isinstance(exceptions, list):
        raise ValueError("exceptions must be a list")
    enforcement_on = _parse_enforcement_date(raw)
    index, errors = _index_exceptions(exceptions)
    return enforcement_on, index, errors


def _finding_from_vulnerability(
    vulnerability: dict[str, Any],
    *,
    target: str,
    package_class: str,
    package_type: str,
) -> dict[str, Any]:
    advisory = str(vulnerability.get("VulnerabilityID", "")).strip()
    package = str(vulnerability.get("PkgName", "")).strip()
    if not advisory or not package:
        raise ValueError(f"Trivy finding is missing advisory or package for target {target}")
    return {
        "target": target,
        "package_class": package_class,
        "package_type": package_type,
        "advisory": advisory,
        "package": package,
        "installed_version": str(vulnerability.get("InstalledVersion", "")),
        "fixed_version": str(vulnerability.get("FixedVersion", "")),
        "severity": str(vulnerability.get("Severity", "UNKNOWN")).upper().strip(),
        "title": str(vulnerability.get("Title", "")),
        "primary_url": str(vulnerability.get("PrimaryURL", "")),
    }


def _result_findings(result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    target = str(result.get("Target", ""))
    vulnerabilities = result.get("Vulnerabilities") or []
    if not isinstance(vulnerabilities, list):
        raise ValueError(f"Trivy vulnerabilities must be a list for target {target}")
    package_class = str(result.get("Class", ""))
    package_type = str(result.get("Type", ""))
    return [
        _finding_from_vulnerability(
            vulnerability,
            target=target,
            package_class=package_class,
            package_type=package_type,
        )
        for vulnerability in vulnerabilities
        if isinstance(vulnerability, dict)
    ]


def _findings(scan: Any) -> list[dict[str, Any]]:
    if not isinstance(scan, dict):
        raise ValueError("Trivy result must be an object")
    results = scan.get("Results", [])
    if not isinstance(results, list):
        raise ValueError("Trivy Results must be a list")
    findings = [finding for result in results for finding in _result_findings(result)]
    return sorted(findings, key=lambda item: (item["severity"], item["advisory"], item["package"]))


def _exception_status(exception: dict[str, str] | None, evaluation_date: date) -> str:
    if exception is None:
        return "none"
    expires_on = date.fromisoformat(exception["expires_on"])
    return "accepted" if evaluation_date <= expires_on else "expired"


def _policy_decision(
    *,
    severity: str,
    exception_status: str,
    mode: str,
    high_enforced: bool,
) -> tuple[bool, str]:
    if severity == "CRITICAL":
        return True, "critical-unwaivable"
    if severity != "HIGH":
        return False, "below-policy-threshold"
    if exception_status == "accepted":
        return False, "accepted-exception"
    if mode == "advisory":
        return False, "pull-request-advisory"
    if not high_enforced:
        return False, "high-baseline-period"
    return True, "high-enforced"


def _apply_policy(
    findings: list[dict[str, Any]],
    exceptions: dict[tuple[str, str], dict[str, str]],
    *,
    mode: str,
    evaluation_date: date,
    high_enforced: bool,
) -> tuple[int, int]:
    blocking_count = 0
    accepted_exception_count = 0
    for finding in findings:
        exception = exceptions.get((finding["advisory"], finding["package"]))
        exception_status = _exception_status(exception, evaluation_date)
        blocked, reason = _policy_decision(
            severity=finding["severity"],
            exception_status=exception_status,
            mode=mode,
            high_enforced=high_enforced,
        )
        blocking_count += int(blocked)
        accepted_exception_count += int(reason == "accepted-exception")
        finding.update(
            {
                "blocked": blocked,
                "policy_reason": reason,
                "exception_status": exception_status,
                "exception": exception or {},
            }
        )
    return blocking_count, accepted_exception_count


def evaluate(
    scan_path: Path,
    exceptions_path: Path,
    image_digest_path: Path,
    sbom_path: Path,
    *,
    mode: str,
    today: date | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    if mode not in {"advisory", "release"}:
        raise ValueError(f"unsupported scan mode: {mode}")
    workspace = root or _common_root((scan_path, exceptions_path, image_digest_path, sbom_path))
    evaluation_date = today or date.today()
    digest_file = _resolve_within(workspace, image_digest_path, require_file=True)
    image_digest = digest_file.read_text(encoding="utf-8").strip()
    if _DIGEST_RE.fullmatch(image_digest) is None:
        raise ValueError("image digest must be a lowercase sha256 digest")

    enforcement_on, exception_index, policy_errors = _load_policy(workspace, exceptions_path)
    findings = _findings(_read_json(workspace, scan_path))
    high_enforced = mode == "release" and evaluation_date >= enforcement_on
    blocking_count, accepted_exception_count = _apply_policy(
        findings,
        exception_index,
        mode=mode,
        evaluation_date=evaluation_date,
        high_enforced=high_enforced,
    )
    sbom_file = _resolve_within(workspace, sbom_path, require_file=True)
    return {
        "schema_version": "1.0",
        "gate_id": "container-vulnerability-policy-v1",
        "passed": not policy_errors and blocking_count == 0,
        "mode": mode,
        "evaluation_date": evaluation_date.isoformat(),
        "high_enforcement_on": enforcement_on.isoformat(),
        "high_enforcement_active": high_enforced,
        "image_digest": image_digest,
        "sbom_sha256": hashlib.sha256(sbom_file.read_bytes()).hexdigest(),
        "finding_count": len(findings),
        "blocking_count": blocking_count,
        "accepted_exception_count": accepted_exception_count,
        "policy_errors": policy_errors,
        "findings": findings,
        "non_claims": [
            "a clean vulnerability scan does not prove deployment security",
            "package findings require exploitability and reachability triage",
        ],
    }


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Container vulnerability scan",
        "",
        f"- Result: **{'PASS' if report['passed'] else 'FAIL'}**",
        f"- Image: `{report['image_digest']}`",
        f"- SBOM SHA-256: `{report['sbom_sha256']}`",
        f"- Mode: `{report['mode']}`",
        f"- High enforcement active: `{str(report['high_enforcement_active']).lower()}`",
        f"- Findings: `{report['finding_count']}`",
        f"- Blocking findings: `{report['blocking_count']}`",
        "",
        "| Severity | Advisory | Package | Installed | Fixed | Policy |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {finding['severity']} | {finding['advisory']} | {finding['package']} | "
        f"{finding['installed_version']} | {finding['fixed_version']} | {finding['policy_reason']} |"
        for finding in report["findings"]
    )
    if report["policy_errors"]:
        lines.extend(["", "## Policy errors", *[f"- {error}" for error in report["policy_errors"]]])
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    """Build the fixed-evidence CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--exceptions", type=Path, required=True)
    parser.add_argument("--image-digest", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--mode", choices=("advisory", "release"), required=True)
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = ROOT.resolve()
    report = evaluate(
        args.scan,
        args.exceptions,
        args.image_digest,
        args.sbom,
        mode=args.mode,
        root=root,
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report_json(report), encoding="utf-8")
    MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
    MARKDOWN_PATH.write_text(report_markdown(report), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
