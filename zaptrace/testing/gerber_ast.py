"""Geometric AST-level semantic canonicalizers for Gerber (RS-274X) and Excellon.

Provides deterministic AST parsing and geometric semantic comparison to distinguish
true functional EDA regression from formatting/aperture-numbering jitter.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass


def _round_coord(val: float, precision: int = 3) -> float:
    """Round coordinate to specified millimeter precision (default 3 decimals = 1 um)."""
    return round(float(val), precision)


def _shoelace_area(vertices: list[tuple[float, float]]) -> float:
    """Calculate polygon area using the Shoelace formula."""
    n = len(vertices)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += vertices[i][0] * vertices[j][1]
        area -= vertices[j][0] * vertices[i][1]
    return 0.5 * abs(area)


@dataclass(frozen=True)
class GerberAperture:
    code: int
    shape: str  # "circle", "rect", "obround"
    params: tuple[float, ...]


@dataclass(frozen=True)
class GerberRegion:
    """Normalized Gerber filled region (G36/G37) representing a pour polygon or cutout."""

    vertices: tuple[tuple[float, float], ...]
    area: float
    bounding_box: tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)

    @classmethod
    def from_raw_vertices(cls, raw: list[tuple[float, float]]) -> GerberRegion | None:
        if not raw or len(raw) < 3:
            return None
        # Remove trailing closure duplicate if identical to start
        pts = list(raw)
        if len(pts) > 1 and pts[-1] == pts[0]:
            _ = pts.pop()
        if len(pts) < 3:
            return None

        # Round coordinates to 1 um precision
        rounded = [(_round_coord(x), _round_coord(y)) for x, y in pts]

        # Rotate vertex list cyclically so lexicographically smallest vertex is index 0
        min_idx = min(range(len(rounded)), key=lambda i: (rounded[i][0], rounded[i][1]))
        normalized_vertices = tuple(rounded[min_idx:] + rounded[:min_idx])

        area = _round_coord(_shoelace_area(list(normalized_vertices)), 4)
        xs = [p[0] for p in normalized_vertices]
        ys = [p[1] for p in normalized_vertices]
        bbox = (_round_coord(min(xs)), _round_coord(min(ys)), _round_coord(max(xs)), _round_coord(max(ys)))
        return cls(vertices=normalized_vertices, area=area, bounding_box=bbox)

    def to_dict(self) -> dict[str, object]:
        return {
            "vertices": [[x, y] for x, y in self.vertices],
            "area": self.area,
            "bounding_box": list(self.bounding_box),
        }


@dataclass(frozen=True)
class GerberFlash:
    """Gerber flash command (D03) representing a pad or via."""

    x: float
    y: float
    shape: str
    size: tuple[float, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "x": self.x,
            "y": self.y,
            "shape": self.shape,
            "size": list(self.size),
        }


@dataclass(frozen=True)
class GerberLine:
    """Gerber draw command (D01) representing a trace segment or thermal spoke."""

    start: tuple[float, float]
    end: tuple[float, float]
    width: float
    length: float

    @classmethod
    def create(cls, p1: tuple[float, float], p2: tuple[float, float], width: float) -> GerberLine:
        rp1 = (_round_coord(p1[0]), _round_coord(p1[1]))
        rp2 = (_round_coord(p2[0]), _round_coord(p2[1]))
        # Canonicalize line orientation so start <= end lexicographically
        start, end = min(rp1, rp2), max(rp1, rp2)
        rw = _round_coord(width)
        length = _round_coord(math.dist(start, end), 4)
        return cls(start=start, end=end, width=rw, length=length)

    def to_dict(self) -> dict[str, object]:
        return {
            "start": [self.start[0], self.start[1]],
            "end": [self.end[0], self.end[1]],
            "width": self.width,
            "length": self.length,
        }


@dataclass(frozen=True)
class GerberAST:
    """Normalized, aperture-independent geometric AST for RS-274X Gerber layers."""

    regions: tuple[GerberRegion, ...]
    flashes: tuple[GerberFlash, ...]
    lines: tuple[GerberLine, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "regions": [r.to_dict() for r in self.regions],
            "flashes": [f.to_dict() for f in self.flashes],
            "lines": [line_item.to_dict() for line_item in self.lines],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True) + "\n"

    def compare(self, other: GerberAST, tolerance_mm: float = 0.001) -> tuple[bool, list[str]]:
        """Compare geometric equivalence against another Gerber AST."""
        diffs = [
            *_compare_regions(self.regions, other.regions, tolerance_mm),
            *_compare_flashes(self.flashes, other.flashes, tolerance_mm),
            *_compare_lines(self.lines, other.lines, tolerance_mm),
        ]
        return (not diffs, diffs)


def _compare_regions(
    left: tuple[GerberRegion, ...],
    right: tuple[GerberRegion, ...],
    tolerance_mm: float,
) -> list[str]:
    if len(left) != len(right):
        return [f"Region count mismatch: {len(left)} vs {len(right)}"]
    diffs: list[str] = []
    for index, (first, second) in enumerate(zip(left, right, strict=True)):
        if abs(first.area - second.area) > tolerance_mm:
            diffs.append(f"Region {index} area mismatch: {first.area} vs {second.area}")
        if len(first.vertices) != len(second.vertices):
            diffs.append(f"Region {index} vertex count mismatch: {len(first.vertices)} vs {len(second.vertices)}")
            continue
        for vertex_index, (first_vertex, second_vertex) in enumerate(zip(first.vertices, second.vertices, strict=True)):
            if math.dist(first_vertex, second_vertex) > tolerance_mm:
                diffs.append(
                    f"Region {index} vertex {vertex_index} position mismatch: {first_vertex} vs {second_vertex}"
                )
    return diffs


def _compare_flashes(
    left: tuple[GerberFlash, ...],
    right: tuple[GerberFlash, ...],
    tolerance_mm: float,
) -> list[str]:
    if len(left) != len(right):
        return [f"Flash count mismatch: {len(left)} vs {len(right)}"]
    diffs: list[str] = []
    for index, (first, second) in enumerate(zip(left, right, strict=True)):
        if math.dist((first.x, first.y), (second.x, second.y)) > tolerance_mm:
            diffs.append(f"Flash {index} position mismatch: ({first.x}, {first.y}) vs ({second.x}, {second.y})")
        if first.shape != second.shape:
            diffs.append(f"Flash {index} shape mismatch: {first.shape} vs {second.shape}")
        if any(abs(a - b) > tolerance_mm for a, b in zip(first.size, second.size, strict=True)):
            diffs.append(f"Flash {index} size mismatch: {first.size} vs {second.size}")
    return diffs


def _compare_lines(
    left: tuple[GerberLine, ...],
    right: tuple[GerberLine, ...],
    tolerance_mm: float,
) -> list[str]:
    if len(left) != len(right):
        return [f"Line count mismatch: {len(left)} vs {len(right)}"]
    diffs: list[str] = []
    for index, (first, second) in enumerate(zip(left, right, strict=True)):
        if math.dist(first.start, second.start) > tolerance_mm or math.dist(first.end, second.end) > tolerance_mm:
            diffs.append(
                f"Line {index} coordinate mismatch: [{first.start}->{first.end}] vs [{second.start}->{second.end}]"
            )
        if abs(first.width - second.width) > tolerance_mm:
            diffs.append(f"Line {index} width mismatch: {first.width} vs {second.width}")
        if abs(first.length - second.length) > tolerance_mm:
            diffs.append(f"Line {index} length mismatch: {first.length} vs {second.length}")
    return diffs


@dataclass(frozen=True)
class ExcellonHit:
    x: float
    y: float
    diameter: float

    def to_dict(self) -> dict[str, object]:
        return {"x": self.x, "y": self.y, "diameter": self.diameter}


@dataclass(frozen=True)
class ExcellonAST:
    """Normalized geometric AST for Excellon drill files."""

    drills: tuple[ExcellonHit, ...]

    def to_dict(self) -> dict[str, object]:
        return {"drills": [d.to_dict() for d in self.drills]}

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True) + "\n"

    def compare(self, other: ExcellonAST, tolerance_mm: float = 0.001) -> tuple[bool, list[str]]:
        """Compare drill hits against another Excellon AST."""
        diffs: list[str] = []
        if len(self.drills) != len(other.drills):
            diffs.append(f"Drill count mismatch: {len(self.drills)} vs {len(other.drills)}")
        else:
            for i, (d1, d2) in enumerate(zip(self.drills, other.drills, strict=True)):
                if math.dist((d1.x, d1.y), (d2.x, d2.y)) > tolerance_mm:
                    diffs.append(f"Drill {i} position mismatch: ({d1.x}, {d1.y}) vs ({d2.x}, {d2.y})")
                if abs(d1.diameter - d2.diameter) > tolerance_mm:
                    diffs.append(f"Drill {i} diameter mismatch: {d1.diameter} vs {d2.diameter}")
        return (len(diffs) == 0, diffs)


@dataclass
class _GerberParseState:
    aperture_code: int | None
    x: float
    y: float
    in_region: bool
    region_points: list[tuple[float, float]]


_APERTURE_DEF_RE = re.compile(r"%ADD(\d+)([A-Z]+),([^*%]+)\*%")
_D_CODE_SELECT_RE = re.compile(r"^D(\d+)\*\s*$")
_OPERATION_RE = re.compile(r"(?:X(-?\d+))?(?:Y(-?\d+))?(?:D0([123]))?\*")


def _parse_aperture_definition(line: str) -> GerberAperture | None:
    match = _APERTURE_DEF_RE.search(line)
    if match is None:
        return None
    code = int(match.group(1))
    shape_type = match.group(2)
    shape = {"C": "circle", "R": "rect", "OB": "obround"}.get(shape_type, shape_type.lower())
    params = tuple(_round_coord(float(item)) for item in re.split(r"[X,]", match.group(3)) if item)
    return GerberAperture(code=code, shape=shape, params=params)


def _finish_region(state: _GerberParseState, regions: list[GerberRegion]) -> None:
    region = GerberRegion.from_raw_vertices(state.region_points)
    if region is not None:
        regions.append(region)
    state.in_region = False
    state.region_points = []


def _selected_aperture(state: _GerberParseState, apertures: dict[int, GerberAperture]) -> GerberAperture | None:
    return apertures.get(state.aperture_code or 0)


def _update_gerber_coordinates(match: re.Match[str], state: _GerberParseState) -> None:
    x_text, y_text, _ = match.groups()
    if x_text is not None:
        state.x = int(x_text) / 1_000_000.0
    if y_text is not None:
        state.y = int(y_text) / 1_000_000.0


def _handle_gerber_draw(
    previous: tuple[float, float],
    current: tuple[float, float],
    state: _GerberParseState,
    apertures: dict[int, GerberAperture],
    lines: list[GerberLine],
) -> None:
    if state.in_region:
        state.region_points.append(current)
        return
    aperture = _selected_aperture(state, apertures)
    width = aperture.params[0] if (aperture is not None and aperture.params) else 0.1
    lines.append(GerberLine.create(previous, current, width))


def _handle_gerber_flash(
    state: _GerberParseState,
    apertures: dict[int, GerberAperture],
    flashes: list[GerberFlash],
) -> None:
    aperture = _selected_aperture(state, apertures)
    shape = aperture.shape if aperture is not None else "circle"
    size = aperture.params if aperture is not None else (0.1,)
    flashes.append(
        GerberFlash(
            x=_round_coord(state.x),
            y=_round_coord(state.y),
            shape=shape,
            size=size,
        )
    )


def _apply_gerber_operation(
    match: re.Match[str],
    state: _GerberParseState,
    apertures: dict[int, GerberAperture],
    flashes: list[GerberFlash],
    lines: list[GerberLine],
) -> None:
    x_text, y_text, operation = match.groups()
    if not any((x_text, y_text, operation)):
        return
    previous = (state.x, state.y)
    _update_gerber_coordinates(match, state)
    current = (state.x, state.y)
    if operation == "1":
        _handle_gerber_draw(previous, current, state, apertures, lines)
    elif operation == "2":
        if state.in_region:
            state.region_points.append(current)
    elif operation == "3":
        _handle_gerber_flash(state, apertures, flashes)


def _consume_gerber_line(
    line: str,
    state: _GerberParseState,
    apertures: dict[int, GerberAperture],
    regions: list[GerberRegion],
    flashes: list[GerberFlash],
    lines: list[GerberLine],
) -> None:
    if not line or line.startswith("G04"):
        return
    aperture = _parse_aperture_definition(line)
    if aperture is not None:
        apertures[aperture.code] = aperture
        return
    if "G36*" in line:
        state.in_region = True
        state.region_points = []
        return
    if "G37*" in line:
        _finish_region(state, regions)
        return
    selection = _D_CODE_SELECT_RE.match(line)
    if selection is not None:
        state.aperture_code = int(selection.group(1))
        return
    for operation in _OPERATION_RE.finditer(line):
        _apply_gerber_operation(operation, state, apertures, flashes, lines)


def parse_gerber(content: str) -> GerberAST:
    """Parse RS-274X Gerber content into a normalized geometric AST."""
    apertures: dict[int, GerberAperture] = {}
    regions: list[GerberRegion] = []
    flashes: list[GerberFlash] = []
    lines: list[GerberLine] = []
    state = _GerberParseState(aperture_code=None, x=0.0, y=0.0, in_region=False, region_points=[])

    for raw_line in content.splitlines():
        _consume_gerber_line(raw_line.strip(), state, apertures, regions, flashes, lines)

    sorted_regions = tuple(
        sorted(
            regions,
            key=lambda region: (
                region.bounding_box,
                region.area,
                region.vertices[0] if region.vertices else (0, 0),
            ),
        )
    )
    sorted_flashes = tuple(sorted(flashes, key=lambda flash: (flash.x, flash.y, flash.shape, flash.size)))
    sorted_lines = tuple(sorted(lines, key=lambda item: (item.start, item.end, item.width, item.length)))
    return GerberAST(regions=sorted_regions, flashes=sorted_flashes, lines=sorted_lines)


def parse_excellon(content: str) -> ExcellonAST:
    """Parse Excellon drill file content into a normalized geometric AST."""
    tools: dict[int, float] = {}
    drills: list[ExcellonHit] = []
    current_tool: int | None = None

    tool_def_re = re.compile(r"T(\d+)C([\d.]+)")
    tool_select_re = re.compile(r"^T(\d+)\s*$")
    coord_re = re.compile(r"X(-?\d+)Y(-?\d+)")

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or line in ("M48", "M30", "%"):
            continue

        # Tool definitions (e.g. T01C1.0000)
        t_def = tool_def_re.search(line)
        if t_def:
            t_num = int(t_def.group(1))
            t_diam = _round_coord(float(t_def.group(2)))
            tools[t_num] = t_diam
            continue

        # Tool selection (e.g. T01)
        t_sel = tool_select_re.match(line)
        if t_sel:
            current_tool = int(t_sel.group(1))
            continue

        # Drill hits (e.g. X1234000Y5678000)
        coord_match = coord_re.search(line)
        if coord_match:
            ix = int(coord_match.group(1))
            iy = int(coord_match.group(2))
            x = _round_coord(ix / 1_000_000.0)
            y = _round_coord(iy / 1_000_000.0)
            diam = tools.get(current_tool or 0, 0.0)
            drills.append(ExcellonHit(x=x, y=y, diameter=diam))

    sorted_drills = tuple(sorted(drills, key=lambda d: (d.x, d.y, d.diameter)))
    return ExcellonAST(drills=sorted_drills)


def canonicalize_gerber(content: str) -> dict[str, object]:
    """Return a JSON-serializable dictionary representation of a Gerber AST."""
    return parse_gerber(content).to_dict()


def canonicalize_excellon(content: str) -> dict[str, object]:
    """Return a JSON-serializable dictionary representation of an Excellon AST."""
    return parse_excellon(content).to_dict()
