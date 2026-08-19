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


def parse_ses(filepath: str | Path) -> RouteResult:
    """Parse a Specctra SES session file and return a RouteResult.

    Args:
        filepath: Path to the .ses file.

    Returns:
        RouteResult with parsed traces and vias.

    Raises:
        ValueError: If the file is malformed.
    """
    try:
        content = Path(filepath).read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"Failed to read SES file: {e}") from e

    try:
        sexp = _parse_sexp(content)
    except SexpParseError as e:
        raise ValueError(f"Malformed SES file (S-expression error): {e}") from e
    except ValueError as e:
        raise ValueError(f"Malformed SES file (S-expression error): {e}") from e

    scale_factor = 1.0
    res_node = _find_node(sexp, "resolution")
    if res_node and len(res_node) >= 3:
        unit = str(res_node[1]).lower()
        try:
            val = _to_float(res_node[2])
            if val != 0:
                if unit == "um":
                    scale_factor = 1.0 / (val * 1000.0)
                elif unit == "mm":
                    scale_factor = 1.0 / val
                elif unit == "mil":
                    scale_factor = 0.0254 / val
                elif unit == "in":
                    scale_factor = 25.4 / val
        except ValueError:
            pass

    result = RouteResult()

    via_defs: dict[str, tuple[float, float]] = {}
    padstacks = _find_nodes(sexp, "padstack")
    for ps in padstacks:
        if len(ps) < 2:
            continue
        name = str(ps[1])

        diam, hole = 0.45, 0.2
        m = re.search(r"_(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)", name)
        if m:
            val1, val2 = float(m.group(1)), float(m.group(2))
            if val1 > 10.0:  # heuristic to assume um
                diam = val1 / 1000.0
                hole = val2 / 1000.0
            else:
                diam = val1
                hole = val2

        via_defs[name] = (diam, hole)

    nets = _find_nodes(sexp, "net")
    layers_used: set[str] = set()
    total_len = 0.0
    routed_nets = 0

    for net in nets:
        if len(net) < 2:
            continue
        net_id = str(net[1])
        net_has_routing = False

        for item in net[2:]:
            if not isinstance(item, list) or not item:
                continue

            if item[0] == "wire":
                path = _find_node(item, "path")
                if path and len(path) >= 4:
                    layer = str(path[1])
                    try:
                        width = _to_float(path[2]) * scale_factor
                        pts = [_to_float(x) * scale_factor for x in path[3:]]
                    except ValueError:
                        continue

                    layers_used.add(layer)

                    for i in range(0, len(pts) - 3, 2):
                        x1, y1 = pts[i], pts[i + 1]
                        x2, y2 = pts[i + 2], pts[i + 3]

                        seg = TraceSegment(
                            layer=layer,
                            start=(x1, y1),
                            end=(x2, y2),
                            width=width,
                            net_id=net_id,
                        )
                        result.traces.append(seg)

                        total_len += math.hypot(x2 - x1, y2 - y1)
                        net_has_routing = True

            elif item[0] == "via" and len(item) >= 4:
                via_name = str(item[1])
                try:
                    x = _to_float(item[2]) * scale_factor
                    y = _to_float(item[3]) * scale_factor
                except ValueError:
                    continue

                diam, hole = via_defs.get(via_name, (0.45, 0.2))
                result.vias.append((x, y, diam, hole))

                vseg = TraceSegment(
                    layer="",
                    start=(x, y),
                    end=(x, y),
                    width=diam,
                    net_id=net_id,
                    via=True,
                    via_diameter=diam,
                    via_hole=hole,
                )
                result.traces.append(vseg)

                net_has_routing = True

        if net_has_routing:
            routed_nets += 1

    result.layers_used = list(layers_used)
    result.total_trace_length_mm = total_len
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
