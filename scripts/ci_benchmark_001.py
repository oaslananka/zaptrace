"""Deterministic release-blocking harness for benchmark 001.

The harness validates the benchmark contract before generated board artifacts are
available. It is intentionally deterministic and CI-friendly: no network calls,
no EDA tool dependency, and no hidden mutation. Later benchmark runs can feed
measured ERC/DRC/DFM/BOM/round-trip results into the same report shape.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from zaptrace.evidence.identity import EvidenceIdentity, EvidenceMode, capture_evidence_identity

PASS = "pass"
FAIL = "fail"

DEFAULT_SPEC = Path("benchmarks/001-esp32-sensor/requirements.yaml")
ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_SOURCE_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "scripts/ci_benchmark_001.py",
    "benchmarks/001-esp32-sensor/requirements.yaml",
    "docs/reports/benchmark-001-bom-risk-sample.json",
)
REQUIRED_FUNCTIONS = {
    "usb_c_power_input",
    "lipo_battery_connector",
    "battery_charger",
    "regulator_3v3",
    "i2c_sensor",
    "programming_debug_header",
    "status_io",
    "mounting",
}
REQUIRED_THRESHOLDS = {
    ("erc", "max_errors"),
    ("erc", "max_warnings"),
    ("drc", "max_errors"),
    ("drc", "max_warnings"),
    ("dfm", "max_critical"),
    ("dfm", "max_high"),
    ("bom", "max_unresolved_required_parts"),
    ("bom", "max_obsolete_required_parts"),
    ("round_trip", "min_fidelity_score"),
    ("proof_pack", "require_manifest"),
    ("proof_pack", "require_artifact_hashes"),
    ("proof_pack", "min_required_checks"),
    ("agent_flow", "max_human_interventions"),
    ("agent_flow", "max_agent_decision_count"),
}
REQUIRED_ARTIFACT_IDS = {
    "requirements",
    "schematic",
    "pcb",
    "bom",
    "manufacturing_bundle",
    "proof_pack",
    "benchmark_report",
}


@dataclass(frozen=True)
class BenchmarkCheck:
    name: str
    status: str
    message: str
    required: bool = True
    details: dict[str, Any] | None = None

    @property
    def blocks_release(self) -> bool:
        return self.required and self.status == FAIL


def _as_mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def _as_sequence(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return value


def load_spec(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read benchmark spec: {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in benchmark spec: {path}: {exc}") from exc
    return _as_mapping(raw, field="benchmark spec")


def _resolve_benchmark_input(
    value: Any,
    *,
    root: Path,
    field: str,
    allowed_suffixes: set[str] | None = None,
) -> Path:
    """Resolve a benchmark input without allowing reads outside *root*."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty path")
    trusted_root = root.resolve(strict=True)
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = trusted_root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(trusted_root)
    except ValueError as exc:
        raise ValueError(f"{field} escapes benchmark root: {value}") from exc
    if allowed_suffixes is not None and resolved.suffix.lower() not in allowed_suffixes:
        expected = ", ".join(sorted(allowed_suffixes))
        raise ValueError(f"{field} must use one of: {expected}")
    return resolved


def _check_required_metadata(spec: dict[str, Any]) -> BenchmarkCheck:
    missing = [key for key in ["schema_version", "id", "name"] if not spec.get(key)]
    if missing:
        return BenchmarkCheck(
            name="metadata",
            status=FAIL,
            message="Missing required benchmark metadata",
            details={"missing": missing},
        )
    if spec.get("deterministic_mode") is not True:
        return BenchmarkCheck(
            name="metadata",
            status=FAIL,
            message="Benchmark must declare deterministic_mode: true",
        )
    return BenchmarkCheck(name="metadata", status=PASS, message="Benchmark metadata is deterministic and complete")


def _check_release_gate(spec: dict[str, Any]) -> BenchmarkCheck:
    release_gate = _as_mapping(spec.get("release_gate", {}), field="release_gate")
    release_gate_keys = ["required", "gate_name", "milestone_readiness", "blocks_release"]
    missing = [key for key in release_gate_keys if key not in release_gate]
    if missing:
        return BenchmarkCheck(
            name="release-gate-link",
            status=FAIL,
            message="Release-gate metadata is incomplete",
            details={"missing": missing},
        )
    if release_gate.get("required") is not True or release_gate.get("blocks_release") is not True:
        return BenchmarkCheck(
            name="release-gate-link",
            status=FAIL,
            message="Benchmark 001 must be release-blocking once enabled",
            details=release_gate,
        )
    if release_gate.get("milestone_readiness") != "M1":
        return BenchmarkCheck(
            name="release-gate-link",
            status=FAIL,
            message="Benchmark result must link to M1 readiness",
            details=release_gate,
        )
    return BenchmarkCheck(
        name="release-gate-link",
        status=PASS,
        message="Benchmark gate is release-blocking and linked to M1 readiness",
        details=release_gate,
    )


def _check_required_functions(spec: dict[str, Any]) -> BenchmarkCheck:
    board_target = _as_mapping(spec.get("board_target", {}), field="board_target")
    functions = _as_sequence(board_target.get("required_functions", []), field="board_target.required_functions")
    found = {item.get("id") for item in functions if isinstance(item, dict)}
    missing = sorted(REQUIRED_FUNCTIONS - found)
    incomplete = [
        item.get("id", "<missing-id>")
        for item in functions
        if isinstance(item, dict)
        and item.get("id") in REQUIRED_FUNCTIONS
        and (not item.get("required_parts") or not isinstance(item.get("required_nets"), list))
    ]
    if missing or incomplete:
        return BenchmarkCheck(
            name="board-requirements",
            status=FAIL,
            message="Board target is missing required functions or function details",
            details={"missing": missing, "incomplete": incomplete},
        )
    return BenchmarkCheck(
        name="board-requirements",
        status=PASS,
        message=f"All {len(REQUIRED_FUNCTIONS)} required board functions are specified",
    )


def _check_constraints(spec: dict[str, Any]) -> BenchmarkCheck:
    constraints = _as_mapping(spec.get("constraints", {}), field="constraints")
    required = ["power_tree", "usb_c", "battery", "i2c", "decoupling", "keepouts", "testpoints"]
    missing = [key for key in required if key not in constraints]
    if missing:
        return BenchmarkCheck(
            name="constraints",
            status=FAIL,
            message="Benchmark constraints are incomplete",
            details={"missing": missing},
        )
    return BenchmarkCheck(
        name="constraints",
        status=PASS,
        message="Power, USB-C, battery, I2C, DFM, and testpoint constraints are present",
    )


def _check_expected_artifacts(spec: dict[str, Any], *, root: Path) -> BenchmarkCheck:
    artifacts = _as_sequence(spec.get("expected_artifacts", []), field="expected_artifacts")
    found = {item.get("id") for item in artifacts if isinstance(item, dict)}
    missing = sorted(REQUIRED_ARTIFACT_IDS - found)
    required_without_path = [
        item.get("id", "<missing-id>")
        for item in artifacts
        if isinstance(item, dict) and item.get("required") is True and not item.get("path")
    ]
    committed_missing: list[str] = []
    invalid_paths: list[str] = []
    for item in artifacts:
        if not isinstance(item, dict) or item.get("stage") != "committed":
            continue
        try:
            path = _resolve_benchmark_input(
                item.get("path"),
                root=root,
                field=f"expected_artifacts.{item.get('id', '<missing-id>')}.path",
            )
        except ValueError as exc:
            invalid_paths.append(str(exc))
            continue
        if not path.exists():
            committed_missing.append(str(path))
    if missing or required_without_path or committed_missing or invalid_paths:
        details = {
            "missing_artifact_ids": missing,
            "required_without_path": required_without_path,
            "committed_missing": committed_missing,
        }
        if invalid_paths:
            details["invalid_paths"] = invalid_paths
        return BenchmarkCheck(
            name="expected-artifacts",
            status=FAIL,
            message="Expected artifact contract is incomplete",
            details=details,
        )
    return BenchmarkCheck(
        name="expected-artifacts",
        status=PASS,
        message=f"All {len(REQUIRED_ARTIFACT_IDS)} expected artifact records are present",
    )


def _check_thresholds(spec: dict[str, Any]) -> BenchmarkCheck:
    thresholds = _as_mapping(spec.get("acceptance_thresholds", {}), field="acceptance_thresholds")
    missing = []
    for section, key in REQUIRED_THRESHOLDS:
        if not isinstance(thresholds.get(section), dict) or key not in thresholds[section]:
            missing.append(f"{section}.{key}")
    round_trip = thresholds.get("round_trip", {})
    proof_pack = thresholds.get("proof_pack", {})
    invalid = []
    if isinstance(round_trip, dict) and float(round_trip.get("min_fidelity_score", 0.0)) < 0.95:
        invalid.append("round_trip.min_fidelity_score must be >= 0.95")
    if isinstance(proof_pack, dict) and int(proof_pack.get("min_required_checks", 0)) < 6:
        invalid.append("proof_pack.min_required_checks must be >= 6")
    if missing or invalid:
        return BenchmarkCheck(
            name="acceptance-thresholds",
            status=FAIL,
            message="Acceptance thresholds are missing or below release-blocking expectations",
            details={"missing": missing, "invalid": invalid},
        )
    return BenchmarkCheck(
        name="acceptance-thresholds",
        status=PASS,
        message="ERC/DRC/DFM/BOM/round-trip/proof thresholds are present",
    )


def _fab_profile_evidence_errors(evidence: dict[str, Any], board: dict[str, Any]) -> list[str]:
    fab_profile = evidence.get("fab_profile", {})
    if not isinstance(fab_profile, dict):
        return ["scoring_evidence.fab_profile must be a mapping"]
    errors: list[str] = []
    if fab_profile.get("name") != board.get("fab_profile"):
        errors.append("fab profile evidence must match board target fab_profile")
    if fab_profile.get("layers") != board.get("layers"):
        errors.append("fab profile evidence layers must match board target layers")
    for key in ["min_clearance_mm", "min_trace_width_mm", "min_drill_mm"]:
        if key not in fab_profile:
            errors.append(f"fab profile evidence missing {key}")
    return errors


def _proof_pack_evidence_errors(evidence: dict[str, Any], *, root: Path) -> list[str]:
    try:
        proof_path = _resolve_benchmark_input(
            evidence.get("proof_pack_manifest"),
            root=root,
            field="scoring_evidence.proof_pack_manifest",
            allowed_suffixes={".yaml", ".yml"},
        )
    except ValueError as exc:
        return [str(exc)]
    if not proof_path.exists():
        return [f"proof-pack manifest missing: {proof_path}"]
    try:
        proof = load_spec(proof_path)
    except ValueError as exc:
        return [str(exc)]
    checks = proof.get("checks", [])
    if not isinstance(checks, list) or len(checks) < 6:
        return ["proof-pack manifest must define at least 6 required checks"]
    return []


def _bom_risk_evidence_errors(evidence: dict[str, Any], *, root: Path) -> list[str]:
    try:
        bom_path = _resolve_benchmark_input(
            evidence.get("bom_risk_report"),
            root=root,
            field="scoring_evidence.bom_risk_report",
            allowed_suffixes={".json"},
        )
    except ValueError as exc:
        return [str(exc)]
    if not bom_path.exists():
        return [f"BOM risk report missing: {bom_path}"]
    try:
        bom = json.loads(bom_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"BOM risk report is not valid JSON: {exc}"]
    errors = [
        f"BOM risk report missing {key}"
        for key in ["provider", "highest_risk", "blocked", "items", "provenance"]
        if key not in bom
    ]
    if not isinstance(bom.get("items"), list) or not bom.get("items"):
        errors.append("BOM risk report must include item-level scoring evidence")
    return errors


def _check_scoring_evidence(spec: dict[str, Any], *, root: Path) -> BenchmarkCheck:
    evidence = _as_mapping(spec.get("scoring_evidence", {}), field="scoring_evidence")
    board = _as_mapping(
        _as_mapping(spec.get("board_target", {}), field="board_target").get("board", {}), field="board_target.board"
    )
    missing = [key for key in ["proof_pack_manifest", "bom_risk_report", "fab_profile"] if key not in evidence]
    invalid = _fab_profile_evidence_errors(evidence, board)
    invalid.extend(_proof_pack_evidence_errors(evidence, root=root))
    invalid.extend(_bom_risk_evidence_errors(evidence, root=root))

    if missing or invalid:
        return BenchmarkCheck(
            name="scoring-evidence",
            status=FAIL,
            message="Benchmark scoring evidence is incomplete",
            details={"missing": missing, "invalid": invalid},
        )
    return BenchmarkCheck(
        name="scoring-evidence",
        status=PASS,
        message="Proof-pack, BOM risk, and fab-profile scoring evidence are present",
    )


def _check_failure_summary(spec: dict[str, Any]) -> BenchmarkCheck:
    summary = _as_mapping(spec.get("failure_summary", {}), field="failure_summary")
    sections = set(summary.get("include_sections", []))
    required = {"blocking_failures", "threshold_violations", "missing_artifacts", "recommended_next_actions"}
    missing = sorted(required - sections)
    if summary.get("audience") != "humans-and-agents" or missing:
        return BenchmarkCheck(
            name="failure-summary",
            status=FAIL,
            message="Failure summary contract must be readable by humans and agents",
            details={"missing_sections": missing, "audience": summary.get("audience")},
        )
    return BenchmarkCheck(
        name="failure-summary",
        status=PASS,
        message="Failure summary contract is human- and agent-readable",
    )


def validate_spec(spec: dict[str, Any], *, root: Path) -> list[BenchmarkCheck]:
    checks = [
        _check_required_metadata(spec),
        _check_release_gate(spec),
        _check_required_functions(spec),
        _check_constraints(spec),
        _check_expected_artifacts(spec, root=root),
        _check_thresholds(spec),
        _check_scoring_evidence(spec, root=root),
        _check_failure_summary(spec),
    ]
    return checks


def build_report(
    spec: dict[str, Any],
    checks: list[BenchmarkCheck],
    *,
    evidence_identity: EvidenceIdentity | None = None,
) -> dict[str, Any]:
    identity = evidence_identity or capture_evidence_identity(
        root=ROOT,
        mode=EvidenceMode.SNAPSHOT,
        source_inputs=EVIDENCE_SOURCE_INPUTS,
    )
    blocking = [check for check in checks if check.blocks_release]
    return {
        "schema_version": "2.0",
        "generated_at": identity.generated_at,
        "evidence_identity": identity.model_dump(mode="json"),
        "benchmark": {
            "id": spec.get("id"),
            "name": spec.get("name"),
            "issue_links": spec.get("issue_links", []),
            "deterministic_mode": spec.get("deterministic_mode"),
            "release_gate": spec.get("release_gate", {}),
        },
        "status": FAIL if blocking else PASS,
        "blocked": bool(blocking),
        "blocking_checks": [check.name for check in blocking],
        "checks": [asdict(check) | {"blocks_release": check.blocks_release} for check in checks],
        "non_claims": [
            "not fabrication-ready",
            "not manufacturer-approved",
            "not no-human-review autonomous signoff",
        ],
        "recommended_next_actions": [
            "Generate schematic, PCB, BOM, manufacturing bundle, and proof-pack artifacts.",
            "Feed measured ERC/DRC/DFM/BOM/KiCad round-trip results into the benchmark report.",
            "Keep this harness strict in release-gate CI once artifact generation is wired in.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    benchmark = report["benchmark"]
    lines = [
        "# Benchmark 001 Release Gate Summary",
        "",
        f"Benchmark: `{benchmark['id']}`",
        f"Status: `{report['status']}`",
        f"Blocked: `{'yes' if report['blocked'] else 'no'}`",
        "",
        "## Evidence identity",
        "",
        f"- Mode: `{report['evidence_identity']['mode']}`",
        f"- Source commit: `{report['evidence_identity']['source_commit']}`",
        f"- Source ref: `{report['evidence_identity']['source_ref']}`",
        f"- Lock SHA-256: `{report['evidence_identity']['lock_sha256']}`",
        f"- Identity SHA-256: `{report['evidence_identity']['identity_sha256']}`",
        "",
        "| Check | Status | Blocks Release | Message |",
        "|-------|--------|----------------|---------|",
    ]
    for check in report["checks"]:
        blocks = "yes" if check["blocks_release"] else "no"
        lines.append(f"| `{check['name']}` | `{check['status']}` | {blocks} | {check['message']} |")
    lines.extend(
        [
            "",
            "## Non-claims",
            "",
            *[f"- {item}" for item in report["non_claims"]],
            "",
            "## Recommended next actions",
            "",
            *[f"- {item}" for item in report["recommended_next_actions"]],
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic benchmark 001 release-gate contract checks")
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC, help="Benchmark requirements YAML")
    parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    parser.add_argument("--markdown", type=Path, help="Append Markdown report to this path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when benchmark blocks release")
    args = parser.parse_args(argv)

    try:
        spec_path = _resolve_benchmark_input(
            str(args.spec),
            root=ROOT,
            field="benchmark spec",
            allowed_suffixes={".yaml", ".yml"},
        )
        spec = load_spec(spec_path)
        checks = validate_spec(spec, root=ROOT)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    report = build_report(spec, checks)
    markdown = render_markdown(report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        print(json.dumps(report, indent=2, sort_keys=True))

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        with args.markdown.open("a", encoding="utf-8") as handle:
            handle.write(markdown)
            handle.write("\n")
    else:
        print(markdown)

    if args.strict and report["blocked"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
