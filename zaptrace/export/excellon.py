"""Excellon drill file format exporter.

Generates NC drill files (``*.DRL`` / ``*.TXT``) from a
:class:`~zaptrace.core.models.Design`. Handles both plated (PTH) and
non-plated (NPTH) holes.

Output format follows the standard Excellon / CNC-7 format used by
PCB manufacturers (JLCPCB, PCBWay, etc.).
"""

from __future__ import annotations

from pathlib import Path

from zaptrace.core.models import Design
from zaptrace.export.path_policy import safe_export_stem

# ---------------------------------------------------------------------------
# Excellon constants
# ---------------------------------------------------------------------------

_HEADER = """M48
; LEADER: ZapTrace generated Excellon drill file
;FILE={filename}
FORMAT={format_str}
{tool_defs}
{units}
""".lstrip()

_TRAILER = """M30
"""

_UNITS_MM = "METRIC,TZ\n"
_UNITS_INCH = "INCH,TZ\n"
_GENERATED_LEADER = "ZapTrace generated Excellon drill file"
_COMBINED_LEADER = "ZapTrace combined drill file"

_DrillHole = tuple[float, float, float, bool]
_DrillCoordinate = tuple[float, float, float]
_ToolCoordinates = dict[int, list[tuple[float, float]]]

# ---------------------------------------------------------------------------
# Drill tool management
# ---------------------------------------------------------------------------


class _ToolManager:
    """Manages drill tool definitions.

    Tools are assigned incrementing T-codes (T01+). Holes with the same
    diameter share the same tool.
    """

    def __init__(self) -> None:
        self._tools: list[tuple[int, float, bool]] = []  # (number, diameter_mm, plated)
        self._diam_to_tool: dict[float, int] = {}

    def get_or_create(self, diameter_mm: float, plated: bool = True) -> int:
        """Get or create a drill tool for the given diameter."""
        key = round(diameter_mm, 4)
        if key in self._diam_to_tool:
            return self._diam_to_tool[key]
        number = len(self._tools) + 1
        self._tools.append((number, key, plated))
        self._diam_to_tool[key] = number
        return number

    def tool_defs_lines(self) -> list[str]:
        """Generate tool definition lines."""
        lines: list[str] = []
        for number, diameter, _plated in self._tools:
            lines.append(f"T{number:02d}C{diameter:.4f}\n")
        return lines

    def format_string(self) -> str:
        """Determine format string based on max diameter precision."""
        return _UNITS_MM

    def count(self) -> int:
        return len(self._tools)


# ---------------------------------------------------------------------------
# Shared collection and rendering helpers
# ---------------------------------------------------------------------------


def _component_drill_holes(design: Design) -> list[_DrillHole]:
    holes: list[_DrillHole] = []
    for component in design.components.values():
        footprint = component.footprint_def
        position = component.position
        if footprint is None or position is None:
            continue
        cx, cy = position
        for pad in footprint.pads:
            drill = pad.drill
            if drill is None or drill <= 0:
                continue
            holes.append((cx + pad.position[0], cy + pad.position[1], drill, pad.plated))
    return holes


def _mounting_drill_holes(design: Design) -> list[_DrillHole]:
    if design.board_def is None:
        return []
    return [
        (hole.position[0], hole.position[1], hole.diameter, hole.plated) for hole in design.board_def.mounting_holes
    ]


def _routing_drill_holes(design: Design) -> list[_DrillHole]:
    if design.routing is None:
        return []
    return [(via[0], via[1], via[3], True) for via in design.routing.vias]


def _collect_drill_holes(design: Design) -> list[_DrillHole]:
    """Collect component, mounting, and via holes in legacy output order."""
    return _component_drill_holes(design) + _mounting_drill_holes(design) + _routing_drill_holes(design)


def _group_holes_by_tool(holes: list[_DrillCoordinate], tools: _ToolManager) -> _ToolCoordinates:
    grouped: _ToolCoordinates = {}
    for x, y, diameter in sorted(holes, key=lambda hole: hole[2]):
        tool = tools.get_or_create(diameter, True)
        grouped.setdefault(tool, []).append((x, y))
    return grouped


def _coordinate_lines(grouped: _ToolCoordinates) -> list[str]:
    lines: list[str] = []
    for tool_number in sorted(grouped):
        lines.append(f"T{tool_number:02d}\n")
        for x, y in grouped[tool_number]:
            ix = int(round(x * 1_000_000))
            iy = int(round(y * 1_000_000))
            lines.append(f"X{ix}Y{iy}\n")
    return lines


def _render_drill_file(holes: list[_DrillCoordinate], *, filename: str, leader: str) -> str:
    """Render one deterministic Excellon file from coordinate/diameter tuples."""
    tools = _ToolManager()
    grouped = _group_holes_by_tool(holes, tools)
    lines = ["M48\n", f"; {leader}\n", f";FILE={filename}\n", _UNITS_MM, "%\n"]
    lines.extend(tools.tool_defs_lines())
    lines.extend(_coordinate_lines(grouped))
    lines.append(_TRAILER)
    return "".join(lines)


def _prepare_output(output_dir: str | Path | None) -> tuple[bool, Path]:
    use_files = output_dir is not None
    out_dir = Path(output_dir) if output_dir else Path()
    if use_files:
        out_dir.mkdir(parents=True, exist_ok=True)
    return use_files, out_dir


def _write_drill_file(out_dir: Path, filename: str, content: str) -> Path:
    path = out_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def _add_drill_result(
    result: dict[str, str | Path],
    *,
    key: str,
    holes: list[_DrillCoordinate],
    filename: str,
    use_files: bool,
    out_dir: Path,
) -> None:
    if not holes:
        return
    content = _render_drill_file(holes, filename=filename, leader=_GENERATED_LEADER)
    result[key] = _write_drill_file(out_dir, filename, content) if use_files else content


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_excellon(design: Design, output_dir: str | Path | None = None, prefix: str = "") -> dict[str, str | Path]:
    """Generate Excellon drill files.

    Produces one drill file for all holes. Both plated (PTH) and non-plated
    holes are included, sorted by tool size.

    Args:
        design: The design containing footprint pad definitions.
        output_dir: Directory to write files. ``None`` = return content as strings.
        prefix: Filename prefix (usually design name).

    Returns:
        Map of drill type → file path (if ``output_dir``) or content string.
    """
    use_files, out_dir = _prepare_output(output_dir)
    safe_prefix = safe_export_stem(prefix or design.meta.name or "board")
    holes = _collect_drill_holes(design)
    plated = [(x, y, diameter) for x, y, diameter, is_plated in holes if is_plated]
    non_plated = [(x, y, diameter) for x, y, diameter, is_plated in holes if not is_plated]

    result: dict[str, str | Path] = {}
    _add_drill_result(
        result,
        key="plated",
        holes=plated,
        filename=f"{safe_prefix}.DRL",
        use_files=use_files,
        out_dir=out_dir,
    )
    _add_drill_result(
        result,
        key="non_plated",
        holes=non_plated,
        filename=f"{safe_prefix}-NPTH.DRL",
        use_files=use_files,
        out_dir=out_dir,
    )
    return result


def generate_composite_drill(design: Design, output_dir: str | Path | None = None, prefix: str = "") -> str | Path:
    """Generate a single combined drill file (PTH + NPTH).

    Convenience wrapper that combines all holes into one file.
    """
    use_files, out_dir = _prepare_output(output_dir)
    safe_prefix = safe_export_stem(prefix or design.meta.name or "board")
    holes = [(x, y, diameter) for x, y, diameter, _is_plated in _collect_drill_holes(design)]
    filename = f"{safe_prefix}-ALL.DRL"
    content = _render_drill_file(holes, filename=filename, leader=_COMBINED_LEADER)
    if use_files:
        return _write_drill_file(out_dir, filename, content)
    return content
