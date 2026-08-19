"""Run the simulation-backed sign-off evidence corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover - direct script bootstrap
    sys.path.insert(0, str(ROOT))

from zaptrace.analysis.simulation_signoff import resolve_simulation_output_path  # noqa: E402
from zaptrace.benchmark.simulation_signoff_corpus import (  # noqa: E402
    DEFAULT_SIMULATION_SIGNOFF_MANIFEST,
    run_simulation_signoff_corpus,
)
from zaptrace.evidence.identity import EvidenceMode, capture_evidence_identity  # noqa: E402

EVIDENCE_SOURCE_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "scripts/ci_simulation_signoff.py",
    "zaptrace/analysis/simulation_signoff.py",
    "zaptrace/analysis/spice_sim.py",
    "zaptrace/analysis/sim_gate.py",
    "zaptrace/analysis/regulator_fixture.py",
    "zaptrace/analysis/usbc_inrush_gate.py",
    "zaptrace/analysis/ac_stability_gate.py",
    "zaptrace/analysis/rail_current.py",
    "zaptrace/analysis/regulator_margin.py",
    "zaptrace/analysis/current_density.py",
    "zaptrace/analysis/sipi_risk.py",
    "zaptrace/benchmark/simulation_signoff_corpus.py",
    "zaptrace/benchmark/manifests/simulation-signoff-v1.json",
    "zaptrace/proof/manifest.py",
    "zaptrace/proof/pack.py",
    "zaptrace/proof/simulation_signoff.py",
    "schemas/simulation-signoff-report-v1.schema.json",
    ".github/workflows/quality.yml",
)


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Simulation Sign-off", ""]
    lines.extend(
        [
            f"Passed: `{str(report['passed']).lower()}`",
            f"Families with evidence: `{report['evidence_family_count']}/{report['family_count']}`",
            f"Live ngspice passes: `{report['live_simulation_pass_count']}`",
            f"Blocked families: `{report['blocked_family_count']}`",
            f"Human-review families: `{report['human_review_family_count']}`",
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
            "| Family | Checks | Live passes | Failed | Skipped | Human review | Blocked |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for family in report.get("families", []):
        lines.append(
            "| `{family_id}` | {checks} | {live} | {failed} | {skipped} | {review} | `{blocked}` |".format(
                family_id=family["family_id"],
                checks=family["check_count"],
                live=family["live_simulation_pass_count"],
                failed=family["fail_count"],
                skipped=family["skipped_count"],
                review=family["human_review_count"],
                blocked=str(family["blocked"]).lower(),
            )
        )
    if report.get("acceptance_failures"):
        lines.extend(["", "## Acceptance failures", ""])
        lines.extend(f"- {item}" for item in report["acceptance_failures"])
    lines.extend(["", "## Non-claims", ""])
    lines.extend(f"- {item}" for item in report.get("non_claims", []))
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_SIMULATION_SIGNOFF_MANIFEST)
    parser.add_argument("--trusted-output-root", type=Path, default=Path("."))
    parser.add_argument("--artifact-dir", type=Path, default=Path("simulation-signoff-artifacts"))
    parser.add_argument("--output", type=Path, default=Path("simulation-signoff-report.json"))
    parser.add_argument("--markdown", type=Path, default=Path("simulation-signoff-report.md"))
    parser.add_argument("--require-live-simulation", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        trusted_root = args.trusted_output_root.resolve(strict=True)
        artifact_dir = resolve_simulation_output_path(args.artifact_dir, trusted_root=trusted_root)
        output_path = resolve_simulation_output_path(args.output, trusted_root=trusted_root, require_json=True)
        markdown_path = resolve_simulation_output_path(args.markdown, trusted_root=trusted_root)
        if markdown_path.suffix.lower() != ".md":
            raise ValueError("simulation sign-off Markdown output must use .md")
        identity = capture_evidence_identity(
            root=ROOT,
            mode=EvidenceMode.SNAPSHOT,
            source_inputs=EVIDENCE_SOURCE_INPUTS,
        )
        report = run_simulation_signoff_corpus(
            artifact_dir,
            manifest_path=args.manifest,
            evidence_identity=identity.model_dump(mode="json"),
            require_live_simulation=args.require_live_simulation,
            trusted_output_root=trusted_root,
        )
        payload = report.model_dump(mode="json")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"simulation sign-off configuration error: {exc}", file=sys.stderr)
        return 2
    if args.strict and not report.passed:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
