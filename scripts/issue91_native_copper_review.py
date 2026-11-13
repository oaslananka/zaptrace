"""Reproducible, fail-closed *partial* physical routing for ESP32 issue #91.

Requires system KiCad 10 pcbnew and native KiCad CLI reports. The companion
shell driver runs independently audited native DRC before and after routing.
Python NEVER launches an external process and refuses an accepted artifact
unless every physical net, file digest and DRC result matches the contract.

This is a review artifact, NOT complete board routing or fabrication signoff.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True)
class RoutedConnection:
    net: str
    source: tuple[str, str, tuple[float, float]]
    target: tuple[str, str, tuple[float, float]]
    points: tuple[tuple[float, float], ...]
    segment_layers: tuple[str, ...] = ()
    via_points: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class PadToViaConnection:
    net: str
    source: tuple[str, str, tuple[float, float]]
    layer_transition: tuple[float, float]
    existing_via: tuple[float, float]


@dataclass(frozen=True)
class TrackToViaConnection:
    net: str
    existing_track_start: tuple[float, float]
    existing_track_end: tuple[float, float]
    new_via: tuple[float, float]
    existing_via: tuple[float, float]


@dataclass(frozen=True)
class PadToTrackConnection:
    net: str
    source: tuple[str, str, tuple[float, float]]
    points: tuple[tuple[float, float], ...]
    existing_track_start: tuple[float, float]
    existing_track_end: tuple[float, float]


# Tested against the pinned 100 x 75 mm reference placement with KiCad 10.0.6/10.0.7.
# These are only the paths KiCad independently proved physically connected.
# Do NOT extrapolate success to the remaining unrouted copper items.
ROUTES: tuple[RoutedConnection, ...] = (
    RoutedConnection(
        "USB_CC1",
        ("J1", "A5", (78.75, 63.32)),
        ("R3", "1", (71.49, 60.0)),
        ((78.75, 63.32), (78.75, 61.8), (71.49, 61.8), (71.49, 60.0)),
    ),
    RoutedConnection(
        "USB_CC2",
        ("J1", "B5", (81.75, 63.32)),
        ("R4", "1", (76.49, 60.0)),
        ((81.75, 63.32), (81.75, 61.1), (76.49, 61.1), (76.49, 60.0)),
    ),
    RoutedConnection(
        "VCC_3V3",
        ("U1", "2", (21.25, 27.02)),
        ("U1", "3", (21.25, 28.29)),
        ((21.25, 27.02), (21.25, 28.29)),
    ),
    RoutedConnection(
        "GND",
        ("U2", "5", (47.975, 61.025)),
        ("U2", "7", (46.675, 61.025)),
        ((47.975, 61.025), (47.975, 60.025), (46.675, 60.025), (46.675, 61.025)),
    ),
    RoutedConnection(
        "VCC_3V3",
        ("U2", "6", (47.325, 61.025)),
        ("U2", "8", (46.025, 61.025)),
        ((47.325, 61.025), (47.325, 62.025), (46.025, 62.025), (46.025, 61.025)),
    ),
    RoutedConnection(
        "GND",
        ("U2", "1", (46.025, 58.975)),
        ("U2", "7", (46.675, 61.025)),
        ((46.025, 58.975), (46.675, 61.025)),
    ),
    RoutedConnection(
        "I2C_SDA",
        ("R1", "2", (54.51, 58.0)),
        ("TP1", "1", (51.0, 66.0)),
        ((54.51, 58.0), (51.0, 66.0)),
    ),
    RoutedConnection(
        "I2C_SCL",
        ("R2", "2", (58.51, 58.0)),
        ("TP2", "1", (55.0, 66.0)),
        ((58.51, 58.0), (55.0, 66.0)),
    ),
    RoutedConnection(
        "I2C_SDA",
        ("U2", "3", (47.325, 58.975)),
        ("R1", "2", (54.51, 58.0)),
        ((47.325, 58.975), (47.325, 57.0), (54.51, 57.0), (54.51, 58.0)),
    ),
    RoutedConnection(
        "VCC_5V",
        ("C3", "1", (67.52, 68.0)),
        ("D1", "1", (60.95, 68.0)),
        ((67.52, 68.0), (67.52, 66.0), (60.95, 66.0), (60.95, 68.0)),
    ),
    RoutedConnection(
        "GND",
        ("C3", "2", (68.48, 68.0)),
        ("D1", "2", (63.05, 68.0)),
        ((68.48, 68.0), (68.48, 70.0), (63.05, 70.0), (63.05, 68.0)),
    ),
    RoutedConnection(
        "GND",
        ("R3", "2", (72.51, 60.0)),
        ("R4", "2", (77.51, 60.0)),
        ((72.51, 60.0), (72.51, 58.8), (77.51, 58.8), (77.51, 60.0)),
    ),
    RoutedConnection(
        "GND",
        ("U1", "1", (21.25, 25.75)),
        ("U1", "38", (38.75, 25.75)),
        ((21.25, 25.75), (38.75, 25.75)),
    ),
    RoutedConnection(
        "VCC_3V3",
        ("U3", "2", (61.85, 36.0)),
        ("U3", "2", (68.15, 36.0)),
        ((61.85, 36.0), (68.15, 36.0)),
    ),
    RoutedConnection(
        "GND",
        ("C1", "2", (30.48, 60.0)),
        ("C2", "2", (37.95, 60.0)),
        ((30.48, 60.0), (30.48, 62.7), (37.95, 62.7), (37.95, 60.0)),
    ),
    RoutedConnection(
        "VCC_3V3",
        ("C1", "1", (29.52, 60.0)),
        ("C2", "1", (36.05, 60.0)),
        ((29.52, 60.0), (29.52, 57.5), (36.05, 57.5), (36.05, 60.0)),
    ),
    RoutedConnection(
        "GND",
        ("C2", "2", (37.95, 60.0)),
        ("U2", "1", (46.025, 58.975)),
        ((37.95, 60.0), (46.025, 58.975)),
    ),
    RoutedConnection(
        "GND",
        ("U1", "15", (24.29, 43.51)),
        ("U1", "39", (27.795, 34.615)),
        ((24.29, 43.51), (27.795, 34.615)),
    ),
    RoutedConnection(
        "VCC_5V",
        ("U3", "3", (61.85, 38.3)),
        ("C3", "1", (67.52, 68.0)),
        ((61.85, 38.3), (61.85, 42.0), (67.52, 42.0), (67.52, 68.0)),
    ),
    RoutedConnection(
        "GND",
        ("R3", "2", (72.51, 60.0)),
        ("C3", "2", (68.48, 68.0)),
        ((72.51, 60.0), (72.51, 57.2), (69.6, 57.2), (69.6, 66.5), (68.48, 68.0)),
    ),
    RoutedConnection(
        "GND",
        ("U1", "38", (38.75, 25.75)),
        ("U3", "1", (61.85, 33.7)),
        ((38.75, 25.75), (44.0, 25.75), (44.0, 33.7), (61.85, 33.7)),
    ),
    RoutedConnection(
        "GND",
        ("D1", "2", (63.05, 68.0)),
        ("U2", "5", (47.975, 61.025)),
        ((63.05, 68.0), (63.05, 72.5), (47.975, 72.5), (47.975, 61.025)),
    ),
    RoutedConnection(
        "GND",
        ("U1", "1", (21.25, 25.75)),
        ("U1", "39", (27.795, 31.565)),
        ((21.25, 25.75), (24.5, 25.75), (24.5, 30.5), (27.795, 31.565)),
    ),
    RoutedConnection(
        "VCC_3V3",
        ("C1", "1", (29.52, 60.0)),
        ("U1", "2", (21.25, 27.02)),
        ((29.52, 60.0), (18.0, 60.0), (18.0, 27.02), (21.25, 27.02)),
    ),
    RoutedConnection(
        "I2C_SDA",
        ("U1", "33", (38.75, 32.1)),
        ("U2", "3", (47.325, 58.975)),
        ((38.75, 32.1), (42.5, 32.1), (42.5, 56.0), (47.325, 56.0), (47.325, 58.975)),
    ),
    # Independent KiCad 10.0.8 proof: F.Cu-only crossing rejected; this
    # bounded 2-layer path reduces unconnected 12 -> 11 without any new DRC
    # finding. It is partial review copper, never a production routing claim.
    RoutedConnection(
        "I2C_SCL",
        ("U1", "36", (38.75, 28.29)),
        ("U2", "4", (47.975, 58.975)),
        ((38.75, 28.29), (40.0, 28.29), (40.0, 55.0), (49.5, 55.0), (49.5, 58.975), (47.975, 58.975)),
        ("F.Cu", "B.Cu", "B.Cu", "B.Cu", "F.Cu"),
        ((40.0, 28.29), (49.5, 58.975)),
    ),
    # Native KiCad 10.0.8 verified R1.1 to R2.1 3.3 V branch. Short
    # two-layer detour avoids both nearby I2C signal pad/trace corridors.
    # Still only a bounded review path, not source PCB/fab certification.
    RoutedConnection(
        "VCC_3V3",
        ("R1", "1", (53.49, 58.0)),
        ("R2", "1", (57.49, 58.0)),
        ((53.49, 58.0), (53.1, 58.8), (57.1, 58.8), (57.49, 58.0)),
        ("F.Cu", "B.Cu", "F.Cu"),
        ((53.1, 58.8), (57.1, 58.8)),
    ),
    # Independent KiCad 10.0.8 accepted the shorter C2.1->U2.8
    # VCC_3V3 branch, with two required layer-change vias. Other
    # single-layer candidates caused crossings or shorts and were rejected.
    RoutedConnection(
        "VCC_3V3",
        ("C2", "1", (36.05, 60.0)),
        ("U2", "8", (46.025, 61.025)),
        ((36.05, 60.0), (36.5, 59.5), (44.5, 60.0), (46.025, 61.025)),
        ("F.Cu", "B.Cu", "F.Cu"),
        ((36.5, 59.5), (44.5, 60.0)),
    ),
    # Exact native KiCad 10.0.8 validation for the C1.2-to-U1.15
    # ground branch. The front-copper pads are connected over B.Cu
    # using two 0.30 mm drill through-vias and no new physical DRC.
    RoutedConnection(
        "GND",
        ("C1", "2", (30.48, 60.0)),
        ("U1", "15", (24.29, 43.51)),
        ((30.48, 60.0), (30.0, 60.8), (23.5, 44.1), (24.29, 43.51)),
        ("F.Cu", "B.Cu", "F.Cu"),
        ((30.0, 60.8), (23.5, 44.1)),
    ),
    # Two native VCC_3V3 pads on the U2 sensor are physically
    # disconnected despite the same netname. The 2-layer route was
    # independently checked against every original DRC defect.
    RoutedConnection(
        "VCC_3V3",
        ("U2", "2", (46.675, 58.975)),
        ("U2", "8", (46.025, 61.025)),
        ((46.675, 58.975), (46.4, 58.0), (45.1, 61.6), (46.025, 61.025)),
        ("F.Cu", "B.Cu", "F.Cu"),
        ((46.4, 58.0), (45.1, 61.6)),
    ),
    # Independent native KiCad 10.0.8 accepts the two separate
    # USB-C VBUS contacts via the lower F.Cu/B.Cu/F.Cu corridor.
    # Upper connector escapes caused actual shorts with CC1/CC2
    # and were rejected; manufacturing hold remains.
    RoutedConnection(
        "VCC_5V",
        ("J1", "A4", (77.6, 63.32)),
        ("J1", "B4", (82.4, 63.32)),
        ((77.6, 63.32), (78.2, 65.5), (81.8, 65.5), (82.4, 63.32)),
        ("F.Cu", "B.Cu", "F.Cu"),
        ((78.2, 65.5), (81.8, 65.5)),
    ),
    # USB-C A1/B1 ground contact pair; upper/lateral exits crossed
    # CC copper or caused NPTH clearance defects. This narrower
    # two-layer escape is native KiCad 10.0.8 DRC verified.
    RoutedConnection(
        "GND",
        ("J1", "A1", (76.8, 63.32)),
        ("J1", "B1", (83.2, 63.32)),
        ((76.8, 63.32), (76.5, 62.5), (83.5, 62.5), (83.2, 63.32)),
        ("F.Cu", "B.Cu", "F.Cu"),
        ((76.5, 62.5), (83.5, 62.5)),
    ),
)


# Stitch only two known via terminals belonging to distinct, pad-backed
# native route islands. No new via, footprint or layer-transition geometry.
VIA_STITCHES: tuple[tuple[str, tuple[float, float], tuple[float, float]], ...] = (
    ("VCC_3V3", (45.1, 61.6), (53.1, 58.8)),
)


# KiCad 10.0.8: source pad U3.2 to an existing VCC_3V3 B.Cu via
# from the previously verified R1.1-to-R2.1 pad-backed route.
PAD_TO_VIA_LINKS: tuple[PadToViaConnection, ...] = (
    PadToViaConnection("VCC_3V3", ("U3", "2", (61.85, 36.0)), (62.4, 36.4), (57.1, 58.8)),
)


# The existing 5V source route spans the new via's F.Cu center;
# the opposite endpoint is a previously verified J1 VBUS same-net via.
TRACK_TO_VIA_LINKS: tuple[TrackToViaConnection, ...] = (
    TrackToViaConnection("VCC_5V", (67.52, 42.0), (67.52, 68.0), (67.52, 65.5), (78.2, 65.5)),
    # Existing J1 ground-pair via is stitched to the genuine board ground track.
    TrackToViaConnection("GND", (77.51, 58.8), (77.51, 60.0), (77.51, 59.2), (76.5, 62.5)),
)


# Final native-only R2.2 SCL branch: two 45-degree front-layer
# turns and a single new via placed on the existing SCL B.Cu track.
PAD_TO_TRACK_LINKS: tuple[PadToTrackConnection, ...] = (
    PadToTrackConnection(
        "I2C_SCL",
        ("R2", "2", (58.51, 58.0)),
        ((58.51, 58.0), (58.51, 56.0), (57.51, 55.0), (49.5, 55.0)),
        (49.5, 55.0),
        (49.5, 58.975),
    ),
)


def _violations(text: str) -> Counter[str]:
    return Counter(re.findall(r"^\[([^]]+)\]:", text, re.MULTILINE))


def _blocking_finding_signatures(text: str) -> Counter[tuple[str, tuple[str, ...]]]:
    """Identify each physical DRC defect, not only its class-level count.

    Native KiCad may reorder the report when tracks are added. Header timestamps,
    source board filenames, and the intentionally reduced unconnected-item list
    do not identify a persistent manufacturability defect. Rule text, severity,
    offending object identities and absolute locations do.
    """
    signatures: Counter[tuple[str, tuple[str, ...]]] = Counter()
    kind: str | None = None
    details: list[str] = []

    def record() -> None:
        if kind is not None and kind != "unconnected_items":
            signatures[(kind, tuple(details))] += 1

    for line in text.splitlines():
        header = re.fullmatch(r"\[([^]]+)\]:\s*(.*)", line)
        if header is not None:
            record()
            kind = header.group(1)
            details = [header.group(2).strip()]
        elif kind is not None and line.startswith((" ", "\t")) and line.strip():
            details.append(line.strip())
        else:
            record()
            kind = None
            details = []
    record()
    return signatures


def _evidence_paths(output: Path) -> tuple[Path, Path, Path, Path]:
    return (
        output.with_suffix(".candidate.kicad_pcb"),
        output.with_suffix(".candidate-evidence.json"),
        output.with_suffix(".baseline-drc.rpt"),
        output.with_suffix(".review-drc.rpt"),
    )


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_native_report(report: Path) -> Counter[str]:
    if not report.is_file() or not report.stat().st_size:
        raise RuntimeError(f"Missing or empty native KiCad DRC report: {report}")
    text = report.read_text(encoding="utf-8")
    findings = _violations(text)
    if "DRC" not in text and not findings:
        raise RuntimeError("Native KiCad DRC output is not parseable")
    return findings


def _require_paths(board: Path, output: Path) -> tuple[Path, Path]:
    board = board.resolve(strict=True)
    output = output.resolve()
    if board.suffix != ".kicad_pcb" or output.suffix != ".kicad_pcb":
        raise ValueError("Review requires KiCad PCB source and output paths")
    if board == output or board.parent != output.parent:
        raise ValueError("Review output must be a distinct PCB in the same portable library directory")
    return board, output


def _require_native_pcbnew() -> ModuleType:
    try:
        return importlib.import_module("pcbnew")
    except ImportError as exc:
        raise RuntimeError("Native system KiCad pcbnew bindings are required") from exc


def prepare_review(board_path: Path, output_path: Path) -> Path:
    """Stage only a candidate; never publish an unverified review PCB."""
    board_path, output_path = _require_paths(board_path, output_path)
    before = _read_native_report(_evidence_paths(output_path)[2])
    if before != {"drill_out_of_range": 12, "hole_clearance": 4, "unconnected_items": 37}:
        raise RuntimeError(f"Board DRC baseline changed; no routing permitted: {dict(before)}")

    pcbnew = _require_native_pcbnew()
    board = pcbnew.LoadBoard(str(board_path))
    if len(board.GetTracks()) != 0:
        raise RuntimeError("Source PCB already contains copper; routing contract must be reviewed again")
    fps = {f.GetReference(): f for f in board.GetFootprints()}

    def check_pad(ref: str, pad_number: str, expected: tuple[float, float], net: str) -> None:
        fp = fps.get(ref)
        if fp is None:
            raise ValueError(f"Missing footprint {ref}")
        for pad in fp.Pads():
            if pad.GetNumber() != pad_number:
                continue
            xy = (pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y))
            if abs(xy[0] - expected[0]) < 0.0005 and abs(xy[1] - expected[1]) < 0.0005:
                if pad.GetNetname() != net or not pad.IsOnLayer(pcbnew.F_Cu):
                    raise ValueError(f"Wrong net or layer on {ref}.{pad_number}")
                return
        raise ValueError(f"Moved or missing physical pad {ref}.{pad_number}")

    for route in ROUTES:
        check_pad(*route.source, route.net)
        check_pad(*route.target, route.net)
        if route.points[0] != route.source[2] or route.points[-1] != route.target[2]:
            raise ValueError(f"Route endpoints differ from pad centers: {route.net}")
        net = board.FindNet(route.net)
        if net is None:
            raise ValueError(f"Unknown net {route.net}")
        layers = route.segment_layers or ("F.Cu",) * (len(route.points) - 1)
        if len(layers) != len(route.points) - 1 or any(layer not in ("F.Cu", "B.Cu") for layer in layers):
            raise ValueError("Invalid physical route layer sequence")
        transitions = tuple(
            route.points[index] for index in range(1, len(layers)) if layers[index - 1] != layers[index]
        )
        if transitions != route.via_points:
            raise ValueError("Missing or misplaced physical layer-transition via")
        for start, end, layer in zip(route.points[:-1], route.points[1:], layers, strict=True):
            if start == end:
                raise ValueError("Zero-length physical trace")
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(start[0]), pcbnew.FromMM(start[1])))
            track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(end[0]), pcbnew.FromMM(end[1])))
            track.SetWidth(pcbnew.FromMM(0.20))
            track.SetLayer(pcbnew.F_Cu if layer == "F.Cu" else pcbnew.B_Cu)
            track.SetNet(net)
            board.Add(track)
        for x, y in route.via_points:
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
            via.SetWidth(pcbnew.FromMM(0.70))
            via.SetDrill(pcbnew.FromMM(0.30))
            via.SetViaType(pcbnew.VIATYPE_THROUGH)
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            via.SetNet(net)
            board.Add(via)

    source_via_terminals = {(route.net, point) for route in ROUTES for point in route.via_points}
    for stitch_net, start, end in VIA_STITCHES:
        if start == end:
            raise ValueError("Zero-length via stitch")
        if (stitch_net, start) not in source_via_terminals or (stitch_net, end) not in source_via_terminals:
            raise ValueError("Via stitch must connect existing same-net pad-backed route vias")
        net = board.FindNet(stitch_net)
        if net is None:
            raise ValueError("Unknown via stitch net")
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(start[0]), pcbnew.FromMM(start[1])))
        track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(end[0]), pcbnew.FromMM(end[1])))
        track.SetWidth(pcbnew.FromMM(0.20))
        track.SetLayer(pcbnew.B_Cu)
        track.SetNet(net)
        board.Add(track)

    for link in PAD_TO_VIA_LINKS:
        check_pad(*link.source, link.net)
        if (link.net, link.existing_via) not in source_via_terminals:
            raise ValueError("Pad-to-via link anchor must be an existing same-net route via")
        if (link.net, link.layer_transition) in source_via_terminals:
            raise ValueError("Pad-to-via transition must be a new distinct via")
        if link.source[2] in (link.layer_transition, link.existing_via) or link.layer_transition == link.existing_via:
            raise ValueError("Pad-to-via connection has coincident endpoints")
        net = board.FindNet(link.net)
        if net is None:
            raise ValueError("Unknown pad-to-via net")
        for start, end, layer in (
            (link.source[2], link.layer_transition, pcbnew.F_Cu),
            (link.layer_transition, link.existing_via, pcbnew.B_Cu),
        ):
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(start[0]), pcbnew.FromMM(start[1])))
            track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(end[0]), pcbnew.FromMM(end[1])))
            track.SetWidth(pcbnew.FromMM(0.20))
            track.SetLayer(layer)
            track.SetNet(net)
            board.Add(track)
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(
            pcbnew.VECTOR2I(pcbnew.FromMM(link.layer_transition[0]), pcbnew.FromMM(link.layer_transition[1]))
        )
        via.SetWidth(pcbnew.FromMM(0.70))
        via.SetDrill(pcbnew.FromMM(0.30))
        via.SetViaType(pcbnew.VIATYPE_THROUGH)
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        via.SetNet(net)
        board.Add(via)

    for link in TRACK_TO_VIA_LINKS:
        if (link.net, link.existing_via) not in source_via_terminals:
            raise ValueError("Track-to-via destination must be an existing same-net route via")
        if (link.net, link.new_via) in source_via_terminals:
            raise ValueError("Track-to-via source must be a distinct new via")
        net = board.FindNet(link.net)
        if net is None:
            raise ValueError("Unknown track-to-via net")
        start, end, via_point = link.existing_track_start, link.existing_track_end, link.new_via
        existing_track = any(
            isinstance(item, pcbnew.PCB_TRACK)
            and not isinstance(item, pcbnew.PCB_VIA)
            and item.GetNetname() == link.net
            and item.GetLayer() == pcbnew.F_Cu
            and (
                (
                    (pcbnew.ToMM(item.GetStart().x), pcbnew.ToMM(item.GetStart().y)) == start
                    and (pcbnew.ToMM(item.GetEnd().x), pcbnew.ToMM(item.GetEnd().y)) == end
                )
                or (
                    (pcbnew.ToMM(item.GetStart().x), pcbnew.ToMM(item.GetStart().y)) == end
                    and (pcbnew.ToMM(item.GetEnd().x), pcbnew.ToMM(item.GetEnd().y)) == start
                )
            )
            for item in board.GetTracks()
        )
        if not existing_track:
            raise ValueError("Track-to-via anchor copper is not the expected physical F.Cu segment")
        if not (
            min(start[0], end[0]) <= via_point[0] <= max(start[0], end[0])
            and min(start[1], end[1]) <= via_point[1] <= max(start[1], end[1])
            and (end[0] - start[0]) * (via_point[1] - start[1]) == (end[1] - start[1]) * (via_point[0] - start[0])
        ):
            raise ValueError("Track-to-via source point is not on the verified copper centerline")
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(via_point[0]), pcbnew.FromMM(via_point[1])))
        track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(link.existing_via[0]), pcbnew.FromMM(link.existing_via[1])))
        track.SetWidth(pcbnew.FromMM(0.20))
        track.SetLayer(pcbnew.B_Cu)
        track.SetNet(net)
        board.Add(track)
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(via_point[0]), pcbnew.FromMM(via_point[1])))
        via.SetWidth(pcbnew.FromMM(0.70))
        via.SetDrill(pcbnew.FromMM(0.30))
        via.SetViaType(pcbnew.VIATYPE_THROUGH)
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        via.SetNet(net)
        board.Add(via)

    for link in PAD_TO_TRACK_LINKS:
        check_pad(*link.source, link.net)
        if len(link.points) < 2 or link.points[0] != link.source[2]:
            raise ValueError("Pad-to-track route must start at the verified pad center")
        if any(start == end for start, end in zip(link.points[:-1], link.points[1:], strict=True)):
            raise ValueError("Zero-length pad-to-track copper segment")
        via_point = link.points[-1]
        if (link.net, via_point) in source_via_terminals:
            raise ValueError("Pad-to-track link requires a distinct new transition via")
        if via_point != link.existing_track_start:
            raise ValueError("Pad-to-track new via must terminate on the existing B.Cu track")
        net = board.FindNet(link.net)
        if net is None:
            raise ValueError("Unknown pad-to-track net")
        existing = any(
            isinstance(item, pcbnew.PCB_TRACK)
            and not isinstance(item, pcbnew.PCB_VIA)
            and item.GetNetname() == link.net
            and item.GetLayer() == pcbnew.B_Cu
            and {
                (pcbnew.ToMM(item.GetStart().x), pcbnew.ToMM(item.GetStart().y)),
                (pcbnew.ToMM(item.GetEnd().x), pcbnew.ToMM(item.GetEnd().y)),
            }
            == {link.existing_track_start, link.existing_track_end}
            for item in board.GetTracks()
        )
        if not existing:
            raise ValueError("Pad-to-track destination is not the verified same-net native B.Cu segment")
        for start, end in zip(link.points[:-1], link.points[1:], strict=True):
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(start[0]), pcbnew.FromMM(start[1])))
            track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(end[0]), pcbnew.FromMM(end[1])))
            track.SetWidth(pcbnew.FromMM(0.20))
            track.SetLayer(pcbnew.F_Cu)
            track.SetNet(net)
            board.Add(track)
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(via_point[0]), pcbnew.FromMM(via_point[1])))
        via.SetWidth(pcbnew.FromMM(0.70))
        via.SetDrill(pcbnew.FromMM(0.30))
        via.SetViaType(pcbnew.VIATYPE_THROUGH)
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        via.SetNet(net)
        board.Add(via)

    candidate, manifest, _, _ = _evidence_paths(output_path)
    candidate.unlink(missing_ok=True)
    manifest.unlink(missing_ok=True)
    pcbnew.SaveBoard(str(candidate), board)
    metadata = {"sourceSha256": _file_sha256(board_path), "candidateSha256": _file_sha256(candidate)}
    manifest.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return candidate


def finalize_review(board_path: Path, output_path: Path, kicad_version: str) -> dict[str, object]:
    """Publish only after *external* native KiCad independently verified both boards."""
    board_path, output_path = _require_paths(board_path, output_path)
    if not kicad_version.startswith("10."):
        raise RuntimeError(f"Only KiCad 10 is currently validated: {kicad_version}")
    candidate, manifest, before_path, after_path = _evidence_paths(output_path)
    if not candidate.is_file() or not manifest.is_file():
        raise RuntimeError("Missing staged PCB or source/candidate integrity manifest")
    hashes = json.loads(manifest.read_text(encoding="utf-8"))
    if hashes != {"sourceSha256": _file_sha256(board_path), "candidateSha256": _file_sha256(candidate)}:
        raise RuntimeError("Source or candidate PCB changed between routing and native KiCad DRC")
    before = _read_native_report(before_path)
    after = _read_native_report(after_path)
    expected_before = {"drill_out_of_range": 12, "hole_clearance": 4, "unconnected_items": 37}
    expected_after = {"drill_out_of_range": 12, "hole_clearance": 4}
    if before != expected_before or after != expected_after:
        raise RuntimeError(f"Native KiCad DRC rejected the physical board: {dict(before)} -> {dict(after)}")
    before_blockers = _blocking_finding_signatures(before_path.read_text(encoding="utf-8"))
    after_blockers = _blocking_finding_signatures(after_path.read_text(encoding="utf-8"))
    if sum(before_blockers.values()) != 16 or before_blockers != after_blockers:
        raise RuntimeError("Native KiCad DRC rejected new or changed physical defect locations/details")

    pcbnew = _require_native_pcbnew()
    routed = pcbnew.LoadBoard(str(candidate))
    total_segments = (
        sum(len(route.points) - 1 for route in ROUTES)
        + len(VIA_STITCHES)
        + 2 * len(PAD_TO_VIA_LINKS)
        + len(TRACK_TO_VIA_LINKS)
        + sum(len(link.points) - 1 for link in PAD_TO_TRACK_LINKS)
    )
    expected_vias = {(route.net, point) for route in ROUTES for point in route.via_points}
    expected_vias.update((link.net, link.layer_transition) for link in PAD_TO_VIA_LINKS)
    expected_vias.update((link.net, link.new_via) for link in TRACK_TO_VIA_LINKS)
    expected_vias.update((link.net, link.points[-1]) for link in PAD_TO_TRACK_LINKS)
    actual_vias = {}
    for item in routed.GetTracks():
        if isinstance(item, pcbnew.PCB_VIA):
            xy = (pcbnew.ToMM(item.GetPosition().x), pcbnew.ToMM(item.GetPosition().y))
            actual_vias[(item.GetNetname(), xy)] = item
    if len(routed.GetTracks()) != total_segments + len(expected_vias) or set(actual_vias) != expected_vias:
        raise RuntimeError("KiCad track/via count or native via identity differs from physical connection contract")
    if any(
        via.GetWidth(pcbnew.F_Cu) != pcbnew.FromMM(0.70)
        or via.GetDrillValue() != pcbnew.FromMM(0.30)
        or via.TopLayer() != pcbnew.F_Cu
        or via.BottomLayer() != pcbnew.B_Cu
        for via in actual_vias.values()
    ):
        raise RuntimeError("Native via geometry or layer pair changed before review")

    candidate.replace(output_path)
    manifest.unlink(missing_ok=True)
    result: dict[str, object] = {
        "kiCadVersion": kicad_version,
        "baseline": dict(before),
        "partialRouted": dict(after),
        "connectionsAdded": len(ROUTES)
        + len(VIA_STITCHES)
        + len(PAD_TO_VIA_LINKS)
        + len(TRACK_TO_VIA_LINKS)
        + len(PAD_TO_TRACK_LINKS),
        "padToPadRoutes": len(ROUTES),
        "viaStitchConnections": len(VIA_STITCHES),
        "padToViaConnections": len(PAD_TO_VIA_LINKS),
        "trackToViaConnections": len(TRACK_TO_VIA_LINKS),
        "padToTrackConnections": len(PAD_TO_TRACK_LINKS),
        "nativeConnectivityComplete": True,
        "traceSegments": total_segments,
        "twoLayerVias": len(expected_vias),
        "fabApproved": False,
        "physicalContinuityComplete": False,
        "warning": "0 native unconnected items, but 16 physical manufacturability DRC violations remain",
    }
    output_path.with_suffix(".review-evidence.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "finalize"))
    parser.add_argument("pcb", type=Path, help="Generated, untouched source KiCad board")
    parser.add_argument("output", type=Path, help="Review-only board in same directory")
    parser.add_argument("--kicad-version", default="", help="Version verified by native DRC driver")
    args = parser.parse_args()
    if args.phase == "prepare":
        print(prepare_review(args.pcb, args.output))
    else:
        print(json.dumps(finalize_review(args.pcb, args.output, args.kicad_version), indent=2))


if __name__ == "__main__":
    main()
