"""Tests for KiCad PCB import and round-trip fidelity scoring."""

from __future__ import annotations

from pathlib import Path

from zaptrace.core.models import (
    BoardConfig,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    Net,
    NetNode,
    Pad,
    Pin,
    PinType,
    RouteResult,
    TraceSegment,
)
from zaptrace.export.kicad import export_kicad_pcb
from zaptrace.kicad.importer import import_kicad_pcb, score_kicad_roundtrip


def _roundtrip_design() -> Design:
    return Design(
        meta=DesignMeta(name="RoundTrip", version="0.2.0", author="tester"),
        board=BoardConfig(width_mm=42.0, height_mm=24.0, layers=2),
        components={
            "r1": Component(
                id="r1",
                ref="R1",
                type="resistor",
                value="10k",
                position=(10.0, 11.0),
                footprint="zaptrace:resistor",
                footprint_def=FootprintDef(
                    pads=[
                        Pad(id="1", position=(0.0, 0.0), size=(1.5, 1.5), drill=0.6),
                        Pad(id="2", position=(2.0, 0.0), size=(1.5, 1.5), drill=0.6),
                    ]
                ),
                pins={
                    "1": Pin(name="1", type=PinType.PASSIVE, net="vcc"),
                    "2": Pin(name="2", type=PinType.PASSIVE, net="gnd"),
                },
            )
        },
        nets={
            "vcc": Net(id="vcc", name="VCC", nodes=[NetNode(component_ref="R1", pin_name="1")]),
            "gnd": Net(id="gnd", name="GND", nodes=[NetNode(component_ref="R1", pin_name="2")]),
        },
        routing=RouteResult(
            traces=[TraceSegment(layer="F.Cu", start=(1.0, 1.0), end=(8.0, 1.0), width=0.25, net_id="vcc")],
            vias=[(8.0, 1.0, 0.6, 0.3, "vcc")],
        ),
    )


def test_import_kicad_pcb_round_trips_exported_design(tmp_path: Path) -> None:
    original = _roundtrip_design()
    pcb_path = export_kicad_pcb(original, tmp_path)["pcb"]

    result = import_kicad_pcb(pcb_path)
    imported = result.design

    assert result.unsupported_count == 0
    assert imported.meta.name == "RoundTrip"
    assert imported.board.width_mm == 42.0
    assert imported.board.height_mm == 24.0
    assert {net.name for net in imported.nets.values()} == {"VCC", "GND"}
    assert imported.components["r1"].ref == "R1"
    assert imported.components["r1"].position == (10.0, 11.0)
    assert set(imported.components["r1"].pins) == {"1", "2"}
    assert imported.components["r1"].footprint_def is not None
    assert [pad.id for pad in imported.components["r1"].footprint_def.pads] == ["1", "2"]
    assert [(node.component_ref, node.pin_name) for node in imported.nets["vcc"].nodes] == [("R1", "1")]
    assert imported.routing is not None
    assert len(imported.routing.traces) == 1
    assert len(imported.routing.vias) == 1


def test_score_kicad_roundtrip_reports_semantic_fidelity(tmp_path: Path) -> None:
    original = _roundtrip_design()
    pcb_path = export_kicad_pcb(original, tmp_path)["pcb"]
    imported_result = import_kicad_pcb(pcb_path)

    report = score_kicad_roundtrip(original, imported_result.design, imported_result.unsupported_count)

    assert report.score == 1.0
    assert report.component_refs_matched == report.component_refs_total == 1
    assert report.net_names_matched == report.net_names_total == 2
    assert report.board_dimensions_match is True
    assert report.trace_count_delta == 0
    assert report.via_count_delta == 0


def test_importer_accounts_for_known_unsupported_construct(tmp_path: Path) -> None:
    pcb_path = export_kicad_pcb(_roundtrip_design(), tmp_path)["pcb"]
    text = pcb_path.read_text(encoding="utf-8")
    prefix, suffix = text.rsplit(")", 1)
    text = f"{prefix}  (image (at 1 1) (scale 1))\n){suffix}"
    pcb_path.write_text(text, encoding="utf-8")

    result = import_kicad_pcb(pcb_path)

    assert result.unsupported_count == 1
    assert result.unsupported[0].kind == "image"
