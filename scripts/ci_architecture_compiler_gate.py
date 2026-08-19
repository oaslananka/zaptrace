"""Validate deterministic requirements-to-architecture compiler evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.generation import (  # noqa: E402
    ArchitectureCompileStatus,
    architecture_traceability_report_json,
    build_architecture_traceability_report,
    compile_electronics_intent_to_architecture,
    electronics_architecture_artifact_json,
    electronics_architecture_schema_json,
)

DEFAULT_CORPUS = ROOT / "tests/fixtures/architecture/prompts.yaml"
MINIMUM_TOTAL_CASES = 8


def _validated_corpus_path(path: Path, *, allowed_root: Path) -> Path:
    root = allowed_root.resolve(strict=True)
    lexical = Path(os.path.abspath(path))
    for candidate in (lexical, *lexical.parents):
        if candidate.is_symlink():
            raise ValueError(f"architecture corpus path must not contain a symbolic link: {candidate}")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"cannot resolve architecture corpus {path}: {exc}") from exc
    if not resolved.is_relative_to(root):
        raise ValueError(f"architecture corpus is outside allowed root {root}: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"architecture corpus is not a regular file: {resolved}")
    if resolved.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError(f"architecture corpus must use .yaml or .yml: {resolved}")
    return resolved


def _load_corpus(path: Path, *, allowed_root: Path) -> list[dict[str, Any]]:
    resolved = _validated_corpus_path(path, allowed_root=allowed_root)
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"architecture corpus must be a list: {resolved}")
    cases: list[dict[str, Any]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"architecture corpus item {index} must be a mapping")
        cases.append(item)
    return cases


def _expected_strings(case: dict[str, Any], key: str) -> list[str]:
    raw = case.get(key, [])
    if not isinstance(raw, list):
        raise ValueError(f"architecture corpus field {key!r} must be a list")
    return sorted(str(item) for item in raw)


def _case_mismatches(case_id: str, expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("status", "subsystems", "interfaces", "rails", "conflicts"):
        if actual[key] != expected[key]:
            errors.append(f"{case_id}: expected {key}={expected[key]!r}, observed {actual[key]!r}")
    if not actual["deterministic"]:
        errors.append(f"{case_id}: repeated compilation produced different JSON evidence")
    if expected["status"] == ArchitectureCompileStatus.READY.value and not actual["ready_evidence_passed"]:
        errors.append(f"{case_id}: ready architecture traceability report is blocked or incomplete")
    if expected["status"] != ArchitectureCompileStatus.READY.value and not actual["blocked"]:
        errors.append(f"{case_id}: non-ready architecture traceability report did not block")
    return errors


def _evaluate_case(case: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    case_id = str(case.get("id") or "unnamed-case")
    intent = str(case.get("intent") or "")
    expected = {
        "status": str(case.get("expected_status") or ""),
        "subsystems": _expected_strings(case, "expected_subsystems"),
        "interfaces": _expected_strings(case, "expected_interfaces"),
        "rails": _expected_strings(case, "expected_rails"),
        "conflicts": _expected_strings(case, "expected_conflicts"),
    }
    try:
        first = compile_electronics_intent_to_architecture(intent, design_name=case_id)
        second = compile_electronics_intent_to_architecture(intent, design_name=case_id)
    except (TypeError, ValueError) as exc:
        error = f"{case_id}: compiler raised {type(exc).__name__}: {exc}"
        return {"id": case_id, "passed": False, "error": error}, [error]

    first_artifact = electronics_architecture_artifact_json(first)
    second_artifact = electronics_architecture_artifact_json(second)
    first_report = build_architecture_traceability_report(first)
    second_report = build_architecture_traceability_report(second)
    first_trace = architecture_traceability_report_json(first_report)
    second_trace = architecture_traceability_report_json(second_report)
    actual = {
        "status": first.status.value,
        "subsystems": sorted(item.id for item in first.subsystems),
        "interfaces": sorted(item.name for item in first.interfaces),
        "rails": sorted(item.net_name for item in first.power_tree),
        "conflicts": sorted(item.code for item in first.conflicts),
        "deterministic": first_artifact == second_artifact and first_trace == second_trace,
        "ready_evidence_passed": (
            first.status is ArchitectureCompileStatus.READY
            and not first_report.blocked
            and first_report.fully_traced
            and not first_report.uncovered_requirement_ids
            and not first_report.untraced_elements
        ),
        "blocked": first_report.blocked,
    }
    errors = _case_mismatches(case_id, expected, actual)
    return {
        "id": case_id,
        "passed": not errors,
        **actual,
        "artifact_sha256": first_report.artifact_sha256,
        "traceability_sha256": hashlib.sha256(first_trace.encode("utf-8")).hexdigest(),
        "requirement_count": len(first.requirements),
        "assumption_count": len(first.assumptions),
        "trace_row_count": len(first_report.traceability),
        "uncovered_requirement_ids": first_report.uncovered_requirement_ids,
        "untraced_elements": first_report.untraced_elements,
        "human_review_required": first_report.human_review_required,
        "errors": errors,
    }, errors


def build_gate_report(
    corpus_path: str | Path = DEFAULT_CORPUS,
    *,
    minimum_ready_cases: int = 5,
    allowed_root: str | Path = ROOT,
) -> dict[str, Any]:
    """Build deterministic architecture compiler corpus and schema evidence."""

    cases = _load_corpus(Path(corpus_path), allowed_root=Path(allowed_root))
    case_ids = [str(case.get("id") or "unnamed-case") for case in cases]
    duplicate_ids = sorted(item for item, count in Counter(case_ids).items() if count > 1)
    results: list[dict[str, Any]] = []
    errors = [f"duplicate architecture corpus id: {item}" for item in duplicate_ids]
    for case in sorted(cases, key=lambda item: str(item.get("id") or "")):
        result, case_errors = _evaluate_case(case)
        results.append(result)
        errors.extend(case_errors)

    passed_count = sum(1 for result in results if result.get("passed") is True)
    status_counts = Counter(str(result.get("status")) for result in results if result.get("status"))
    ready_count = status_counts[ArchitectureCompileStatus.READY.value]
    ready_shortfall = max(0, minimum_ready_cases - ready_count)
    total_shortfall = max(0, MINIMUM_TOTAL_CASES - len(results))
    if ready_shortfall:
        errors.append(f"ready architecture case shortfall: {ready_shortfall}")
    if total_shortfall:
        errors.append(f"architecture corpus case shortfall: {total_shortfall}")

    schema_json = electronics_architecture_schema_json()
    return {
        "schema_version": "1.0",
        "gate": "requirements-architecture-compiler",
        "historical_snapshot": True,
        "evidence_status": "historical-governance-snapshot",
        "passed": not errors and passed_count == len(results),
        "case_count": len(results),
        "passed_case_count": passed_count,
        "failed_case_count": len(results) - passed_count,
        "minimum_total_cases": MINIMUM_TOTAL_CASES,
        "total_case_shortfall": total_shortfall,
        "minimum_ready_cases": minimum_ready_cases,
        "ready_case_count": ready_count,
        "ready_case_shortfall": ready_shortfall,
        "status_counts": dict(sorted(status_counts.items())),
        "schema_sha256": hashlib.sha256(schema_json.encode("utf-8")).hexdigest(),
        "cases": results,
        "errors": errors,
        "non_claims": [
            "architecture corpus success does not prove requirement extraction completeness",
            "architecture traceability does not prove electrical or physical correctness",
            "a passing architecture gate is not fabrication or production approval",
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    status = "passed" if report["passed"] else "blocked"
    return "\n".join(
        [
            "# Requirements Architecture Compiler",
            "",
            f"Status: **{status}**",
            f"Corpus: `{report['passed_case_count']}/{report['case_count']}`",
            f"Ready families: `{report['ready_case_count']}`",
            f"Schema SHA-256: `{report['schema_sha256']}`",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate architecture compiler corpus and schema evidence")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--minimum-ready-cases", type=int, default=5)
    parser.add_argument("--schema-output", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    report = build_gate_report(
        args.corpus,
        minimum_ready_cases=args.minimum_ready_cases,
        allowed_root=Path.cwd(),
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.schema_output:
        args.schema_output.parent.mkdir(parents=True, exist_ok=True)
        args.schema_output.write_text(electronics_architecture_schema_json(), encoding="utf-8")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        with args.markdown.open("a", encoding="utf-8") as handle:
            handle.write(_markdown(report))
    for error in report["errors"]:
        print(error, file=sys.stderr)
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
