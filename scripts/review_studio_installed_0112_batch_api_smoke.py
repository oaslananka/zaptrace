#!/usr/bin/python3
"""Independent real system-installed Ubuntu 0.1.12 multi-net API verification.

Uses the actual Debian-installed application, native system pcbnew/KiCad
subprocesses, an original SHA-locked user ZIP, and a private localhost
session. Never imports developer source or changes real user files.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from review_studio_local_file_guard import read_regular_bytes


def call(base: str, token: str, path: str, payload: dict | None = None) -> tuple[int, bytes]:
    headers = {"X-Review-Token": token}
    if payload is not None:
        headers.update({"Origin": base, "Content-Type": "application/json"})
    req = Request(
        base + path,
        method="POST" if payload is not None else "GET",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
    )
    try:
        with urlopen(req, timeout=35) as response:
            return response.status, response.read()
    except HTTPError as e:
        return e.code, e.read()


def verify(installed: Path, portable: Path) -> None:
    assert installed.name == "scripts" and installed.is_dir()
    for name in (
        "review_studio_local_server.py",
        "review_studio_native_copper_batch.py",
        "review_studio_native_copper_bundle.py",
        "review_studio_native_copper_link.py",
    ):
        assert (installed / name).is_file(), name
    sys.path.insert(0, str(installed.resolve()))
    from review_studio_local_server import ReviewLocalServer

    original = read_regular_bytes(portable, max_size=34 * 1024 * 1024)
    original_hash = hashlib.sha256(original).hexdigest()
    upload = {"project_base64": base64.b64encode(original).decode(), "project_sha256": original_hash}
    with tempfile.TemporaryDirectory(prefix="zaptrace-012-actual-installed-multinet-") as temp:
        base_dir = Path(temp)
        server = ReviewLocalServer(("127.0.0.1", 0), base_dir / "private-workspace")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            status, resp = call(base, server.secret, "/api/native-copper/inspect", upload)
            assert status == 200, (status, resp[:200])
            report = json.loads(resp)
            assert report["unconnected_count"] == 37
            assert report["physical_drc_count"] == 16

            def pads(left: str, right: str) -> list[str]:
                matches = [
                    item
                    for item in report["links"]
                    if any(left in pad["label"] for pad in item["pads"])
                    and any(right in pad["label"] for pad in item["pads"])
                ]
                assert len(matches) == 1, (left, right)
                return [pad["uuid"] for pad in matches[0]["pads"]]

            pair_gnd = pads("Pad 2 [GND] of R3", "Pad 2 [GND] of R4")
            pair_vcc = pads("Pad 2 [VCC_3V3] of U1", "Pad 3 [VCC_3V3] of U1")
            plans = [
                {
                    "start_pad_uuid": pair_gnd[0],
                    "end_pad_uuid": pair_gnd[1],
                    "waypoints": [[72.51, 58.8], [77.51, 58.8]],
                    "via_indices": [1, 2],
                },
                {"start_pad_uuid": pair_vcc[0], "end_pad_uuid": pair_vcc[1], "waypoints": [], "via_indices": []},
            ]
            request = {**upload, "routes": plans}
            code, _ = call(base, "unauthorized", "/api/native-copper/batch", request)
            assert code == 403
            code, response = call(base, server.secret, "/api/native-copper/batch", request)
            assert code == 202, (code, response)
            job_id = json.loads(response)["id"]
            until = time.monotonic() + 570
            while time.monotonic() < until:
                code, data = call(base, server.secret, "/api/jobs/" + job_id)
                assert code == 200
                job = json.loads(data)
                if job["state"] != "running":
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("Actual installed native KiCad batch job timed out")
            assert job["state"] == "complete", job
            proof = job["native_copper"]
            assert proof["mode"] == "transactional_multinet_review"
            assert proof["step_count"] == 2
            assert proof["distinct_nets"] == ["GND", "VCC_3V3"]
            assert proof["before_unconnected"] == 37 and proof["after_unconnected"] == 35
            assert proof["before_violations"] == proof["after_violations"] == 16
            assert proof["archive_sha256"] == original_hash
            assert proof["fabApproved"] is False and proof["zone_refill_verified"] is False
            assert proof["steps"][0]["link"]["via_indices"] == [1, 2]
            assert proof["steps"][0]["link"]["segment_layers"] == ["F.Cu", "B.Cu", "F.Cu"]
            assert proof["steps"][1]["link"]["segment_layers"] == ["F.Cu"]
            assert proof["steps"][1]["source_sha256"] == proof["steps"][0]["working_sha256"]
            assert all(step["rule_context"]["custom_rule_loader_probe_passed"] for step in proof["steps"])
            assert all(step["rule_context"]["default_drc_crosscheck_passed"] for step in proof["steps"])
            route = "/api/native-copper/result/" + job_id
            code, output_zip = call(base, server.secret, route + "/native-copper-project.zip")
            assert code == 200
            assert hashlib.sha256(output_zip).hexdigest() == proof["download_sha256"]["native-copper-project.zip"]
            with zipfile.ZipFile(io.BytesIO(output_zip)) as output:
                assert output.testzip() is None
                evidence = json.loads(output.read("EVIDENCE.json"))
                assert evidence["cumulative_drc"]["after_unconnected"] == 35
                assert evidence["cumulative_drc"]["after_violations"] == 16
                assert evidence["step_count"] == 2
                assert (
                    evidence["working_sha256"]
                    == hashlib.sha256(output.read("ESP32_I2C_Sensor_Board.kicad_pcb")).hexdigest()
                )
                assert json.loads(output.read("candidate-drc.json"))["unconnected_items"].__len__() == 35
                assert output.read("before.svg") != output.read("after.svg")
                assert all("step-" + str(i) + "-evidence.json" in output.namelist() for i in (1, 2))
                assert "ESP32_I2C_Sensor_Board.kicad_dru" in output.namelist()
                assert "step-1-candidate-default-drc.json" in output.namelist()
                assert "step-2-candidate-default-drc.json" in output.namelist()
            code, _ = call(base, "unauthorized", route + "/native-copper-project.zip")
            assert code == 403
            code, body = call(base, server.secret, "/api/native-copper/discard", {"id": job_id})
            assert code == 200 and json.loads(body)["state"] == "discarded"
            code, _ = call(base, server.secret, route + "/EVIDENCE.json")
            assert code == 404
            assert not list((base_dir / "private-workspace/native-copper-results").glob("*/EVIDENCE.json"))
            assert hashlib.sha256(read_regular_bytes(portable, max_size=34 * 1024 * 1024)).hexdigest() == original_hash
            print("INSTALLED_0112_NATIVE_MULTINET_37_TO_35_AND_16_TO_16=PASS")
            print("INSTALLED_0112_MULTINET_TWO_NET_SHA_CHAIN_AND_CUSTOM_DEFAULT_DRC=PASS")
            print("INSTALLED_0112_MULTINET_PRIVATE_ZIP_DOWNLOAD_DISCARD_AND_SOURCE_SHA=PASS")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=8)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed-scripts", required=True, type=Path)
    parser.add_argument("--portable-project-zip", required=True, type=Path)
    args = parser.parse_args()
    verify(args.installed_scripts, args.portable_project_zip)


if __name__ == "__main__":
    main()
