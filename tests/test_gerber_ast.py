"""Unit tests for the Gerber and Excellon geometric AST canonicalizer."""

from __future__ import annotations

from zaptrace.testing.gerber_ast import (
    ExcellonAST,
    ExcellonHit,
    GerberAST,
    GerberFlash,
    GerberLine,
    GerberRegion,
    canonicalize_excellon,
    canonicalize_gerber,
    parse_excellon,
    parse_gerber,
)


def test_gerber_region_normalization_and_area() -> None:
    # Triangle: (0, 0) -> (10, 0) -> (0, 10) -> (0, 0)
    raw_vertices = [(0.0, 0.0), (10.0, 0.0), (0.0, 10.0), (0.0, 0.0)]
    region = GerberRegion.from_raw_vertices(raw_vertices)
    assert region is not None
    assert region.area == 50.0
    assert region.bounding_box == (0.0, 0.0, 10.0, 10.0)
    assert len(region.vertices) == 3
    # Lexicographically minimum point must be at index 0
    assert region.vertices[0] == (0.0, 0.0)


def test_gerber_region_cyclic_shift_invariance() -> None:
    # Same rectangle started at different vertices
    poly1 = [(10.0, 10.0), (20.0, 10.0), (20.0, 30.0), (10.0, 30.0)]
    poly2 = [(20.0, 10.0), (20.0, 30.0), (10.0, 30.0), (10.0, 10.0)]
    r1 = GerberRegion.from_raw_vertices(poly1)
    r2 = GerberRegion.from_raw_vertices(poly2)
    assert r1 is not None and r2 is not None
    assert r1.vertices == r2.vertices
    assert r1.area == r2.area == 200.0


def test_gerber_region_degenerate_skipped() -> None:
    assert GerberRegion.from_raw_vertices([]) is None
    assert GerberRegion.from_raw_vertices([(0.0, 0.0), (1.0, 1.0)]) is None


def test_gerber_line_canonical_orientation() -> None:
    l1 = GerberLine.create((10.0, 5.0), (2.0, 1.0), width=0.5)
    l2 = GerberLine.create((2.0, 1.0), (10.0, 5.0), width=0.5)
    assert l1.start == (2.0, 1.0)
    assert l1.end == (10.0, 5.0)
    assert l1 == l2
    assert l1.width == 0.5
    assert l1.length > 0


def test_parse_gerber_full_pipeline() -> None:
    sample_gerber = """G04 Test file*
%FSLAX36Y36*%
%MOMM*%
%ADD10C,0.250000*%
%ADD11R,1.500000X2.000000*%
%ADD12OB,2.000000X1.000000*%
D10*
X10000000Y10000000D02*
X20000000Y10000000D01*
D11*
X15000000Y25000000D03*
D12*
X25000000Y25000000D03*
D10*
G36*
X0Y0D02*
X10000000Y0D01*
X10000000Y10000000D01*
X0Y10000000D01*
X0Y0D01*
G37*
M02*
"""
    ast = parse_gerber(sample_gerber)
    assert len(ast.lines) == 1
    assert ast.lines[0].start == (10.0, 10.0)
    assert ast.lines[0].end == (20.0, 10.0)
    assert ast.lines[0].width == 0.25

    assert len(ast.flashes) == 2
    assert ast.flashes[0].shape == "rect"
    assert ast.flashes[0].x == 15.0
    assert ast.flashes[1].shape == "obround"
    assert ast.flashes[1].x == 25.0

    assert len(ast.regions) == 1
    assert ast.regions[0].area == 100.0
    assert ast.regions[0].bounding_box == (0.0, 0.0, 10.0, 10.0)

    # JSON export test
    dict_data = canonicalize_gerber(sample_gerber)
    assert "regions" in dict_data
    assert "flashes" in dict_data
    assert "lines" in dict_data


def test_gerber_ast_compare_mismatches() -> None:
    r1 = GerberRegion.from_raw_vertices([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    assert r1 is not None
    f1 = GerberFlash(x=5.0, y=5.0, shape="circle", size=(1.0,))
    l1 = GerberLine.create((0.0, 0.0), (5.0, 5.0), width=0.3)

    ast_base = GerberAST(regions=(r1,), flashes=(f1,), lines=(l1,))
    ast_same = GerberAST(regions=(r1,), flashes=(f1,), lines=(l1,))

    matched, diffs = ast_base.compare(ast_same)
    assert matched
    assert len(diffs) == 0

    # Region mismatch
    r2 = GerberRegion.from_raw_vertices([(0.0, 0.0), (12.0, 0.0), (12.0, 10.0), (0.0, 10.0)])
    assert r2 is not None
    ast_diff_region = GerberAST(regions=(r2,), flashes=(f1,), lines=(l1,))
    matched, diffs = ast_base.compare(ast_diff_region)
    assert not matched
    assert any("area mismatch" in d for d in diffs)

    # Flash mismatch
    f2 = GerberFlash(x=5.0, y=5.0, shape="circle", size=(1.5,))
    ast_diff_flash = GerberAST(regions=(r1,), flashes=(f2,), lines=(l1,))
    matched, diffs = ast_base.compare(ast_diff_flash)
    assert not matched
    assert any("Flash 0 size mismatch" in d for d in diffs)


def test_parse_excellon_full_pipeline() -> None:
    sample_excellon = """M48
; ZapTrace drill test
METRIC,TZ
%
T01C0.8000
T02C1.2000
T01
X10000000Y15000000
X20000000Y15000000
T02
X50000000Y50000000
M30
"""
    ast = parse_excellon(sample_excellon)
    assert len(ast.drills) == 3
    assert ast.drills[0].x == 10.0
    assert ast.drills[0].y == 15.0
    assert ast.drills[0].diameter == 0.8
    assert ast.drills[2].x == 50.0
    assert ast.drills[2].diameter == 1.2

    # Compare against self
    matched, diffs = ast.compare(ast)
    assert matched
    assert len(diffs) == 0

    # Compare against modified
    ast_mod = ExcellonAST(drills=(ExcellonHit(x=10.0, y=15.0, diameter=1.0),))
    matched, diffs = ast.compare(ast_mod)
    assert not matched
    assert any("Drill count mismatch" in d for d in diffs)

    dict_data = canonicalize_excellon(sample_excellon)
    assert "drills" in dict_data
    assert len(dict_data["drills"]) == 3
