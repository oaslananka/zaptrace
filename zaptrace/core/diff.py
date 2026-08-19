from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from zaptrace.core.models import Design


class DiffType(StrEnum):
    COMPONENT_ADDED = "component_added"
    COMPONENT_REMOVED = "component_removed"
    COMPONENT_CHANGED = "component_changed"
    NET_ADDED = "net_added"
    NET_REMOVED = "net_removed"
    NET_NODE_ADDED = "net_node_added"
    NET_NODE_REMOVED = "net_node_removed"
    VALUE_CHANGED = "value_changed"
    FOOTPRINT_CHANGED = "footprint_changed"
    BOARD_CHANGED = "board_changed"


@dataclass
class DiffEntry:
    type: DiffType
    ref: str
    detail: str
    old_value: str | None = None
    new_value: str | None = None


def diff_designs(old: Design, new: Design) -> list[DiffEntry]:
    """
    Return a list of semantic differences between two Design objects.
    Suitable for PR comments, design review, and git difftool output.
    """
    entries: list[DiffEntry] = []

    old_comps = {c.ref: c for c in old.components.values()}
    new_comps = {c.ref: c for c in new.components.values()}

    for ref in sorted(old_comps.keys() - new_comps.keys()):
        c = old_comps[ref]
        entries.append(DiffEntry(DiffType.COMPONENT_REMOVED, ref, f"{ref} ({c.type}) removed"))

    for ref in sorted(new_comps.keys() - old_comps.keys()):
        c = new_comps[ref]
        entries.append(DiffEntry(DiffType.COMPONENT_ADDED, ref, f"{ref} ({c.type}) added"))

    for ref in sorted(old_comps.keys() & new_comps.keys()):
        oc, nc = old_comps[ref], new_comps[ref]
        if oc.value != nc.value:
            entries.append(
                DiffEntry(
                    DiffType.VALUE_CHANGED,
                    ref,
                    f"{ref} value changed",
                    oc.value,
                    nc.value,
                )
            )
        if oc.footprint != nc.footprint:
            entries.append(
                DiffEntry(
                    DiffType.FOOTPRINT_CHANGED,
                    ref,
                    f"{ref} footprint changed",
                    oc.footprint,
                    nc.footprint,
                )
            )

    old_nets = {n.name: n for n in old.nets.values()}
    new_nets = {n.name: n for n in new.nets.values()}

    for name in sorted(old_nets.keys() - new_nets.keys()):
        entries.append(DiffEntry(DiffType.NET_REMOVED, name, f"net '{name}' removed"))

    for name in sorted(new_nets.keys() - old_nets.keys()):
        entries.append(DiffEntry(DiffType.NET_ADDED, name, f"net '{name}' added"))

    board_fields = ["width_mm", "height_mm", "layers"]
    for field in board_fields:
        ov, nv = getattr(old.board, field), getattr(new.board, field)
        if ov != nv:
            entries.append(
                DiffEntry(
                    DiffType.BOARD_CHANGED,
                    "board",
                    f"board.{field} changed",
                    str(ov),
                    str(nv),
                )
            )

    return entries


def format_diff(entries: list[DiffEntry]) -> str:
    """Return a human-readable Markdown string of diff entries."""
    if not entries:
        return "No differences found."
    lines: list[str] = []
    for e in entries:
        if e.old_value is not None and e.new_value is not None:
            lines.append(f"- **{e.type}**: {e.detail} (`{e.old_value}` -> `{e.new_value}`)")
        else:
            lines.append(f"- **{e.type}**: {e.detail}")
    return "\n".join(lines)
