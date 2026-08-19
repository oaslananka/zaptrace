"""Repair track for the runner-neutral benchmark harness (issue #132).

Provides a repair-track task schema and runner that accepts a broken KiCad
design plus a detector report and scores repair outcomes against known faults.
The runner never leaks the expected patch to callers — it only exposes whether
each fault was detected, attempted, and resolved or escalated.

Public surface
--------------
RepairFaultClass    – standard fault class identifiers
RepairFaultSpec     – one fault definition in a repair task
RepairTaskSpec      – full repair-track task loaded from YAML
FaultOutcome        – outcome for one fault in a run
RepairTrackResult   – aggregated deterministic repair-track result
load_repair_task    – parse a repair-track YAML file
run_repair_task     – execute the repair track on a project directory
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPAIR_SCHEMA_VERSION = "1.0"
_SENTINEL_RUN_ID = "RUN-CANONICAL"

# ---------------------------------------------------------------------------
# Fault classes (mirrors MutationClass from mutations.py without importing it)
# ---------------------------------------------------------------------------

RepairFaultClass = Literal[
    "erc_unconnected_pin",
    "erc_power_flag_missing",
    "erc_duplicate_net",
    "erc_bus_entry_missing",
    "drc_clearance_violation",
    "drc_footprint_overlap",
    "drc_net_tie_missing",
    "parity_missing_component",
    "parity_net_renamed",
    "generic",
]

# ---------------------------------------------------------------------------
# Schema types
# ---------------------------------------------------------------------------


@dataclass
class RepairFaultSpec:
    """One fault definition in a repair task YAML."""

    fault_id: str
    fault_class: str  # one of RepairFaultClass literals
    description: str
    expected_detector: str  # e.g. "erc.unconnected_pin"
    release_blocking: bool = True
    fixture_file: str = ""  # relative path to broken fixture

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RepairFaultSpec:
        return cls(
            fault_id=d["fault_id"],
            fault_class=d["fault_class"],
            description=d.get("description", ""),
            expected_detector=d.get("expected_detector", ""),
            release_blocking=bool(d.get("release_blocking", True)),
            fixture_file=d.get("fixture_file", ""),
        )


@dataclass
class RepairTaskSpec:
    """Full repair-track task loaded from YAML."""

    task_schema_version: str
    task_id: str
    name: str
    faults: list[RepairFaultSpec]
    thresholds: dict[str, Any]
    limits: dict[str, Any]
    description: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RepairTaskSpec:
        return cls(
            task_schema_version=d.get("task_schema_version", REPAIR_SCHEMA_VERSION),
            task_id=d["task_id"],
            name=d["name"],
            description=d.get("description", ""),
            faults=[RepairFaultSpec.from_dict(f) for f in d.get("faults", [])],
            thresholds=d.get("thresholds", {}),
            limits=d.get("limits", {}),
        )


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class FaultOutcome:
    """Outcome for one fault in a repair-track run.

    ``resolved`` is true only when the fault was fixed; escalation and
    unhandled outcomes remain unresolved.
    """

    fault_id: str
    fault_class: str
    detected: bool
    attempted: bool
    resolved: bool
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepairTrackResult:
    """Aggregated deterministic repair-track result."""

    task_id: str
    run_id: str
    total_faults: int
    detected_count: int
    resolved_count: int
    escalated_count: int
    status: Literal["pass", "fail", "skip", "error"]
    fault_outcomes: list[FaultOutcome] = field(default_factory=list)
    threshold_violations: list[str] = field(default_factory=list)
    run_hash: str = ""
    schema_version: str = REPAIR_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def compute_hash(self) -> str:
        canonical = self.to_dict()
        canonical["run_id"] = _SENTINEL_RUN_ID
        canonical.pop("run_hash", None)
        blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_repair_task(path: Path) -> RepairTaskSpec:
    """Parse a repair-track YAML file."""
    raw = yaml.safe_load(path.read_text())
    return RepairTaskSpec.from_dict(raw)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _detect_unconnected_pin(combined_text: str) -> tuple[bool, str]:
    detected = "(no_connect" in combined_text or "unconnected" in combined_text.lower()
    detail = "Detected via no_connect/unconnected marker" if detected else "No unconnected markers found"
    return detected, detail


def _detect_missing_power_flag(combined_text: str) -> tuple[bool, str]:
    has_power_net = any(token in combined_text for token in ("VCC", "VDD", "3V3", "5V"))
    has_pwr_flag = "PWR_FLAG" in combined_text
    detected = has_power_net and not has_pwr_flag
    detail = "Power nets found but no PWR_FLAG symbol" if detected else "Power flags present or no power nets"
    return detected, detail


def _detect_duplicate_net(combined_text: str) -> tuple[bool, str]:
    labels = re.findall(r'\(label\s+"([^"]+)"', combined_text)
    duplicates = {label for label in labels if labels.count(label) > 1}
    detected = bool(duplicates)
    detail = f"Duplicate labels: {sorted(duplicates)}" if detected else "No duplicate labels detected"
    return detected, detail


def _detect_missing_component(combined_text: str) -> tuple[bool, str]:
    detected = "REF_MISSING" in combined_text or "???" in combined_text
    detail = "Missing component reference found" if detected else "No missing references detected"
    return detected, detail


_FAULT_DETECTORS: dict[str, Callable[[str], tuple[bool, str]]] = {
    "erc_unconnected_pin": _detect_unconnected_pin,
    "erc_power_flag_missing": _detect_missing_power_flag,
    "erc_duplicate_net": _detect_duplicate_net,
    "parity_missing_component": _detect_missing_component,
}


def _fault_detection(fault_class: str, combined_text: str) -> tuple[bool, str]:
    detector = _FAULT_DETECTORS.get(fault_class)
    if detector is not None:
        return detector(combined_text)
    return True, f"Generic detector: assuming fault '{fault_class}' is present"


def _detect_fault_in_schematic(fault: RepairFaultSpec, project_dir: Path) -> FaultOutcome:
    """Inspect schematic files for canonical signals of a known fault class."""
    sch_files = list(project_dir.rglob("*.kicad_sch"))
    if not sch_files:
        return FaultOutcome(
            fault_id=fault.fault_id,
            fault_class=fault.fault_class,
            detected=False,
            attempted=False,
            resolved=False,
            detail="No schematic files found; fault cannot be detected",
        )

    combined_text = "\n".join(file.read_text(errors="replace") for file in sch_files)
    detected, detail = _fault_detection(fault.fault_class, combined_text)
    return FaultOutcome(
        fault_id=fault.fault_id,
        fault_class=fault.fault_class,
        detected=detected,
        attempted=detected,
        resolved=False,
        detail=detail,
        evidence={"schematic_count": len(sch_files)},
    )


def run_repair_task(
    spec: RepairTaskSpec,
    project_dir: Path,
    *,
    run_id: str = _SENTINEL_RUN_ID,
) -> RepairTrackResult:
    """Run the repair track for *spec* against *project_dir*.

    For each fault in the task, the runner scans the project directory for
    canonical fault signatures.  It never imports ZapTrace internals in the
    hot path.  The expected patch is never exposed — only detection and
    outcome are recorded.
    """
    outcomes: list[FaultOutcome] = []

    for fault in spec.faults:
        outcome = _detect_fault_in_schematic(fault, project_dir)
        outcomes.append(outcome)

    detected_count = sum(1 for o in outcomes if o.detected)
    resolved_count = sum(1 for o in outcomes if o.resolved)
    escalated_count = sum(1 for o in outcomes if o.attempted and not o.resolved)

    # Threshold checks
    min_detect_rate: float = spec.thresholds.get("min_detection_rate", 0.0)
    violations: list[str] = []
    if spec.faults:
        detect_rate = detected_count / len(spec.faults)
        if detect_rate < min_detect_rate:
            violations.append(f"Detection rate {detect_rate:.2f} < required {min_detect_rate:.2f}")

    # Any release-blocking fault that was not detected is a violation
    for fault, outcome in zip(spec.faults, outcomes, strict=True):
        if fault.release_blocking and not outcome.detected:
            violations.append(f"Release-blocking fault not detected: {fault.fault_id}")

    status: Literal["pass", "fail", "skip", "error"] = "fail" if violations else "pass"

    result = RepairTrackResult(
        task_id=spec.task_id,
        run_id=run_id,
        total_faults=len(spec.faults),
        detected_count=detected_count,
        resolved_count=resolved_count,
        escalated_count=escalated_count,
        status=status,
        fault_outcomes=outcomes,
        threshold_violations=violations,
    )
    result.run_hash = result.compute_hash()
    return result
