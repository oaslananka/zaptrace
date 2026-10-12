"""Browser-facing localhost KiCad copper intake, native DRC, and private ZIP security."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import shutil
import stat
import zipfile
from pathlib import Path

import pytest

from zaptrace.core.parser import parse_file
from zaptrace.export.kicad import export_kicad

ROOT = Path(__file__).resolve().parents[1]
HELPERS_SPEC = importlib.util.spec_from_file_location(
    "copper_local_server_fixture", ROOT / "tests/test_review_studio_schematic_eco_server.py"
)
assert HELPERS_SPEC and HELPERS_SPEC.loader
HELPERS = importlib.util.module_from_spec(HELPERS_SPEC)
HELPERS_SPEC.loader.exec_module(HELPERS)
local_studio, fetch, await_job = HELPERS.local_studio, HELPERS.fetch, HELPERS.await_job
pytestmark = pytest.mark.skipif(
    not shutil.which("kicad-cli") or not Path("/usr/lib/python3/dist-packages/pcbnew.py").is_file(),
    reason="Real KiCad 10 system CLI and native pcbnew required",
)


@pytest.fixture(scope="module")
def portable() -> tuple[bytes, dict[str, bytes]]:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="zaptrace-native-copper-http-fixture-") as folder:
        root = Path(folder)
        files = export_kicad(
            parse_file(ROOT / "build/source-reference-readonly/issue91-design.yaml"),
            root / "project",
        )
        assert files["pcb"].is_file()
        contents = {
            path.relative_to(root / "project").as_posix(): path.read_bytes()
            for path in (root / "project").rglob("*")
            if path.is_file()
        }
    return make_zip(contents), contents


def make_zip(contents: dict[str, bytes]) -> bytes:
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(contents.items()):
            archive.writestr(name, raw)
    return memory.getvalue()


def upload(raw: bytes) -> dict:
    return {
        "project_base64": base64.b64encode(raw).decode(),
        "project_sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_local_native_copper_inspect_select_route_download_discard(
    tmp_path: Path, portable: tuple[bytes, dict[str, bytes]]
) -> None:
    raw, contents = portable
    original_contents = dict(contents)
    payload = upload(raw)
    with local_studio(tmp_path) as (server, base):
        code, html = fetch(base + "/", server.secret)
        assert code == 200
        assert b'id="copperLab"' in html and b'id="copperPair"' in html
        assert b'id="copperInspectForm"' in html and b'id="copperRouteForm"' in html
        assert b"window.__REVIEW_LOCAL__=" in html
        code, _ = fetch(base + "/api/native-copper/inspect", "wrong-token", data=payload)
        assert code == 403
        code, report_raw = fetch(base + "/api/native-copper/inspect", server.secret, data=payload)
        assert code == 200, report_raw
        report = json.loads(report_raw)
        assert report["mode"] == "read_only_native_kicad_links"
        assert report["archive_sha256"] == payload["project_sha256"]
        assert report["physical_drc_count"] == 16
        assert report["unconnected_count"] == 37
        assert report["schematic_parity_count"] == 0
        assert len(report["links"]) == 37
        assert report["fabApproved"] is False
        assert not list((tmp_path / "workspace").glob(".zaptrace-copper-inspect-*"))
        link = next(
            x
            for x in report["links"]
            if any("Pad 2 [VCC_3V3] of U1" in pad["label"] for pad in x["pads"])
            and any("Pad 3 [VCC_3V3] of U1" in pad["label"] for pad in x["pads"])
        )
        uuids = [pad["uuid"] for pad in link["pads"]]
        code, started_bytes = fetch(
            base + "/api/native-copper",
            server.secret,
            data={**payload, "start_pad_uuid": uuids[0], "end_pad_uuid": uuids[1], "waypoints": []},
        )
        assert code == 202, started_bytes
        started = json.loads(started_bytes)
        assert started["state"] == "running"
        result = await_job(base, server.secret, started["id"])
        assert result["state"] == "complete", result
        assert result["native_copper"]["before_unconnected"] == 37
        assert result["native_copper"]["after_unconnected"] == 36
        assert result["native_copper"]["before_violations"] == 16
        assert result["native_copper"]["after_violations"] == 16
        assert result["native_copper"]["link"]["pad_uuids"] == uuids
        assert result["native_copper"]["fabApproved"] is False
        assert result["native_copper"]["automatic_complete_routing"] is False
        root = base + "/api/native-copper/result/" + started["id"]
        code, bundle = fetch(root + "/native-copper-project.zip", server.secret)
        assert code == 200 and len(bundle) > 100
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            assert "EVIDENCE.json" in archive.namelist()
            assert "baseline-drc.json" in archive.namelist()
            assert "candidate-drc.json" in archive.namelist()
            assert "ESP32_I2C_Sensor_Board.kicad_pcb" in archive.namelist()
            evidence = json.loads(archive.read("EVIDENCE.json"))
            assert (
                evidence["source_asset_sha256"]["ESP32_I2C_Sensor_Board.kicad_pcb"]
                == hashlib.sha256(contents["ESP32_I2C_Sensor_Board.kicad_pcb"]).hexdigest()
            )
            assert evidence["native_drc"]["before_unconnected"] == 37
            assert evidence["native_drc"]["after_unconnected"] == 36
            assert len(json.loads(archive.read("candidate-drc.json"))["unconnected_items"]) == 36
            assert archive.read("ESP32_I2C_Sensor_Board.kicad_pcb") != contents["ESP32_I2C_Sensor_Board.kicad_pcb"]
            assert "ESP32_I2C_Sensor_Board.kicad_netlist_evidence.json" not in archive.namelist()
        code, _ = fetch(root + "/native-copper-project.zip", "invalid-token")
        assert code == 403
        assert (
            result["native_copper"]["download_sha256"]["native-copper-project.zip"]
            == hashlib.sha256(bundle).hexdigest()
        )
        artifact = tmp_path / "workspace/native-copper-results" / started["id"] / "EVIDENCE.json"
        valid_evidence_bytes = artifact.read_bytes()
        artifact.write_bytes(b'{"forged":true}')
        code, _ = fetch(root + "/EVIDENCE.json", server.secret)
        assert code == 404, "Native artifact edits must invalidate the URL's pinned SHA"
        artifact.write_bytes(valid_evidence_bytes)
        code, _ = fetch(root + "/../native-copper-project.zip", server.secret)
        assert code in (403, 404)
        code, raw_discard = fetch(base + "/api/native-copper/discard", server.secret, data={"id": started["id"]})
        assert code == 200 and json.loads(raw_discard)["state"] == "discarded"
        code, _ = fetch(root + "/EVIDENCE.json", server.secret)
        assert code == 404
        assert not list((tmp_path / "workspace/native-copper-working").glob("*/project"))
        assert not list((tmp_path / "workspace/native-copper-results").glob("*/EVIDENCE.json"))
    assert contents == original_contents


def test_native_two_through_via_http_workflow_uses_real_kicad_drc_and_private_sha(
    tmp_path: Path, portable: tuple[bytes, dict[str, bytes]]
) -> None:
    original, contents = portable
    source_sha = hashlib.sha256(original).hexdigest()
    with local_studio(tmp_path) as (server, base):
        code, raw = fetch(base + "/api/native-copper/inspect", server.secret, data=upload(original))
        assert code == 200
        candidates = json.loads(raw)["links"]
        selected = next(
            item
            for item in candidates
            if any("Pad 2 [GND] of R3" in pad["label"] for pad in item["pads"])
            and any("Pad 2 [GND] of R4" in pad["label"] for pad in item["pads"])
        )
        uuids = [item["uuid"] for item in selected["pads"]]
        assert len(uuids) == 2
        payload = {
            **upload(original),
            "start_pad_uuid": uuids[0],
            "end_pad_uuid": uuids[1],
            "waypoints": [[72.51, 58.8], [77.51, 58.8]],
            "via_indices": [1, 2],
        }
        code, queued = fetch(base + "/api/native-copper", server.secret, data=payload)
        assert code == 202, queued
        identifier = json.loads(queued)["id"]
        finished = await_job(base, server.secret, identifier)
        assert finished["state"] == "complete", finished
        result = finished["native_copper"]
        assert result["archive_sha256"] == source_sha
        assert result["link"]["segment_layers"] == ["F.Cu", "B.Cu", "F.Cu"]
        assert result["link"]["via_count"] == 2
        assert result["link"]["via_diameter_mm"] == 0.6
        assert result["link"]["via_drill_mm"] == 0.3
        assert result["before_unconnected"] == 37 and result["after_unconnected"] == 36
        assert result["before_violations"] == result["after_violations"] == 16
        assert result["fabApproved"] is False
        url = base + "/api/native-copper/result/" + identifier
        code, data = fetch(url + "/native-copper-project.zip", server.secret)
        assert code == 200
        assert result["download_sha256"]["native-copper-project.zip"] == hashlib.sha256(data).hexdigest()
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            manifest = json.loads(package.read("EVIDENCE.json"))
            assert manifest["source_sha256"] == hashlib.sha256(contents["ESP32_I2C_Sensor_Board.kicad_pcb"]).hexdigest()
            assert manifest["link"]["via_indices"] == [1, 2]
            assert b"<svg" in package.read("after.svg")
            assert package.read("after.svg") != package.read("before.svg")
            assert b"NOT FABRICATION APPROVED" in package.read("PREVIEW.html")
            assert len(json.loads(package.read("candidate-drc.json"))["unconnected_items"]) == 36
        code, discarded = fetch(base + "/api/native-copper/discard", server.secret, data={"id": identifier})
        assert code == 200 and json.loads(discarded)["state"] == "discarded"
        code, _ = fetch(url + "/native-copper-project.zip", server.secret)
        assert code == 404
    assert source_sha == hashlib.sha256(original).hexdigest()


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"project_sha256": "0" * 64}, 400),
        ({"project_base64": "%%%not-base64%%%"}, 400),
        ({"unknown_control": True}, 400),
        ({"start_pad_uuid": "no-uuid"}, 400),
        ({"waypoints": [True]}, 400),
        ({"waypoints": [[0, float("inf")]]}, 400),
        ({"via_indices": [0, 2]}, 400),
        ({"via_indices": [2, 1]}, 400),
        ({"via_indices": [1, 1]}, 400),
        ({"via_indices": [True, 2]}, 400),
        ({"via_indices": [1.0, 2]}, 400),
        ({"via_indices": [1, 2, 3]}, 400),
        ({"via_indices": "[]"}, 400),
    ],
)
def test_native_copper_api_rejects_invalid_privileged_requests(
    tmp_path: Path, portable: tuple[bytes, dict[str, bytes]], change: dict, expected: int
) -> None:
    payload = {
        **upload(portable[0]),
        "start_pad_uuid": "7f4b347d-3a6a-4708-8435-312dcd6dba41",
        "end_pad_uuid": "e618cebe-80cf-46c2-9ebe-de7ad60265d2",
        "waypoints": [],
    }
    with local_studio(tmp_path) as (server, base):
        code, _ = fetch(base + "/api/native-copper", server.secret, data={**payload, **change})
        assert code == expected
        assert not list((tmp_path / "workspace").glob("native-copper-working/*/project"))


@pytest.mark.parametrize(
    "member",
    [
        "../secret.kicad_pcb",
        "ZapTrace.pretty/../../../escape.kicad_mod",
        "exfiltrate.kicad_dru",
        "other/fp-lib-table",
        "/absolute.kicad_pcb",
        "invalid\\entry.kicad_mod",
    ],
)
def test_native_copper_zip_blocks_path_traversal_and_non_source_member(
    tmp_path: Path, portable: tuple[bytes, dict[str, bytes]], member: str
) -> None:
    bad = make_zip({**portable[1], member: b"evil"})
    with local_studio(tmp_path) as (server, base):
        code, _ = fetch(base + "/api/native-copper/inspect", server.secret, data=upload(bad))
        assert code == 400
        assert not list((tmp_path / "workspace").glob(".zaptrace-copper-inspect-*"))


def test_native_copper_zip_rejects_symlinks_and_remote_library(
    tmp_path: Path, portable: tuple[bytes, dict[str, bytes]]
) -> None:
    with local_studio(tmp_path) as (server, base):
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, raw in portable[1].items():
                if name.endswith(".kicad_mod"):
                    record = zipfile.ZipInfo(name)
                    record.create_system = 3
                    record.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(record, b"/tmp/evil")
                else:
                    archive.writestr(name, raw)
        code, _ = fetch(base + "/api/native-copper/inspect", server.secret, data=upload(memory.getvalue()))
        assert code == 400
        bad = dict(portable[1])
        bad["fp-lib-table"] = bad["fp-lib-table"].replace(
            b"${KIPRJMOD}/ZapTrace.pretty", b"/tmp/external-footprints.pretty"
        )
        code, _ = fetch(base + "/api/native-copper/inspect", server.secret, data=upload(make_zip(bad)))
        assert code == 400
        assert not list((tmp_path / "workspace").glob(".zaptrace-copper-inspect-*"))


def test_native_copper_server_restart_erases_only_unreachable_private_drafts(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    stale_id = "a" * 32
    for name in ("native-copper-working", "native-copper-results"):
        folder = root / name / stale_id
        folder.mkdir(parents=True)
        (folder / "private-native-source.kicad_pcb").write_bytes(b"private temp artifact")
    unrelated = root / "projects" / ("b" * 32)
    unrelated.mkdir(parents=True)
    (unrelated / "preserved.txt").write_text("saved review")
    with local_studio(tmp_path):
        assert not (root / "native-copper-working" / stale_id).exists()
        assert not (root / "native-copper-results" / stale_id).exists()
        assert (unrelated / "preserved.txt").read_text() == "saved review"
