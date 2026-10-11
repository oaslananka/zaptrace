"""External KiCad 10.0.x oracle fixture for Issue #35.

Generates a minimal two-net, four-pad PCB from real GridRouter traces.
The physical pad coordinates are asserted before PCB export.
This fixture is NOT an ESP32 demo signoff or complete PCB router acceptance.

Run using system Python with pcbnew, via issue35_native_grid_oracle.sh.
"""

import argparse
import hashlib
import importlib
import json
import re
from pathlib import Path

# The optional KiCad python binding is supplied by the system KiCad 10
# installation, not uv's project interpreter.
pcbnew = importlib.import_module("pcbnew")

parser = argparse.ArgumentParser(description="Two-net, pad-centered native KiCad GridRouter oracle")
parser.add_argument("phase", choices=("prepare", "verify"))
parser.add_argument("output", type=Path)
args = parser.parse_args()
D = args.output.resolve()
D.mkdir(parents=True, exist_ok=True)
if args.phase == "verify":
    evidence = json.loads((D / "manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256((D / "route-plan.json").read_bytes()).hexdigest() != evidence["planSha256"]:
        raise RuntimeError("GridRouter plan changed before KiCad DRC verification")
    for board in ("baseline", "routed"):
        path = D / (board + ".kicad_pcb")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != evidence[board + "Sha256"]:
            raise RuntimeError("KiCad fixture mutated after independently routed PCB export")
    reports = []
    for board in ("baseline", "routed"):
        path = D / (board + ".rpt")
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError("Independent KiCad report is missing or empty")
        report = path.read_text(encoding="utf-8")
        if "** Drc report" not in report:
            raise RuntimeError("Unrecognized KiCad DRC report")
        from collections import Counter

        reports.append(Counter(re.findall(r"^\[([^]]+)\]:", report, re.MULTILINE)))
    if reports != [{"unconnected_items": 2}, {}]:
        raise RuntimeError(f"Native KiCad DRC failed: {reports}")
    print(
        json.dumps(
            {
                "baseline": dict(reports[0]),
                "routed": dict(reports[1]),
                "expectedPadConnections": 2,
                "manufacturingApproved": False,
            },
            indent=2,
        )
    )
    raise SystemExit(0)
plan_path = D / "route-plan.json"
plan = json.loads(plan_path.read_text(encoding="utf-8"))
if plan.get("schema") != "issue35.native-grid.v1" or plan.get("manufacturingApproved") is not False:
    raise RuntimeError("Unexpected native-grid plan schema or hardware approval flag")
pos = {key: tuple(value) for key, value in plan["positions"].items()}
routes = plan["routes"]
expected = {"n1": {pos["a1"], pos["a2"]}, "n2": {pos["b1"], pos["b2"]}}
if len(routes) != 2 or plan["routeCount"] != 2:
    raise RuntimeError("Fixture must contain exactly two routed nets")
for route in routes:
    if (
        route["net"] not in expected
        or route["layer"] != "layer_0"
        or {tuple(route["start"]), tuple(route["end"])} != expected[route["net"]]
    ):
        raise RuntimeError("Native KiCad candidate does not connect exact physical pad centers")
b = pcbnew.BOARD()
nets = {}
for k in ("n1", "n2"):
    n = pcbnew.NETINFO_ITEM(b, k)
    b.Add(n)
    nets[k] = n
for key, xy in pos.items():
    fp = pcbnew.FOOTPRINT(b)
    fp.SetReference(key.upper())
    fp.SetValue("TEST_PAD")
    fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(xy[0]), pcbnew.FromMM(xy[1])))
    pad = pcbnew.PAD(fp)
    pad.SetNumber("1")
    pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
    pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
    pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(1.8), pcbnew.FromMM(1.8)))
    pad.SetDrillSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.8), pcbnew.FromMM(0.8)))
    pad.SetLayerSet(pcbnew.LSET.AllCuMask())
    pad.SetPosition(fp.GetPosition())
    pad.SetNet(nets["n1" if key[0] == "a" else "n2"])
    fp.Add(pad)
    b.Add(fp)
edges = [((5.0, 5.0), (40.0, 5.0)), ((40.0, 5.0), (40.0, 25.0)), ((40.0, 25.0), (5.0, 25.0)), ((5.0, 25.0), (5.0, 5.0))]
for a, z in edges:
    shape = pcbnew.PCB_SHAPE(b)
    shape.SetShape(pcbnew.SHAPE_T_SEGMENT)
    shape.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(a[0]), pcbnew.FromMM(a[1])))
    shape.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(z[0]), pcbnew.FromMM(z[1])))
    shape.SetLayer(pcbnew.Edge_Cuts)
    shape.SetWidth(pcbnew.FromMM(0.05))
    b.Add(shape)
base = D / "baseline.kicad_pcb"
pcbnew.SaveBoard(str(base), b)
for route in routes:
    track = pcbnew.PCB_TRACK(b)
    track.SetStart(pcbnew.VECTOR2I(*[pcbnew.FromMM(v) for v in route["start"]]))
    track.SetEnd(pcbnew.VECTOR2I(*[pcbnew.FromMM(v) for v in route["end"]]))
    track.SetLayer(pcbnew.F_Cu)
    track.SetWidth(pcbnew.FromMM(route["width"]))
    track.SetNet(nets[route["net"]])
    b.Add(track)
ready = D / "routed.kicad_pcb"
pcbnew.SaveBoard(str(ready), b)

(D / "manifest.json").write_text(
    json.dumps(
        {
            "baselineSha256": hashlib.sha256(base.read_bytes()).hexdigest(),
            "routedSha256": hashlib.sha256(ready.read_bytes()).hexdigest(),
            "routedNetCount": plan["routeCount"],
            "traceSegments": len(routes),
            "planSha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            "manufacturingApproved": False,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(f"Staged pad-centered KiCad fixture: {base} / {ready}")
