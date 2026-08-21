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
        diffs: list[str] = []

        # Compare regions
        if len(self.regions) != len(other.regions):
            diffs.append(f"Region count mismatch: {len(self.regions)} vs {len(other.regions)}")
        else:
            for i, (r1, r2) in enumerate(zip(self.regions, other.regions, strict=True)):
                if abs(r1.area - r2.area) > tolerance_mm:
                    diffs.append(f"Region {i} area mismatch: {r1.area} vs {r2.area}")
                if len(r1.vertices) != len(r2.vertices):
                    diffs.append(f"Region {i} vertex count mismatch: {len(r1.vertices)} vs {len(r2.vertices)}")
                else:
                    for v_idx, (v1, v2) in enumerate(zip(r1.vertices, r2.vertices, strict=True)):
                        if math.dist(v1, v2) > tolerance_mm:
                            diffs.append(f"Region {i} vertex {v_idx} position mismatch: {v1} vs {v2}")

        # Compare flashes
        if len(self.flashes) != len(other.flashes):
            diffs.append(f"Flash count mismatch: {len(self.flashes)} vs {len(other.flashes)}")
        else:
            for i, (f1, f2) in enumerate(zip(self.flashes, other.flashes, strict=True)):
                if math.dist((f1.x, f1.y), (f2.x, f2.y)) > tolerance_mm:
                    diffs.append(f"Flash {i} position mismatch: ({f1.x}, {f1.y}) vs ({f2.x}, {f2.y})")
                if f1.shape != f2.shape:
                    diffs.append(f"Flash {i} shape mismatch: {f1.shape} vs {f2.shape}")
                if any(abs(s1 - s2) > tolerance_mm for s1, s2 in zip(f1.size, f2.size, strict=True)):
                    diffs.append(f"Flash {i} size mismatch: {f1.size} vs {f2.size}")

        # Compare lines
        if len(self.lines) != len(other.lines):
            diffs.append(f"Line count mismatch: {len(self.lines)} vs {len(other.lines)}")
        else:
            for i, (l1, l2) in enumerate(zip(self.lines, other.lines, strict=True)):
                if math.dist(l1.start, l2.start) > tolerance_mm or math.dist(l1.end, l2.end) > tolerance_mm:
                    diffs.append(f"Line {i} coordinate mismatch: [{l1.start}->{l1.end}] vs [{l2.start}->{l2.end}]")
                if abs(l1.width - l2.width) > tolerance_mm:
                    diffs.append(f"Line {i} width mismatch: {l1.width} vs {l2.width}")
                if abs(l1.length - l2.length) > tolerance_mm:
                    diffs.append(f"Line {i} length mismatch: {l1.length} vs {l2.length}")

        return (len(diffs) == 0, diffs)


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


def parse_gerber(content: str) -> GerberAST:
    """Parse RS-274X Gerber content into a normalized geometric AST."""
    apertures: dict[int, GerberAperture] = {}
    regions: list[GerberRegion] = []
    flashes: list[GerberFlash] = []
    lines: list[GerberLine] = []

    current_aperture_code: int | None = None
    current_x: float = 0.0
    current_y: float = 0.0
    in_region: bool = False
    region_points: list[tuple[float, float]] = []

    # Regex patterns
    aperture_def_re = re.compile(r"%ADD(\d+)([A-Z]+),([^*%]+)\*%")
    d_code_select_re = re.compile(r"^D(\d+)\*\s*$")
    op_re = re.compile(r"(?:X(-?\d+))?(?:Y(-?\d+))?(?:D0([123]))?\*")

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("G04"):
            continue

        # Aperture definitions
        ap_match = aperture_def_re.search(line)
        if ap_match:
            code = int(ap_match.group(1))
            shape_type = ap_match.group(2)
            params_raw = ap_match.group(3)
            shape_map = {"C": "circle", "R": "rect", "OB": "obround"}
            shape = shape_map.get(shape_type, shape_type.lower())
            params_split = re.split(r"[X,]", params_raw)
            params = tuple(_round_coord(float(p)) for p in params_split if p)
            apertures[code] = GerberAperture(code=code, shape=shape, params=params)
            continue

        # Region mode toggles
        if "G36*" in line:
            in_region = True
            region_points = []
            continue
        if "G37*" in line:
            in_region = False
            region = GerberRegion.from_raw_vertices(region_points)
            if region is not None:
                regions.append(region)
            region_points = []
            continue

        # Aperture selection standalone (e.g. D10*)
        d_sel = d_code_select_re.match(line)
        if d_sel:
            current_aperture_code = int(d_sel.group(1))
            continue

        # Coordinate / Operation commands
        for match in op_re.finditer(line):
            x_str, y_str, op = match.groups()
            if not any((x_str, y_str, op)):
                continue

            prev_x, prev_y = current_x, current_y
            if x_str is not None:
                current_x = int(x_str) / 1_000_000.0
            if y_str is not None:
                current_y = int(y_str) / 1_000_000.0

            if op == "1":  # D01: draw line
                if in_region:
                    region_points.append((current_x, current_y))
                else:
                    ap = apertures.get(current_aperture_code or 0)
                    width = ap.params[0] if ap and ap.params else 0.1
                    line_geom = GerberLine.create((prev_x, prev_y), (current_x, current_y), width)
                    lines.append(line_geom)
            elif op == "2":  # D02: move without draw
                if in_region:
                    region_points.append((current_x, current_y))
            elif op == "3":  # D03: flash
                ap = apertures.get(current_aperture_code or 0)
                shape = ap.shape if ap else "circle"
                size = ap.params if ap else (0.1,)
                flashes.append(
                    GerberFlash(
                        x=_round_coord(current_x),
                        y=_round_coord(current_y),
                        shape=shape,
                        size=size,
                    )
                )

    # Sort all geometry collections deterministically
    sorted_regions = tuple(
        sorted(regions, key=lambda r: (r.bounding_box, r.area, r.vertices[0] if r.vertices else (0, 0)))
    )
    sorted_flashes = tuple(sorted(flashes, key=lambda f: (f.x, f.y, f.shape, f.size)))
    sorted_lines = tuple(
        sorted(lines, key=lambda line_item: (line_item.start, line_item.end, line_item.width, line_item.length))
    )

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
