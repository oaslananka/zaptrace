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


# Tested against the pinned 100 x 75 mm reference placement with KiCad 10.0.6/10.0.7.
# These are only the paths KiCad independently proved physically connected.
# Do NOT extrapolate success to the 15 remaining unconnected copper items.
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
        for start, end in zip(route.points, route.points[1:], strict=False):
            if start == end:
                raise ValueError("Zero-length physical trace")
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(start[0]), pcbnew.FromMM(start[1])))
            track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(end[0]), pcbnew.FromMM(end[1])))
            track.SetWidth(pcbnew.FromMM(0.20))
            track.SetLayer(pcbnew.F_Cu)
            track.SetNet(net)
            board.Add(track)

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
    expected_after = {"drill_out_of_range": 12, "hole_clearance": 4, "unconnected_items": 15}
    if before != expected_before or after != expected_after:
        raise RuntimeError(f"Native KiCad DRC rejected the physical board: {dict(before)} -> {dict(after)}")
    before_blockers = _blocking_finding_signatures(before_path.read_text(encoding="utf-8"))
    after_blockers = _blocking_finding_signatures(after_path.read_text(encoding="utf-8"))
    if sum(before_blockers.values()) != 16 or before_blockers != after_blockers:
        raise RuntimeError("Native KiCad DRC rejected new or changed physical defect locations/details")

    pcbnew = _require_native_pcbnew()
    routed = pcbnew.LoadBoard(str(candidate))
    total_segments = sum(len(route.points) - 1 for route in ROUTES)
    if len(routed.GetTracks()) != total_segments:
        raise RuntimeError("KiCad track count differs from the verified physical connection contract")

    candidate.replace(output_path)
    manifest.unlink(missing_ok=True)
    result: dict[str, object] = {
        "kiCadVersion": kicad_version,
        "baseline": dict(before),
        "partialRouted": dict(after),
        "connectionsAdded": len(ROUTES),
        "traceSegments": total_segments,
        "fabApproved": False,
        "physicalContinuityComplete": False,
        "warning": "15 real unconnected items and 16 manufacturability DRC violations remain",
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
