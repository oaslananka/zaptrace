"""Emit a real pad-owned SMD obstacle-detour route using locked ZapTrace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from zaptrace.algo.grid_router import GridRouter
from zaptrace.algo.pad_copper import rotated_offset
from zaptrace.core.models import BoardConfig, Component, Design, DesignMeta, FootprintDef, Net, NetNode, Pad, PadShape

parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
args = parser.parse_args()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=True)

design = Design(meta=DesignMeta(name="native-smd-pad-detour"), board=BoardConfig(width_mm=40, height_mm=30))
positions = {"a1": (6.0, 11.0), "a2": (30.0, 10.0), "barrier": (18.0, 10.0)}
rotations = {"a1": 90.0, "a2": 0.0, "barrier": 0.0}
pads = {
    "a1": Pad(id="1", position=(1.0, 0.0), shape=PadShape.RECT, size=(1.5, 1.0)),
    "a2": Pad(id="1", shape=PadShape.RECT, size=(1.5, 1.0)),
    "barrier": Pad(id="1", shape=PadShape.RECT, size=(5.0, 2.0), rotation=90.0),
}
for ref, pad in pads.items():
    design.components[ref] = Component(
        id=ref,
        ref=ref.upper(),
        type="connector",
        footprint_def=FootprintDef(pads=[pad], courtyard=(1.8, 1.8)),
        properties={"rotation": rotations[ref]},
    )
design.nets["SIGNAL_A"] = Net(
    id="SIGNAL_A",
    name="SIGNAL_A",
    nodes=[NetNode(component_ref=ref.upper(), pin_name="1") for ref in ("a1", "a2")],
)
design.nets["SIGNAL_B"] = Net(
    id="SIGNAL_B",
    name="SIGNAL_B",
    nodes=[NetNode(component_ref="BARRIER", pin_name="1")],
)
result = GridRouter(resolution_mm=0.5, pad_aware=True).route(design, positions)
if result.net_count != 1 or result.routed_net_count != 1 or result.vias or len(result.traces) <= 1:
    raise RuntimeError("Native SMD test must route exactly one net around a foreign rotated pad")
if any(track.layer != "layer_0" or track.net_id != "SIGNAL_A" for track in result.traces):
    raise RuntimeError("SMD fixture route must be entirely on F.Cu with correct net")
centers = {
    ref: tuple(positions[ref][axis] + rotated_offset(*pad.position, rotations[ref])[axis] for axis in (0, 1))
    for ref, pad in pads.items()
}
if result.traces[0].start != tuple(round(x, 3) for x in centers["a1"]) or result.traces[-1].end != tuple(
    round(x, 3) for x in centers["a2"]
):
    raise RuntimeError("SMD route must terminate on exact physical pad centres")
(out / "route-plan.json").write_text(
    json.dumps(
        {
            "schema": "issue35.native-smd.v1",
            "positions": positions,
            "padCenters": centers,
            "pads": {
                ref: {
                    "shape": pad.shape.value,
                    "size": pad.size,
                    "rotation": pad.rotation,
                    "position": pad.position,
                    "footprintRotation": rotations[ref],
                    "net": "SIGNAL_B" if ref == "barrier" else "SIGNAL_A",
                }
                for ref, pad in pads.items()
            },
            "routes": [
                {"net": t.net_id, "start": t.start, "end": t.end, "layer": t.layer, "width": t.width}
                for t in result.traces
            ],
            "routeCount": 1,
            "manufacturingApproved": False,
        },
        sort_keys=True,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(f"GridRouter generated a real SMD detour of {len(result.traces)} segments")
