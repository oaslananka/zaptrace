"""Validate the placement/routing correctness fixture corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from zaptrace.core.parser import parse_str
from zaptrace.security.paths import resolve_trusted_path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_CATEGORIES = {
    "placement-edge-connector",
    "placement-proximity",
    "routing-obstacle",
    "routing-differential-pair",
}


def load_corpus(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def validate_corpus(path: Path) -> dict[str, Any]:
    corpus = load_corpus(path)
    cases = corpus.get("cases") or []
    errors: list[str] = []
    categories = {case.get("category", "") for case in cases}
    missing = sorted(REQUIRED_CATEGORIES - categories)
    if missing:
        errors.append(f"missing required categories: {', '.join(missing)}")
    seen_ids: set[str] = set()
    for case in cases:
        case_id = str(case.get("id", ""))
        if not case_id:
            errors.append("case missing id")
        if case_id in seen_ids:
            errors.append(f"duplicate case id: {case_id}")
        seen_ids.add(case_id)
        try:
            parse_str(yaml.safe_dump(case.get("design") or {}), strict=True)
        except Exception as exc:  # pragma: no cover - message is asserted through errors list
            errors.append(f"{case_id}: design failed strict parse: {exc}")
        expected = case.get("expected") or {}
        if expected.get("current_support") not in {"supported", "partial", "documented-gap"}:
            errors.append(f"{case_id}: invalid current_support")
        if not expected.get("acceptance"):
            errors.append(f"{case_id}: missing acceptance statement")
    return {
        "schema_version": corpus.get("schema_version"),
        "case_count": len(cases),
        "categories": sorted(categories),
        "passed": not errors,
        "errors": errors,
    }


def main(argv: list[str] | None = None, *, trusted_root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Validate correctness fixture corpus")
    parser.add_argument(
        "path", type=Path, nargs="?", default=Path("benchmarks/correctness-placement-routing-corpus.yaml")
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        corpus_path = resolve_trusted_path(args.path, trusted_root=trusted_root, label="corpus path")
        result = validate_corpus(corpus_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
