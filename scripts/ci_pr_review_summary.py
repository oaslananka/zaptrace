"""Generate a safe GitHub PR review summary for ZapTrace validation gates."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
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
SKIPPED = "skipped"

DEFAULT_ARTIFACTS = [
    "zaptrace-proof-pack",
    "zaptrace-validation-reports",
    "zaptrace-manufacturing-artifacts",
    "zaptrace-kicad-oracle",
]
DEFAULT_CONFIG = {
    "mode": "pr-review",
    "fail_on": ["error", "critical"],
    "fab_profile": "jlcpcb-2layer",
    "public_logs": False,
    "upload_artifacts": True,
    "artifact_names": DEFAULT_ARTIFACTS,
}


@dataclass(frozen=True)
class ReviewGate:
    name: str
    status: str
    summary: str = ""
    next_action: str = ""
    artifact: str = ""

    @property
    def blocks_merge(self) -> bool:
        return self.status == FAIL


def _load_mapping(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Expected mapping in {path}")
    return raw


def load_config(path: Path | None, *, trusted_root: Path = ROOT) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if path is not None:
        config_path = resolve_trusted_path(path, trusted_root=trusted_root, label="config path")
        config.update(_load_mapping(config_path))
    return config


def parse_gate(raw: str) -> ReviewGate:
    name, sep, rest = raw.partition("=")
    if not sep or not name.strip() or not rest.strip():
        raise ValueError(f"Gate must use name=status format: {raw!r}")
    parts = rest.split("|", 3)
    status = parts[0].strip().lower()
    if status not in {PASS, FAIL, WARN, SKIPPED}:
        raise ValueError(f"Unsupported gate status for {name}: {status}")
    summary = parts[1].strip() if len(parts) > 1 else ""
    next_action = parts[2].strip() if len(parts) > 2 else ""
    artifact = parts[3].strip() if len(parts) > 3 else ""
    return ReviewGate(name=name.strip(), status=status, summary=summary, next_action=next_action, artifact=artifact)


def build_summary(gates: list[ReviewGate], config: dict[str, Any]) -> dict[str, Any]:
    blocking = [gate for gate in gates if gate.blocks_merge]
    artifacts = config.get("artifact_names") or DEFAULT_ARTIFACTS
    return {
        "schema_version": "1.0",
        "status": FAIL if blocking else PASS,
        "blocked": bool(blocking),
        "blocking_gates": [gate.name for gate in blocking],
        "fab_profile": config.get("fab_profile", ""),
        "public_logs": bool(config.get("public_logs", False)),
        "upload_artifacts": bool(config.get("upload_artifacts", True)),
        "artifact_names": list(artifacts),
        "gates": [asdict(gate) | {"blocks_merge": gate.blocks_merge} for gate in gates],
        "privacy": [
            "Do not print design files, netlists, BOM prices, or secrets to public logs unless explicitly configured.",
            "Prefer artifact uploads with repository access controls over inline PR comments for sensitive evidence.",
            "Redact provider tokens, user-local KiCad paths, and generated manufacturing files from logs.",
        ],
    }


def render_markdown(summary: dict[str, Any]) -> str:
    icon = "❌" if summary["blocked"] else "✅"
    lines = [
        f"## {icon} ZapTrace PR Review",
        "",
        f"Status: `{'blocked' if summary['blocked'] else 'pass'}`",
        f"Fab profile: `{summary['fab_profile']}`",
        f"Public logs: `{'enabled' if summary['public_logs'] else 'disabled'}`",
        "",
        "| Gate | Status | Blocks Merge | Summary | Next Action | Artifact |",
        "|------|--------|--------------|---------|-------------|----------|",
    ]
    for gate in summary["gates"]:
        lines.append(
            f"| `{gate['name']}` | `{gate['status']}` | "
            f"{'yes' if gate['blocks_merge'] else 'no'} | "
            f"{gate['summary'] or '-'} | {gate['next_action'] or '-'} | `{gate['artifact'] or '-'}` |"
        )
    lines.extend(["", "### Deterministic artifacts", ""])
    for artifact in summary["artifact_names"]:
        lines.append(f"- `{artifact}`")
    lines.extend(["", "### Security and privacy", ""])
    for item in summary["privacy"]:
        lines.append(f"- {item}")
    lines.append("")
    if summary["blocked"]:
        lines.append("Merge should remain blocked until failing gates are fixed or explicitly reconfigured.")
    else:
        lines.append("No blocking ZapTrace gates were reported by this run.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, trusted_root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Generate a ZapTrace GitHub PR review summary")
    parser.add_argument("--config", type=Path, help="Optional PR review YAML config")
    parser.add_argument("--gate", action="append", default=[], help="Gate as name=status|summary|next action|artifact")
    parser.add_argument("--output", type=Path, help="Write JSON summary")
    parser.add_argument("--markdown", type=Path, help="Write Markdown PR comment")
    parser.add_argument("--strict", action="store_true", help="Return non-zero if merge is blocked")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config, trusted_root=trusted_root)
        gates = [parse_gate(raw) for raw in args.gate]
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    summary = build_summary(gates, config)
    markdown = render_markdown(summary)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    else:
        print(markdown)

    if args.strict and summary["blocked"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
