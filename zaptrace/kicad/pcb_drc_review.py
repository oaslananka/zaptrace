"""Independent native KiCad 10 PCB DRC delta, never a manufacturing approval.

Runs the unchanged original and proposed candidate against the same original
project settings in isolated temporary folders. Neither the user's original
board nor candidate board is written, and existing violations remain visible.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from zaptrace.kicad.oracle import KiCadOracle
from zaptrace.kicad.schematic_hierarchy import (
    candidate_source_hierarchy,
    sheet_relative_path,
    snapshot_source_hierarchy,
)

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
            entry.get("sheet_path", ""),
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
class NativeElectricalEvidence:
    """Native schematic/PCB parity and ERC *deltas*; never electrical approval."""

    original_schematic_sha256: str
    candidate_schematic_sha256: str
    original_child_sha256: dict[str, str]
    candidate_child_sha256: dict[str, str]
    sheet_file_count: int
    baseline_schematic_parity_issues: int
    baseline_schematic_parity_types: dict[str, int]
    candidate_schematic_parity_issues: int
    candidate_schematic_parity_types: dict[str, int]
    new_schematic_parity_issues: int
    new_schematic_parity_types: dict[str, int]
    baseline_erc_violations: int
    candidate_erc_violations: int
    new_erc_violations: int
    new_erc_violation_types: dict[str, int]
    no_electrical_regression: bool
    baseline_electrical_clean: bool
    candidate_electrical_clean: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    electrical_review: NativeElectricalEvidence | None = None

    @property
    def no_review_regression(self) -> bool:
        return self.no_drc_regression and (
            self.electrical_review is None or self.electrical_review.no_electrical_regression
        )

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
            "no_review_regression": self.no_review_regression,
            "electrical_review": self.electrical_review.to_dict() if self.electrical_review else None,
            "original_files_modified": False,
            "manufacturing_approved": False,
            "scope": (
                "native KiCad 10 PCB DRC plus opt-in schematic parity/ERC delta; "
                "not manufacturing, full electrical, or fabrication approval"
                if self.electrical_review
                else "native KiCad 10 PCB DRC delta only; no schematic parity, ERC or fabrication approval"
            ),
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


def _run_native_drc(
    oracle: KiCadOracle,
    directory: Path,
    board: bytes,
    project: bytes,
    *,
    schematic: bytes | None = None,
    child_sheets: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Only fixed filenames inside our new temporary directory are writable."""
    directory.mkdir()
    # The filesystem paths are constants inside our exclusive private
    # TemporaryDirectory. Untrusted bytes are only written through an opened
    # file handle, never interpreted as path components.
    board_file = directory / "review.kicad_pcb"
    files = [
        (board_file, board),
        (directory / "review.kicad_pro", project),
    ]
    if schematic is not None:
        files.append((directory / "review.kicad_sch", schematic))
    for name, payload in sorted((child_sheets or {}).items()):
        relative = sheet_relative_path(name)
        target = directory.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        files.append((target, payload))
    for path, payload in files:
        with path.open("xb") as destination:
            destination.write(payload)
    report_file = directory / "native-drc.json"
    result = oracle.run_drc(
        board_file,
        output_path=report_file,
        timeout=_DRC_TIMEOUT_SECONDS,
        severity="all",
        exit_code_violations=False,
        schematic_parity=schematic is not None,
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
    if schematic is not None and (
        not isinstance(report.get("schematic_parity"), list)
        or not all(isinstance(item, dict) for item in report["schematic_parity"])
    ):
        raise RuntimeError("Native KiCad did not produce valid schematic-PCB parity evidence")
    return report


def _run_native_erc(oracle: KiCadOracle, directory: Path) -> list[dict[str, Any]]:
    """Flatten sheet-scoped ERC findings with source sheet identity preserved."""
    report_file = directory / "native-erc.json"
    result = oracle.run_erc(
        directory / "review.kicad_sch",
        output_path=report_file,
        timeout=_DRC_TIMEOUT_SECONDS,
        severity="all",
        exit_code_violations=False,
    )
    if result.exit_code != 0:
        raise RuntimeError(f"Native KiCad schematic ERC execution failed: {result.message}")
    try:
        raw = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Native KiCad did not produce readable ERC JSON evidence") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("sheets"), list) or not raw["sheets"]:
        raise RuntimeError("Native KiCad ERC report lacks schematic sheets")
    findings: list[dict[str, Any]] = []
    for sheet in raw["sheets"]:
        if not isinstance(sheet, dict) or not isinstance(sheet.get("violations"), list):
            raise RuntimeError("Native KiCad ERC sheet evidence is invalid")
        for finding in sheet["violations"]:
            if not isinstance(finding, dict):
                raise RuntimeError("Native KiCad ERC finding is invalid")
            findings.append({**finding, "sheet_path": sheet.get("uuid_path", sheet.get("path", ""))})
    return findings


def _review_electrical_delta(
    oracle: KiCadOracle,
    root: Path,
    before: dict[str, Any],
    after: dict[str, Any],
    original_schematic_sha256: str,
    candidate_schematic_sha256: str,
    original_child_sha256: dict[str, str],
    candidate_child_sha256: dict[str, str],
) -> NativeElectricalEvidence:
    before_parity = before["schematic_parity"]
    after_parity = after["schematic_parity"]
    before_erc = _run_native_erc(oracle, root / "baseline")
    after_erc = (
        before_erc
        if (original_schematic_sha256 == candidate_schematic_sha256 and original_child_sha256 == candidate_child_sha256)
        else _run_native_erc(oracle, root / "candidate")
    )
    new_parity, _ = _delta_fingerprints(before_parity, after_parity)
    new_erc, _ = _delta_fingerprints(before_erc, after_erc)
    return NativeElectricalEvidence(
        original_schematic_sha256=original_schematic_sha256,
        candidate_schematic_sha256=candidate_schematic_sha256,
        original_child_sha256=original_child_sha256,
        candidate_child_sha256=candidate_child_sha256,
        sheet_file_count=1 + len(original_child_sha256),
        baseline_schematic_parity_issues=len(before_parity),
        baseline_schematic_parity_types=dict(
            sorted(Counter(str(item.get("type", "unknown")) for item in before_parity).items())
        ),
        candidate_schematic_parity_issues=len(after_parity),
        candidate_schematic_parity_types=dict(
            sorted(Counter(str(item.get("type", "unknown")) for item in after_parity).items())
        ),
        new_schematic_parity_issues=len(new_parity),
        new_schematic_parity_types=dict(
            sorted(Counter(str(item.get("type", "unknown")) for item in new_parity).items())
        ),
        baseline_erc_violations=len(before_erc),
        candidate_erc_violations=len(after_erc),
        new_erc_violations=len(new_erc),
        new_erc_violation_types=dict(sorted(Counter(str(item.get("type", "unknown")) for item in new_erc).items())),
        no_electrical_regression=not new_parity and not new_erc,
        baseline_electrical_clean=not before_parity and not before_erc,
        candidate_electrical_clean=not after_parity and not after_erc,
    )


def review_native_pcb_drc_delta(
    original_board: str | Path,
    candidate_board: str | Path,
    *,
    expected_original_sha256: str,
    expected_candidate_sha256: str,
    expected_project_sha256: str,
    include_electrical_checks: bool = False,
    expected_original_schematic_sha256: str | None = None,
    candidate_schematic: str | Path | None = None,
    expected_candidate_schematic_sha256: str | None = None,
    candidate_child_sheets: dict[str, Path] | None = None,
    expected_candidate_child_sha256: dict[str, str] | None = None,
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
    if not include_electrical_checks and (
        candidate_schematic is not None
        or expected_original_schematic_sha256
        or candidate_child_sheets is not None
        or expected_candidate_child_sha256 is not None
    ):
        raise ValueError("Schematic input requires include_electrical_checks=True")
    original_schematic: bytes | None = None
    new_schematic: bytes | None = None
    new_schematic_sha: str | None = None
    original_child_bytes: dict[str, bytes] = {}
    candidate_child_bytes: dict[str, bytes] = {}
    original_child_hashes: dict[str, str] = {}
    candidate_child_hashes: dict[str, str] = {}
    if include_electrical_checks:
        if not expected_original_schematic_sha256:
            raise ValueError("Original schematic SHA-256 is required for electrical review")
        original_schematic_file = original.with_suffix(".kicad_sch")
        original_schematic = _pinned_bytes(
            original_schematic_file, expected_original_schematic_sha256, "Original schematic"
        )
        original_hierarchy = snapshot_source_hierarchy(original_schematic, original.parent)
        original_child_bytes = original_hierarchy.children
        original_child_hashes = original_hierarchy.child_sha256
        if candidate_schematic is not None:
            new_file = Path(candidate_schematic)
            if new_file.suffix != ".kicad_sch" or not expected_candidate_schematic_sha256:
                raise ValueError("Candidate schematic must be a .kicad_sch with its SHA-256")
            new_schematic = _pinned_bytes(new_file, expected_candidate_schematic_sha256, "Candidate schematic")
            new_schematic_sha = expected_candidate_schematic_sha256
        else:
            new_schematic = original_schematic
            new_schematic_sha = expected_original_schematic_sha256
        candidate_hierarchy = candidate_source_hierarchy(
            original_hierarchy,
            new_schematic,
            candidate_child_sheets,
            expected_candidate_child_sha256,
        )
        candidate_child_bytes = candidate_hierarchy.children
        candidate_child_hashes = candidate_hierarchy.child_sha256
    oracle = _require_native_kicad_10()
    with TemporaryDirectory(prefix="zaptrace-native-drc-delta-") as temp:
        root = Path(temp)
        before = _run_native_drc(
            oracle,
            root / "baseline",
            original_bytes,
            project_bytes,
            schematic=original_schematic,
            child_sheets=original_child_bytes,
        )
        after = _run_native_drc(
            oracle,
            root / "candidate",
            candidate_bytes,
            project_bytes,
            schematic=new_schematic,
            child_sheets=candidate_child_bytes,
        )
        electrical_review = None
        if original_schematic is not None and new_schematic_sha and expected_original_schematic_sha256:
            electrical_review = _review_electrical_delta(
                oracle,
                root,
                before,
                after,
                expected_original_schematic_sha256,
                new_schematic_sha,
                original_child_hashes,
                candidate_child_hashes,
            )

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
        electrical_review=electrical_review,
    )
