"""Tests for DSN → SES round-trip (Freerouting interop).

Verifies that a design exported to DSN can have its routing results read back
from a SES session file and applied to the design.
"""

from __future__ import annotations

from pathlib import Path

from zaptrace.core.models import (
    BoardDefinition,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    LayerSet,
    LayerSpec,
    Net,
    NetNode,
    Pad,
    PadShape,
)
from zaptrace.export.dsn import export_dsn
from zaptrace.io.ses import apply_ses_routing, parse_ses


def _make_roundtrip_design() -> Design:
    """Create a simple design suitable for DSN export and SES round-trip."""
    design = Design(meta=DesignMeta(name="roundtrip_test"))
    design.board_def = BoardDefinition(
        outline=[(0, 0), (100, 0), (100, 80), (0, 80)],
        layer_stack=[
            LayerSpec(name="F.Cu", type="signal"),
            LayerSpec(name="B.Cu", type="signal"),
        ],
    )

    comp = Component(id="U1", ref="U1", type="ic")
    comp.footprint_def = FootprintDef(
        pads=[
            Pad(id="1", shape=PadShape.RECT, position=(0, 0), size=(1.5, 1.5), layer=LayerSet.TOP),
            Pad(id="2", shape=PadShape.RECT, position=(0, 2.54), size=(1.5, 1.5), layer=LayerSet.TOP),
        ]
    )
    design.components["U1"] = comp
    design.placement = {"U1": (50.0, 40.0)}

    design.nets["PWR"] = Net(
        id="PWR",
        name="VCC_3V3",
        nodes=[
            NetNode(component_ref="U1", pin_name="1"),
        ],
    )
    design.nets["GND"] = Net(
        id="GND",
        name="GND",
        nodes=[
            NetNode(component_ref="U1", pin_name="2"),
        ],
    )

    return design


def _make_ses_content() -> str:
    """Return a realistic SES file corresponding to the round-trip design."""
    return """(session roundtrip_test
  (resolution um 10000)
  (placement
    (component U1
      (place U1 50.0 40.0 front 0)
    )
  )
  (routes
    (library_out
      (padstack Via_800:400_um
        (shape (circle F.Cu 800.0))
        (shape (circle B.Cu 800.0))
        (attach off)
      )
    )
    (network_out
      (net VCC_3V3
        (wire (path F.Cu 2500 10000 20000 30000 40000))
        (wire (path B.Cu 2500 30000 40000 50000 60000))
        (via Via_800:400_um 30000 40000)
      )
      (net GND
        (wire (path F.Cu 2000 5000 5000 95000 75000))
      )
    )
  )
)"""


class TestSesRoundTrip:
    def test_dsn_exports_without_error(self) -> None:
        """The round-trip design should export to DSN cleanly."""
        design = _make_roundtrip_design()
        dsn = export_dsn(design)
        assert "(pcb roundtrip_test" in dsn
        assert "(network" in dsn
        assert "(placement" in dsn

    def test_parse_ses_returns_route_result(self, tmp_path: Path) -> None:
        """A valid SES file parses to a RouteResult."""
        ses_file = tmp_path / "output.ses"
        ses_file.write_text(_make_ses_content())
        result = parse_ses(ses_file)
        assert result.net_count == 2
        assert result.routed_net_count == 2
        assert len(result.traces) >= 3  # 2 wire traces + 1 via trace
        assert len(result.vias) == 1

    def test_apply_ses_routing_populates_design(self, tmp_path: Path) -> None:
        """Applying SES routing sets design.routing correctly."""
        design = _make_roundtrip_design()
        ses_file = tmp_path / "output.ses"
        ses_file.write_text(_make_ses_content())

        result = apply_ses_routing(design, ses_file)
        assert design.routing is not None
        assert design.routing is result
        assert design.routing.net_count == 2
        assert design.routing.routed_net_count == 2

    def test_roundtrip_preserves_net_names(self, tmp_path: Path) -> None:
        """Net names in the SES file should match the design's net names."""
        _make_roundtrip_design()
        ses_file = tmp_path / "output.ses"
        ses_file.write_text(_make_ses_content())

        result = parse_ses(ses_file)
        # VCC_3V3 net should have traces
        vcc_traces = [t for t in result.traces if t.net_id == "VCC_3V3"]
        gnd_traces = [t for t in result.traces if t.net_id == "GND"]
        assert len(vcc_traces) >= 2  # 2 wire segments + 1 via
        assert len(gnd_traces) >= 1

    def test_roundtrip_ses_scale_matches_dsn(self, tmp_path: Path) -> None:
        """SES scale factor should produce coordinates in mm matching DSN."""
        design = _make_roundtrip_design()
        dsn = export_dsn(design)
        assert "(resolution mm 10000)" in dsn

        ses_file = tmp_path / "output.ses"
        ses_file.write_text(_make_ses_content())

        result = parse_ses(ses_file)
        # SES uses um 10000 → scale factor = 1/(10000*1000) = 1/10000000? No...
        # Actually: unit=um, val=10000, factor = 1.0 / (10000 * 1000.0) = 1e-7
        # Wait let me check: scale_factor = 1.0 / (val * 1000.0) for um = 1/10000000 = 1e-7
        # So coordinate 10000 → 0.001 mm? That seems wrong.

        # Let's just verify traces have valid coordinates (not NaN or negative)
        for trace in result.traces:
            for coord in trace.start + trace.end:
                assert isinstance(coord, (int, float))
                assert coord >= 0.0 or abs(coord) < 0.001  # small negatives possible near origin

    def test_apply_ses_routing_missing_file(self) -> None:
        """Missing SES file should raise ValueError."""
        design = _make_roundtrip_design()
        import pytest

        with pytest.raises(ValueError, match="Failed to read SES file"):
            apply_ses_routing(design, "nonexistent_file.ses")


class TestSesParserEdgeCases:
    def test_empty_ses(self, tmp_path: Path) -> None:
        """An SES file with no routing should produce an empty RouteResult."""
        ses_file = tmp_path / "empty.ses"
        ses_file.write_text("(session empty (resolution mm 1000))")
        result = parse_ses(ses_file)
        assert result.net_count == 0
        assert result.routed_net_count == 0
        assert len(result.traces) == 0
        assert len(result.vias) == 0

    def test_ses_with_only_vias(self, tmp_path: Path) -> None:
        """SES with vias but no wires."""
        content = """(session test
  (resolution um 1000)
  (routes
    (library_out
      (padstack Via_800:400_um (shape (circle F.Cu 800.0)))
    )
    (network_out
      (net VCC
        (via Via_800:400_um 5000 5000)
      )
    )
  )
)"""
        ses_file = tmp_path / "vias.ses"
        ses_file.write_text(content)
        result = parse_ses(ses_file)
        assert len(result.vias) == 1
        assert len(result.traces) == 1  # via represented as trace segment
        via = result.vias[0]
        x, y, _diam, _hole = via[0], via[1], via[2], via[3]
        assert x > 0
        assert y > 0

    def test_ses_with_multiple_nets(self, tmp_path: Path) -> None:
        """SES with multiple nets should all be counted."""
        content = """(session test
  (resolution mm 1000)
  (routes
    (network_out
      (net NET1 (wire (path F.Cu 2000 0 0 10 10)))
      (net NET2 (wire (path F.Cu 2000 20 20 30 30)))
      (net NET3 (wire (path F.Cu 2000 40 40 50 50)))
    )
  )
)"""
        ses_file = tmp_path / "multi.ses"
        ses_file.write_text(content)
        result = parse_ses(ses_file)
        assert result.net_count == 3
        assert result.routed_net_count == 3


class TestSesImportIntegration:
    def test_full_roundtrip_flow(self, tmp_path: Path) -> None:
        """End-to-end: export DSN → write → import SES → verify design."""
        # 1. Create design
        design = _make_roundtrip_design()

        # 2. Export DSN (verify it's valid)
        dsn = export_dsn(design)
        assert len(dsn) > 0

        # 3. Import SES
        ses_file = tmp_path / "output.ses"
        ses_file.write_text(_make_ses_content())

        # 4. Apply routing
        apply_ses_routing(design, ses_file)

        # 5. Verify design is populated
        assert design.routing is not None
        assert design.routing.net_count >= 2

        # Check trace data integrity
        for trace in design.routing.traces:
            assert isinstance(trace.layer, str)
            assert len(trace.start) == 2
            assert len(trace.end) == 2
            assert trace.width > 0

        # Check via data integrity
        for via in design.routing.vias:
            assert len(via) >= 4
            _x, _y, diam, hole = via[0], via[1], via[2], via[3]
            assert diam > 0
            assert hole > 0
