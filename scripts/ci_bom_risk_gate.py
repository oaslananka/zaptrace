#!/usr/bin/env python3
"""Hardware CI/CD — BOM risk gate script.

Parses a ZapTrace BOM JSON or CSV and fails CI if any component exceeds the
allowed risk level. Intended as a required CI check before a design release.

Exit codes:
  0 — BOM risk gate passed (no components above the threshold).
  1 — BOM risk gate failed (one or more components above the threshold).
  2 — Input/config error.

Usage:
  python scripts/ci_bom_risk_gate.py bom.json [--max-risk high] [--pr-comment pr_comment.md]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.security.paths import resolve_trusted_path  # noqa: E402

# Risk level ordering (lowest to highest).
_RISK_ORDER = ["low", "medium", "high", "critical", "obsolete"]


def _risk_rank(level: str) -> int:
    return _RISK_ORDER.index(level.lower()) if level.lower() in _RISK_ORDER else -1


def _load_bom(path: Path) -> list[dict[str, str]]:
    """Load BOM from JSON or CSV (auto-detected by extension)."""
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix.lower() == ".csv":
        import csv

        with path.open(encoding="utf-8") as f:
            return list(csv.DictReader(f))
    raise ValueError(f"Unsupported BOM format: {path.suffix}. Use .json or .csv")


def _gate(bom: list[dict[str, str]], max_risk: str) -> tuple[bool, list[dict[str, str]]]:
    """Return (passed, failing_rows)."""
    threshold_rank = _risk_rank(max_risk)
    failing = [row for row in bom if _risk_rank(row.get("risk", "low")) > threshold_rank]
    return not failing, failing


def _write_pr_comment(failing: list[dict[str, str]], max_risk: str, output_path: Path) -> None:
    """Write a GitHub PR comment markdown file summarising failing components."""
    lines = [
        "## :warning: BOM Risk Gate FAILED",
        "",
        f"The following component(s) exceed the allowed risk level (`{max_risk}`):",
        "",
        "| Ref | MPN | Risk | Reason |",
        "| --- | --- | ---- | ------ |",
    ]
    for row in failing:
        ref = row.get("reference", row.get("ref", "?"))
        mpn = row.get("mpn", row.get("manufacturer_part_number", "?"))
        risk = row.get("risk", "?")
        reason = row.get("risk_reason", row.get("reason", "see BOM report"))
        lines.append(f"| `{ref}` | `{mpn}` | **{risk}** | {reason} |")
    lines += ["", "_Resolve by replacing obsolete/high-risk parts or updating alternates._"]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None, *, trusted_root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="BOM risk gate for hardware CI/CD")
    parser.add_argument("bom", help="Path to BOM JSON or CSV file")
    parser.add_argument(
        "--max-risk",
        default="medium",
        choices=_RISK_ORDER,
        help="Maximum allowed risk level (default: medium)",
    )
    parser.add_argument("--pr-comment", default=None, help="Write a GitHub PR comment markdown to this file on failure")
    args = parser.parse_args(argv)

    try:
        bom_path = resolve_trusted_path(args.bom, trusted_root=trusted_root, label="BOM path")
        pr_path = (
            resolve_trusted_path(args.pr_comment, trusted_root=trusted_root, label="PR comment path")
            if args.pr_comment
            else None
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not bom_path.exists():
        print("ERROR: BOM file not found inside repository root", file=sys.stderr)
        return 2

    try:
        bom = _load_bom(bom_path)
    except (OSError, ValueError) as exc:
        print(f"ERROR: Could not load BOM: {exc}", file=sys.stderr)
        return 2

    passed, failing = _gate(bom, args.max_risk)

    if passed:
        print(f"BOM risk gate PASSED: {len(bom)} components, all at or below '{args.max_risk}' risk.")
        return 0

    print(f"BOM risk gate FAILED: {len(failing)} component(s) exceed '{args.max_risk}' risk threshold:")
    for row in failing:
        ref = row.get("reference", row.get("ref", "?"))
        risk = row.get("risk", "?")
        mpn = row.get("mpn", "?")
        print(f"  {ref}: {mpn} [{risk}]")

    if pr_path is not None:
        _write_pr_comment(failing, args.max_risk, pr_path)
        print(f"PR comment written to: {args.pr_comment}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
