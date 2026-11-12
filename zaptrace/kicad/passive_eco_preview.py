"""One operator-specified KiCad passive ECO draft with independent native review.

This produces a *reviewable proposal*, never an approved electrical design.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from zaptrace.kicad.pcb_drc_review import review_native_pcb_drc_delta
from zaptrace.kicad.pcb_source_edit import replace_kicad_pcb_footprint_value
from zaptrace.kicad.schematic_hierarchy import snapshot_source_hierarchy
from zaptrace.kicad.schematic_importer import (
    KiCadSchematicSourceSnapshot,
    import_kicad_schematic,
    import_kicad_schematic_string,
)
from zaptrace.kicad.source_edit import replace_kicad_source_passive_value


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique_passive_uuid(snapshot: KiCadSchematicSourceSnapshot, reference: str) -> str:
    matches: list[str] = []
    for item in snapshot.nodes("symbol"):
        if not isinstance(item, list):
            continue
        refs = [
            entry[2]
            for entry in item
            if isinstance(entry, list) and entry[:2] == ["property", "Reference"] and len(entry) > 2
        ]
        if reference not in refs:
            continue
        uuids = [
            entry[1] for entry in item if isinstance(entry, list) and entry and entry[0] == "uuid" and len(entry) == 2
        ]
        if len(refs) != 1 or len(uuids) != 1 or not isinstance(uuids[0], str):
            raise ValueError("Schematic passive component UUID/reference is ambiguous")
        matches.append(uuids[0])
    if len(matches) != 1:
        raise ValueError("Schematic passive reference must identify one unique component")
    return matches[0]


def _new_destination(original_board: Path, output_dir: Path) -> None:
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("Output directory already exists; refusing to overwrite a draft")
    if not output_dir.parent.is_dir() or output_dir.parent.is_symlink():
        raise ValueError("Output parent must be an existing non-symlink directory")
    if output_dir.resolve().is_relative_to(original_board.parent.resolve()):
        raise ValueError("Output directory cannot be inside the original source project")


def _write_new_draft(output_dir: Path, files: dict[str, bytes]) -> None:
    """Exclusive new directory and fixed leaf names; never overwrite user files."""
    output_dir.mkdir(mode=0o700, exist_ok=False)
    for name, payload in files.items():
        target = output_dir / name
        if target.name != name or name in ("", ".", ".."):
            raise ValueError("Invalid ECO artifact filename")
        with target.open("xb") as handle:
            handle.write(payload)


def _make_proposed_sources(
    board: Path, schematic: Path, reference: str, old_value: str, new_value: str
) -> tuple[bytes, bytes, bool, str]:
    before = import_kicad_schematic(schematic)
    snapshot = before.source_snapshot
    if snapshot is None:
        raise ValueError("A complete original KiCad source snapshot is required")
    if snapshot_source_hierarchy(snapshot.raw_bytes, schematic.parent).file_count != 1:
        raise ValueError("Passive ECO preview supports only single-sheet sources; multi-sheet ECO not verified")
    symbol_uuid = _unique_passive_uuid(snapshot, reference)
    proposed_schematic = replace_kicad_source_passive_value(
        snapshot,
        symbol_uuid,
        reference,
        old_value,
        new_value,
        expected_sha256=snapshot.sha256,
    )
    after = import_kicad_schematic_string(proposed_schematic.decode("utf-8"), source_path=schematic)
    graphs_equal = before.design.nets == after.design.nets
    if not graphs_equal or after.unsupported_count != before.unsupported_count:
        raise ValueError("Proposed ECO changes or degrades canonical schematic net evidence")
    raw_board = board.read_bytes()
    proposed_board = replace_kicad_pcb_footprint_value(
        raw_board, reference, old_value, new_value, expected_sha256=_digest(raw_board)
    )
    return proposed_board, proposed_schematic, graphs_equal, symbol_uuid


def preview_passive_value_eco(
    original_board: str | Path,
    reference: str,
    old_value: str,
    new_value: str,
    output_dir: str | Path,
) -> dict[str, object]:
    """Create independent/native-reviewed draft files; keep original source untouched.

    No new native KiCad 10 DRC/ERC/parity errors is an engineering *regression
    check*, not evidence of expected timing/electrical behavior or fabrication.
    """
    started = perf_counter()
    board = Path(original_board)
    output = Path(output_dir)
    if board.suffix != ".kicad_pcb" or not board.is_file():
        raise ValueError("A readable original .kicad_pcb board is required")
    schematic, project = board.with_suffix(".kicad_sch"), board.with_suffix(".kicad_pro")
    if not schematic.is_file() or not project.is_file():
        raise ValueError("Original board requires matching .kicad_sch and .kicad_pro files")
    _new_destination(board, output)
    board_bytes, sheet_bytes, graph_equal, symbol_uuid = _make_proposed_sources(
        board, schematic, reference, old_value, new_value
    )
    original_hashes = {
        "original_pcb_sha256": _digest(board.read_bytes()),
        "original_schematic_sha256": _digest(schematic.read_bytes()),
        "original_project_sha256": _digest(project.read_bytes()),
    }
    with TemporaryDirectory(prefix="zaptrace-native-passive-eco-") as temp:
        scratch = Path(temp)
        candidate_board = scratch / board.name
        candidate_sheet = scratch / schematic.name
        for path, payload in ((candidate_board, board_bytes), (candidate_sheet, sheet_bytes)):
            with path.open("xb") as handle:
                handle.write(payload)
        native = review_native_pcb_drc_delta(
            board,
            candidate_board,
            expected_original_sha256=original_hashes["original_pcb_sha256"],
            expected_candidate_sha256=_digest(board_bytes),
            expected_project_sha256=original_hashes["original_project_sha256"],
            include_electrical_checks=True,
            expected_original_schematic_sha256=original_hashes["original_schematic_sha256"],
            candidate_schematic=candidate_sheet,
            expected_candidate_schematic_sha256=_digest(sheet_bytes),
        )
    if not native.no_review_regression:
        raise ValueError("Native KiCad DRC/ERC/schematic-parity regression detected; refusing ECO draft publication")
    if any(
        _digest(path.read_bytes()) != original_hashes[key]
        for path, key in (
            (board, "original_pcb_sha256"),
            (schematic, "original_schematic_sha256"),
            (project, "original_project_sha256"),
        )
    ):
        raise ValueError("Original KiCad source changed during review; refuse stale ECO")
    report: dict[str, object] = {
        "task_kind": "human-directed-passive-value-edit",
        "attempt_status": "human-review-required",
        "g0_verified": False,
        "manufacturing_approved": False,
        "reference": reference,
        "old_value": old_value,
        "new_value": new_value,
        "schematic_symbol_uuid": symbol_uuid,
        "canonical_nets_preserved": graph_equal,
        "native_kicad_version": native.native_kicad_version,
        **original_hashes,
        "candidate_pcb_sha256": _digest(board_bytes),
        "candidate_schematic_sha256": _digest(sheet_bytes),
        "elapsed_seconds": round(perf_counter() - started, 3),
        "human_interventions": None,
        "independent_human_review": "not_run",
        "functional_timing_validation": "not_run",
        "physical_fabrication_review": "not_run",
        "native_review": native.to_dict(),
        "candidate_board": str(output / board.name),
        "candidate_schematic": str(output / schematic.name),
        "candidate_project": str(output / project.name),
    }
    files = {
        board.name: board_bytes,
        schematic.name: sheet_bytes,
        project.name: project.read_bytes(),
        "eco-review.json": (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"),
    }
    if len({board.name, schematic.name, project.name, "eco-review.json"}) != 4:
        raise ValueError("ECO artifact names conflict")
    _new_destination(board, output)
    _write_new_draft(output, files)
    return report
