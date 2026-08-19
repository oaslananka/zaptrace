"""Strict component schema-v2, trust-tier, and monotonic-baseline CI gate.

Repository mode permits honest heuristic records while rejecting schema errors,
unknown keys, removals, trust downgrades, and unsupported stronger claims.
Release mode additionally requires every inspected component to be eligible.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from zaptrace.library.governance import ComponentGovernanceReport
from zaptrace.library.loader import LIBRARY_ROOT, LibraryLoader
from zaptrace.library.trust_baseline import (
    TrustBaselineReport,
    compare_trust_baseline,
    load_trust_baseline,
)


def _markdown(summary: dict[str, object]) -> str:
    status = "blocked" if summary["blocked"] else "passed"
    return "\n".join(
        [
            "# Component Metadata Gate",
            "",
            f"Status: **{status}**",
            "",
            f"Components: `{summary['component_count']}`",
            f"Schema-valid: `{summary['valid_count']}`",
            f"Reviewed-ready: `{summary['reviewed_ready_count']}`",
            f"Release-eligible: `{summary['release_eligible_count']}`",
            f"Release-blocked: `{summary['blocked_component_count']}`",
            f"Human review required: `{summary['human_review_required_count']}`",
            f"Trust tiers: `{json.dumps(summary['trust_tier_counts'], sort_keys=True)}`",
            f"Errors: `{summary['error_count']}` / budget `{summary['max_errors']}`",
            f"Warnings: `{summary['warning_count']}` / budget `{summary['max_warnings']}`",
            f"Mean coverage: `{summary['mean_coverage_score']}`",
            f"Trust baseline: `{summary['trust_baseline_status']}`",
            "",
            "This gate is evidence only and does not claim manufacturer approval.",
            "",
        ]
    )


def _trust_baseline_status(report: TrustBaselineReport | None) -> str:
    if report is None:
        return "not-configured"
    return "passed" if report.passed else "blocked"


def build_gate_summary(
    report: ComponentGovernanceReport,
    *,
    max_errors: int,
    max_warnings: int,
    require_release_eligible: bool = False,
    trust_baseline_report: TrustBaselineReport | None = None,
) -> dict[str, object]:
    error_count = report.error_count
    warning_count = report.warning_count
    blocked = (
        error_count > max_errors
        or warning_count > max_warnings
        or (require_release_eligible and report.blocked_component_count > 0)
        or (trust_baseline_report is not None and not trust_baseline_report.passed)
    )
    return {
        "schema_version": "2.0",
        "gate": "component-metadata",
        "blocked": blocked,
        "component_count": report.component_count,
        "valid_count": report.valid_count,
        "reviewed_ready_count": report.reviewed_ready_count,
        "release_eligible_count": report.release_eligible_count,
        "blocked_component_count": report.blocked_component_count,
        "human_review_required_count": report.human_review_required_count,
        "trust_tier_counts": report.trust_tier_counts,
        "provenance_source_counts": report.provenance_source_counts,
        "repeated_pin_signature_count": len(report.repeated_pin_signatures),
        "require_release_eligible": require_release_eligible,
        "error_count": error_count,
        "warning_count": warning_count,
        "max_errors": max_errors,
        "max_warnings": max_warnings,
        "mean_coverage_score": report.mean_coverage_score,
        "trust_baseline_status": _trust_baseline_status(trust_baseline_report),
        "trust_baseline": (
            trust_baseline_report.model_dump(mode="json") if trust_baseline_report is not None else None
        ),
        "report": report.model_dump(mode="json"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate governed component metadata and enforce a CI budget")
    parser.add_argument("--library-root", type=Path, default=LIBRARY_ROOT)
    parser.add_argument("--max-errors", type=int, default=0, help="Allowed schema error budget")
    parser.add_argument("--max-warnings", type=int, default=0, help="Allowed warning budget")
    parser.add_argument("--output", type=Path, help="Write machine-readable JSON gate evidence")
    parser.add_argument(
        "--trust-baseline",
        type=Path,
        help="Committed component trust baseline JSON used to reject removals and downgrades",
    )
    parser.add_argument("--markdown", type=Path, help="Append Markdown gate summary")
    parser.add_argument(
        "--require-release-eligible",
        action="store_true",
        help="Block when any inspected component is not release/fabrication eligible",
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero when the gate is blocked")
    args = parser.parse_args(argv)

    loader = LibraryLoader(args.library_root)
    specs = loader.load_all()
    report = loader.governance_report()
    trust_report = None
    if args.trust_baseline is not None:
        trust_report = compare_trust_baseline(specs, load_trust_baseline(args.trust_baseline, allowed_root=Path.cwd()))
    summary = build_gate_summary(
        report,
        max_errors=args.max_errors,
        max_warnings=args.max_warnings,
        require_release_eligible=args.require_release_eligible,
        trust_baseline_report=trust_report,
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        with args.markdown.open("a", encoding="utf-8") as handle:
            handle.write(_markdown(summary))
    if summary["blocked"]:
        print(
            "Component metadata gate FAILED: "
            f"errors={summary['error_count']}/{summary['max_errors']} "
            f"warnings={summary['warning_count']}/{summary['max_warnings']}",
            file=sys.stderr,
        )
        return 1 if args.strict else 0
    print(
        "Component metadata gate PASSED: "
        f"errors={summary['error_count']}/{summary['max_errors']} "
        f"warnings={summary['warning_count']}/{summary['max_warnings']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
