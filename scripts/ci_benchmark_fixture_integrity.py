"""Generate benchmark fixture integrity evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.benchmark.integrity import (  # noqa: E402
    FixtureIntegrityReport,
    evaluate_fixture_integrity,
)
from zaptrace.evidence.identity import EvidenceIdentity, EvidenceMode, capture_evidence_identity  # noqa: E402

EVIDENCE_SOURCE_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "scripts/ci_benchmark_fixture_integrity.py",
    "zaptrace/benchmark/families.py",
    "zaptrace/benchmark/integrity.py",
)


def evidence_payload(
    report: FixtureIntegrityReport,
    *,
    identity: EvidenceIdentity | None = None,
) -> dict[str, object]:
    identity = identity or capture_evidence_identity(
        root=ROOT,
        mode=EvidenceMode.SNAPSHOT,
        source_inputs=EVIDENCE_SOURCE_INPUTS,
    )
    payload = report.model_dump(mode="json")
    payload["schema_version"] = "2.0"
    payload["evidence_identity"] = identity.model_dump(mode="json")
    return payload


def evidence_json(report: FixtureIntegrityReport, *, identity: EvidenceIdentity | None = None) -> str:
    return json.dumps(evidence_payload(report, identity=identity), indent=2, sort_keys=True) + "\n"


def render_markdown(report: FixtureIntegrityReport, *, identity: EvidenceIdentity | None = None) -> str:
    """Render fixture integrity as a compact Markdown report."""
    identity_data = evidence_payload(report, identity=identity)["evidence_identity"]
    if not isinstance(identity_data, dict):
        raise TypeError("evidence_identity must serialize as a mapping")
    lines = ["# Benchmark Fixture Integrity", ""]
    lines.append("## Evidence identity")
    lines.append("")
    lines.append(f"- Mode: `{identity_data['mode']}`")
    lines.append(f"- Source commit: `{identity_data['source_commit']}`")
    lines.append(f"- Identity SHA-256: `{identity_data['identity_sha256']}`")
    lines.append("")
    lines.append(f"Passed families: {report.passed_family_count}/{report.family_count}")
    lines.append(f"Failed checks: {report.failed_check_count}")
    lines.append("")
    lines.append("| Family | Status | Failed checks |")
    lines.append("|--------|--------|---------------|")
    for family in report.families:
        lines.append(f"| `{family.family_id}` | `{family.status}` | {family.failed_check_count} |")
    lines.append("")
    lines.append("## Non-claims")
    lines.append("")
    for claim in report.non_claims:
        lines.append(f"- {claim}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate benchmark fixture integrity evidence")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root to inspect")
    parser.add_argument("--output", type=Path, help="Write JSON integrity evidence to this path")
    parser.add_argument("--markdown", type=Path, help="Write Markdown integrity summary to this path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero if any integrity check fails")
    args = parser.parse_args(argv)

    identity = capture_evidence_identity(
        root=ROOT,
        mode=EvidenceMode.SNAPSHOT,
        source_inputs=EVIDENCE_SOURCE_INPUTS,
    )
    report = evaluate_fixture_integrity(args.root)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(evidence_json(report, identity=identity), encoding="utf-8")
    else:
        print(evidence_json(report, identity=identity), end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report, identity=identity), encoding="utf-8")
    if args.strict and not report.passed:
        print(f"benchmark fixture integrity failed with {report.failed_check_count} failed check(s)")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
