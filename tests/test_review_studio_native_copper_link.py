"""Native KiCad 10 fail-closed single pad-to-pad copper review acceptance."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from zaptrace.core.parser import parse_file
from zaptrace.export.kicad import export_kicad

ROOT = Path(__file__).resolve().parents[1]
IR = ROOT / "build/source-reference-readonly/issue91-design.yaml"
SCRIPT = ROOT / "scripts/review_studio_native_copper_link.py"

pytestmark = pytest.mark.skipif(
    not shutil.which("kicad-cli") or not Path("/usr/lib/python3/dist-packages/pcbnew.py").exists(),
    reason="Native KiCad 10 and PCB Python bindings required",
)


def source_project(tmp_path: Path) -> tuple[Path, dict[tuple[str, str], str]]:
    folder = tmp_path / "source"
    files = export_kicad(parse_file(IR), folder)
    pcb = files["pcb"]
    process = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            "-c",
            """
import pcbnew as pcb,json,sys
board=pcb.LoadBoard(sys.argv[1])
print(json.dumps({f'{f.GetReference()}:{p.GetNumber()}':p.m_Uuid.AsString()
                  for f in board.GetFootprints() for p in f.Pads() if p.GetNumber()}))
""",
            str(pcb),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    identities = {tuple(key.split(":", 1)): value for key, value in json.loads(process.stdout).items()}
    return pcb, identities


def execute(
    pcb: Path, output: Path, first: str, second: str, waypoints: str = "[]"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            str(SCRIPT),
            "--board",
            str(pcb),
            "--output",
            str(output),
            "--start-pad-uuid",
            first,
            "--end-pad-uuid",
            second,
            "--waypoints-json",
            waypoints,
        ],
        capture_output=True,
        text=True,
        timeout=115,
        check=False,
    )


def test_native_straight_copper_copy_reduces_unconnected_without_any_new_drc(tmp_path: Path) -> None:
    pcb, identities = source_project(tmp_path)
    original_bytes = pcb.read_bytes()
    original_sha = hashlib.sha256(original_bytes).hexdigest()
    output = tmp_path / "only-safe-copy"
    run = execute(pcb, output, identities[("U1", "2")], identities[("U1", "3")])
    assert run.returncode == 0, run.stderr
    evidence = json.loads((output / "EVIDENCE.json").read_text())
    assert json.loads(run.stdout) == evidence
    assert evidence["source_sha256"] == original_sha
    assert evidence["link"]["net"] == "VCC_3V3"
    assert evidence["link"]["length_mm"] == pytest.approx(1.27, abs=0.001)
    assert set(evidence["link"]["pad_uuids"]) == {identities[("U1", "2")], identities[("U1", "3")]}
    assert evidence["native_drc"]["before_violations"] == 16
    assert evidence["native_drc"]["after_violations"] == 16
    assert evidence["native_drc"]["before_unconnected"] == 37
    assert evidence["native_drc"]["after_unconnected"] == 36
    assert evidence["native_drc"]["new_findings"] == 0
    assert evidence["native_drc"]["schematic_parity"] == 0
    assert evidence["automatic_complete_routing"] is False
    assert evidence["electricallyApproved"] is False
    assert evidence["fabApproved"] is False
    saved = output / "project" / pcb.name
    assert saved.is_file()
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == evidence["working_sha256"]
    assert (output / "project/ZapTrace.pretty").is_dir()
    assert (output / "project/fp-lib-table").is_file()
    assert (output / "project" / pcb.with_suffix(".kicad_sch").name).is_file()
    assert len(json.loads((output / "candidate-drc.json").read_text())["unconnected_items"]) == 36
    assert pcb.read_bytes() == original_bytes
    for relative, sha in evidence["source_asset_sha256"].items():
        assert hashlib.sha256((pcb.parent / relative).read_bytes()).hexdigest() == sha


@pytest.mark.parametrize(
    ("first", "second", "error"),
    [
        (("U1", "1"), ("U1", "2"), "not a unique native unconnected link"),
        (("U1", "2"), ("U1", "2"), "Two different native physical pad UUIDs"),
    ],
)
def test_native_copper_route_denies_nonconnection_and_same_pad_without_artifact(
    tmp_path: Path, first: tuple[str, str], second: tuple[str, str], error: str
) -> None:
    pcb, ids = source_project(tmp_path)
    original = pcb.read_bytes()
    output = tmp_path / "blocked-copy"
    run = execute(pcb, output, ids[first], ids[second])
    assert run.returncode == 2
    assert error in run.stderr
    assert not output.exists()
    assert pcb.read_bytes() == original


def test_native_copper_route_blocks_real_new_manufacturing_drc_findings(tmp_path: Path) -> None:
    pcb, ids = source_project(tmp_path)
    original = pcb.read_bytes()
    output = tmp_path / "blocked-clearance"
    # KiCad 10 detects actual new copper clearance issues for this straight
    # connection of U2 pads 7 and 5. Geometry cannot be accepted by "same net".
    run = execute(pcb, output, ids[("U2", "7")], ids[("U2", "5")])
    assert run.returncode == 2
    assert "New physical KiCad DRC violation" in run.stderr
    assert not output.exists()
    assert pcb.read_bytes() == original


def test_generated_vendor_pads_have_stable_kiid_and_drc_uses_exact_ids(tmp_path: Path) -> None:
    pcb, _ids = source_project(tmp_path)
    drc_json = tmp_path / "original-native-drc.json"
    drc = subprocess.run(
        [
            "kicad-cli",
            "pcb",
            "drc",
            "--schematic-parity",
            "--severity-all",
            "--format",
            "json",
            "--output",
            str(drc_json),
            str(pcb),
        ],
        capture_output=True,
        text=True,
        timeout=75,
        check=False,
    )
    assert drc.returncode == 0, drc.stderr
    d = json.loads(drc_json.read_text())
    assert len(d["unconnected_items"]) == 37
    assert len(d["violations"]) == 16
    assert d["schematic_parity"] == []
    for _ in range(2):
        native = subprocess.run(
            [
                "/usr/bin/python3",
                "-B",
                "-c",
                """
import pcbnew as pcb,json,sys
board=pcb.LoadBoard(sys.argv[1])
uuids={pad.m_Uuid.AsString() for fp in board.GetFootprints() for pad in fp.Pads()}
assert len(uuids)==sum(len(fp.Pads()) for fp in board.GetFootprints())
print(json.dumps(sorted(uuids)))
""",
                str(pcb),
            ],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
        assert native.returncode == 0, native.stderr
        uuids = set(json.loads(native.stdout))
        assert len(uuids) == 112
        assert all(item["uuid"] in uuids for finding in d["unconnected_items"] for item in finding["items"])


def test_native_manhattan_bypass_reduces_real_open_count_without_drc_regression(tmp_path: Path) -> None:
    board, ids = source_project(tmp_path)
    source_sha = hashlib.sha256(board.read_bytes()).hexdigest()
    dest = tmp_path / "native-three-segment-route"
    run = execute(
        board,
        dest,
        ids[("R3", "2")],
        ids[("R4", "2")],
        "[[72.51,58.8],[77.51,58.8]]",
    )
    assert run.returncode == 0, run.stderr
    proof = json.loads((dest / "EVIDENCE.json").read_text())
    assert proof["source_sha256"] == source_sha
    assert proof["link"]["net"] == "GND"
    assert proof["link"]["segment_count"] == 3
    assert proof["link"]["length_mm"] == pytest.approx(7.4, abs=0.001)
    assert proof["link"]["points_mm"] == [[72.51, 60.0], [72.51, 58.8], [77.51, 58.8], [77.51, 60.0]]
    assert proof["native_drc"]["before_unconnected"] == 37
    assert proof["native_drc"]["after_unconnected"] == 36
    assert proof["native_drc"]["before_violations"] == proof["native_drc"]["after_violations"] == 16
    assert proof["native_drc"]["new_findings"] == 0
    assert proof["fabApproved"] is False


@pytest.mark.parametrize(
    ("waypoints", "issue"),
    [
        ("[[72.51,58.8],[77.51,58.8]]", "New physical KiCad DRC violation"),
        ("[[72.51,58.8],[72.51,58.8]]", "Repeated route points"),
        ("[[9999.0,58.8]]", "Every route waypoint must"),
        ("[[null,58.8]]", "Every route waypoint must"),
        ("[[72.51,999.0]]", "Intermediate route point outside"),
        ("[[72.51,58.8],[77.51,58.8],[72.51,58.8]]", "Repeated route points"),
        ("[[", "Expecting value"),
    ],
)
def test_native_waypoint_validation_denies_wrong_direction_and_untrusted_geometry(
    tmp_path: Path, waypoints: str, issue: str
) -> None:
    board, ids = source_project(tmp_path)
    original = board.read_bytes()
    output = tmp_path / "never-published"
    # Wrong-way waypoint order is a new DRC failure even though both
    # endpoint UUIDs are physically in the same net.
    run = execute(board, output, ids[("R4", "2")], ids[("R3", "2")], waypoints)
    assert run.returncode == 2
    assert issue in run.stderr
    assert not output.exists()
    assert board.read_bytes() == original


def test_native_link_rejects_unattested_custom_rules_even_for_good_geometry(tmp_path: Path) -> None:
    board, ids = source_project(tmp_path)
    dru = board.with_suffix(".kicad_dru")
    dru.write_text('(version 1)\n(rule "demo" (constraint clearance (min 0.2mm)))\n')
    output = tmp_path / "rules-prohibited"
    run = execute(board, output, ids[("U1", "2")], ids[("U1", "3")])
    assert run.returncode == 2
    assert "Custom KiCad design rules" in run.stderr
    assert not output.exists()


def test_native_two_straight_links_prove_cumulative_drc_nonworsening(tmp_path: Path) -> None:
    board, ids = source_project(tmp_path)
    first = tmp_path / "first"
    one = execute(board, first, ids[("U1", "2")], ids[("U1", "3")])
    assert one.returncode == 0, one.stderr
    second_source = first / "project" / board.name
    second_ids = source_project_uuids(second_source)
    second = tmp_path / "second"
    two = execute(second_source, second, second_ids[("U2", "7")], second_ids[("U2", "1")])
    assert two.returncode == 0, two.stderr
    final = json.loads((second / "EVIDENCE.json").read_text())
    assert final["native_drc"]["before_unconnected"] == 36
    assert final["native_drc"]["after_unconnected"] == 35
    assert final["native_drc"]["before_violations"] == final["native_drc"]["after_violations"] == 16
    assert final["native_drc"]["new_findings"] == 0
    assert final["automatic_complete_routing"] is False


def source_project_uuids(pcb: Path) -> dict[tuple[str, str], str]:
    proc = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            "-c",
            """import pcbnew as p,json,sys
b=p.LoadBoard(sys.argv[1])
print(json.dumps({f'{f.GetReference()}:{q.GetNumber()}':q.m_Uuid.AsString()
 for f in b.GetFootprints() for q in f.Pads() if q.GetNumber()}))""",
            str(pcb),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return {tuple(x.split(":", 1)): v for x, v in json.loads(proc.stdout).items()}


def test_native_copper_review_refuses_extra_untrusted_library_uri(tmp_path: Path) -> None:
    board, ids = source_project(tmp_path)
    table = board.parent / "fp-lib-table"
    initial = table.read_text()
    table.write_text(
        initial.replace(
            ")\n",
            '  (lib (name "Untrusted")(type "KiCad")(uri "/tmp/untrusted.pretty")(options "")(descr ""))\n)\n',
            1,
        )
    )
    output = tmp_path / "no-untrusted-library-output"
    run = execute(board, output, ids[("U1", "2")], ids[("U1", "3")])
    assert run.returncode == 2
    assert "Only exact project-local ZapTrace library tables" in run.stderr
    assert not output.exists()
