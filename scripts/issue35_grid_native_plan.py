"""Emit a deterministic two-net GridRouter plan for native KiCad 10 DRC.

Uses the repository's locked Python interpreter; no pcbnew required.
The system pcbnew adapter imports this JSON without importing project code.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from zaptrace.algo.grid_router import GridRouter
from zaptrace.core.models import BoardConfig, Component, Design, DesignMeta, FootprintDef, Net, NetNode, Pad

parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
args = parser.parse_args()
D = args.output.resolve()
D.mkdir(parents=True, exist_ok=True)
design = Design(meta=DesignMeta(name="issue35-native-two-nets"), board=BoardConfig(width_mm=45, height_mm=30))
pos = {"a1": (10.0, 10.0), "a2": (35.0, 10.0), "b1": (10.0, 20.0), "b2": (35.0, 20.0)}
for component_id in pos:
    design.components[component_id] = Component(
        id=component_id,
        ref=component_id.upper(),
        type="connector",
        footprint_def=FootprintDef(
            courtyard=(0.0, 0.0), pads=[Pad(id="1", position=(0.0, 0.0), size=(1.8, 1.8), drill=0.8)]
        ),
    )
for name, pair in {"n1": ("a1", "a2"), "n2": ("b1", "b2")}.items():
    design.nets[name] = Net(
        id=name, name="VCC_" + name, nodes=[NetNode(component_ref=i.upper(), pin_name="1") for i in pair]
    )
router = GridRouter(resolution_mm=0.5, max_ripup_passes=1)
result = router.route(design, pos)
if result.routed_net_count != 2 or len(result.traces) != 2 or result.vias:
    raise RuntimeError("Routing no longer connects both fixture nets without vias")
expected = {
    "n1": {pos["a1"], pos["a2"]},
    "n2": {pos["b1"], pos["b2"]},
}
for trace in result.traces:
    if trace.layer != "layer_0" or {trace.start, trace.end} != expected[trace.net_id]:
        raise RuntimeError("Router no longer reaches the exact physical pad centers")
(D / "route-plan.json").write_text(
    json.dumps(
        {
            "schema": "issue35.native-grid.v1",
            "positions": pos,
            "routes": [
                {
                    "net": segment.net_id,
                    "start": segment.start,
                    "end": segment.end,
                    "layer": segment.layer,
                    "width": segment.width,
                }
                for segment in result.traces
            ],
            "routeCount": result.routed_net_count,
            "manufacturingApproved": False,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
