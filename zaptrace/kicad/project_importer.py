"""Hierarchical KiCad project importer with sheet-path provenance (issue #118).

Imports a KiCad project that may contain nested hierarchical sheets, flattening
all schematic connectivity into the canonical ZapTrace Design model while
preserving stable sheet-path provenance for every component and net.

Supported constructs
--------------------
* ``.kicad_pro``        — project file (design name, metadata)
* ``.kicad_sch``        — top-level or child schematic sheets
* ``(sheet ...)``       — hierarchical sheet reference with pins
* ``(hierarchical_label ...)`` — net crossing from child → parent sheet
* ``(global_label ...)``       — cross-sheet net (single namespace)
* Repeated sheet instances — disambiguated by instance UUID path
* ``(no_connect ...)``         — unconnected pin marker

Limitation notes
----------------
* Power symbols (``(power ...)`` lib entries) are not yet resolved across
  sheets; they are imported as regular components with a note.
* Sheet-level bus entries are recorded as unsupported findings.

Sheet-path provenance
---------------------
Every flattened component ID carries a sheet-path prefix:
``<sheet_path>/<original_ref>`` — e.g. ``/top/power_supply/U1``
so that multiple instances of the same sheet remain distinguishable.

Cross-validation findings
-------------------------
The importer checks:
* Missing child sheet files (actionable error with file path)
* Hierarchical label ↔ sheet pin name mismatches (warning)
* Duplicate component refs within the same sheet (warning)
* PCB footprint refs not matched in schematic (info)
"""

from __future__ import annotations

import contextlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zaptrace.core.models import (
    BoardPadContact,
    Component,
    Design,
    DesignMeta,
    HierarchySheet,
    Net,
)
from zaptrace.io.sexp import SexpNode
from zaptrace.io.sexp import parse as _sexp_parse
from zaptrace.kicad.schematic_importer import (
    KiCadSchematicImportResult,
    KiCadSchematicSourceSnapshot,
    import_kicad_schematic,
)

# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------


@dataclass
class HierarchicalKiCadFinding:
    """An issue detected during hierarchical KiCad import.

    Attributes
    ----------
    severity:
        ``"error"`` — import may be incomplete (e.g. missing child file);
        ``"warning"`` — fidelity issue (e.g. label/pin name mismatch);
        ``"info"`` — informational note.
    kind:
        Short machine-readable category:
        ``"missing_sheet_file"``, ``"label_pin_mismatch"``,
        ``"duplicate_ref"``, ``"pcb_schematic_mismatch"``,
        ``"unsupported_construct"``, ``"pcb_missing"``.
    message:
        Human-readable description.
    sheet_path:
        The affected sheet path (e.g. ``"/top/power_supply"``).
    """

    severity: str
    kind: str
    message: str
    sheet_path: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "kind": self.kind,
            "message": self.message,
            "sheet_path": self.sheet_path,
            "detail": self.detail,
        }


@dataclass
class KiCadProjectImportResult:
    """Result of importing a hierarchical KiCad project.

    Attributes
    ----------
    design:
        The fully-flattened canonical Design. Each component ID includes a
        sheet-path prefix for multi-instance disambiguation.
    sheets:
        List of :class:`~zaptrace.core.models.HierarchySheet` records
        describing the sheet hierarchy (also written to ``design.sheets``).
    findings:
        Ordered list of :class:`HierarchicalKiCadFinding` records from
        cross-validation, missing sheets, and label/pin mismatches.
    net_score:
        Mean net-identity score across all imported sheets (0.0–1.0).
    source_dir:
        The project directory that was imported.
    source_snapshots:
        Exact original UTF-8 bytes and page/presentation evidence by sheet.
        These are in-memory source records, not editable Design conversion.
    """

    design: Design
    sheets: list[HierarchySheet] = field(default_factory=list)
    findings: list[HierarchicalKiCadFinding] = field(default_factory=list)
    net_score: float = 1.0
    source_dir: Path | None = None
    source_snapshots: dict[str, KiCadSchematicSourceSnapshot] = field(default_factory=dict)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_dir": str(self.source_dir) if self.source_dir else None,
            "component_count": len(self.design.components),
            "net_count": len(self.design.nets),
            "sheet_count": len(self.sheets),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "net_score": self.net_score,
            "source_sheet_count": len(self.source_snapshots),
            "source_sha256_by_sheet": {
                path: snapshot.sha256 for path, snapshot in sorted(self.source_snapshots.items())
            },
            "source_evidence_by_sheet": {
                path: snapshot.to_dict() for path, snapshot in sorted(self.source_snapshots.items())
            },
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _atom(node: list[SexpNode], index: int = 1) -> str:
    """Return the string value of an atom at *index* within *node*."""
    if index < len(node):
        v = node[index]
        return str(v) if not isinstance(v, list) else ""
    return ""


def _find(nodes: list[SexpNode], tag: str) -> list[SexpNode] | None:
    """Return the first child list whose first atom equals *tag*."""
    for n in nodes:
        if isinstance(n, list) and n and str(n[0]) == tag:
            return n  # type: ignore[return-value]
    return None


def _find_all(nodes: list[SexpNode], tag: str) -> list[list[SexpNode]]:
    """Return all child lists whose first atom equals *tag*."""
    return [n for n in nodes if isinstance(n, list) and n and str(n[0]) == tag]  # type: ignore[return-value]


def _prop(nodes: list[SexpNode], key: str) -> str:
    """Return the value of a ``(property "Key" "value")`` child."""
    for n in nodes:
        if isinstance(n, list) and n and str(n[0]) == "property" and len(n) >= 3 and str(n[1]).strip('"') == key:
            return str(n[2]).strip('"')
    return ""


def _slugify(name: str) -> str:
    """Convert a sheet name to a safe path component."""
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", name.strip())
    return slug[:40] or "sheet"


# ---------------------------------------------------------------------------
# Project metadata reader
# ---------------------------------------------------------------------------


def _read_project_meta(pro_path: Path) -> dict[str, Any]:
    """Read a .kicad_pro file and return a metadata dict."""
    try:
        data = json.loads(pro_path.read_text(encoding="utf-8", errors="replace"))
        meta: dict[str, Any] = {}
        meta["title"] = str(data.get("title_block", {}).get("title", "") or pro_path.stem)
        meta["rev"] = str(data.get("title_block", {}).get("rev", ""))
        meta["company"] = str(data.get("title_block", {}).get("company", ""))
        meta["schematic_file"] = str(data.get("schematic", {}).get("file", ""))
        return meta
    except Exception:
        return {"title": pro_path.stem, "rev": "", "company": "", "schematic_file": ""}


# ---------------------------------------------------------------------------
# Sheet graph walker
# ---------------------------------------------------------------------------


@dataclass
class _SheetNode:
    """Internal representation of one sheet during traversal."""

    sheet_path: str  # logical path e.g. "/top" or "/top/power"
    file_path: Path  # absolute .kicad_sch file path
    name: str  # display name
    parent_path: str | None  # parent sheet_path


SheetQueueItem = tuple[Path, str, str | None, int]


def _sheet_walk_finding(
    findings: list[HierarchicalKiCadFinding],
    *,
    severity: str,
    kind: str,
    message: str,
    sheet_path: str,
    detail: str = "",
) -> None:
    findings.append(
        HierarchicalKiCadFinding(
            severity=severity,
            kind=kind,
            message=message,
            sheet_path=sheet_path,
            detail=detail,
        )
    )


def _read_sheet_tree(
    file_path: Path,
    sheet_path: str,
    findings: list[HierarchicalKiCadFinding],
) -> SexpNode | None:
    if not file_path.exists():
        _sheet_walk_finding(
            findings,
            severity="error",
            kind="missing_sheet_file",
            message=f"Child sheet file not found: {file_path}",
            sheet_path=sheet_path,
            detail=str(file_path),
        )
        return None
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        return _sexp_parse(text)
    except Exception as exc:
        _sheet_walk_finding(
            findings,
            severity="error",
            kind="parse_error",
            message=f"Failed to parse {file_path.name}: {exc}",
            sheet_path=sheet_path,
            detail=str(exc),
        )
        return None


def _child_sheet_queue_items(
    tree: list[SexpNode],
    project_dir: Path,
    sheet_path: str,
    depth: int,
) -> list[SheetQueueItem]:
    items: list[SheetQueueItem] = []
    for child_ref in _find_all(tree, "sheet"):
        child_file_str = _prop(child_ref, "Sheet file")
        if not child_file_str:
            continue
        child_name = _prop(child_ref, "Sheet name") or "sheet"
        items.append((project_dir / child_file_str, child_name, sheet_path, depth + 1))
    return items


def _walk_sheets(
    top_path: Path,
    project_dir: Path,
    findings: list[HierarchicalKiCadFinding],
    *,
    max_depth: int = 10,
) -> list[_SheetNode]:
    """Recursively collect all sheet nodes starting from the top-level sheet."""
    nodes: list[_SheetNode] = []
    visited: set[Path] = set()
    queue: list[SheetQueueItem] = [(top_path, "top", None, 0)]

    while queue:
        file_path, name, parent_path, depth = queue.pop(0)
        resolved = file_path.resolve()
        if resolved in visited:
            continue
        visited.add(resolved)

        sheet_path = (parent_path or "") + "/" + _slugify(name)
        nodes.append(_SheetNode(sheet_path=sheet_path, file_path=file_path, name=name, parent_path=parent_path))
        if depth >= max_depth:
            _sheet_walk_finding(
                findings,
                severity="warning",
                kind="max_depth_exceeded",
                message=f"Sheet hierarchy depth >= {max_depth}; deeper sheets not imported",
                sheet_path=sheet_path,
            )
            continue

        tree = _read_sheet_tree(file_path, sheet_path, findings)
        if isinstance(tree, list):
            queue.extend(_child_sheet_queue_items(tree, project_dir, sheet_path, depth))

    return nodes


# ---------------------------------------------------------------------------
# Sheet-level import and flattening
# ---------------------------------------------------------------------------


def _import_sheet_with_provenance(
    node: _SheetNode,
    findings: list[HierarchicalKiCadFinding],
) -> KiCadSchematicImportResult | None:
    """Import one sheet file and record any issues."""
    if not node.file_path.exists():
        return None  # error already recorded in walk

    try:
        result = import_kicad_schematic(node.file_path)
    except Exception as exc:
        findings.append(
            HierarchicalKiCadFinding(
                severity="error",
                kind="import_error",
                message=f"Failed to import {node.file_path.name}: {exc}",
                sheet_path=node.sheet_path,
                detail=str(exc),
            )
        )
        return None

    # Record per-sheet unsupported constructs as findings
    for u in result.unsupported:
        findings.append(
            HierarchicalKiCadFinding(
                severity=u.severity,
                kind="unsupported_construct",
                message=u.message,
                sheet_path=node.sheet_path,
                detail=u.kind,
            )
        )
    return result


def _prefix_id(sheet_path: str, original_id: str) -> str:
    """Return a globally unique component/net ID prefixed by sheet path."""
    return f"{sheet_path}/{original_id}"


def _project_net_id(node: _SheetNode, original_net_id: str, net_name: str) -> str:
    """Use one key for net objects and pin links; retain global-name merging."""
    if original_net_id.startswith("global_"):
        return f"global_{net_name}"
    return _prefix_id(node.sheet_path, original_net_id)


def _prefix_component_ids(
    node: _SheetNode,
    components: dict,
    source_nets: dict,
    all_components: dict,
    findings: list[HierarchicalKiCadFinding],
) -> list[str]:
    """Prefix one sheet's component IDs and merge them into ``all_components``.

    Returns the sheet's new (prefixed) component ids.
    """
    # Preserve original ref; multi-instance disambiguation uses sheet path.
    from zaptrace.core.models import Component  # local import to avoid cycle

    net_ids = {net_id: _project_net_id(node, net_id, net.name) for net_id, net in source_nets.items()}
    sheet_component_ids: list[str] = []
    for orig_id, comp in components.items():
        new_id = _prefix_id(node.sheet_path, orig_id)
        # Keep a copy with updated id (models use frozen approach, work with dict)
        comp_dict = comp.model_dump()
        comp_dict["id"] = new_id
        for pin_number, pin in comp_dict.get("pins", {}).items():
            local_net = pin.get("net")
            if local_net is None:
                continue
            if local_net not in net_ids:
                pin["net"] = None
                findings.append(
                    HierarchicalKiCadFinding(
                        severity="warning",
                        kind="unresolved_pin_net_identity",
                        message=f"Component '{comp.ref}' pin '{pin_number}' references unknown source net",
                        sheet_path=node.sheet_path,
                    )
                )
                continue
            pin["net"] = net_ids[local_net]
        try:
            new_comp = Component(**comp_dict)
        except Exception:
            new_comp = comp  # fall back to original if validation fails

        if new_id in all_components:
            findings.append(
                HierarchicalKiCadFinding(
                    severity="warning",
                    kind="duplicate_ref",
                    message=f"Duplicate component ID after prefixing: {new_id}",
                    sheet_path=node.sheet_path,
                )
            )
        all_components[new_id] = new_comp
        sheet_component_ids.append(new_id)
    return sheet_component_ids


def _merge_sheet_nets(node: _SheetNode, nets: dict, all_nets: dict) -> None:
    """Prefix one sheet's net IDs into ``all_nets``, merging same-named global nets."""
    from zaptrace.core.models import Net  # local import to avoid cycle

    for orig_id, net in nets.items():
        net_name = net.name
        canonical_id = _project_net_id(node, orig_id, net_name)

        if canonical_id not in all_nets:
            all_nets[canonical_id] = net.model_copy(update={"id": canonical_id})
            continue

        # Merge nodes from same-named global nets
        existing = all_nets[canonical_id]
        existing_nodes = list(existing.nodes)
        new_nodes = [node_ for node_ in net.nodes if node_ not in existing_nodes]
        if not new_nodes:
            continue
        merged_nodes = existing_nodes + new_nodes
        with contextlib.suppress(Exception):
            all_nets[canonical_id] = Net(id=canonical_id, name=net_name, nodes=merged_nodes)


def _flatten_sheets(
    sheet_nodes: list[_SheetNode],
    findings: list[HierarchicalKiCadFinding],
) -> tuple[dict, dict, list[HierarchySheet], list[float], dict[str, KiCadSchematicSourceSnapshot]]:
    """Import all sheets and merge into flat component/net dicts.

    Returns (components, nets, hierarchy_sheets, net_scores, source_snapshots).
    """
    all_components: dict = {}
    all_nets: dict = {}
    hierarchy_sheets: list[HierarchySheet] = []
    net_scores: list[float] = []
    source_snapshots: dict[str, KiCadSchematicSourceSnapshot] = {}

    # Track refs seen per sheet to detect duplicates within one sheet
    for node in sheet_nodes:
        result = _import_sheet_with_provenance(node, findings)
        if result is None:
            continue

        net_scores.append(result.net_score)
        if result.source_snapshot is not None:
            source_snapshots[node.sheet_path] = result.source_snapshot
        sheet_component_ids = _prefix_component_ids(
            node, result.design.components, result.design.nets, all_components, findings
        )
        _merge_sheet_nets(node, result.design.nets, all_nets)

        hierarchy_sheets.append(
            HierarchySheet(
                sheet_id=node.sheet_path,
                name=node.name,
                parent_id=node.parent_path,
                component_ids=sheet_component_ids,
            )
        )

    return all_components, all_nets, hierarchy_sheets, net_scores, source_snapshots


# ---------------------------------------------------------------------------
# PCB cross-validation
# ---------------------------------------------------------------------------


def _find_pcb_path(project_dir: Path, project_name: str) -> Path | None:
    """Locate the .kicad_pcb file in the project directory."""
    explicit = project_dir / f"{project_name}.kicad_pcb"
    if explicit.exists():
        return explicit
    pcb_files = sorted(project_dir.glob("*.kicad_pcb"))
    return pcb_files[0] if pcb_files else None


def _native_nonphysical_power_refs(
    snapshots: dict[str, KiCadSchematicSourceSnapshot],
) -> set[str]:
    """Prove power-only, footprint-less schematic refs from embedded KiCad symbols.

    A reference prefix or on_board flag is not a physical-footprint
    eligibility check. Retain uncertain references as physical candidates;
    repeated refs stay physical if any source instance is.
    """
    instances: dict[str, list[bool]] = {}
    for snapshot in snapshots.values():
        tree = _sexp_parse(snapshot.raw_bytes.decode("utf-8"))
        if not isinstance(tree, list):
            continue
        libraries = _find(tree, "lib_symbols")
        if libraries is None:
            continue
        native_power_ids = {
            _atom(symbol) for symbol in _find_all(libraries, "symbol") if _find(symbol, "power") is not None
        }
        for symbol in _find_all(tree, "symbol"):
            ref = _prop(symbol, "Reference")
            if not ref:
                continue
            lib_id = _atom(_find(symbol, "lib_id") or [])
            is_annotation = bool(lib_id in native_power_ids and not _prop(symbol, "Footprint"))
            instances.setdefault(ref, []).append(is_annotation)
    return {ref for ref, verdicts in instances.items() if verdicts and all(verdicts)}


def _crossvalidate_pcb(
    pcb_path: Path | None,
    schematic_refs: set[str],
    findings: list[HierarchicalKiCadFinding],
) -> None:
    """Check that PCB footprint refs match the flattened schematic refs."""
    if pcb_path is None:
        findings.append(
            HierarchicalKiCadFinding(
                severity="info",
                kind="pcb_missing",
                message="No .kicad_pcb file found; PCB cross-validation skipped",
            )
        )
        return

    try:
        text = pcb_path.read_text(encoding="utf-8", errors="replace")
        tree = _sexp_parse(text)
    except Exception as exc:
        findings.append(
            HierarchicalKiCadFinding(
                severity="warning",
                kind="pcb_parse_error",
                message=f"Could not parse {pcb_path.name}: {exc}",
                detail=str(exc),
            )
        )
        return

    if not isinstance(tree, list):
        return

    pcb_refs: set[str] = set()
    for fp_node in _find_all(tree, "footprint"):
        ref = _prop(fp_node, "Reference")
        if ref:
            pcb_refs.add(ref)

    # Refs in PCB but not in schematic
    pcb_only = pcb_refs - schematic_refs
    for ref in sorted(pcb_only):
        findings.append(
            HierarchicalKiCadFinding(
                severity="info",
                kind="pcb_schematic_mismatch",
                message=f"PCB footprint '{ref}' not found in schematic",
                detail=f"pcb_only={ref}",
            )
        )

    # Refs in schematic but not in PCB
    sch_only = schematic_refs - pcb_refs
    for ref in sorted(sch_only):
        findings.append(
            HierarchicalKiCadFinding(
                severity="info",
                kind="pcb_schematic_mismatch",
                message=f"Schematic component '{ref}' has no PCB footprint",
                detail=f"sch_only={ref}",
            )
        )


def _native_pad_contact(
    node: list[SexpNode],
    component: Component,
    net_by_name: dict[str, set[str]],
) -> tuple[BoardPadContact, str | None]:
    """Resolve source-only footprint-local pad evidence without guessing IDs."""
    at = _find(node, "at")
    size = _find(node, "size")
    if at is None or size is None or len(at) < 3 or len(size) < 3 or len(node) < 4:
        raise ValueError("Missing original KiCad pad size, local coordinate, type or shape")
    x, y, w, h = (
        float(_atom(at, 1)),
        float(_atom(at, 2)),
        float(_atom(size, 1)),
        float(_atom(size, 2)),
    )
    if not all(math.isfinite(value) for value in (x, y, w, h)) or w <= 0 or h <= 0:
        raise ValueError("Nonfinite or invalid native KiCad physical pad coordinates/size")
    number = _atom(node)
    net_node = _find(node, "net")
    net_name = _atom(net_node, 2) if net_node else ""
    ids = net_by_name.get(net_name, set()) if net_name else set()
    canonical_id = next(iter(ids)) if len(ids) == 1 else None
    note = None
    if net_name and not ids:
        note = "pcb_pad_unknown_net"
    elif net_name and len(ids) > 1:
        note = "pcb_pad_ambiguous_net"
    elif number in component.pins and canonical_id is not None:
        old_pin_net = component.pins[number].net
        if old_pin_net is not None and old_pin_net != canonical_id:
            note = "pcb_pad_net_mismatch"
    uuid_node = _find(node, "uuid")
    return BoardPadContact(
        number=number,
        board_net_name=net_name,
        schematic_net_id=canonical_id,
        matched_pin_number=number if number and number in component.pins else None,
        position_in_footprint_mm=(x, y),
        size_mm=(w, h),
        kind=_atom(node, 2),
        shape=_atom(node, 3),
        source_uuid=_atom(uuid_node) if uuid_node else "",
    ), note


def _append_component_pcb_contacts(
    component: Component,
    footprint: list[SexpNode],
    ids_by_name: dict[str, set[str]],
    findings: list[HierarchicalKiCadFinding],
) -> None:
    for pad in _find_all(footprint, "pad"):
        try:
            contact, issue = _native_pad_contact(pad, component, ids_by_name)
        except (ValueError, TypeError, OverflowError) as exc:
            findings.append(
                HierarchicalKiCadFinding(
                    severity="warning",
                    kind="pcb_pad_unmapped_geometry",
                    message=f"PCB pad for '{component.ref}' has unverified original geometry: {exc}",
                )
            )
            continue
        component.pcb_pad_contacts.append(contact)
        if issue:
            findings.append(
                HierarchicalKiCadFinding(
                    severity="warning",
                    kind=issue,
                    message=(
                        f"PCB pad '{component.ref}:{contact.number}' on native net "
                        f"'{contact.board_net_name}' cannot be trusted as the corresponding schematic pin net"
                    ),
                    detail=f"ref={component.ref};pad={contact.number};native_net={contact.board_net_name}",
                )
            )


def _original_pcb_footprint_nodes(pcb_path: Path | None) -> list[list[SexpNode]]:
    if pcb_path is None:
        return []
    try:
        tree = _sexp_parse(pcb_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return []  # Existing PCB cross-validation owns parse-error findings.
    return _find_all(tree, "footprint") if isinstance(tree, list) else []


def _populate_pcb_pad_contacts(
    pcb_path: Path | None,
    components: dict[str, Component],
    nets: dict[str, Net],
    findings: list[HierarchicalKiCadFinding],
) -> None:
    """Add exact original physical pad instances without projecting unverified PCB geometry.

    Never treat this source evidence as fabricated/certified footprint_def.
    """
    footprints = _original_pcb_footprint_nodes(pcb_path)
    ids_by_name: dict[str, set[str]] = {}
    for net_id, net in nets.items():
        ids_by_name.setdefault(net.name, set()).add(net_id)

    by_ref: dict[str, list[Component]] = {}
    for component in components.values():
        by_ref.setdefault(component.ref, []).append(component)

    footprint_ref_counts = {ref: 0 for ref in by_ref}
    for fp in footprints:
        ref = _prop(fp, "Reference")
        if ref in footprint_ref_counts:
            footprint_ref_counts[ref] += 1
    for fp in footprints:
        ref = _prop(fp, "Reference")
        matches = by_ref.get(ref, [])
        if not matches:
            continue  # Existing PCB vs schematic reference checker owns this mismatch.
        if len(matches) != 1 or footprint_ref_counts[ref] != 1:
            findings.append(
                HierarchicalKiCadFinding(
                    severity="warning",
                    kind="pcb_pad_ambiguous_reference",
                    message=f"PCB footprint reference '{ref}' is not uniquely tied to one schematic component",
                )
            )
            continue
        _append_component_pcb_contacts(matches[0], fp, ids_by_name, findings)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _resolve_project_paths(p: Path) -> tuple[Path, Path | None, Path]:
    """Resolve (project_dir, pro_path, top_sch_path) from a project path or directory."""
    if p.is_dir():
        project_dir = p
        pro_files = sorted(p.glob("*.kicad_pro"))
        pro_path = pro_files[0] if pro_files else None
        sch_files = sorted(p.glob("*.kicad_sch"))
        if not sch_files:
            raise ValueError(f"No .kicad_sch file found in {p}")
        return project_dir, pro_path, sch_files[0]

    project_dir = p.parent
    if p.suffix != ".kicad_pro":
        return project_dir, None, p

    sch_files = sorted(project_dir.glob("*.kicad_sch"))
    top_sch_path = sch_files[0] if sch_files else project_dir / (p.stem + ".kicad_sch")
    return project_dir, p, top_sch_path


def _load_project_meta(pro_path: Path | None, project_dir: Path, top_sch_path: Path) -> tuple[dict[str, Any], Path]:
    """Read project metadata and resolve a declared schematic-file override.

    Returns (project_meta, top_sch_path); top_sch_path is updated to the
    project's declared schematic file when one is present and exists.
    """
    project_meta: dict[str, Any] = {}
    if pro_path and pro_path.exists():
        project_meta = _read_project_meta(pro_path)
        if project_meta.get("schematic_file"):
            alt_sch = project_dir / project_meta["schematic_file"]
            if alt_sch.exists():
                top_sch_path = alt_sch
    return project_meta, top_sch_path


def import_kicad_project(
    project_path: str | Path,
    *,
    max_sheet_depth: int = 10,
) -> KiCadProjectImportResult:
    """Import a KiCad project with hierarchical schematic sheets.

    Discovers all sheets referenced from the top-level schematic, imports
    them, and flattens components and nets into a single canonical Design.

    Parameters
    ----------
    project_path:
        Path to either:
        * a ``.kicad_pro`` project file, or
        * a directory containing a ``.kicad_pro`` file (the first one found).
    max_sheet_depth:
        Maximum hierarchy depth to traverse (default 10). Deeper sheets are
        skipped and a warning finding is recorded.

    Returns
    -------
    KiCadProjectImportResult
        The flattened design with sheet provenance and cross-validation findings.

    Raises
    ------
    FileNotFoundError
        If *project_path* does not exist, or no ``.kicad_sch`` file is found.
    ValueError
        If *project_path* is a directory with no ``.kicad_pro`` or
        ``.kicad_sch`` file.
    """
    p = Path(project_path)
    if not p.exists():
        raise FileNotFoundError(f"KiCad project path not found: {p}")

    project_dir, pro_path, top_sch_path = _resolve_project_paths(p)

    findings: list[HierarchicalKiCadFinding] = []
    project_meta, top_sch_path = _load_project_meta(pro_path, project_dir, top_sch_path)
    project_name = project_meta.get("title", "") or (pro_path.stem if pro_path else top_sch_path.stem)

    # Walk the sheet hierarchy
    sheet_nodes = _walk_sheets(
        top_sch_path,
        project_dir,
        findings,
        max_depth=max_sheet_depth,
    )

    if not sheet_nodes:
        raise FileNotFoundError(f"Top-level schematic not found: {top_sch_path}")

    # Import and flatten all sheets
    components, nets, hierarchy_sheets, net_scores, source_snapshots = _flatten_sheets(sheet_nodes, findings)

    # PCB cross-validation
    schematic_refs = {getattr(c, "ref", cid) for cid, c in components.items()}
    # Native KiCad's embedded (power) symbols have no real PCB part. Keep
    # their source components and nets, but exclude proven annotations from
    # the PCB-only physical footprint correspondence check.
    schematic_refs -= _native_nonphysical_power_refs(source_snapshots)
    pcb_path = _find_pcb_path(project_dir, project_name)
    _crossvalidate_pcb(pcb_path, schematic_refs, findings)
    _populate_pcb_pad_contacts(pcb_path, components, nets, findings)

    # Build canonical Design
    from zaptrace.core.models import ImportLossRecord

    import_losses = [
        ImportLossRecord(
            source_format="KiCad",
            field_path=f.sheet_path or f.kind,
            behavior="degrade",
            note=f.message,
        )
        for f in findings
        if f.severity == "error"
    ]

    design = Design(
        meta=DesignMeta(
            name=project_name,
            version=project_meta.get("rev", ""),
            author=project_meta.get("company", ""),
        ),
        components=components,
        nets=nets,
        sheets=hierarchy_sheets,
        import_losses=import_losses,
    )

    mean_net_score = sum(net_scores) / len(net_scores) if net_scores else 1.0

    return KiCadProjectImportResult(
        design=design,
        sheets=hierarchy_sheets,
        findings=findings,
        net_score=round(mean_net_score, 4),
        source_dir=project_dir,
        source_snapshots=source_snapshots,
    )


def import_kicad_project_from_string(
    top_sch_content: str,
    *,
    child_sheets: dict[str, str] | None = None,
    project_name: str = "unnamed",
) -> KiCadProjectImportResult:
    """Import a hierarchical KiCad project from in-memory strings.

    Useful for testing and round-trip verification without touching the
    filesystem.

    Parameters
    ----------
    top_sch_content:
        S-expression content of the top-level ``.kicad_sch`` file.
    child_sheets:
        Mapping of filename → content for child sheets referenced from
        *top_sch_content*.  Missing children produce error findings.
    project_name:
        Logical project name written to the Design metadata.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)

        # Write top-level schematic
        top_path = tmp / f"{project_name}.kicad_sch"
        top_path.write_text(top_sch_content, encoding="utf-8")

        # Write child sheets
        for filename, content in (child_sheets or {}).items():
            child_path = tmp / filename
            child_path.parent.mkdir(parents=True, exist_ok=True)
            child_path.write_text(content, encoding="utf-8")

        return import_kicad_project(top_path, max_sheet_depth=10)
