"""Four-family automated convergence benchmark for release verify/repair."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.benchmark.families import BenchmarkBoardFamily, builtin_board_family_manifest
from zaptrace.core.models import Design
from zaptrace.pipeline.verify_repair import run_verify_repair
from zaptrace.pipeline.verify_repair_gates import default_gate_adapters, default_repair_adapters
from zaptrace.pipeline.verify_repair_models import (
    VerifyRepairOutcome,
    VerifyRepairPolicy,
    VerifyRepairStopReason,
    resolve_verify_repair_output_path,
    write_release_verify_repair_report,
)
from zaptrace.synthesis.architecture import build_architecture_design
from zaptrace.synthesis.requirements import parse_requirements

CANONICAL_RELEASE_CONVERGENCE_FAMILIES: tuple[str, ...] = (
    "esp32_usb_sensor",
    "stm32_rs485_industrial",
    "nrf52_ble_multisensor",
    "rp2040_can_node",
)
_OUTPUT_MARKER = ".zaptrace-release-convergence-output"
_REPORT_NAME = "release-convergence-report.json"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class RepairScorecard(BaseModel):
    """Compact measured repair progress for one benchmark family."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    family_id: str
    policy_sha256: str = Field(pattern=_SHA256_PATTERN)
    initial_design_state_hash: str = Field(pattern=_SHA256_PATTERN)
    final_design_state_hash: str = Field(pattern=_SHA256_PATTERN)
    stop_reason: VerifyRepairStopReason
    converged: bool
    iterations_used: int = Field(ge=0)
    repair_count: int = Field(ge=0)
    patch_count: int = Field(ge=0)
    improving_repair_count: int = Field(ge=0)
    initial_blocking_count: int = Field(ge=0)
    final_blocking_count: int = Field(ge=0)
    verify_repair_report_sha256: str = Field(pattern=_SHA256_PATTERN)
    non_claims: list[str] = Field(default_factory=list)
    scorecard_sha256: str = ""

    def compute_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"scorecard_sha256"})
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def finalize(self) -> RepairScorecard:
        self.scorecard_sha256 = self.compute_sha256()
        return self


class ReleaseConvergenceFamilyResult(BaseModel):
    """One board-family convergence result."""

    model_config = ConfigDict(strict=False)

    family_id: str
    title: str
    intent_sha256: str = Field(pattern=_SHA256_PATTERN)
    initial_design_state_hash: str = Field(pattern=_SHA256_PATTERN)
    final_design_state_hash: str = Field(pattern=_SHA256_PATTERN)
    converged: bool
    stop_reason: VerifyRepairStopReason
    iterations_used: int = Field(ge=0)
    repair_count: int = Field(ge=0)
    gate_history_count: int = Field(ge=1)
    verify_repair_report_path: str
    verify_repair_report_sha256: str = Field(pattern=_SHA256_PATTERN)
    repair_scorecard_path: str
    repair_scorecard_sha256: str = Field(pattern=_SHA256_PATTERN)


class ReleaseConvergenceReport(BaseModel):
    """Aggregate four-family convergence benchmark evidence."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    benchmark_version: str = "2026.07"
    policy_version: str
    policy_sha256: str = Field(pattern=_SHA256_PATTERN)
    passed: bool
    family_count: int = Field(ge=0)
    converged_count: int = Field(ge=0)
    families: list[ReleaseConvergenceFamilyResult]
    evidence_identity: dict[str, object] = Field(default_factory=dict)
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "This benchmark measures bounded ERC software convergence, not release readiness.",
            "DRC, DFM, simulation, KiCad oracle, supply-chain, and physical gates are not run or waived here.",
            "A convergence pass is not manufacturing, fabrication, electrical, EMC, or safety approval.",
        ]
    )
    report_sha256: str = ""

    def compute_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"report_sha256"})
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def finalize(self) -> ReleaseConvergenceReport:
        self.report_sha256 = self.compute_sha256()
        return self


def _remove_benchmark_owned_children(resolved: Path, marker: Path) -> None:
    """Remove only children of a marker-owned benchmark output directory."""
    for child in resolved.iterdir():
        if child == marker:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)


def _prepare_existing_output_dir(resolved: Path, marker: Path) -> None:
    """Validate ownership before cleaning a pre-existing output directory."""
    if not resolved.is_dir():
        raise ValueError(f"release convergence output is not a directory: {resolved}")
    if any(resolved.iterdir()) and not marker.is_file():
        raise ValueError(f"existing release convergence output is not benchmark-owned: {resolved}")
    _remove_benchmark_owned_children(resolved, marker)


def _prepare_output_dir(path: str | Path, *, trusted_root: str | Path | None) -> Path:
    root = Path(trusted_root or Path.cwd()).resolve(strict=True)
    resolved = resolve_verify_repair_output_path(path, trusted_root=root)
    if resolved in {Path("/").resolve(), Path.home().resolve(), root}:
        raise ValueError(f"unsafe release convergence output directory: {resolved}")
    marker = resolved / _OUTPUT_MARKER
    if resolved.exists():
        _prepare_existing_output_dir(resolved, marker)
    else:
        resolved.mkdir(parents=True)
    marker.write_text("ZapTrace release convergence output\n", encoding="utf-8")
    return resolved


def _family_index() -> dict[str, BenchmarkBoardFamily]:
    return {item.family_id: item for item in builtin_board_family_manifest().families}


def _selected_families(family_ids: list[str] | tuple[str, ...] | None) -> list[BenchmarkBoardFamily]:
    requested = list(family_ids or CANONICAL_RELEASE_CONVERGENCE_FAMILIES)
    index = _family_index()
    unknown = [family_id for family_id in requested if family_id not in index]
    if unknown:
        raise ValueError("unknown benchmark family: " + ", ".join(unknown))
    return [index[family_id] for family_id in requested]


def _initial_candidate(family: BenchmarkBoardFamily) -> Design:
    requirements = parse_requirements(family.representative_intent)
    design, _plan, _log = build_architecture_design(requirements, name=family.family_id)
    return design


def _write_repair_scorecard(
    *,
    root: Path,
    family: BenchmarkBoardFamily,
    outcome: VerifyRepairOutcome,
) -> tuple[Path, RepairScorecard]:
    report = outcome.report
    scorecard = RepairScorecard(
        family_id=family.family_id,
        policy_sha256=report.policy_sha256,
        initial_design_state_hash=report.initial_design_state_hash,
        final_design_state_hash=report.final_design_state_hash,
        stop_reason=report.stop_reason,
        converged=report.converged,
        iterations_used=report.iterations_used,
        repair_count=len(report.repairs),
        patch_count=sum(len(item.patches) for item in report.repairs),
        improving_repair_count=sum(item.improved for item in report.repairs),
        initial_blocking_count=report.gate_history[0].blocking_count,
        final_blocking_count=report.gate_history[-1].blocking_count,
        verify_repair_report_sha256=report.report_sha256,
        non_claims=[
            "Repair progress is measured software evidence, not release or fabrication approval.",
            "This scorecard inherits the enabled-domain limits of its verify/repair policy.",
        ],
    ).finalize()
    path = root / family.family_id / "repair-scorecard.json"
    path.write_text(
        json.dumps(scorecard.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path, scorecard


def run_release_convergence_benchmark(
    output_dir: str | Path,
    *,
    family_ids: list[str] | tuple[str, ...] | None = None,
    evidence_identity: dict[str, object] | None = None,
    trusted_output_root: str | Path | None = None,
) -> ReleaseConvergenceReport:
    """Run four generated candidates through the software-only convergence policy."""
    selected = _selected_families(family_ids)
    root = _prepare_output_dir(output_dir, trusted_root=trusted_output_root)
    policy = VerifyRepairPolicy.automated_convergence()
    family_results: list[ReleaseConvergenceFamilyResult] = []

    for family in selected:
        candidate = _initial_candidate(family)
        family_dir = root / family.family_id
        family_dir.mkdir(parents=True, exist_ok=True)
        outcome = run_verify_repair(
            candidate,
            policy=policy,
            gate_adapters=default_gate_adapters(),
            repair_adapters=default_repair_adapters(),
            output_dir=family_dir,
            trusted_output_root=root,
        )
        report_path = write_release_verify_repair_report(
            outcome.report,
            family_dir / "verify-repair.json",
            trusted_root=root,
        )
        scorecard_path, scorecard = _write_repair_scorecard(root=root, family=family, outcome=outcome)
        family_results.append(
            ReleaseConvergenceFamilyResult(
                family_id=family.family_id,
                title=family.title,
                intent_sha256=hashlib.sha256(family.representative_intent.encode("utf-8")).hexdigest(),
                initial_design_state_hash=outcome.report.initial_design_state_hash,
                final_design_state_hash=outcome.report.final_design_state_hash,
                converged=outcome.report.converged,
                stop_reason=outcome.report.stop_reason,
                iterations_used=outcome.report.iterations_used,
                repair_count=len(outcome.report.repairs),
                gate_history_count=len(outcome.report.gate_history),
                verify_repair_report_path=report_path.relative_to(root).as_posix(),
                verify_repair_report_sha256=outcome.report.report_sha256,
                repair_scorecard_path=scorecard_path.relative_to(root).as_posix(),
                repair_scorecard_sha256=scorecard.scorecard_sha256,
            )
        )

    converged_count = sum(item.converged for item in family_results)
    report = ReleaseConvergenceReport(
        policy_version=policy.policy_version,
        policy_sha256=policy.identity_sha256(),
        passed=converged_count == len(family_results) and len(family_results) >= 4,
        family_count=len(family_results),
        converged_count=converged_count,
        families=family_results,
        evidence_identity=evidence_identity or {},
    ).finalize()
    (root / _REPORT_NAME).write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "CANONICAL_RELEASE_CONVERGENCE_FAMILIES",
    "ReleaseConvergenceFamilyResult",
    "RepairScorecard",
    "ReleaseConvergenceReport",
    "run_release_convergence_benchmark",
]
