from __future__ import annotations

import math
import re
from pathlib import Path

from zaptrace.core.models import Design, RouteResult, TraceSegment
from zaptrace.io.sexp import SexpNode, SexpParseError
from zaptrace.io.sexp import parse as _parse_sexp


def _find_node(node: SexpNode, name: str) -> list[SexpNode] | None:
    """Find the first list node whose first element equals *name*."""
    if not isinstance(node, list) or not node:
        return None
    if node[0] == name:
        return node  # type: ignore[return-value]
    for child in node[1:]:
        if isinstance(child, list):
            res = _find_node(child, name)
            if res:
                return res
    return None


def _find_nodes(node: SexpNode, name: str) -> list[list[SexpNode]]:
    """Find all list nodes whose first element equals *name*."""
    results: list[list[SexpNode]] = []
    if not isinstance(node, list) or not node:
        return results
    if node[0] == name:
        results.append(node)  # type: ignore[arg-type]
    for child in node[1:]:
        if isinstance(child, list):
            results.extend(_find_nodes(child, name))
    return results


def _to_float(node: SexpNode) -> float:
    """Convert a leaf *node* to float; raises ``ValueError`` if not possible."""
    if isinstance(node, str):
        return float(node)
    raise ValueError(f"Expected atom, got list: {node!r}")


def _read_ses(filepath: str | Path) -> SexpNode:
    try:
        content = Path(filepath).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Failed to read SES file: {exc}") from exc
    try:
        return _parse_sexp(content)
    except (SexpParseError, ValueError) as exc:
        raise ValueError(f"Malformed SES file (S-expression error): {exc}") from exc


def _ses_scale_factor(sexp: SexpNode) -> float:
    node = _find_node(sexp, "resolution")
    if not node or len(node) < 3:
        return 1.0
    unit = str(node[1]).lower()
    try:
        value = _to_float(node[2])
    except ValueError:
        return 1.0
    if value == 0:
        return 1.0
    factors = {"um": 1.0 / (value * 1000.0), "mm": 1.0 / value, "mil": 0.0254 / value, "in": 25.4 / value}
    return factors.get(unit, 1.0)


def _ses_via_defs(sexp: SexpNode) -> dict[str, tuple[float, float]]:
    definitions: dict[str, tuple[float, float]] = {}
    for padstack in _find_nodes(sexp, "padstack"):
        if len(padstack) < 2:
            continue
        name = str(padstack[1])
        diameter, hole = 0.45, 0.2
        match = re.search(r"_(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)", name)
        if match:
            first, second = float(match.group(1)), float(match.group(2))
            if first > 10.0:
                diameter, hole = first / 1000.0, second / 1000.0
            else:
                diameter, hole = first, second
        definitions[name] = (diameter, hole)
    return definitions


def _ses_wire_segments(
    item: list[SexpNode], net_id: str, scale_factor: float
) -> tuple[list[TraceSegment], str | None, float]:
    path = _find_node(item, "path")
    if not path or len(path) < 4:
        return [], None, 0.0
    layer = str(path[1])
    try:
        width = _to_float(path[2]) * scale_factor
        points = [_to_float(value) * scale_factor for value in path[3:]]
    except ValueError:
        return [], None, 0.0
    segments: list[TraceSegment] = []
    total = 0.0
    for index in range(0, len(points) - 3, 2):
        start = (points[index], points[index + 1])
        end = (points[index + 2], points[index + 3])
        segments.append(TraceSegment(layer=layer, start=start, end=end, width=width, net_id=net_id))
        total += math.hypot(end[0] - start[0], end[1] - start[1])
    return segments, layer, total


def _ses_via_segment(
    item: list[SexpNode], net_id: str, scale_factor: float, via_defs: dict[str, tuple[float, float]]
) -> tuple[tuple[float, float, float, float], TraceSegment] | None:
    if len(item) < 4:
        return None
    try:
        x = _to_float(item[2]) * scale_factor
        y = _to_float(item[3]) * scale_factor
    except ValueError:
        return None
    diameter, hole = via_defs.get(str(item[1]), (0.45, 0.2))
    via = (x, y, diameter, hole)
    segment = TraceSegment(
        layer="",
        start=(x, y),
        end=(x, y),
        width=diameter,
        net_id=net_id,
        via=True,
        via_diameter=diameter,
        via_hole=hole,
    )
    return via, segment


def _append_ses_net(
    net: list[SexpNode],
    result: RouteResult,
    scale_factor: float,
    via_defs: dict[str, tuple[float, float]],
    layers: set[str],
) -> tuple[bool, float]:
    if len(net) < 2:
        return False, 0.0
    net_id = str(net[1])
    routed = False
    total = 0.0
    for item in net[2:]:
        if not isinstance(item, list) or not item:
            continue
        if item[0] == "wire":
            segments, layer, length = _ses_wire_segments(item, net_id, scale_factor)
            result.traces.extend(segments)
            if layer is not None:
                layers.add(layer)
            routed = routed or bool(segments)
            total += length
        elif item[0] == "via":
            parsed = _ses_via_segment(item, net_id, scale_factor, via_defs)
            if parsed is not None:
                via, segment = parsed
                result.vias.append(via)
                result.traces.append(segment)
                routed = True
    return routed, total


def parse_ses(filepath: str | Path) -> RouteResult:
    """Parse a Specctra SES session file and return a RouteResult."""
    sexp = _read_ses(filepath)
    scale_factor = _ses_scale_factor(sexp)
    via_defs = _ses_via_defs(sexp)
    nets = _find_nodes(sexp, "net")
    result = RouteResult()
    layers: set[str] = set()
    routed_nets = 0
    total_length = 0.0
    for net in nets:
        routed, length = _append_ses_net(net, result, scale_factor, via_defs, layers)
        routed_nets += int(routed)
        total_length += length
    result.layers_used = list(layers)
    result.total_trace_length_mm = total_length
    result.net_count = len(nets)
    result.routed_net_count = routed_nets
    return result


def apply_ses_routing(design: Design, ses_filepath: str | Path) -> RouteResult:
    """Parse a Specctra SES file and apply its routing results to the Design.

    Sets ``design.routing`` to the parsed :class:`RouteResult` so the routed
    traces and vias are available for export, DRC, and downstream tools.

    This completes the DSN → Freerouting → SES round-trip::

        export_dsn(design)    →  write .dsn → Freerouting → .ses
        apply_ses_routing(design, "output.ses")  →  design.routing populated

    Args:
        design: The design to apply routing to (must match the source DSN).
        ses_filepath: Path to the .ses file produced by the autorouter.

    Returns:
        The parsed RouteResult (also stored in ``design.routing``).

    Raises:
        ValueError: If the SES file cannot be read or parsed.
    """
    result = parse_ses(ses_filepath)
    design.routing = result
    return result
