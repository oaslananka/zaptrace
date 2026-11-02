# pyright: reportMissingImports=false
#!/usr/bin/python3
"""Native multi-footprint copy-on-write ECO: 2–4 distinct unrouted footprint translations.

Reuse the already verified one-move KiCad editor for each step. All intermediates
live in a disposable directory. Publish only when the final original-to-copy
native integrity and DRC checks pass; never touch the source design.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

import pcbnew as pcb
from review_studio_pcb_eco import (
    REFERENCE,
    compare_drc,
    create,
    sha,
    state,
)


def verified_global_state(before: dict, after: dict, moves: dict[str, tuple[float, float]]) -> None:
    if before["tracks"] != after["tracks"] or before["zones"] != after["zones"]:
        raise RuntimeError("Global KiCad copper tracks or zone inventory changed")
    if set(before["footprints"]) != set(after["footprints"]):
        raise RuntimeError("Footprint identity/inventory drift")
    for ref, original in before["footprints"].items():
        proposed = after["footprints"][ref]
        for field in ("uuid", "value", "locked", "layer", "library"):
            if original[field] != proposed[field]:
                raise RuntimeError("Footprint native metadata changed outside ECO")
        if proposed["angle"] != original["angle"]:
            raise RuntimeError("Unexpected footprint rotation")
        delta = tuple(pcb.FromMM(v) for v in moves.get(ref, (0.0, 0.0)))
        if proposed["pos"] != (original["pos"][0] + delta[0], original["pos"][1] + delta[1]):
            raise RuntimeError("Unexpected footprint position outside exact multi-ECO")
        if set(original["pads"]) != set(proposed["pads"]):
            raise RuntimeError("Native pad identities differ")
        for uuid, old in original["pads"].items():
            new = proposed["pads"][uuid]
            if old[:3] != new[:3] or old[4:] != new[4:]:
                raise RuntimeError("Native pad/net/shape/rotation metadata changed")
            if new[3] != (old[3][0] + delta[0], old[3][1] + delta[1]):
                raise RuntimeError("Native pad XY not translated with its footprint")


def create_multi(source: Path, output: Path, moves: list[tuple[str, float, float]]) -> dict:
    source = source.resolve(strict=True)
    output = output.absolute()
    if not source.is_file() or source.suffix != ".kicad_pcb" or source.stat().st_size > 10_000_000:
        raise ValueError("Regular native source PCB (max 10 MB) required")
    if not 2 <= len(moves) <= 4 or len({move[0] for move in moves}) != len(moves):
        raise ValueError("Exactly 2–4 distinct native footprint translations required")
    offsets: dict[str, tuple[float, float]] = {}
    for ref, dx, dy in moves:
        if not REFERENCE.fullmatch(ref):
            raise ValueError("Invalid footprint reference")
        if any(not math.isfinite(v) or abs(v) > 5 or abs(v * 20 - round(v * 20)) > 1e-7 for v in (dx, dy)):
            raise ValueError("Translation must be finite, at most 5 mm and on a 0.05 mm grid")
        if dx == dy == 0:
            raise ValueError("Zero translation not allowed")
        offsets[ref] = (dx, dy)
    if (
        output.exists()
        or output.is_symlink()
        or output.resolve().is_relative_to(source.parent)
        or not output.parent.is_dir()
        or output.parent.is_symlink()
    ):
        raise ValueError("Use a new output directory outside the original KiCad source folder")
    source_sha = sha(source)
    snapshots: dict[str, str] = {}
    for suffix, limit in ((".kicad_pro", 3_000_000), (".kicad_dru", 1_000_000)):
        sidecar = source.with_suffix(suffix)
        if sidecar.is_symlink() or (sidecar.exists() and not sidecar.is_file()):
            raise ValueError("Unsafe KiCad native rule sidecar")
        if sidecar.exists():
            if sidecar.stat().st_size > limit:
                raise ValueError("Oversized KiCad rule file")
            snapshots[suffix] = sha(sidecar)

    initial = pcb.LoadBoard(str(source))
    if initial is None:
        raise ValueError("Native KiCad rejected original PCB")
    first = state(initial)
    with tempfile.TemporaryDirectory(prefix=".zaptrace-multieco-", dir=output.parent) as scratch:
        temp = Path(scratch)
        previous = source
        steps = []
        first_drc = None
        last_drc = None
        rule_context = None
        for index, (ref, dx, dy) in enumerate(moves):
            destination = temp / f"step-{index + 1}"
            step = create(previous, destination, ref, dx, dy, 0)
            if rule_context is None:
                rule_context = step["rule_context"]
            elif step["rule_context"] != rule_context:
                raise RuntimeError("KiCad rule context changed between native ECO steps")
            if first_drc is None:
                first_drc = json.loads((destination / "before-drc.json").read_text())
            last_drc = json.loads((destination / "after-drc.json").read_text())
            steps.append(
                {
                    "ref": ref,
                    "dx_mm": dx,
                    "dy_mm": dy,
                    "source_sha256": step["source_sha256"],
                    "working_sha256": step["working_sha256"],
                    "old_mm": step["old_mm"],
                    "new_mm": step["new_mm"],
                    "native_drc": step["native_drc"],
                }
            )
            if index and steps[index - 1]["working_sha256"] != step["source_sha256"]:
                raise RuntimeError("Native multi-ECO chain is discontinuous")
            previous = destination / "source.kicad_pcb"

        last = pcb.LoadBoard(str(previous))
        if last is None:
            raise RuntimeError("Native KiCad cannot reload completed multi-ECO")
        verified_global_state(first, state(last), offsets)
        if first_drc is None or last_drc is None:
            raise RuntimeError("Native KiCad DRC evidence missing")
        final_drc = compare_drc(first_drc, last_drc)
        if sha(source) != source_sha or any(
            sha(source.with_suffix(suffix)) != checksum for suffix, checksum in snapshots.items()
        ):
            raise RuntimeError("Original PCB/rules modified during isolated multi-ECO")
        if output.exists() or output.is_symlink():
            raise RuntimeError("ECO destination appeared during native validation")
        output.mkdir(mode=0o700)
        try:
            result_board = output / "source.kicad_pcb"
            shutil.copyfile(previous, result_board)
            for suffix, checksum in snapshots.items():
                dest = output / ("source" + suffix)
                shutil.copyfile(previous.with_suffix(suffix), dest)
                if sha(dest) != checksum:
                    raise RuntimeError("Published rule sidecar hash changed")
            if sha(result_board) != steps[-1]["working_sha256"]:
                raise RuntimeError("Published proposed board hash changed")
            result = {
                "type": "PCB_UNROUTED_MULTI_FOOTPRINT_PLACEMENT_ECO",
                "status": "native_drc_verified_copy_not_original",
                "source_sha256": source_sha,
                "working_sha256": sha(result_board),
                "moves": [{"ref": item["ref"], "old_mm": item["old_mm"], "new_mm": item["new_mm"]} for item in steps],
                "steps": steps,
                "native_drc": final_drc,
                "rule_context": rule_context,
                "fabApproved": False,
                "electricallyApproved": False,
                "scope": "2–4 unrouted translated footprints; no fabricated electrical/DFM approval",
            }
            (output / "ECO_EVIDENCE.json").write_text(json.dumps(result, indent=2) + "\n")
        except Exception:
            shutil.rmtree(output)
            raise
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--move", action="append", required=True, metavar="REF,DX,DY")
    args = parser.parse_args()
    try:
        moves = []
        for spec in args.move:
            ref, dx, dy = spec.split(",")
            moves.append((ref, float(dx), float(dy)))
        result = create_multi(args.board, args.output, moves)
    except (ValueError, RuntimeError, OSError) as exc:
        print("MULTI PCB ECO BLOCKED:", str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
