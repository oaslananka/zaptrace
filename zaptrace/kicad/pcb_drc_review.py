"""Independent native KiCad 10 PCB DRC delta, never a manufacturing approval.

Runs the unchanged original and proposed candidate against the same original
project settings in isolated temporary folders. Neither the user's original
board nor candidate board is written, and existing violations remain visible.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from zaptrace.kicad.oracle import KiCadOracle

_DRC_TIMEOUT_SECONDS = 80


def _fingerprint(entry: dict[str, Any]) -> str:
    """Stable native issue identity, retaining multiplicity of repeated findings."""
    items = entry.get("items", [])
    ordered_items = sorted(json.dumps(item, sort_keys=True, ensure_ascii=False) for item in items)
    return json.dumps(
        (
            entry.get("type", ""),
            entry.get("severity", ""),
            entry.get("description", ""),
            ordered_items,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _delta_fingerprints(
    baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return added and removed native issues, including duplicate occurrences."""
    before = Counter(_fingerprint(entry) for entry in baseline)
    after = Counter(_fingerprint(entry) for entry in candidate)
    added_counts = after - before
    removed_counts = before - after
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for entry in candidate:
        identity = _fingerprint(entry)
        if added_counts[identity] > 0:
            added.append(entry)
            added_counts[identity] -= 1
    for entry in baseline:
        identity = _fingerprint(entry)
        if removed_counts[identity] > 0:
            removed.append(entry)
            removed_counts[identity] -= 1
    return added, removed


@dataclass(frozen=True, slots=True)
class NativePcbDrcDeltaReview:
    native_kicad_version: str
    original_sha256: str
    candidate_sha256: str
    project_sha256: str
    baseline_violations: int
    candidate_violations: int
    baseline_unconnected_items: int
    candidate_unconnected_items: int
    new_violations: int
    removed_violations: int
    new_unconnected_items: int
    new_violation_types: dict[str, int]
    new_finding_samples: list[dict[str, str]]
    no_drc_regression: bool
    baseline_drc_clean: bool
    candidate_drc_clean: bool
    candidate_identical: bool

    @property
    def manufacturing_approved(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "native_kicad_version": self.native_kicad_version,
            "original_sha256": self.original_sha256,
            "candidate_sha256": self.candidate_sha256,
            "project_sha256": self.project_sha256,
            "baseline_violations": self.baseline_violations,
            "candidate_violations": self.candidate_violations,
            "baseline_unconnected_items": self.baseline_unconnected_items,
            "candidate_unconnected_items": self.candidate_unconnected_items,
            "new_violations": self.new_violations,
            "removed_violations": self.removed_violations,
            "new_unconnected_items": self.new_unconnected_items,
            "new_violation_types": self.new_violation_types,
            "new_finding_samples": self.new_finding_samples,
            "no_drc_regression": self.no_drc_regression,
            "baseline_drc_clean": self.baseline_drc_clean,
            "candidate_drc_clean": self.candidate_drc_clean,
            "candidate_identical": self.candidate_identical,
            "original_files_modified": False,
            "manufacturing_approved": False,
            "scope": "native KiCad 10 PCB DRC delta only; no schematic parity, ERC or fabrication approval",
        }


def _require_native_kicad_10() -> KiCadOracle:
    """Reuse the existing vetted native KiCad process boundary."""
    oracle = KiCadOracle()
    if not oracle.available:
        raise RuntimeError("Native KiCad 10 CLI is required for PCB DRC; no simulated DRC success")
    if not oracle.version.startswith("10."):
        raise RuntimeError(f"Independent PCB DRC requires native KiCad 10, got {oracle.version!r}")
    return oracle


def _pinned_bytes(path: Path, expected_sha: str, description: str) -> bytes:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Could not read {description} file") from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError(f"{description} SHA-256 mismatch; stale review input")
    return raw


def _run_native_drc(oracle: KiCadOracle, directory: Path, board: bytes, project: bytes) -> dict[str, Any]:
    """Only fixed filenames inside our new temporary directory are writable."""
    directory.mkdir()
    board_file = directory / "review.kicad_pcb"
    board_file.write_bytes(board)
    (directory / "review.kicad_pro").write_bytes(project)
    report_file = directory / "native-drc.json"
    result = oracle.run_drc(
        board_file,
        output_path=report_file,
        timeout=_DRC_TIMEOUT_SECONDS,
        severity="all",
        exit_code_violations=False,
    )
    # Real native DRC may find errors on an existing board; that is NOT a
    # process failure. Enforce a successful process and a valid report instead.
    if result.exit_code != 0:
        raise RuntimeError(f"Native KiCad PCB DRC execution failed: {result.message}")
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Native KiCad did not produce a readable DRC JSON report") from exc
    if not isinstance(report, dict) or not all(
        isinstance(report.get(k), list) and all(isinstance(x, dict) for x in report[k])
        for k in ("violations", "unconnected_items")
    ):
        raise RuntimeError("Native KiCad PCB DRC report is missing verified issue arrays")
    return report


def review_native_pcb_drc_delta(
    original_board: str | Path,
    candidate_board: str | Path,
    *,
    expected_original_sha256: str,
    expected_candidate_sha256: str,
    expected_project_sha256: str,
) -> NativePcbDrcDeltaReview:
    """Compare real source and candidate PCB DRC without modifying either file.

    A no-regression DRC delta does *not* imply that existing violations are
    acceptable, nor does it prove schematic parity, ERC or manufacturing.
    """
    original = Path(original_board)
    candidate = Path(candidate_board)
    if original.suffix != ".kicad_pcb" or candidate.suffix != ".kicad_pcb":
        raise ValueError("Original and candidate must both be KiCad .kicad_pcb files")
    project_file = original.with_suffix(".kicad_pro")
    if not project_file.is_file():
        raise ValueError("Original PCB must have a matching .kicad_pro project settings file")
    original_bytes = _pinned_bytes(original, expected_original_sha256, "Original PCB")
    candidate_bytes = _pinned_bytes(candidate, expected_candidate_sha256, "Candidate PCB")
    project_bytes = _pinned_bytes(project_file, expected_project_sha256, "Original project")
    oracle = _require_native_kicad_10()
    with TemporaryDirectory(prefix="zaptrace-native-drc-delta-") as temp:
        root = Path(temp)
        before = _run_native_drc(oracle, root / "baseline", original_bytes, project_bytes)
        after = _run_native_drc(oracle, root / "candidate", candidate_bytes, project_bytes)

    added, removed = _delta_fingerprints(before["violations"], after["violations"])
    new_unconnected, _ = _delta_fingerprints(before["unconnected_items"], after["unconnected_items"])
    violation_types = dict(sorted(Counter(str(item.get("type", "unknown")) for item in added).items()))
    return NativePcbDrcDeltaReview(
        native_kicad_version=oracle.version,
        original_sha256=expected_original_sha256,
        candidate_sha256=expected_candidate_sha256,
        project_sha256=expected_project_sha256,
        baseline_violations=len(before["violations"]),
        candidate_violations=len(after["violations"]),
        baseline_unconnected_items=len(before["unconnected_items"]),
        candidate_unconnected_items=len(after["unconnected_items"]),
        new_violations=len(added),
        removed_violations=len(removed),
        new_unconnected_items=len(new_unconnected),
        new_violation_types=violation_types,
        new_finding_samples=[
            {
                "type": str(item.get("type", "")),
                "severity": str(item.get("severity", "")),
                "description": str(item.get("description", "")),
            }
            for item in added[:10]
        ],
        no_drc_regression=not added and not new_unconnected,
        baseline_drc_clean=not before["violations"] and not before["unconnected_items"],
        candidate_drc_clean=not after["violations"] and not after["unconnected_items"],
        candidate_identical=original_bytes == candidate_bytes,
    )
