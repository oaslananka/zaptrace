#!/usr/bin/env python3
"""Enforce exact line-coverage floors for security-critical runtime modules."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
import tomllib
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path, PurePath
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.evidence.identity import EvidenceMode, capture_evidence_identity  # noqa: E402

POLICY_PATH = ROOT / "config/critical-runtime-coverage.json"
PYPROJECT_FILE = "pyproject.toml"
_PRAGMA_NO_COVER_RE = re.compile(r"#\s*pragma:\s*no\s*cover\b", re.IGNORECASE)


class CriticalModulePolicy(BaseModel):
    """Approved owner and line-coverage floor for one critical module."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    minimum_line_coverage: float = Field(ge=0.0, le=100.0)
    rationale: str = Field(min_length=10)


class CoverageException(BaseModel):
    """Time-bounded reviewed exception that can temporarily lower one floor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    minimum_line_coverage: float = Field(ge=0.0, le=100.0)
    rationale: str = Field(min_length=10)
    approved_by: str = Field(min_length=1)
    tracking_issue: str = Field(min_length=1)
    expires_on: date


class AllowedCoverageExclusion(BaseModel):
    """Exact, time-bounded source-line exclusion approved by review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    line: int = Field(ge=1)
    rationale: str = Field(min_length=10)
    approved_by: str = Field(min_length=1)
    tracking_issue: str = Field(min_length=1)
    expires_on: date


class CriticalCoveragePolicy(BaseModel):
    """Versioned policy for critical runtime coverage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    modules: list[CriticalModulePolicy] = Field(min_length=1)
    exceptions: list[CoverageException] = Field(default_factory=list)
    allowed_exclusions: list[AllowedCoverageExclusion] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_entries(self) -> Self:
        module_paths = [item.path for item in self.modules]
        if len(module_paths) != len(set(module_paths)):
            raise ValueError("critical module paths must be unique")
        exception_paths = [item.path for item in self.exceptions]
        if len(exception_paths) != len(set(exception_paths)):
            raise ValueError("coverage exception paths must be unique")
        exclusion_keys = [(item.path, item.line) for item in self.allowed_exclusions]
        if len(exclusion_keys) != len(set(exclusion_keys)):
            raise ValueError("allowed coverage exclusion path/line pairs must be unique")
        unknown_exception_paths = sorted(set(exception_paths) - set(module_paths))
        if unknown_exception_paths:
            raise ValueError(f"coverage exceptions reference unknown modules: {unknown_exception_paths}")
        unknown_exclusion_paths = sorted({item.path for item in self.allowed_exclusions} - set(module_paths))
        if unknown_exclusion_paths:
            raise ValueError(f"coverage exclusions reference unknown modules: {unknown_exclusion_paths}")
        return self


class CoverageViolation(BaseModel):
    """One machine-readable coverage policy violation."""

    model_config = ConfigDict(frozen=True)

    code: str
    path: str
    message: str


class CriticalModuleCoverage(BaseModel):
    """Measured coverage and effective policy result for one module."""

    model_config = ConfigDict(frozen=True)

    path: str
    owner: str
    covered_lines: int = Field(ge=0)
    num_statements: int = Field(ge=0)
    missing_lines: int = Field(ge=0)
    actual_line_coverage: float = Field(ge=0.0, le=100.0)
    baseline_line_coverage: float = Field(ge=0.0, le=100.0)
    required_line_coverage: float = Field(ge=0.0, le=100.0)
    status: Literal["pass", "exception-approved", "fail"]
    owner_rationale: str
    exception: CoverageException | None = None


class CriticalCoverageAudit(BaseModel):
    """Complete critical-runtime coverage audit."""

    model_config = ConfigDict(frozen=True)

    passed: bool
    coverage_input_sha256: str
    policy_sha256: str
    modules: list[CriticalModuleCoverage]
    violations: list[CoverageViolation]


def _violation(code: str, path: str, message: str) -> CoverageViolation:
    return CoverageViolation(code=code, path=path, message=message)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def load_policy(path: str | Path = POLICY_PATH) -> CriticalCoveragePolicy:
    """Load and validate the committed critical-runtime coverage policy."""
    return CriticalCoveragePolicy.model_validate(_load_json_object(Path(path)))


def _path_matches(pattern: str, path: str) -> bool:
    normalized_pattern = pattern.replace("\\", "/")
    normalized_path = path.replace("\\", "/")
    return fnmatch.fnmatch(normalized_path, normalized_pattern) or PurePath(normalized_path).match(normalized_pattern)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coverage_configuration(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    data = tomllib.loads((root / PYPROJECT_FILE).read_text(encoding="utf-8"))
    coverage = _mapping(_mapping(data.get("tool")).get("coverage"))
    return _mapping(coverage.get("run")), _mapping(coverage.get("report"))


def _omit_violations(
    policy: CriticalCoveragePolicy,
    omit_patterns: Any,
) -> list[CoverageViolation]:
    patterns = (
        [pattern for pattern in omit_patterns if isinstance(pattern, str)] if isinstance(omit_patterns, list) else []
    )
    return [
        _violation(
            "critical-module-omitted",
            module.path,
            f"coverage omit pattern {pattern!r} hides a critical runtime module",
        )
        for module in policy.modules
        for pattern in patterns
        if _path_matches(pattern, module.path)
    ]


def _report_exclusion_violations(report_config: dict[str, Any]) -> list[CoverageViolation]:
    return [
        _violation(
            "global-coverage-exclusion",
            PYPROJECT_FILE,
            f"global coverage.report.{setting} is not allowed for critical runtime policy",
        )
        for setting in ("exclude_lines", "exclude_also")
        if report_config.get(setting, [])
    ]


def _audit_coverage_configuration(root: Path, policy: CriticalCoveragePolicy) -> list[CoverageViolation]:
    run_config, report_config = _coverage_configuration(root)
    return [
        *_omit_violations(policy, run_config.get("omit", [])),
        *_report_exclusion_violations(report_config),
    ]


def _active_exception(
    policy: CriticalCoveragePolicy,
    module_path: str,
    *,
    today: date,
    violations: list[CoverageViolation],
) -> CoverageException | None:
    exception = next((item for item in policy.exceptions if item.path == module_path), None)
    if exception is None:
        return None
    if exception.expires_on < today:
        violations.append(
            _violation(
                "expired-coverage-exception",
                module_path,
                f"coverage exception expired on {exception.expires_on.isoformat()}",
            )
        )
        return None
    return exception


def _audit_source_exclusions(
    root: Path,
    policy: CriticalCoveragePolicy,
    *,
    today: date,
) -> list[CoverageViolation]:
    violations: list[CoverageViolation] = []
    active_allowed: dict[tuple[str, int], AllowedCoverageExclusion] = {}
    for item in policy.allowed_exclusions:
        if item.expires_on < today:
            violations.append(
                _violation(
                    "expired-coverage-exclusion",
                    f"{item.path}:{item.line}",
                    f"coverage exclusion expired on {item.expires_on.isoformat()}",
                )
            )
            continue
        active_allowed[(item.path, item.line)] = item

    observed: set[tuple[str, int]] = set()
    for module in policy.modules:
        source_path = root / module.path
        if not source_path.is_file():
            violations.append(
                _violation("missing-critical-source", module.path, "critical runtime source file is missing")
            )
            continue
        for line_number, line in enumerate(source_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not _PRAGMA_NO_COVER_RE.search(line):
                continue
            key = (module.path, line_number)
            observed.add(key)
            if key not in active_allowed:
                violations.append(
                    _violation(
                        "unapproved-coverage-exclusion",
                        f"{module.path}:{line_number}",
                        "critical runtime coverage exclusion lacks an active reviewed policy entry",
                    )
                )

    for key in sorted(set(active_allowed) - observed):
        violations.append(
            _violation(
                "stale-coverage-exclusion",
                f"{key[0]}:{key[1]}",
                "policy allows a coverage exclusion that is not present in source",
            )
        )
    return violations


def _coverage_summaries(coverage_path: Path) -> dict[str, dict[str, Any]]:
    data = _load_json_object(coverage_path)
    files = data.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("coverage JSON must contain a files object")
    return {str(path).replace("\\", "/"): value for path, value in files.items() if isinstance(value, dict)}


def _summary_numbers(path: str, payload: dict[str, Any]) -> tuple[int, int, float]:
    summary = payload.get("summary", {})
    if not isinstance(summary, dict):
        raise ValueError(f"coverage summary is missing for {path}")
    covered_lines = int(summary.get("covered_lines", 0))
    num_statements = int(summary.get("num_statements", 0))
    if num_statements <= 0:
        raise ValueError(f"coverage statement count must be positive for {path}")
    raw_percent = summary.get("percent_covered")
    percent = float(raw_percent) if raw_percent is not None else covered_lines * 100.0 / num_statements
    return covered_lines, num_statements, percent


def audit_critical_coverage(
    *,
    root: str | Path,
    coverage_path: str | Path,
    policy_path: str | Path = POLICY_PATH,
    today: date | None = None,
) -> CriticalCoverageAudit:
    """Audit Coverage.py JSON, repository config, and source exclusions."""
    root_path = Path(root).resolve()
    coverage_file = Path(coverage_path).resolve()
    policy_file = Path(policy_path).resolve()
    policy = load_policy(policy_file)
    audit_date = today or datetime.now(UTC).date()
    violations = _audit_coverage_configuration(root_path, policy)
    violations.extend(_audit_source_exclusions(root_path, policy, today=audit_date))
    summaries = _coverage_summaries(coverage_file)
    modules: list[CriticalModuleCoverage] = []

    for module in policy.modules:
        exception = _active_exception(policy, module.path, today=audit_date, violations=violations)
        required = exception.minimum_line_coverage if exception is not None else module.minimum_line_coverage
        payload = summaries.get(module.path)
        if payload is None:
            violations.append(
                _violation(
                    "missing-module-coverage",
                    module.path,
                    "critical runtime module is absent from Coverage.py JSON",
                )
            )
            modules.append(
                CriticalModuleCoverage(
                    path=module.path,
                    owner=module.owner,
                    covered_lines=0,
                    num_statements=0,
                    missing_lines=0,
                    actual_line_coverage=0.0,
                    baseline_line_coverage=module.minimum_line_coverage,
                    required_line_coverage=required,
                    status="fail",
                    owner_rationale=module.rationale,
                    exception=exception,
                )
            )
            continue
        try:
            covered_lines, num_statements, actual = _summary_numbers(module.path, payload)
        except (TypeError, ValueError) as exc:
            violations.append(_violation("invalid-module-coverage", module.path, str(exc)))
            covered_lines, num_statements, actual = 0, 0, 0.0
        below_floor = Decimal(str(actual)) < Decimal(str(required))
        if below_floor:
            violations.append(
                _violation(
                    "coverage-below-floor",
                    module.path,
                    f"line coverage {actual:.2f}% is below required {required:.2f}%",
                )
            )
        status: Literal["pass", "exception-approved", "fail"]
        if below_floor:
            status = "fail"
        elif exception is not None and required < module.minimum_line_coverage:
            status = "exception-approved"
        else:
            status = "pass"
        modules.append(
            CriticalModuleCoverage(
                path=module.path,
                owner=module.owner,
                covered_lines=covered_lines,
                num_statements=num_statements,
                missing_lines=max(0, num_statements - covered_lines),
                actual_line_coverage=round(actual, 6),
                baseline_line_coverage=module.minimum_line_coverage,
                required_line_coverage=required,
                status=status,
                owner_rationale=module.rationale,
                exception=exception,
            )
        )

    return CriticalCoverageAudit(
        passed=not violations,
        coverage_input_sha256=_sha256_file(coverage_file),
        policy_sha256=_sha256_file(policy_file),
        modules=modules,
        violations=violations,
    )


def _relative_source_input(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def build_report(
    *,
    root: str | Path,
    coverage_path: str | Path,
    policy_path: str | Path = POLICY_PATH,
    mode: EvidenceMode | str = EvidenceMode.SNAPSHOT,
) -> dict[str, Any]:
    """Build an identity-bound machine-readable critical coverage report."""
    root_path = Path(root).resolve()
    policy_file = Path(policy_path).resolve()
    audit = audit_critical_coverage(root=root_path, coverage_path=coverage_path, policy_path=policy_file)
    source_inputs = [
        PYPROJECT_FILE,
        _relative_source_input(root_path, policy_file),
        "scripts/ci_critical_runtime_coverage.py",
        ".github/workflows/quality.yml",
        ".github/workflows/release.yml",
    ]
    identity = capture_evidence_identity(
        root=root_path,
        mode=EvidenceMode(mode),
        source_inputs=source_inputs,
    )
    return {
        "schema_version": "1.0",
        "generated_at": identity.generated_at,
        "evidence_identity": identity.model_dump(mode="json"),
        **audit.model_dump(mode="json"),
        "non_claims": [
            "line coverage is not proof of security or correctness",
            "the gate measures selected runtime modules and does not replace qualified review",
            "Codecov remains the repository and patch trend reporter; SonarQube remains the new-code quality gate",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Render a compact human-readable critical coverage report."""
    identity = report["evidence_identity"]
    lines = [
        "# Critical Runtime Coverage",
        "",
        f"Passed: `{'yes' if report['passed'] else 'no'}`",
        f"Source commit: `{identity['source_commit']}`",
        f"Coverage input SHA-256: `{report['coverage_input_sha256']}`",
        "",
        "| Module | Owner | Actual | Baseline | Required | Status |",
        "|--------|-------|--------|----------|----------|--------|",
    ]
    for module in report["modules"]:
        lines.append(
            f"| `{module['path']}` | `{module['owner']}` | {module['actual_line_coverage']:.2f}% | "
            f"{module['baseline_line_coverage']:.2f}% | {module['required_line_coverage']:.2f}% | "
            f"`{module['status']}` |"
        )
    lines.extend(["", "## Violations", ""])
    if report["violations"]:
        lines.extend(f"- `{item['code']}` `{item['path']}` — {item['message']}" for item in report["violations"])
    else:
        lines.append("- none")
    lines.extend(["", "## Non-claims", ""])
    lines.extend(f"- {item}" for item in report["non_claims"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--coverage", type=Path, required=True, help="Coverage.py JSON input")
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument("--mode", choices=[item.value for item in EvidenceMode], default=EvidenceMode.SNAPSHOT.value)
    parser.add_argument("--output", type=Path, help="Write machine-readable JSON report")
    parser.add_argument("--markdown", type=Path, help="Write human-readable Markdown report")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when policy violations exist")
    args = parser.parse_args(argv)

    report = build_report(root=args.root, coverage_path=args.coverage, policy_path=args.policy, mode=args.mode)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    if report["violations"]:
        for item in report["violations"]:
            print(f"{item['code']}: {item['path']}: {item['message']}", file=sys.stderr)
    if args.strict and not report["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
