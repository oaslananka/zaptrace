"""Run the four-family release verify/repair convergence benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.benchmark.release_convergence import run_release_convergence_benchmark  # noqa: E402
from zaptrace.evidence.identity import EvidenceMode, capture_evidence_identity  # noqa: E402
from zaptrace.pipeline.verify_repair_models import resolve_verify_repair_output_path  # noqa: E402

EVIDENCE_SOURCE_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "scripts/ci_release_verify_repair.py",
    "zaptrace/pipeline/verify_repair_models.py",
    "zaptrace/pipeline/verify_repair.py",
    "zaptrace/pipeline/verify_repair_gates.py",
    "zaptrace/benchmark/release_convergence.py",
    "zaptrace/proof/manifest.py",
    "zaptrace/proof/pack.py",
    "zaptrace/proof/verify_repair.py",
    "schemas/release-verify-repair-report-v1.schema.json",
    ".github/workflows/quality.yml",
)


def render_markdown(report: dict[str, Any]) -> str:
    """Render a compact benchmark summary for the GitHub step summary."""
    lines = ["# Release Verify/Repair Convergence", ""]
    lines.extend(
        [
            f"Passed: `{str(report['passed']).lower()}`",
            f"Families: `{report['converged_count']}/{report['family_count']}`",
            f"Policy: `{report['policy_version']}`",
            f"Policy SHA-256: `{report['policy_sha256']}`",
            f"Report SHA-256: `{report['report_sha256']}`",
            "",
        ]
    )
    identity = report.get("evidence_identity", {})
    if identity:
        lines.extend(
            [
                "## Evidence identity",
                "",
                f"- Source commit: `{identity.get('source_commit', '')}`",
                f"- Lock SHA-256: `{identity.get('lock_sha256', '')}`",
                f"- Identity SHA-256: `{identity.get('evidence_identity_hash', identity.get('identity_sha256', ''))}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Families",
            "",
            "| Family | Converged | Stop reason | Iterations | Repairs |",
            "|---|---:|---|---:|---:|",
        ]
    )
    for family in report.get("families", []):
        lines.append(
            "| `{family_id}` | `{converged}` | `{stop_reason}` | {iterations} | {repairs} |".format(
                family_id=family["family_id"],
                converged=str(family["converged"]).lower(),
                stop_reason=family["stop_reason"],
                iterations=family["iterations_used"],
                repairs=family["repair_count"],
            )
        )
    lines.extend(["", "## Non-claims", ""])
    lines.extend(f"- {claim}" for claim in report.get("non_claims", []))
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trusted-output-root", type=Path, default=Path("."))
    parser.add_argument("--artifact-dir", type=Path, default=Path("release-verify-repair-artifacts"))
    parser.add_argument("--output", type=Path, default=Path("release-convergence-report.json"))
    parser.add_argument("--markdown", type=Path, default=Path("release-convergence-report.md"))
    parser.add_argument("--family", action="append", default=[], help="Run only this family; repeatable")
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        trusted_root = args.trusted_output_root.resolve(strict=True)
        artifact_dir = resolve_verify_repair_output_path(args.artifact_dir, trusted_root=trusted_root)
        output_path = resolve_verify_repair_output_path(args.output, trusted_root=trusted_root, require_json=True)
        markdown_path = resolve_verify_repair_output_path(args.markdown, trusted_root=trusted_root)
        if markdown_path.suffix.lower() != ".md":
            raise ValueError("release verify/repair Markdown output must use .md")
        identity = capture_evidence_identity(
            root=ROOT,
            mode=EvidenceMode.SNAPSHOT,
            source_inputs=EVIDENCE_SOURCE_INPUTS,
        )
        report = run_release_convergence_benchmark(
            artifact_dir,
            family_ids=args.family or None,
            evidence_identity=identity.model_dump(mode="json"),
            trusted_output_root=trusted_root,
        )
        payload = report.model_dump(mode="json")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"release verify/repair configuration error: {exc}", file=sys.stderr)
        return 2
    if args.strict and not report.passed:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
