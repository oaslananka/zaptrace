"""Build a machine-readable snapshot or tagged-release gate summary.

GitHub Actions passes job results as ``--gate name=result`` pairs. The script
normalizes them into ZapTrace's release vocabulary and attaches the shared
source/toolchain identity needed to audit the exact run.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.evidence.identity import (  # noqa: E402
    EvidenceIdentity,
    EvidenceMode,
    capture_evidence_identity,
    parse_name_value_pairs,
)

PASS = "pass"
FAIL = "fail"
SKIP_APPROVED = "skip-approved"
SKIP_UNAPPROVED = "skip-unapproved"
WARN = "warn"

_BLOCKING = {FAIL, SKIP_UNAPPROVED}
_VALID = {PASS, FAIL, SKIP_APPROVED, SKIP_UNAPPROVED, WARN}
_DEFAULT_SOURCE_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "scripts/ci_release_gate.py",
    ".github/workflows/quality.yml",
)

_CI_RESULT_MAP = {
    "success": PASS,
    "pass": PASS,
    "passed": PASS,
    "failure": FAIL,
    "failed": FAIL,
    "fail": FAIL,
    "cancelled": FAIL,
    "canceled": FAIL,
    "timed_out": FAIL,
    "timed-out": FAIL,
    "action_required": FAIL,
    "startup_failure": FAIL,
    "skipped": SKIP_APPROVED,
    "skip-approved": SKIP_APPROVED,
    "skip_unapproved": SKIP_UNAPPROVED,
    "skip-unapproved": SKIP_UNAPPROVED,
    "neutral": WARN,
    "warn": WARN,
    "warning": WARN,
}


@dataclass(frozen=True)
class GateRecord:
    name: str
    status: str
    raw_result: str
    reason: str = ""
    required: bool = True

    @property
    def blocks_release(self) -> bool:
        return self.required and self.status in _BLOCKING


def normalize_status(raw_result: str) -> str:
    """Normalize a CI/native result into the ZapTrace release-gate vocabulary."""
    key = raw_result.strip().lower()
    return _CI_RESULT_MAP.get(key, WARN)


def parse_name_value(value: str, *, option: str) -> tuple[str, str]:
    parsed = parse_name_value_pairs([value], option=option)
    return next(iter(parsed.items()))


def build_records(gates: list[str], skip_reasons: list[str]) -> list[GateRecord]:
    reasons = parse_name_value_pairs(skip_reasons, option="--skip-reason")
    records: list[GateRecord] = []
    for item in gates:
        name, raw_result = parse_name_value(item, option="--gate")
        status = normalize_status(raw_result)
        reason = reasons.get(name, "")
        if status == SKIP_APPROVED and not reason:
            status = SKIP_UNAPPROVED
            reason = "missing approved skip reason"
        if status not in _VALID:
            status = WARN
        records.append(GateRecord(name=name, raw_result=raw_result, status=status, reason=reason))
    return records


def require_external_oracles(
    records: list[GateRecord],
    required_oracles: list[str],
    skip_reasons: list[str],
) -> list[GateRecord]:
    """Add blocking records for required external oracles that are absent."""
    if not required_oracles:
        return records

    reasons = parse_name_value_pairs(skip_reasons, option="--skip-reason")
    existing = {record.name for record in records}
    out = list(records)
    for name in required_oracles:
        if name in existing:
            continue
        reason = reasons.get(name, "required external oracle evidence missing")
        status = SKIP_APPROVED if name in reasons else SKIP_UNAPPROVED
        out.append(GateRecord(name=name, raw_result="missing", status=status, reason=reason))
    return out


def render_markdown(records: list[GateRecord], identity: EvidenceIdentity) -> str:
    blocked = [record for record in records if record.blocks_release]
    mode_title = "Release" if identity.mode == EvidenceMode.RELEASE else "Snapshot"
    lines = [f"# ZapTrace {mode_title} Evidence Summary", ""]
    lines.extend(
        [
            f"- Package version: `{identity.package_version}`",
            f"- Source commit: `{identity.source_commit}`",
            f"- Source ref: `{identity.source_ref}`",
            f"- Dirty working tree: `{str(identity.dirty).lower()}`",
            f"- Lock SHA-256: `{identity.lock_sha256}`",
            f"- Identity SHA-256: `{identity.identity_sha256}`",
            f"- Generated: `{identity.generated_at}`",
            "",
            "| Gate | Status | Blocks Release | Reason | Raw Result |",
            "|------|--------|----------------|--------|------------|",
        ]
    )
    for record in records:
        lines.append(
            f"| `{record.name}` | `{record.status}` | {'yes' if record.blocks_release else 'no'} | "
            f"{record.reason or '-'} | `{record.raw_result}` |"
        )
    lines.append("")
    if blocked:
        lines.append(f"**Release blocked:** {len(blocked)} blocking gate(s).")
        for record in blocked:
            lines.append(f"- `{record.name}`: `{record.status}` ({record.reason or record.raw_result})")
    else:
        lines.append("**Release gate summary:** no blocking gates in this run.")
    lines.extend(
        [
            "",
            (
                "This summary is evidence only. It does not claim fabrication readiness, manufacturer approval, "
                "or no-human-review correctness."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def build_summary(records: list[GateRecord], identity: EvidenceIdentity) -> dict[str, object]:
    blocked = [record for record in records if record.blocks_release]
    return {
        "schema_version": "2.0",
        "evidence_kind": "tagged-release" if identity.mode == EvidenceMode.RELEASE else "development-snapshot",
        "release": identity.source_ref.removeprefix("refs/tags/") if identity.mode == EvidenceMode.RELEASE else None,
        "evidence_identity": identity.model_dump(mode="json"),
        "status_vocabulary": [PASS, FAIL, SKIP_APPROVED, SKIP_UNAPPROVED, WARN],
        "blocked": bool(blocked),
        "blocking_gates": [record.name for record in blocked],
        "gates": [asdict(record) | {"blocks_release": record.blocks_release} for record in records],
        "non_claims": [
            "not fabrication-ready",
            "not manufacturer-approved",
            "not no-human-review autonomous signoff",
        ],
    }


_HELP_EPILOG = """
Examples:
  python scripts/ci_release_gate.py --gate lint=success --gate tests=success
  python scripts/ci_release_gate.py --mode snapshot --gate lint=success --required-oracle kicad-oracle --strict
  python scripts/ci_release_gate.py --mode release --gate tests=success --strict

Notes:
  Snapshot evidence is used for pull requests, branches, schedules, and local
  validation. Release evidence requires refs/tags/v<package-version> and a clean
  tree unless --dirty-override-id records an explicit policy approval.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate an identity-bound release-gate summary",
        epilog=_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--gate", action="append", default=[], help="Gate result in name=value form")
    parser.add_argument("--skip-reason", action="append", default=[], help="Approved skip reason in name=reason form")
    parser.add_argument(
        "--required-oracle",
        action="append",
        default=[],
        help="Required external oracle gate name; missing entries block unless approved via --skip-reason",
    )
    parser.add_argument("--mode", choices=tuple(EvidenceMode), default=EvidenceMode.SNAPSHOT.value)
    parser.add_argument("--source-ref", help="Override the detected Git/GitHub source ref")
    parser.add_argument("--source-commit", help="Override the detected full Git commit")
    dirty_group = parser.add_mutually_exclusive_group()
    dirty_group.add_argument("--dirty", dest="dirty", action="store_const", const=True, help="Record a dirty tree")
    dirty_group.add_argument("--clean", dest="dirty", action="store_const", const=False, help="Record a clean tree")
    parser.set_defaults(dirty=None)
    parser.add_argument("--dirty-override-id", default="", help="Policy approval identifier for dirty release evidence")
    parser.add_argument(
        "--source-input",
        action="append",
        default=[],
        help="Repository-relative source input included in the stale-evidence hash",
    )
    parser.add_argument(
        "--tool-version",
        action="append",
        default=[],
        help="Relevant tool identity in name=value form",
    )
    parser.add_argument("--output", type=Path, help="Write JSON evidence to this path")
    parser.add_argument("--markdown", type=Path, help="Append Markdown summary to this path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when a required gate blocks release")
    args = parser.parse_args(argv)

    try:
        records = build_records(args.gate, args.skip_reason)
        records = require_external_oracles(records, args.required_oracle, args.skip_reason)
        toolchain = parse_name_value_pairs(args.tool_version, option="--tool-version") or None
        identity = capture_evidence_identity(
            root=ROOT,
            mode=args.mode,
            source_inputs=args.source_input or _DEFAULT_SOURCE_INPUTS,
            source_commit=args.source_commit,
            source_ref=args.source_ref,
            dirty=args.dirty,
            dirty_override_id=args.dirty_override_id,
            toolchain=toolchain,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not records:
        print("ERROR: at least one --gate entry is required", file=sys.stderr)
        return 2

    summary = build_summary(records, identity)
    markdown = render_markdown(records, identity)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        with args.markdown.open("a", encoding="utf-8") as handle:
            handle.write(markdown)
    else:
        print(markdown)

    if args.strict and summary["blocked"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
