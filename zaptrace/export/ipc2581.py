"""IPC-2581 (PCB fabrication data) export.

Generates a standard IPC-2581 revision D XML file from a :class:`Design`,
covering the board stackup, component placements, pad/via definitions, net
connectivity, and routing.  This is a *native* ZapTrace exporter (no external
tool required), targeting the IPC-2581D subset that covers the majority of
fabrication and assembly needs.

References
----------
- IPC-2581C/D: Generic Requirements for Electronics Manufacturing Data Exchange
- https://www.ipc2581.com/
- Compared to Gerber + Excellon + pick-place, IPC-2581 bundles everything in
  one self-contained XML file — easier to archive, transfer, and validate.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from zaptrace.core.models import Design, RouteResult

# ---------------------------------------------------------------------------
# IPC-2581 constants
# ---------------------------------------------------------------------------

# Canonical IPC-2581D XML namespace identifier; it is metadata and is never dereferenced.
_NS = "http://www.ipc2581.com/schema/IPC2581D"  # NOSONAR
_ET_NS = {"": _NS}

_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>\n'

# The first token identifies the namespace; the second is a local relative XSD reference.
_SCHEMA_LOCATION = "http://www.ipc2581.com/schema/IPC2581D IPC-2581_D.xsd"  # NOSONAR

# Minimum IPC specification version this exporter targets.
_SPEC_VERSION = "D.01.00"

_SOFTWARE_NAME = "ZapTrace"

_STANDARD_LAYER_NAMES = ("F.Cu", "Inner1", "Inner2", "Inner3", "Inner4", "B.Cu")


# ---------------------------------------------------------------------------
# Panelisation helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PanelLayout:
    """A simple rectangular PCB panel layout.

    ``cols`` × ``rows`` copies of the board are arranged in a grid with
    ``spacing_mm`` between them.  Tooling rails (fiducials, mouse-bites /
    V-grooves) are not yet modelled but the panel dimensions are reported so
    an external step can be applied.
    """

    cols: int = 1
    rows: int = 1
    spacing_mm: float = 2.0
    tooling_rail_width_mm: float = 5.0
    total_width_mm: float = 0.0
    total_height_mm: float = 0.0
    panel_count: int = 1


def compute_panel(
    board_width_mm: float,
    board_height_mm: float,
    cols: int = 1,
    rows: int = 1,
    spacing_mm: float = 2.0,
    tooling_rail_width_mm: float = 5.0,
) -> PanelLayout:
    """Compute panel dimensions for an *cols* × *rows* array of boards."""
    if cols < 1 or rows < 1:
        raise ValueError("cols and rows must be >= 1")
    inner_w = cols * board_width_mm + (cols - 1) * spacing_mm
    inner_h = rows * board_height_mm + (rows - 1) * spacing_mm
    total_w = inner_w + 2 * tooling_rail_width_mm
    total_h = inner_h + 2 * tooling_rail_width_mm
    return PanelLayout(
        cols=cols,
        rows=rows,
        spacing_mm=spacing_mm,
        tooling_rail_width_mm=tooling_rail_width_mm,
        total_width_mm=total_w,
        total_height_mm=total_h,
        panel_count=cols * rows,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_element(tag: str, attrib: dict[str, str] | None = None, text: str | None = None) -> ET.Element:
    el = ET.Element(f"{{{_NS}}}{tag}", attrib or {})
    if text is not None:
        el.text = text
    return el


def _add_sub(parent: ET.Element, tag: str, attrib: dict[str, str] | None = None, text: str | None = None) -> ET.Element:
    el = _make_element(tag, attrib, text)
    parent.append(el)
    return el


_LAYER_FUNCTION_MAP = {
    "signal": "Signal",
    "power": "Plane",
    "ground": "Plane",
    "mixed": "Mixed",
}


def _layer_function(layer_type: str) -> str:
    return _LAYER_FUNCTION_MAP.get(layer_type.lower(), "Signal")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def export_ipc2581(design: Design, panel: PanelLayout | None = None) -> str:
    """Export a :class:`Design` to an IPC-2581D XML string.

    Args:
        design: The design to export.
        panel: Optional panel arrangement. When provided, the panel outline
            and board-array placement is embedded in the output.

    Returns:
        A complete IPC-2581 XML document as a string.
    """
    root = ET.Element(f"{{{_NS}}}IPC-2581", attrib={"schemaVersion": _SPEC_VERSION, "xmlns": _NS})
    root.set("xsi:schemaLocation", _SCHEMA_LOCATION)
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")

    # --- Header ---
    header = _add_sub(root, "Header")
    _add_sub(header, "author", text="ZapTrace IPC-2581 Exporter")
    _add_sub(header, "creationDate", text=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    _add_sub(header, "software", text=_SOFTWARE_NAME)
    _add_sub(header, "softwareVersion", text="1.0")
    _add_sub(header, "specVersion", text=_SPEC_VERSION)
    _add_sub(header, "company", text="")
    _add_sub(header, "projectName", text=design.meta.name)

    # --- Content ---
    content = _add_sub(root, "Content")

    # 1. Stackup (layer definitions + physical stack)
    _export_stackup(content, design)

    # 2. Component definitions (library)
    _export_components(content, design)

    # 3. Net definitions
    _export_nets(content, design)

    # 4. Placement (component instances on the board)
    _export_placement(content, design)

    # 5. Routing (traces)
    _export_routing(content, design)

    # 6. Panel (if provided)
    if panel is not None:
        _export_panel(content, panel, design)

    ET.indent(root, space="  ")
    return _XML_DECLARATION + ET.tostring(root, encoding="unicode")


def _export_stackup(parent: ET.Element, design: Design) -> None:
    """Emit the Stackup element — layer definitions and physical stack."""
    stackup = _add_sub(parent, "Stackup")

    # Determine layers from board_def or default to 2-layer
    if design.board_def and design.board_def.layer_stack:
        layers = design.board_def.layer_stack
    else:
        # Default 2-layer stackup
        layers = []
        for _, name in enumerate(_STANDARD_LAYER_NAMES[:2]):
            from zaptrace.core.models import LayerSpec

            layers.append(LayerSpec(name=name, type="signal"))

    for i, layer in enumerate(layers):
        lf = _layer_function(layer.type)
        seq = str(i)
        if i == 0:
            side = "Top"
        elif i == len(layers) - 1:
            side = "Bottom"
        else:
            side = "Inner"
        layer_el = _add_sub(
            stackup,
            "Layer",
            attrib={
                "layerFunction": lf,
                "layerNumber": seq,
                "layerName": layer.name,
                "side": side,
            },
        )
        _add_sub(
            layer_el,
            "etchedLayer",
            attrib={
                "conductiveMaterial": "Copper",
                "layerType": "Conductive",
                "thickness": f"{layer.thickness:.4f}",
            },
        )

    # Board outline / physical dimensions
    bw = design.board.width_mm if hasattr(design.board, "width_mm") else 100.0
    bh = design.board.height_mm if hasattr(design.board, "height_mm") else 80.0
    outline = _add_sub(stackup, "BoardOutline")

    _add_sub(
        outline,
        "PolygonOutline",
        attrib={
            "width": f"{bw:.4f}",
            "height": f"{bh:.4f}",
        },
    )


def _export_components(parent: ET.Element, design: Design) -> None:
    """Emit the Component Library — unique part definitions."""
    lib = _add_sub(parent, "ComponentLibrary")

    for cid, comp in design.components.items():
        comp_el = _add_sub(
            lib,
            "Component",
            attrib={
                "name": comp.ref or cid,
                "componentId": cid,
                "package": comp.footprint or "unknown",
            },
        )
        if comp.value:
            _add_sub(comp_el, "Value", text=comp.value)
        if comp.mpn:
            _add_sub(comp_el, "ManufacturerPartNumber", text=comp.mpn)
        if comp.manufacturer:
            _add_sub(comp_el, "Manufacturer", text=comp.manufacturer)


def _export_nets(parent: ET.Element, design: Design) -> None:
    """Emit the Netlist — connectivity between pins."""
    netlist = _add_sub(parent, "Netlist")

    for net_id, net in design.nets.items():
        net_el = _add_sub(netlist, "Net", attrib={"name": net.name, "netId": net_id})
        for node in net.nodes:
            _add_sub(
                net_el,
                "Pin",
                attrib={
                    "componentId": node.component_ref,
                    "pin": node.pin_name,
                },
            )


def _export_placement(parent: ET.Element, design: Design) -> None:
    """Emit component placement — where each part is on the board."""
    placement = _add_sub(parent, "Placement")

    if not design.placement:
        return

    for cid, pos in design.placement.items():
        comp = design.components.get(cid)
        comp_ref = comp.ref if comp else cid

        x, y = pos[0], pos[1]
        rotation = pos[2] if len(pos) >= 3 else 0.0
        side = "Top"

        _add_sub(
            placement,
            "Place",
            attrib={
                "componentId": cid,
                "refDes": comp_ref,
                "x": f"{x:.4f}",
                "y": f"{y:.4f}",
                "rotation": f"{rotation:.1f}",
                "side": side,
                "mountType": "SMT",
            },
        )


def _export_routing(parent: ET.Element, design: Design) -> None:
    """Emit routing data — trace segments and vias."""
    routing = _add_sub(parent, "Routing")

    result: RouteResult | None = design.routing
    if result is None:
        return

    for trace in result.traces:
        if trace.via:
            continue  # vias as trace segments are skipped; we emit from result.vias instead
        wire_el = _add_sub(
            routing,
            "Wire",
            attrib={
                "layer": trace.layer,
                "width": f"{trace.width:.4f}",
                "net": trace.net_id,
            },
        )
        # Start point
        _add_sub(wire_el, "Start", attrib={"x": f"{trace.start[0]:.4f}", "y": f"{trace.start[1]:.4f}"})
        # End point
        _add_sub(wire_el, "End", attrib={"x": f"{trace.end[0]:.4f}", "y": f"{trace.end[1]:.4f}"})

    for via in result.vias:
        x, y, diam, hole = via[0], via[1], via[2], via[3]
        _add_sub(
            routing,
            "Via",
            attrib={
                "x": f"{x:.4f}",
                "y": f"{y:.4f}",
                "diameter": f"{diam:.4f}",
                "drillDiameter": f"{hole:.4f}",
            },
        )


def _export_panel(parent: ET.Element, panel: PanelLayout, design: Design) -> None:
    """Emit panelization data — board array and panel outline."""
    panel_el = _add_sub(
        parent,
        "Panel",
        attrib={
            "width": f"{panel.total_width_mm:.4f}",
            "height": f"{panel.total_height_mm:.4f}",
        },
    )

    bw = design.board.width_mm if hasattr(design.board, "width_mm") else 100.0
    bh = design.board.height_mm if hasattr(design.board, "height_mm") else 80.0

    for row in range(panel.rows):
        for col in range(panel.cols):
            x = panel.tooling_rail_width_mm + col * (bw + panel.spacing_mm)
            y = panel.tooling_rail_width_mm + row * (bh + panel.spacing_mm)
            _add_sub(
                panel_el,
                "BoardArray",
                attrib={
                    "col": str(col),
                    "row": str(row),
                    "x": f"{x:.4f}",
                    "y": f"{y:.4f}",
                },
            )

    _add_sub(
        panel_el,
        "ArraySpacing",
        attrib={
            "x": f"{panel.spacing_mm:.4f}",
            "y": f"{panel.spacing_mm:.4f}",
        },
    )
    _add_sub(
        panel_el,
        "ToolingRail",
        attrib={
            "width": f"{panel.tooling_rail_width_mm:.4f}",
        },
    )


# ---------------------------------------------------------------------------
# Fab capability DB — profile query and DIFF
# ---------------------------------------------------------------------------


class FabCapabilityDb:
    """A queryable database of fabrication capability profiles.

    Wraps :class:`ProfileRegistry` with additional query methods: find
    profiles that can satisfy a set of design constraints, diff two
    profiles, and check design-to-profile compatibility.

    Usage::

        db = FabCapabilityDb()
        candidates = db.find_profiles_for_design(design, min_layers=2)
        db.diff_profiles("jlcpcb-2layer", "jlcpcb-4layer")
    """

    def __init__(self) -> None:
        from zaptrace.fab.profile import ProfileRegistry

        self._registry = ProfileRegistry()

    @property
    def profile_names(self) -> list[str]:
        return self._registry.available_names

    def get_profile(self, name: str) -> object:
        """Return a fab profile by name, or raise ValueError."""
        profile = self._registry.get(name)
        if profile is None:
            raise ValueError(f"Unknown fab profile: {name!r}. Available: {self.profile_names}")
        return profile

    def find_profiles_for_design(
        self,
        design: Design,
        *,
        min_layers: int = 2,
        max_trace_mm: float = 0.15,
        min_drill_mm: float = 0.2,
        max_board_dim_mm: float = 100.0,
    ) -> list[dict[str, Any]]:
        """Return profiles that can satisfy the given design constraints.

        Each result includes the profile name and a compatibility score
        (1.0 = fully compatible, <1.0 = some constraints exceed capabilities).
        """
        candidates: list[dict[str, Any]] = []
        for profile in self._registry.all():
            issues: list[str] = []
            score = 1.0

            if max_trace_mm < profile.min_trace_mm:
                issues.append(f"min trace {max_trace_mm} < profile {profile.min_trace_mm}")
                score -= 0.2

            if min_drill_mm < profile.min_drill_mm:
                issues.append(f"min drill {min_drill_mm} < profile {profile.min_drill_mm}")
                score -= 0.2

            if max_board_dim_mm > profile.max_board_width_mm or max_board_dim_mm > profile.max_board_height_mm:
                issues.append(f"board dimension {max_board_dim_mm} > profile max {profile.max_board_width_mm}")
                score -= 0.15

            if min_layers > max(profile.capabilities.layer_counts) if profile.capabilities.layer_counts else 2:
                issues.append(f"layer count {min_layers} > profile max layers")
                score -= 0.25

            candidates.append(
                {
                    "name": profile.name,
                    "manufacturer": profile.manufacturer,
                    "compatible": not issues,
                    "score": max(0.0, score),
                    "issues": issues,
                }
            )

        return sorted(candidates, key=lambda c: c["score"], reverse=True)

    def diff_profiles(self, name_a: str, name_b: str) -> dict[str, Any]:
        """Diff two profiles and return the differences.

        Returns a dict with common, only_a, only_b fields.
        """
        profile_a = self.get_profile(name_a)
        profile_b = self.get_profile(name_b)

        fields = [
            "min_trace_mm",
            "min_space_mm",
            "min_drill_mm",
            "min_annular_ring_mm",
            "max_board_width_mm",
            "max_board_height_mm",
            "impedance_control",
            "via_in_pad",
            "blind_buried_vias",
        ]

        common: dict[str, Any] = {}
        only_a: dict[str, Any] = {}
        only_b: dict[str, Any] = {}

        for f in fields:
            va = getattr(profile_a, f)
            vb = getattr(profile_b, f)
            if va == vb:
                common[f] = va
            else:
                only_a[f] = va
                only_b[f] = vb

        return {
            "profile_a": name_a,
            "profile_b": name_b,
            "common": common,
            "only_a": only_a,
            "only_b": only_b,
        }
