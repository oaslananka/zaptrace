"""Guarded, explicitly mapped KiCad parity repair candidates, never manufacturing approval."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

from zaptrace.io.sexp import SexpNode, parse
from zaptrace.kicad.passive_eco_preview import _new_destination, _write_new_draft
from zaptrace.kicad.pcb_drc_review import review_native_pcb_drc_delta
from zaptrace.kicad.schematic_hierarchy import snapshot_source_hierarchy


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pairs(entries: list[tuple[str, str]], kind: str) -> dict[str, str]:
    if len(entries) > 16:
        raise ValueError("At most 16 explicit source mappings are supported")
    result: dict[str, str] = {}
    for old, new in entries:
        if not all(
            isinstance(value, str)
            and 0 < len(value) <= 120
            and all(char.isprintable() and char not in '"\\' for char in value)
            for value in (old, new)
        ):
            raise ValueError(f"Invalid {kind} mapping; quoted/escaped/control input not supported")
        if old == new:
            raise ValueError(f"Unchanged {kind} mapping is not a repair")
        if old in result:
            raise ValueError(f"Duplicate {kind} mapping source")
        result[old] = new
    if len(set(result.values())) != len(result):
        raise ValueError(f"Duplicate {kind} mapping target")
    return result


def _child(node: list[SexpNode], tag: str) -> list[SexpNode] | None:
    return next((item for item in node if isinstance(item, list) and item and item[0] == tag), None)


def _property(node: list[SexpNode], key: str) -> list[SexpNode] | None:
    return next(
        (item for item in node if isinstance(item, list) and len(item) >= 3 and item[:2] == ["property", key]),
        None,
    )


def _schematic_testpoints(source: list[SexpNode]) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for item in source[1:]:
        if not isinstance(item, list) or not item or item[0] != "symbol":
            continue
        lib, reference, uuid, footprint = (
            _child(item, "lib_id"),
            _property(item, "Reference"),
            _child(item, "uuid"),
            _property(item, "Footprint"),
        )
        if lib is None or len(lib) < 2 or lib[1] != "Connector:TestPoint":
            continue
        if reference is None or uuid is None or footprint is None:
            raise ValueError("Schematic test point must have reference, UUID and footprint")
        if (
            sum(isinstance(entry, list) and entry[:2] == ["property", "Reference"] for entry in item) != 1
            or sum(isinstance(entry, list) and entry[:2] == ["property", "Footprint"] for entry in item) != 1
            or sum(isinstance(entry, list) and entry[:1] == ["uuid"] for entry in item) != 1
        ):
            raise ValueError("Schematic test point source fields are ambiguous")
        if len(uuid) != 2 or not isinstance(uuid[1], str):
            raise ValueError("Schematic test point UUID is invalid")
        ref = reference[2]
        if not isinstance(ref, str) or ref in found or not re.fullmatch(r"TP[1-9]\d*", ref):
            raise ValueError("Schematic test point reference is ambiguous")
        value = footprint[2]
        if not isinstance(value, str):
            raise ValueError("Schematic test point footprint is invalid")
        found[ref] = (uuid[1], value)
    return found


def _board_footprints(source: list[SexpNode]) -> list[list[SexpNode]]:
    return [item for item in source[1:] if isinstance(item, list) and item and item[0] == "footprint"]


def _renamed_nets(node: SexpNode, mappings: dict[str, str], parent: str = "") -> int:
    if not isinstance(node, list) or not node:
        return 0
    if node[0] == "net" and len(node) == 2 and isinstance(node[1], str) and node[1] in mappings:
        if parent not in {"pad", "segment", "zone", "via", "arc"}:
            raise ValueError("Net rename outside PCB copper constructs is unsupported")
        node[1] = mappings[node[1]]
        return 1
    name = node[0] if isinstance(node[0], str) else ""
    return sum(_renamed_nets(item, mappings, name) for item in node[1:])


def _board_net_values(node: SexpNode) -> set[str]:
    if not isinstance(node, list):
        return set()
    if len(node) == 2 and node[0] == "net" and isinstance(node[1], str):
        return {node[1]}
    return set().union(*(_board_net_values(child) for child in node))


def _schematic_named_labels(source: list[SexpNode]) -> set[str]:
    labels: set[str] = set()
    for item in source[1:]:
        if (
            isinstance(item, list)
            and len(item) >= 2
            and item[0] in {"label", "global_label", "hierarchical_label"}
            and isinstance(item[1], str)
        ):
            labels.add(item[1])
    return labels


def propose_source_bound_parity_board(
    original_board: bytes,
    original_schematic: bytes,
    *,
    reference_mappings: list[tuple[str, str]],
    net_mappings: list[tuple[str, str]],
    expected_sha256: str,
) -> bytes:
    """Edit only approved PCB test point references and copper net-name atoms."""
    if _digest(original_board) != expected_sha256:
        raise ValueError("PCB source SHA-256 mismatch; refusing stale parity proposal")
    refs, nets = _pairs(reference_mappings, "reference"), _pairs(net_mappings, "net")
    if not refs and not nets:
        raise ValueError("At least one explicit reference or net mapping is required")
    board_text = original_board.decode("utf-8")
    ast = parse(board_text)
    schematic = parse(original_schematic.decode("utf-8"))
    if not isinstance(ast, list) or not ast or ast[0] != "kicad_pcb":
        raise ValueError("Source is not a KiCad PCB")
    if not isinstance(schematic, list) or not schematic or schematic[0] != "kicad_sch":
        raise ValueError("Source is not a KiCad schematic")
    expected = copy.deepcopy(ast)
    points = _schematic_testpoints(schematic)
    footprints = _board_footprints(expected)
    actual_refs = [_property(item, "Reference") for item in footprints]
    existing_refs = [prop[2] for prop in actual_refs if prop is not None]
    for old, new in refs.items():
        if new not in points:
            raise ValueError("Target test point reference is not present in schematic")
        if new in existing_refs:
            raise ValueError("New footprint reference already exists on PCB")
        matches = [item for item in footprints if (prop := _property(item, "Reference")) is not None and prop[2] == old]
        if len(matches) != 1:
            raise ValueError("PCB test point reference must be unique")
        footprint = matches[0]
        if (
            sum(isinstance(entry, list) and entry[:2] == ["property", "Reference"] for entry in footprint) != 1
            or sum(isinstance(entry, list) and entry[:1] == ["path"] for entry in footprint) != 1
            or sum(isinstance(entry, list) and entry[:1] == ["uuid"] for entry in footprint) != 1
        ):
            raise ValueError("PCB test point footprint source fields are ambiguous")
        path = _child(footprint, "path")
        expected_uuid, expected_lib = points[new]
        if (
            len(footprint) < 2
            or footprint[1] != expected_lib
            or not expected_lib.startswith("TestPoint:")
            or path is None
            or len(path) != 2
            or path[1] != f"/{expected_uuid}"
        ):
            raise ValueError("PCB test point mapping conflicts with schematic symbol UUID/footprint")
        prop = _property(footprint, "Reference")
        if prop is None:
            raise ValueError("Missing PCB footprint reference")
        prop[2] = new

    original_net_names = _board_net_values(ast)
    labels = _schematic_named_labels(schematic)
    for old, new in nets.items():
        if old not in original_net_names:
            raise ValueError("Net mapping source is unused in original board")
        if new in original_net_names:
            raise ValueError("Net mapping would merge with an existing PCB net")
        if new.lstrip("/") not in labels:
            raise ValueError("Net mapping target has no matching schematic label")
    counts: dict[str, int] = {}
    for old, new in nets.items():
        counts[old] = _renamed_nets(expected, {old: new})
        if counts[old] < 1:
            raise ValueError("Net mapping did not touch PCB copper")
    updated = board_text
    for old, new in refs.items():
        needle = f'(property "Reference" "{old}"'
        if updated.count(needle) != 1:
            raise ValueError("Reference source text is ambiguous")
        updated = updated.replace(needle, f'(property "Reference" "{new}"', 1)
    for old, new in nets.items():
        needle = f'(net "{old}")'
        if updated.count(needle) != counts[old]:
            raise ValueError("Net source text is ambiguous or unsupported")
        updated = updated.replace(needle, f'(net "{new}")')
    if parse(updated) != expected:
        raise ValueError("Unexpected KiCad source construct changed; parity draft refused")
    if updated == board_text:
        raise ValueError("Parity candidate would be identical")
    return updated.encode("utf-8")


def preview_parity_repair(
    original_board: str | Path,
    output_dir: str | Path,
    *,
    reference_mappings: list[tuple[str, str]],
    net_mappings: list[tuple[str, str]],
) -> dict[str, Any]:
    """Create an independently native-reviewed KiCad draft, NOT an accepted board."""
    start = perf_counter()
    board, output = Path(original_board), Path(output_dir)
    if board.suffix != ".kicad_pcb" or not board.is_file():
        raise ValueError("Original .kicad_pcb file is required")
    schematic, project = board.with_suffix(".kicad_sch"), board.with_suffix(".kicad_pro")
    if not schematic.is_file() or not project.is_file():
        raise ValueError("Matching .kicad_sch and .kicad_pro files are required")
    _new_destination(board, output)
    original = {
        board.name: board.read_bytes(),
        schematic.name: schematic.read_bytes(),
        project.name: project.read_bytes(),
    }
    if snapshot_source_hierarchy(original[schematic.name], schematic.parent).file_count != 1:
        raise ValueError("Only single-sheet original KiCad sources are supported")
    proposed = propose_source_bound_parity_board(
        original[board.name],
        original[schematic.name],
        reference_mappings=reference_mappings,
        net_mappings=net_mappings,
        expected_sha256=_digest(original[board.name]),
    )
    with TemporaryDirectory(prefix="zaptrace-parity-repair-candidate-") as scratch:
        candidate = Path(scratch) / board.name
        with candidate.open("xb") as handle:
            handle.write(proposed)
        native = review_native_pcb_drc_delta(
            board,
            candidate,
            expected_original_sha256=_digest(original[board.name]),
            expected_candidate_sha256=_digest(proposed),
            expected_project_sha256=_digest(original[project.name]),
            include_electrical_checks=True,
            expected_original_schematic_sha256=_digest(original[schematic.name]),
        )
    er = native.electrical_review
    if not native.no_review_regression or er is None:
        raise ValueError("Native KiCad electrical/DRC regression; parity draft refused")
    if er.baseline_schematic_parity_issues <= er.candidate_schematic_parity_issues:
        raise ValueError("Native KiCad parity was not improved; parity draft refused")
    if any(_digest(path.read_bytes()) != _digest(original[path.name]) for path in (board, schematic, project)):
        raise ValueError("Original KiCad source changed during review")
    report: dict[str, Any] = {
        "task_kind": "source-bound-testpoint-and-net-alias-parity-preview",
        "attempt_status": (
            "human-review-required"
            if native.candidate_drc_clean and er.candidate_electrical_clean
            else "human-review-required-existing-native-findings"
        ),
        "g0_verified": False,
        "manufacturing_approved": False,
        "native_kicad_version": native.native_kicad_version,
        "native_candidate_clean": bool(native.candidate_drc_clean and er.candidate_electrical_clean),
        "original_pcb_sha256": _digest(original[board.name]),
        "candidate_pcb_sha256": _digest(proposed),
        "original_schematic_sha256": _digest(original[schematic.name]),
        "candidate_schematic_sha256": _digest(original[schematic.name]),
        "original_project_sha256": _digest(original[project.name]),
        "reference_mappings": [{"from": old, "to": new} for old, new in reference_mappings],
        "net_mappings": [{"from": old, "to": new} for old, new in net_mappings],
        "copper_pad_track_zone_geometry_preserved": True,
        "physical_silkscreen_review": "not_run",
        "functional_and_human_review": "not_run",
        "silkscreen_warning": (
            "PCB footprint Reference text on F.SilkS changes; original human-readable net labels "
            "may disappear. Independent physical legibility and assembly review required."
        ),
        "elapsed_seconds": round(perf_counter() - start, 3),
        "native_review": native.to_dict(),
        "candidate_board": str(output / board.name),
        "candidate_schematic": str(output / schematic.name),
        "candidate_project": str(output / project.name),
    }
    files = {
        **original,
        board.name: proposed,
        "parity-review.json": (json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    }
    _new_destination(board, output)
    _write_new_draft(output, files)
    return report
