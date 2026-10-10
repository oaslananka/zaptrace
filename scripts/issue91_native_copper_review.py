"""Reproducible, fail-closed *partial* physical routing for ESP32 issue #91.

Requires system KiCad 10 pcbnew + kicad-cli. Runs *native* KiCad DRC both
before and after routing and refuses to emit an accepted artifact if new
violations appear or the expected six pad connections are not established.

This is a review artifact, NOT complete board routing or fabrication signoff.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RoutedConnection:
    net: str
    source: tuple[str, str, tuple[float, float]]
    target: tuple[str, str, tuple[float, float]]
    points: tuple[tuple[float, float], ...]


# Tested against the pinned 100 x 75 mm reference placement with KiCad 10.0.6.
# These are only the paths KiCad independently proved physically connected.
# Do NOT extrapolate success to the 31 remaining unconnected copper items.
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
)


def _violations(text: str) -> Counter[str]:
    return Counter(re.findall(r"^\[([^]]+)\]:", text, re.MULTILINE))


def _native_drc(board: Path, report: Path) -> Counter[str]:
    command = ["kicad-cli", "pcb", "drc", "--exit-code-violations", "--output", str(report), str(board)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode not in (0, 5) or not report.is_file():
        raise RuntimeError(f"KiCad DRC could not produce evidence: {result.stderr or result.stdout}")
    return _violations(report.read_text(encoding="utf-8"))


def run_review(board_path: Path, output_path: Path) -> dict[str, object]:
    try:
        import importlib

        pcbnew = importlib.import_module("pcbnew")
    except ImportError as exc:
        raise RuntimeError("Native KiCad pcbnew Python bindings are required") from exc

    version = subprocess.run(["kicad-cli", "version"], capture_output=True, text=True, check=True).stdout.strip()
    if not version.startswith("10."):
        raise RuntimeError(f"Validated only on KiCad 10, not {version!r}")
    board_path = board_path.resolve()
    output_path = output_path.resolve()
    if not board_path.exists() or output_path == board_path or output_path.parent != board_path.parent:
        raise ValueError("Both PCB paths must be distinct files in one portable KiCad library directory")

    before = _native_drc(board_path, output_path.with_suffix(".baseline-drc.rpt"))
    if before != {"drill_out_of_range": 12, "hole_clearance": 4, "unconnected_items": 37}:
        raise RuntimeError(f"Board baseline changed: {dict(before)}. Revalidate physical routing first.")

    board = pcbnew.LoadBoard(str(board_path))
    fps = {f.GetReference(): f for f in board.GetFootprints()}

    def check_pad(ref: str, pad_number: str, expected: tuple[float, float], net: str) -> None:
        fp = fps.get(ref)
        if fp is None:
            raise ValueError(f"Missing footprint {ref}")
        matches = [pad for pad in fp.Pads() if pad.GetNumber() == pad_number]
        if not matches:
            raise ValueError(f"Missing pad {ref}.{pad_number}")
        for pad in matches:
            xy = (pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y))
            if abs(xy[0] - expected[0]) < 0.0005 and abs(xy[1] - expected[1]) < 0.0005:
                if pad.GetNetname() != net or not pad.IsOnLayer(pcbnew.F_Cu):
                    raise ValueError(f"Incorrect pad net/layer {ref}.{pad_number}")
                return
        raise ValueError(f"Moved or unmatched physical pad {ref}.{pad_number}")

    for route in ROUTES:
        check_pad(*route.source, route.net)
        check_pad(*route.target, route.net)
        assert route.points[0] == route.source[2] and route.points[-1] == route.target[2]
        net = board.FindNet(route.net)
        if net is None:
            raise ValueError(f"Missing physical net {route.net}")
        for start, end in zip(route.points, route.points[1:], strict=False):
            if start == end:
                raise ValueError("Zero-length track")
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(start[0]), pcbnew.FromMM(start[1])))
            track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(end[0]), pcbnew.FromMM(end[1])))
            track.SetWidth(pcbnew.FromMM(0.20))
            track.SetLayer(pcbnew.F_Cu)
            track.SetNet(net)
            board.Add(track)

    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".kicad_pcb", dir=output_path.parent, delete=False) as temp:
        candidate = Path(temp.name)
    try:
        pcbnew.SaveBoard(str(candidate), board)
        after = _native_drc(candidate, output_path.with_suffix(".review-drc.rpt"))
        if (
            after["drill_out_of_range"] != before["drill_out_of_range"]
            or after["hole_clearance"] != before["hole_clearance"]
            or after["unconnected_items"] != before["unconnected_items"] - len(ROUTES)
            or set(after) - {"drill_out_of_range", "hole_clearance", "unconnected_items"}
        ):
            raise RuntimeError(f"Routing is NOT KiCad-DRC safe: before={dict(before)}, after={dict(after)}")
        candidate.replace(output_path)
    finally:
        candidate.unlink(missing_ok=True)
        candidate.with_suffix(".kicad_pro").unlink(missing_ok=True)
        candidate.with_suffix(".kicad_prl").unlink(missing_ok=True)

    evidence = {
        "kiCadVersion": version,
        "baseline": dict(before),
        "partialRouted": dict(after),
        "connectionsAdded": len(ROUTES),
        "traceSegments": sum(len(route.points) - 1 for route in ROUTES),
        "fabApproved": False,
        "physicalContinuityComplete": False,
        "warning": "31 real unconnected items and 16 manufacturability DRC violations remain",
    }
    output_path.with_suffix(".review-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcb", type=Path, help="Generated, untouched KiCad source PCB")
    parser.add_argument("output", type=Path, help="Review-only PCB in same KiCad library directory")
    args = parser.parse_args()
    print(json.dumps(run_review(args.pcb, args.output), indent=2))


if __name__ == "__main__":
    main()
