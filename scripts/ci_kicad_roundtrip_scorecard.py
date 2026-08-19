"""Deterministic KiCad round-trip fidelity scorecard harness.

This harness validates the scorecard corpus contract and enforces configured
fidelity thresholds. It is intentionally deterministic: it consumes committed
case metadata and diff artifacts, then produces machine-readable and
human-readable release-gate evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.security.paths import resolve_trusted_path  # noqa: E402

PASS = "pass"
FAIL = "fail"
WARN = "warn"

DEFAULT_CORPUS = Path("benchmarks/kicad_roundtrip/corpus.yaml")
REQUIRED_CATEGORIES = {"schematic", "net", "footprint", "constraint", "board", "manufacturing"}


@dataclass(frozen=True)
class ScorecardCheck:
    name: str
    status: str
    message: str
    required: bool = True
    details: dict[str, Any] | None = None

    @property
    def blocks_release(self) -> bool:
        return self.required and self.status == FAIL


def _as_mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def _as_sequence(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return value


def load_corpus(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read KiCad round-trip corpus: {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in KiCad round-trip corpus: {path}: {exc}") from exc
    return _as_mapping(raw, field="KiCad round-trip corpus")


def _score_average(scores: dict[str, Any]) -> float:
    values = [float(scores[category]) for category in REQUIRED_CATEGORIES]
    return round(sum(values) / len(values), 4)


def _check_metadata(corpus: dict[str, Any]) -> ScorecardCheck:
    missing = [key for key in ["schema_version", "id", "name"] if not corpus.get(key)]
    if missing:
        return ScorecardCheck(
            name="metadata",
            status=FAIL,
            message="Corpus metadata is incomplete",
            details={"missing": missing},
        )
    return ScorecardCheck(name="metadata", status=PASS, message="Corpus metadata is complete")


def _check_categories(corpus: dict[str, Any]) -> ScorecardCheck:
    categories = set(_as_sequence(corpus.get("categories", []), field="categories"))
    thresholds = _as_mapping(corpus.get("thresholds", {}), field="thresholds")
    category_thresholds = _as_mapping(thresholds.get("categories", {}), field="thresholds.categories")
    missing_categories = sorted(REQUIRED_CATEGORIES - categories)
    missing_thresholds = sorted(REQUIRED_CATEGORIES - set(category_thresholds))
    if missing_categories or missing_thresholds:
        return ScorecardCheck(
            name="category-contract",
            status=FAIL,
            message="Scorecard categories or thresholds are incomplete",
            details={"missing_categories": missing_categories, "missing_thresholds": missing_thresholds},
        )
    return ScorecardCheck(
        name="category-contract",
        status=PASS,
        message="Schematic, net, footprint, constraint, board, and manufacturing categories are configured",
    )


def _validate_degradations(case: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    degradations = _as_sequence(case.get("unsupported_features", []), field=f"{case.get('id')}.unsupported_features")
    for index, item in enumerate(degradations):
        if not isinstance(item, dict):
            errors.append(f"unsupported_features[{index}] must be a mapping")
            continue
        for field in ["feature", "degradation", "severity"]:
            if not item.get(field):
                errors.append(f"unsupported_features[{index}] missing {field}")
    return errors


def _check_cases(corpus: dict[str, Any], *, root: Path) -> ScorecardCheck:
    cases = _as_sequence(corpus.get("cases", []), field="cases")
    if not cases:
        return ScorecardCheck(name="cases", status=FAIL, message="Corpus must include at least one case")

    errors: list[str] = []
    warnings: list[str] = []
    for case in cases:
        if not isinstance(case, dict):
            errors.append("case entry must be a mapping")
            continue
        case_id = case.get("id", "<missing-id>")
        scores = _as_mapping(case.get("scores", {}), field=f"case {case_id}.scores")
        missing_scores = sorted(REQUIRED_CATEGORIES - set(scores))
        if missing_scores:
            errors.append(f"{case_id}: missing score categories {missing_scores}")
        for category, value in scores.items():
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                errors.append(f"{case_id}: score {category} is not numeric")
                continue
            if numeric < 0.0 or numeric > 1.0:
                errors.append(f"{case_id}: score {category} must be between 0 and 1")

        diff_artifact = case.get("expected_diff_artifact")
        if not diff_artifact or not (root / str(diff_artifact)).exists():
            errors.append(f"{case_id}: expected diff artifact is missing")

        for path_key in ["source_project", "source_schematic", "source_pcb"]:
            raw_path = case.get(path_key)
            if raw_path is None:
                warnings.append(f"{case_id}: {path_key} is intentionally absent")
                continue
            if not (root / str(raw_path)).exists():
                errors.append(f"{case_id}: {path_key} does not exist: {raw_path}")

        degradation_errors = _validate_degradations(case)
        if degradation_errors:
            errors.extend(f"{case_id}: {item}" for item in degradation_errors)
        if any(case.get(path_key) is None for path_key in ["source_project", "source_schematic", "source_pcb"]):
            degradations = case.get("unsupported_features", [])
            if not degradations:
                errors.append(f"{case_id}: absent source artifacts require explicit unsupported_features degradation")

    if errors:
        return ScorecardCheck(
            name="case-contract",
            status=FAIL,
            message="One or more corpus cases violate the round-trip contract",
            details={"errors": errors, "warnings": warnings},
        )
    return ScorecardCheck(
        name="case-contract",
        status=PASS if not warnings else WARN,
        message="All corpus cases are complete; unsupported features are explicit degradations",
        required=not warnings,
        details={"warnings": warnings} if warnings else None,
    )


def evaluate_cases(corpus: dict[str, Any]) -> list[dict[str, Any]]:
    thresholds = _as_mapping(corpus.get("thresholds", {}), field="thresholds")
    category_thresholds = _as_mapping(thresholds.get("categories", {}), field="thresholds.categories")
    overall_min = float(thresholds.get("overall_min_score", 1.0))
    evaluated: list[dict[str, Any]] = []
    for case in _as_sequence(corpus.get("cases", []), field="cases"):
        case_id = str(case.get("id", "<missing-id>"))
        scores = _as_mapping(case.get("scores", {}), field=f"case {case_id}.scores")
        category_failures = []
        for category in REQUIRED_CATEGORIES:
            score = float(scores.get(category, 0.0))
            threshold = float(category_thresholds.get(category, 1.0))
            if score < threshold:
                category_failures.append({"category": category, "score": score, "threshold": threshold})
        overall = _score_average(scores)
        overall_failed = overall < overall_min
        evaluated.append(
            {
                "id": case_id,
                "description": case.get("description", ""),
                "complexity": case.get("complexity", ""),
                "overall_score": overall,
                "overall_threshold": overall_min,
                "scores": {category: float(scores[category]) for category in sorted(REQUIRED_CATEGORIES)},
                "category_failures": category_failures,
                "overall_failed": overall_failed,
                "passed": not category_failures and not overall_failed,
                "expected_diff_artifact": case.get("expected_diff_artifact"),
                "unsupported_features": case.get("unsupported_features", []),
            }
        )
    return evaluated


def _check_thresholds(evaluated_cases: list[dict[str, Any]]) -> ScorecardCheck:
    failing = [case for case in evaluated_cases if not case["passed"]]
    if failing:
        return ScorecardCheck(
            name="fidelity-thresholds",
            status=FAIL,
            message="One or more KiCad round-trip cases fell below configured thresholds",
            details={"failing_cases": failing},
        )
    return ScorecardCheck(name="fidelity-thresholds", status=PASS, message="All KiCad round-trip cases meet thresholds")


def build_report(
    corpus: dict[str, Any],
    checks: list[ScorecardCheck],
    evaluated_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    blocking = [check for check in checks if check.blocks_release]
    degradations = []
    for case in evaluated_cases:
        for item in case.get("unsupported_features", []):
            degradations.append({"case_id": case["id"], **item})
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus": {
            "id": corpus.get("id"),
            "name": corpus.get("name"),
            "issue_links": corpus.get("issue_links", []),
            "thresholds": corpus.get("thresholds", {}),
            "categories": sorted(REQUIRED_CATEGORIES),
        },
        "status": FAIL if blocking else PASS,
        "blocked": bool(blocking),
        "blocking_checks": [check.name for check in blocking],
        "checks": [asdict(check) | {"blocks_release": check.blocks_release} for check in checks],
        "cases": evaluated_cases,
        "degradations": degradations,
        "non_claims": [
            "Round-trip scorecard evidence is not a claim of full KiCad compatibility.",
            "Unsupported features must remain explicit degradations until implemented.",
            "Human review is required before relying on imported/exported manufacturing data.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# KiCad Round-trip Fidelity Scorecard",
        "",
        f"Corpus: `{report['corpus']['id']}`",
        f"Status: `{report['status']}`",
        f"Blocked: `{'yes' if report['blocked'] else 'no'}`",
        "",
        "| Case | Overall | Passed | Degradations | Diff Artifact |",
        "|------|---------|--------|--------------|---------------|",
    ]
    for case in report["cases"]:
        lines.append(
            f"| `{case['id']}` | `{case['overall_score']:.3f}` | "
            f"`{'yes' if case['passed'] else 'no'}` | "
            f"{len(case.get('unsupported_features', []))} | `{case['expected_diff_artifact']}` |"
        )
    lines.extend(
        [
            "",
            "## Checks",
            "",
            "| Check | Status | Blocks Release | Message |",
            "|-------|--------|----------------|---------|",
        ]
    )
    for check in report["checks"]:
        lines.append(
            f"| `{check['name']}` | `{check['status']}` | "
            f"{'yes' if check['blocks_release'] else 'no'} | {check['message']} |"
        )
    lines.extend(["", "## Explicit degradations", ""])
    if report["degradations"]:
        for degradation in report["degradations"]:
            lines.append(
                f"- `{degradation['case_id']}` / `{degradation['feature']}` "
                f"({degradation['severity']}): {degradation['degradation']}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Non-claims", "", *[f"- {item}" for item in report["non_claims"]], ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, trusted_root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Generate KiCad round-trip fidelity scorecard evidence")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS, help="KiCad round-trip corpus YAML")
    parser.add_argument("--output", type=Path, help="Write JSON scorecard to this path")
    parser.add_argument("--markdown", type=Path, help="Append Markdown scorecard to this path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when scorecard blocks release")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root for relative corpus artifacts")
    args = parser.parse_args(argv)

    try:
        corpus_path = resolve_trusted_path(args.corpus, trusted_root=trusted_root, label="corpus path")
        corpus = load_corpus(corpus_path)
        checks = [
            _check_metadata(corpus),
            _check_categories(corpus),
            _check_cases(corpus, root=args.root.resolve()),
        ]
        evaluated = evaluate_cases(corpus)
        checks.append(_check_thresholds(evaluated))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    report = build_report(corpus, checks, evaluated)
    markdown = render_markdown(report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        print(json.dumps(report, indent=2, sort_keys=True))

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        with args.markdown.open("a", encoding="utf-8") as handle:
            handle.write(markdown)
            handle.write("\n")
    else:
        print(markdown)

    if args.strict and report["blocked"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
