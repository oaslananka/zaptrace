"""Transactional multi-net copy proof: two genuine KiCad DRC passes and rollback."""

# pyright: reportMissingImports=false
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_review_studio_native_copper_link import source_project

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/review_studio_native_copper_batch.py"

pytestmark = pytest.mark.skipif(
    not shutil.which("kicad-cli") or not Path("/usr/lib/python3/dist-packages/pcbnew.py").exists(),
    reason="Native KiCad 10 and pcbnew required",
)


def selected(ids: dict[tuple[str, str], str]) -> list[dict]:
    return [
        {
            "start_pad_uuid": ids["R3", "2"],
            "end_pad_uuid": ids["R4", "2"],
            "waypoints": [[72.51, 58.8], [77.51, 58.8]],
            "via_indices": [1, 2],
        },
        {
            "start_pad_uuid": ids["U1", "2"],
            "end_pad_uuid": ids["U1", "3"],
            "waypoints": [],
            "via_indices": [],
        },
    ]


def run(board: Path, output: Path, routes: list[dict], *, timeout: int = 250) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            str(SCRIPT),
            "--board",
            str(board),
            "--output",
            str(output),
            "--routes-json",
            json.dumps(routes),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def test_native_two_distinct_nets_transactional_cumulative_drc_and_sha(tmp_path: Path) -> None:
    board, ids = source_project(tmp_path)
    original = board.read_bytes()
    out = tmp_path / "native-multinet-copy"
    process = run(board, out, selected(ids))
    assert process.returncode == 0, process.stderr
    proof = json.loads((out / "EVIDENCE.json").read_text())
    assert json.loads(process.stdout) == proof
    assert proof["distinct_nets"] == ["GND", "VCC_3V3"]
    assert proof["step_count"] == 2
    assert [
        (step["native_drc"]["before_unconnected"], step["native_drc"]["after_unconnected"]) for step in proof["steps"]
    ] == [(37, 36), (36, 35)]
    assert proof["cumulative_drc"] == {
        "before_unconnected": 37,
        "after_unconnected": 35,
        "before_violations": 16,
        "after_violations": 16,
        "new_findings": 0,
        "schematic_parity": 0,
        "kiCadVersion": "10.0.7",
    }
    assert proof["steps"][1]["source_sha256"] == proof["steps"][0]["working_sha256"]
    assert proof["working_sha256"] == hashlib.sha256((out / "project" / board.name).read_bytes()).hexdigest()
    assert proof["zone_refill_verified"] is False
    assert proof["fabApproved"] is False and proof["electricallyApproved"] is False
    assert board.read_bytes() == original
    for name, digest in proof["source_asset_sha256"].items():
        assert hashlib.sha256((board.parent / name).read_bytes()).hexdigest() == digest
    # Actual system pcbnew reopens final KiCad board independently and proves
    # exactly two vias, one buried-side corridor and one extra F.Cu trace.
    reopen = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            "-c",
            """import json,pcbnew as p,sys
b=p.LoadBoard(sys.argv[1])
via=[i for i in b.GetTracks() if isinstance(i,p.PCB_VIA)]
bottom=[i for i in b.GetTracks() if not isinstance(i,p.PCB_VIA) and i.GetLayer()==p.B_Cu]
front=[i for i in b.GetTracks() if not isinstance(i,p.PCB_VIA) and i.GetLayer()==p.F_Cu]
assert len(via)==2 and len(bottom)==1 and len(front)==3
assert {i.GetNetname() for i in via+bottom}=={'GND'}
assert {i.GetNetname() for i in front}=={'GND','VCC_3V3'}
assert all(i.GetDrillValue()==p.FromMM(0.3) and i.GetWidth(p.F_Cu)==p.FromMM(0.6)
 and i.GetLayerSet().Contains(p.F_Cu) and i.GetLayerSet().Contains(p.B_Cu) for i in via)
print('ACTUAL_SAVED_TWO_DISTINCT_KICAD_NETS_AND_TWO_VIAS=PASS')
""",
            str(out / "project" / board.name),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert "ACTUAL_SAVED_TWO_DISTINCT_KICAD_NETS_AND_TWO_VIAS=PASS" in reopen.stdout


def test_second_route_failure_discards_every_previously_accepted_stage(tmp_path: Path) -> None:
    board, ids = source_project(tmp_path)
    sha = hashlib.sha256(board.read_bytes()).hexdigest()
    routes = selected(ids)
    # Validly shaped UUIDs, but second route is not a DRC-selected pair.
    routes[1]["end_pad_uuid"] = ids["U1", "1"]
    out = tmp_path / "must-never-partially-publish"
    process = run(board, out, routes)
    assert process.returncode == 2
    assert "not a unique native unconnected link" in process.stderr
    assert not out.exists()
    assert hashlib.sha256(board.read_bytes()).hexdigest() == sha


@pytest.mark.parametrize(
    "change",
    [
        lambda routes: routes[:1],
        lambda routes: routes + routes + routes[:1],
        lambda routes: [routes[0], routes[0]],
        lambda routes: [{**routes[0], "start_pad_uuid": routes[0]["end_pad_uuid"]}, routes[1]],
        lambda routes: [{**routes[0], "unknown": "unsafe"}, routes[1]],
        lambda routes: [{**routes[0], "via_indices": [True, 2]}, routes[1]],
        lambda routes: [{**routes[0], "via_indices": [1, 1]}, routes[1]],
        lambda routes: [{**routes[0], "waypoints": [[float("nan"), 1.0]]}, routes[1]],
    ],
)
def test_invalid_batch_plan_never_publishes(tmp_path: Path, change) -> None:
    board, ids = source_project(tmp_path)
    routes = change(selected(ids))
    original = board.read_bytes()
    out = tmp_path / "invalid"
    result = run(board, out, routes, timeout=40)
    assert result.returncode == 2
    assert not out.exists()
    assert board.read_bytes() == original


def test_zone_bearing_board_denied_before_any_route(tmp_path: Path) -> None:
    board, ids = source_project(tmp_path)
    native = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            "-c",
            """import pcbnew as p,sys
b=p.LoadBoard(sys.argv[1])
zone=p.ZONE(b)
zone.SetLayer(p.F_Cu)
zone.SetNet(b.FindNet('GND'))
shape=zone.Outline()
shape.NewOutline()
for x,y in [(70,55),(80,55),(80,65),(70,65)]:
 shape.Append(p.FromMM(x),p.FromMM(y))
b.Add(zone)
assert b.GetAreaCount()==1
p.SaveBoard(sys.argv[1],b)
r=p.LoadBoard(sys.argv[1])
assert r.GetAreaCount()==1
print('GENUINE_NATIVE_ZONE_KEPT_UNFILLED')
""",
            str(board),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert native.returncode == 0, native.stderr
    original = board.read_bytes()
    out = tmp_path / "zone-must-not-be-edited"
    result = run(board, out, selected(ids), timeout=50)
    assert result.returncode == 2, result.stderr
    assert "Zone-bearing boards are blocked" in result.stderr
    assert not out.exists()
    assert board.read_bytes() == original


def test_packaged_native_multinet_includes_its_worker_and_never_replaces_frozen_0111(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from review_studio_build_deb import build

    proposal = build(ROOT, tmp_path / "draft-012")
    assert proposal.name == "zaptrace-review-studio_0.1.12_all.deb"
    inspected = subprocess.run(
        ["dpkg-deb", "-c", str(proposal)],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    ).stdout
    assert "usr/lib/zaptrace-review-studio/scripts/review_studio_native_copper_batch.py" in inspected
    assert "usr/lib/zaptrace-review-studio/scripts/review_studio_native_copper_bundle.py" in inspected
    assert "usr/lib/zaptrace-review-studio/scripts/review_studio_local_server.py" in inspected
    frozen = ROOT / "build/distribution/zaptrace-review-studio_0.1.11_all.deb"
    frozen_sha = ROOT / "build/distribution/zaptrace-review-studio_0.1.11_all.sha256"
    digest = hashlib.sha256(frozen.read_bytes()).hexdigest()
    assert frozen_sha.read_text().strip() == f"{digest}  {frozen.name}"
