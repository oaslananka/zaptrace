"""Audit component-selection evidence coverage and representative prompt outcomes."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from zaptrace.library.governance import validate_governed_component
from zaptrace.library.loader import LIBRARY_ROOT, ComponentSpec, LibraryLoader
from zaptrace.library.schema import ComponentField, ComponentTrustTier
from zaptrace.library.selection import ComponentSelectionRequirement, select_component

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "tests/fixtures/component_selection/prompts.yaml"


def _validated_corpus_path(path: Path, *, allowed_root: Path) -> Path:
    root = allowed_root.resolve(strict=True)
    if path.is_symlink():
        raise ValueError(f"component-selection corpus must not be a symbolic link: {path}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"cannot resolve component-selection corpus {path}: {exc}") from exc
    if not resolved.is_file():
        raise ValueError(f"component-selection corpus is not a regular file: {resolved}")
    if resolved.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError(f"component-selection corpus must use .yaml or .yml: {resolved}")
    if not resolved.is_relative_to(root):
        raise ValueError(f"component-selection corpus is outside allowed root {root}: {resolved}")
    return resolved


def _load_corpus(path: Path, *, allowed_root: Path) -> list[dict[str, Any]]:
    resolved = _validated_corpus_path(path, allowed_root=allowed_root)
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"component-selection corpus must be a list: {path}")
    cases: list[dict[str, Any]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"component-selection corpus item {index} must be a mapping")
        cases.append(item)
    return cases


def _has_governed_field(spec: ComponentSpec, field: ComponentField, value: str) -> bool:
    return bool(value.strip()) and field in spec.field_provenance


def _coverage(specs: dict[str, ComponentSpec]) -> dict[str, Any]:
    governed_datasheet = 0
    governed_footprint = 0
    governed_both = 0
    verified_both = 0
    release_eligible = 0
    human_review_required = 0
    trust_tiers: Counter[str] = Counter()

    for component_id in sorted(specs):
        spec = specs[component_id]
        has_datasheet = _has_governed_field(spec, ComponentField.DATASHEET, spec.datasheet)
        has_footprint = _has_governed_field(spec, ComponentField.FOOTPRINT, spec.footprint)
        governed_datasheet += int(has_datasheet)
        governed_footprint += int(has_footprint)
        complete = has_datasheet and has_footprint and bool(spec.package and spec.pins)
        governed_both += int(complete)
        validation = validate_governed_component(spec)
        trust_tiers[validation.trust_tier.value] += 1
        release_eligible += int(validation.release_eligible)
        human_review_required += int(validation.human_review_required)
        verified_both += int(complete and validation.trust_tier is ComponentTrustTier.VERIFIED)

    return {
        "component_count": len(specs),
        "governed_datasheet_count": governed_datasheet,
        "governed_footprint_count": governed_footprint,
        "governed_datasheet_and_footprint_count": governed_both,
        "verified_datasheet_and_footprint_count": verified_both,
        "release_eligible_count": release_eligible,
        "human_review_required_count": human_review_required,
        "trust_tier_counts": dict(sorted(trust_tiers.items())),
    }


def _requirement(case: dict[str, Any]) -> ComponentSelectionRequirement:
    return ComponentSelectionRequirement.model_validate(
        {
            "requirement_id": case.get("id"),
            "position": case.get("position"),
            "category": case.get("category"),
            "operating_voltage_v": case.get("operating_voltage_v"),
            "operating_current_a": case.get("operating_current_a"),
            "operating_power_w": case.get("operating_power_w"),
            "allowed_packages": case.get("allowed_packages", []),
            "required_footprint": case.get("required_footprint", ""),
            "required_pin_functions": case.get("required_pin_functions", {}),
            "max_supply_risk": case.get("max_supply_risk", "high"),
            "require_release_eligible": case.get("require_release_eligible", False),
        }
    )


def _evaluate_case(
    case: dict[str, Any],
    specs: dict[str, ComponentSpec],
) -> tuple[dict[str, Any], list[str]]:
    case_id = str(case.get("id") or "unnamed-case")
    candidate_ids = [str(item) for item in case.get("candidate_ids", [])]
    missing = sorted(component_id for component_id in candidate_ids if component_id not in specs)
    if missing:
        errors = [f"{case_id}: missing candidate id {component_id}" for component_id in missing]
        return {
            "id": case_id,
            "passed": False,
            "selected_component_id": "",
            "blocked": True,
            "decision_hash": "",
            "rationale": errors[0],
        }, errors

    decision = select_component(_requirement(case), [specs[component_id] for component_id in candidate_ids])
    expected_selected = str(case.get("expected_selected_id") or "")
    expected_blocked = bool(case.get("expected_blocked", False))
    passed = decision.selected_component_id == expected_selected and decision.blocked is expected_blocked
    errors = (
        []
        if passed
        else [
            f"{case_id}: expected selected={expected_selected!r} blocked={expected_blocked}, "
            f"observed selected={decision.selected_component_id!r} blocked={decision.blocked}"
        ]
    )
    return {
        "id": case_id,
        "passed": passed,
        "selected_component_id": decision.selected_component_id,
        "blocked": decision.blocked,
        "human_review_required": decision.human_review_required,
        "decision_hash": decision.decision_hash,
        "rationale": decision.rationale,
    }, errors


def _corpus_results(
    cases: list[dict[str, Any]],
    specs: dict[str, ComponentSpec],
) -> tuple[list[dict[str, Any]], list[str]]:
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for case in cases:
        result, case_errors = _evaluate_case(case, specs)
        results.append(result)
        errors.extend(case_errors)
    return results, errors


def build_gate_report(
    library_root: str | Path = LIBRARY_ROOT,
    corpus_path: str | Path = DEFAULT_CORPUS,
    *,
    minimum_governed_parts: int = 100,
    allowed_root: str | Path = ROOT,
) -> dict[str, Any]:
    """Build deterministic component-selection coverage and corpus evidence."""
    loader = LibraryLoader(Path(library_root))
    specs = loader.load_all()
    cases = _load_corpus(Path(corpus_path), allowed_root=Path(allowed_root))
    coverage = _coverage(specs)
    corpus_results, corpus_errors = _corpus_results(cases, specs)
    load_errors = [f"{item.path}: {item.reason}" for item in loader.load_errors()]
    governed_count = int(coverage["governed_datasheet_and_footprint_count"])
    shortfall = max(0, minimum_governed_parts - governed_count)
    errors = [*load_errors, *corpus_errors]
    passed_count = sum(1 for result in corpus_results if result["passed"])
    passed = shortfall == 0 and not errors and passed_count == len(corpus_results)
    return {
        "schema_version": "1.0",
        "gate": "component-selection-coverage",
        "historical_snapshot": True,
        "evidence_status": "historical-governance-snapshot",
        "passed": passed,
        **coverage,
        "minimum_governed_parts": minimum_governed_parts,
        "coverage_shortfall": shortfall,
        "load_error_count": len(load_errors),
        "corpus_case_count": len(corpus_results),
        "corpus_passed_count": passed_count,
        "corpus_failed_count": len(corpus_results) - passed_count,
        "corpus_results": corpus_results,
        "errors": errors,
        "non_claims": [
            "governed provenance coverage does not mean manufacturer verification",
            "heuristic records are not release or fabrication eligible without policy-scoped review",
            "selection corpus success does not prove electrical, thermal, supply, or physical board correctness",
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    status = "passed" if report["passed"] else "blocked"
    return "\n".join(
        [
            "# Component Selection Coverage",
            "",
            f"Status: **{status}**",
            f"Governed datasheet + footprint: `{report['governed_datasheet_and_footprint_count']}`",
            f"Verified datasheet + footprint: `{report['verified_datasheet_and_footprint_count']}`",
            f"Release eligible: `{report['release_eligible_count']}`",
            f"Prompt corpus: `{report['corpus_passed_count']}/{report['corpus_case_count']}`",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit component-selection evidence coverage and prompt outcomes")
    parser.add_argument("--library-root", type=Path, default=LIBRARY_ROOT)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--minimum-governed-parts", type=int, default=100)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    report = build_gate_report(
        args.library_root,
        args.corpus,
        minimum_governed_parts=args.minimum_governed_parts,
        allowed_root=Path.cwd(),
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        with args.markdown.open("a", encoding="utf-8") as handle:
            handle.write(_markdown(report))
    if report["errors"]:
        for error in report["errors"]:
            print(error, file=sys.stderr)
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
