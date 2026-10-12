"""Authenticated KiCad multi-net copy: 2-step native DRC and atomic discard."""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

import pytest

from tests import test_review_studio_native_copper_server as base_server

fetch = base_server.fetch
local_studio = base_server.local_studio
upload = base_server.upload


@pytest.fixture(scope="module")
def portable_project() -> tuple[bytes, dict[str, bytes]]:
    import tempfile

    from zaptrace.core.parser import parse_file
    from zaptrace.export.kicad import export_kicad

    with tempfile.TemporaryDirectory(prefix="zaptrace-multinet-native-http-fixture-") as folder:
        source = Path(folder) / "project"
        export_kicad(
            parse_file(Path(__file__).resolve().parents[1] / "build/source-reference-readonly/issue91-design.yaml"),
            source,
        )
        contents = {
            path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*") if path.is_file()
        }
    return base_server.make_zip(contents), contents


def _pair(links: list[dict], left: str, right: str) -> list[str]:
    matched = next(
        item
        for item in links
        if any(left in pad["label"] for pad in item["pads"]) and any(right in pad["label"] for pad in item["pads"])
    )
    return [pad["uuid"] for pad in matched["pads"]]


def _routes(links: list[dict]) -> list[dict]:
    a, b = _pair(links, "Pad 2 [GND] of R3", "Pad 2 [GND] of R4")
    c, d = _pair(links, "Pad 2 [VCC_3V3] of U1", "Pad 3 [VCC_3V3] of U1")
    return [
        {"start_pad_uuid": a, "end_pad_uuid": b, "waypoints": [[72.51, 58.8], [77.51, 58.8]], "via_indices": [1, 2]},
        {"start_pad_uuid": c, "end_pad_uuid": d, "waypoints": [], "via_indices": []},
    ]


def _wait(base: str, token: str, job_id: str, *, seconds: int = 330) -> dict:
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        status, raw = fetch(base + "/api/jobs/" + job_id, token)
        assert status == 200
        job = json.loads(raw)
        if job["state"] != "running":
            return job
        time.sleep(0.3)
    pytest.fail("Multi-net native KiCad DRC timed out")


def test_authenticated_two_distinct_nets_real_native_zip_sha_and_discard(
    tmp_path: Path, portable_project: tuple[bytes, dict[str, bytes]]
) -> None:
    original, source_files = portable_project
    archive_sha = hashlib.sha256(original).hexdigest()
    with local_studio(tmp_path) as (server, base):
        code, candidates = fetch(base + "/api/native-copper/inspect", server.secret, data=upload(original))
        assert code == 200
        routes = _routes(json.loads(candidates)["links"])
        request = {**upload(original), "routes": routes}
        code, _ = fetch(base + "/api/native-copper/batch", "bad-token", data=request)
        assert code == 403
        code, response = fetch(base + "/api/native-copper/batch", server.secret, data=request)
        assert code == 202, response
        job_id = json.loads(response)["id"]
        result = _wait(base, server.secret, job_id)
        assert result["state"] == "complete", result
        proof = result["native_copper"]
        assert proof["mode"] == "transactional_multinet_review"
        assert proof["step_count"] == 2
        assert proof["distinct_nets"] == ["GND", "VCC_3V3"]
        assert proof["archive_sha256"] == archive_sha
        assert proof["before_unconnected"] == 37 and proof["after_unconnected"] == 35
        assert proof["before_violations"] == proof["after_violations"] == 16
        assert proof["fabApproved"] is False and proof["zone_refill_verified"] is False
        endpoint = base + "/api/native-copper/result/" + job_id
        code, data = fetch(endpoint + "/native-copper-project.zip", server.secret)
        assert code == 200
        assert proof["download_sha256"]["native-copper-project.zip"] == hashlib.sha256(data).hexdigest()
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            assert bundle.testzip() is None
            record = json.loads(bundle.read("EVIDENCE.json"))
            assert (
                record["source_sha256"] == hashlib.sha256(source_files["ESP32_I2C_Sensor_Board.kicad_pcb"]).hexdigest()
            )
            assert record["cumulative_drc"]["after_unconnected"] == 35
            assert record["steps"][1]["source_sha256"] == record["steps"][0]["working_sha256"]
            assert all("step-" + str(i) + "-evidence.json" in bundle.namelist() for i in (1, 2))
            assert len(json.loads(bundle.read("candidate-drc.json"))["unconnected_items"]) == 35
            assert bundle.read("before.svg") != bundle.read("after.svg")
            assert b"NOT FABRICATION APPROVED" in bundle.read("PREVIEW.html")
        code, _ = fetch(endpoint + "/native-copper-project.zip", "bad-token")
        assert code == 403
        code, discarded = fetch(base + "/api/native-copper/discard", server.secret, data={"id": job_id})
        assert code == 200 and json.loads(discarded)["state"] == "discarded"
        code, _ = fetch(endpoint + "/native-copper-project.zip", server.secret)
        assert code == 404
        assert not list((tmp_path / "workspace/native-copper-working").glob("*/project"))
        assert not list((tmp_path / "workspace/native-copper-results").glob("*/EVIDENCE.json"))
    assert hashlib.sha256(original).hexdigest() == archive_sha


@pytest.mark.parametrize(
    "mutate",
    [
        lambda routes: routes[:1],
        lambda routes: routes + routes,
        lambda routes: [routes[0], routes[0]],
        lambda routes: [{**routes[0], "unknown": True}, routes[1]],
        lambda routes: [{**routes[0], "via_indices": [True, 2]}, routes[1]],
        lambda routes: [{**routes[0], "waypoints": [[float("nan"), 1.0]]}, routes[1]],
    ],
)
def test_invalid_native_batch_schema_rejected_before_start(
    tmp_path: Path, portable_project: tuple[bytes, dict[str, bytes]], mutate
) -> None:
    original, _ = portable_project
    with local_studio(tmp_path) as (server, base):
        code, raw = fetch(base + "/api/native-copper/inspect", server.secret, data=upload(original))
        assert code == 200
        routes = mutate(_routes(json.loads(raw)["links"]))
        code, response = fetch(
            base + "/api/native-copper/batch", server.secret, data={**upload(original), "routes": routes}
        )
        assert code == 400, (code, response)
        assert not list((tmp_path / "workspace/native-copper-results").glob("*/EVIDENCE.json"))


def test_second_http_batch_link_failure_rolls_back_first_native_route(
    tmp_path: Path, portable_project: tuple[bytes, dict[str, bytes]]
) -> None:
    raw, source_files = portable_project
    original_sha = hashlib.sha256(raw).hexdigest()
    with local_studio(tmp_path) as (server, base):
        code, native = fetch(base + "/api/native-copper/inspect", server.secret, data=upload(raw))
        assert code == 200
        candidates = json.loads(native)["links"]
        routes = _routes(candidates)
        # Looks like a real UUID, but U1.2->U1.1 is not a native open
        # same-net DRC link. Step 1 must complete before step 2 fails.
        legitimate_u1_1 = next(
            item["uuid"] for link in candidates for item in link["pads"] if "Pad 1 [GND] of U1" in item["label"]
        )
        routes[1]["end_pad_uuid"] = legitimate_u1_1
        code, start = fetch(
            base + "/api/native-copper/batch",
            server.secret,
            data={
                **upload(raw),
                "routes": routes,
            },
        )
        assert code == 202, start
        job_id = json.loads(start)["id"]
        result = _wait(base, server.secret, job_id)
        assert result["state"] == "failed", result
        url = base + "/api/native-copper/result/" + job_id
        code, _ = fetch(url + "/native-copper-project.zip", server.secret)
        assert code == 404
        assert not (tmp_path / "workspace/native-copper-results" / job_id).exists()
        assert not list((tmp_path / "workspace/native-copper-working").glob("*/project"))
        assert hashlib.sha256(raw).hexdigest() == original_sha
        assert source_files["ESP32_I2C_Sensor_Board.kicad_pcb"].startswith(b"(kicad_pcb")
