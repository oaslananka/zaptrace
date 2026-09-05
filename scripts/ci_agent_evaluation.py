"""Run the deterministic end-to-end agent evaluation corpus for CI or nightly evidence."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.benchmark.agent_evaluation_corpus import (  # noqa: E402
    load_agent_evaluation_corpus,
)
from zaptrace.benchmark.agent_evaluation_models import (  # noqa: E402
    AgentEvaluationCorpus,
    AgentEvaluationMode,
    AgentEvaluationReport,
)
from zaptrace.benchmark.agent_evaluation_runner import run_agent_evaluation  # noqa: E402
from zaptrace.evidence.identity import EvidenceMode, capture_evidence_identity  # noqa: E402

DEFAULT_CORPUS = ROOT / "zaptrace/benchmark/manifests/agent-evaluation-v1.json"
REPORT_SCHEMA = ROOT / "schemas/agent-evaluation-report-v1.schema.json"
_ARTIFACT_MARKER = ".zaptrace-agent-evaluation-output"

EVIDENCE_SOURCE_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "scripts/ci_agent_evaluation.py",
    "zaptrace/benchmark/agent_evaluation_models.py",
    "zaptrace/benchmark/agent_evaluation_corpus.py",
    "zaptrace/benchmark/agent_evaluation_runner.py",
    "zaptrace/benchmark/manifests/agent-evaluation-v1.json",
    "schemas/agent-evaluation-report-v1.schema.json",
    ".github/workflows/quality.yml",
)


def _prepare_artifact_dir(path: Path) -> Path:
    """Create or safely reset a harness-owned artifact directory."""
    resolved = path.resolve()
    forbidden = {Path("/").resolve(), Path.home().resolve(), ROOT.resolve()}
    if resolved in forbidden:
        raise ValueError(f"refusing unsafe artifact directory: {resolved}")
    marker = resolved / _ARTIFACT_MARKER
    if resolved.exists():
        if not marker.is_file():
            raise ValueError(f"existing artifact directory is not harness-owned: {resolved}")
        for child in resolved.iterdir():
            if child == marker:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)
    else:
        resolved.mkdir(parents=True)
    marker.write_text("ZapTrace agent evaluation output\n", encoding="utf-8")
    return resolved


def _validate_report_schema_contract() -> None:
    """Fail closed when the committed machine-readable report schema drifts from the model."""
    committed = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
    expected = AgentEvaluationReport.model_json_schema()
    if committed != expected:
        raise ValueError("committed agent evaluation report schema does not match the runtime model")


def _selected_corpus(corpus: AgentEvaluationCorpus, scenario_ids: list[str]) -> AgentEvaluationCorpus:
    if not scenario_ids:
        return corpus
    wanted = set(scenario_ids)
    known = {scenario.scenario_id for scenario in corpus.scenarios}
    missing = sorted(wanted - known)
    if missing:
        raise ValueError("unknown scenario id(s): " + ", ".join(missing))
    return AgentEvaluationCorpus(
        schema_version=corpus.schema_version,
        corpus_version=corpus.corpus_version,
        scenarios=[scenario for scenario in corpus.scenarios if scenario.scenario_id in wanted],
        non_claims=corpus.non_claims,
    )


def render_markdown(report: dict[str, Any]) -> str:
    """Render a compact human-readable evaluation summary."""
    lines = ["# Agent Evaluation Harness", ""]
    lines.append(f"Mode: `{report['mode']}`")
    lines.append(f"Passed: `{str(report['passed']).lower()}`")
    lines.append(f"Scenarios: `{report['scenario_count']}`")
    lines.append(f"Mismatches: `{report['mismatch_count']}`")
    lines.append(f"Corpus SHA-256: `{report['corpus_sha256']}`")
    lines.append(f"MCP protocol: `{report['protocol_version']}`")
    lines.append(f"Surface contract SHA-256: `{report['surface_contract_sha256']}`")
    lines.append(f"Surface regressions: `{report['surface_regression_count']}`")
    lines.append(f"Report SHA-256: `{report['report_sha256']}`")
    lines.append("")
    identity = report.get("evidence_identity", {})
    if identity:
        lines.extend(
            [
                "## Evidence identity",
                "",
                f"- Source commit: `{identity.get('source_commit', '')}`",
                f"- Lock SHA-256: `{identity.get('lock_sha256', '')}`",
                f"- Identity SHA-256: `{identity.get('identity_sha256', '')}`",
                "",
            ]
        )
    lines.extend(
        [
            "## MCP surface metrics",
            "",
            (
                "| Surface | Visible tools | Calls | Invalid-call rate | Authorization-denial rate | "
                "Expected policy denials | Unexpected policy denials | Runtime failures | Tasks | "
                "Task completion | Replay equivalent |"
            ),
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for surface, metrics in report.get("surface_metrics", {}).items():
        lines.append(
            "| `{surface}` | {tools} | {calls} | {invalid:.2%} | {authorization_denial:.2%} | "
            "{expected_denials} | {unexpected_denials} | {runtime_failures} | {tasks} | {completion:.2%} | "
            "{replay:.2%} |".format(
                surface=surface,
                tools=metrics["visible_tool_count"],
                calls=metrics["planned_call_count"],
                invalid=metrics["invalid_call_rate"],
                authorization_denial=metrics["authorization_denial_rate"],
                expected_denials=metrics["expected_policy_denial_count"],
                unexpected_denials=metrics["unexpected_policy_denial_count"],
                runtime_failures=metrics["runtime_failure_count"],
                tasks=metrics["task_count"],
                completion=metrics["task_completion_rate"],
                replay=metrics["replay_equivalence_rate"],
            )
        )
    lines.append("")

    lines.extend(
        [
            "## Scenarios",
            "",
            "| Scenario | Risk | Expected | Observed | Match | Calls | Artifacts |",
            "|---|---|---|---|---:|---:|---:|",
        ]
    )
    for scenario in report["scenarios"]:
        row = (
            "| `{scenario_id}` | `{risk_class}` | `{expected_outcome}` | `{outcome}` | "
            "`{matched}` | {calls} | {artifacts} |"
        )
        lines.append(
            row.format(
                scenario_id=scenario["scenario_id"],
                risk_class=scenario["risk_class"],
                expected_outcome=scenario["expected_outcome"],
                outcome=scenario["outcome"],
                matched=str(scenario["matched_expectation"]).lower(),
                calls=scenario["tool_call_count"],
                artifacts=len(scenario["artifacts"]),
            )
        )
    lines.extend(["", "## Non-claims", ""])
    for claim in report["non_claims"]:
        lines.append(f"- {claim}")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--mode", choices=[mode.value for mode in AgentEvaluationMode], default="ci")
    parser.add_argument("--scenario", action="append", default=[], help="Run only the named scenario; repeatable")
    parser.add_argument("--artifact-dir", type=Path, default=Path("agent-evaluation-artifacts"))
    parser.add_argument("--output", type=Path, default=Path("agent-evaluation-report.json"))
    parser.add_argument("--markdown", type=Path, default=Path("agent-evaluation-report.md"))
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _validate_report_schema_contract()
        corpus = _selected_corpus(load_agent_evaluation_corpus(args.corpus), args.scenario)
        artifact_dir = _prepare_artifact_dir(args.artifact_dir)
        identity = capture_evidence_identity(
            root=ROOT,
            mode=EvidenceMode.SNAPSHOT,
            source_inputs=EVIDENCE_SOURCE_INPUTS,
        )
        report = run_agent_evaluation(
            corpus,
            mode=AgentEvaluationMode(args.mode),
            output_dir=artifact_dir,
            evidence_identity=identity.model_dump(mode="json"),
        )
        payload = report.model_dump(mode="json")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(payload), encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"agent evaluation configuration error: {exc}", file=sys.stderr)
        return 2
    if args.strict and not report.passed:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
